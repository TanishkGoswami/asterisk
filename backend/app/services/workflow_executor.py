import logging
import re
import json
import httpx
import asyncio
from typing import Dict, Any, List, Optional, Tuple
from datetime import datetime
import xml.etree.ElementTree as ET

from app.db.client import Client
from app.services.llm_service import LLMService

logger = logging.getLogger(__name__)

class WorkflowExecutor:
    def __init__(self, db: Client):
        self.db = db
        from app.core.config import settings
        self.llm = LLMService(
            openai_key=settings.openai_api_key or "",
        )

    def _get_workflow_data(self, agent: dict) -> dict:
        """Extract nodes and connections from agent database metadata"""
        kb_metadata = agent.get("kb_metadata") or {}
        return kb_metadata.get("workflow_data") or {}

    def _find_start_node(self, workflow_data: dict) -> Optional[dict]:
        """Find the starting node of the workflow"""
        nodes = workflow_data.get("nodes") or []
        if not nodes:
            return None

        # 1. Look for node-greeting or type conversation
        for n in nodes:
            if n.get("id") == "node-greeting" or n.get("type") == "conversation":
                return n

        # 2. Look for nodes with no incoming connections
        connections = workflow_data.get("connections") or []
        target_ids = {c.get("targetId") for c in connections if c.get("targetId")}
        for n in nodes:
            if n.get("id") not in target_ids:
                return n

        # 3. Fallback to first node
        return nodes[0]

    def _interpolate_variables(self, text: str, variables: Dict[str, Any]) -> str:
        """Replace double curly braces {{variable}} with their values from context"""
        if not text:
            return ""
        
        def replace(match):
            var_name = match.group(1).strip()
            return str(variables.get(var_name, match.group(0)))
            
        return re.sub(r"\{\{([^}]+)\}\}", replace, text)

    async def _evaluate_logic_split(self, node: dict, variables: Dict[str, Any], connections: List[dict]) -> Optional[str]:
        """Evaluate logic split branching conditions"""
        conditions = node.get("data", {}).get("conditions") or []
        node_id = node.get("id")

        for cond in conditions:
            var_name = cond.get("variable", "")
            operator = cond.get("operator", "equals")
            val = cond.get("value", "")
            target = cond.get("targetNodeId", "")

            var_val = variables.get(var_name, "")
            matched = False

            try:
                if operator == "equals":
                    matched = str(var_val).lower() == str(val).lower()
                elif operator == "contains":
                    matched = str(val).lower() in str(var_val).lower()
                elif operator == "greater_than":
                    matched = float(var_val) > float(val)
                elif operator == "less_than":
                    matched = float(var_val) < float(val)
                elif operator == "exists":
                    matched = var_val is not None and str(var_val).strip() != ""
            except Exception as e:
                logger.warning(f"Error evaluating condition {cond} in node {node_id}: {e}")

            if matched and target:
                logger.info(f"Logic Split matched branch: variable '{var_name}' matches condition pointing to node '{target}'")
                return target

        # If no condition matched, return default connected target node
        cond_targets = {c.get("targetNodeId") for c in conditions if c.get("targetNodeId")}
        for conn in connections:
            if conn.get("sourceId") == node_id and conn.get("targetId") not in cond_targets:
                logger.info(f"Logic Split fallback: routing to default target '{conn.get('targetId')}'")
                return conn.get("targetId")

        return None

    async def _execute_semantic_routing(self, source_id: str, connections: List[dict], nodes: List[dict], user_input: str) -> Optional[str]:
        """Use LLM to choose the best outgoing connection semantically based on user utterance"""
        outgoing = [c for c in connections if c.get("sourceId") == source_id]
        if not outgoing:
            return None
        if len(outgoing) == 1:
            return outgoing[0].get("targetId")

        # Gather target metadata
        options = []
        node_map = {n.get("id"): n for n in nodes}
        for conn in outgoing:
            target_id = conn.get("targetId")
            target_node = node_map.get(target_id, {})
            title = target_node.get("data", {}).get("title") or target_node.get("type") or "Next Step"
            label = conn.get("label") or ""
            options.append({"id": target_id, "title": title, "label": label})

        logger.info(f"Executing semantic routing for node {source_id} among options: {options}")

        system_prompt = (
            "You are a routing classification engine. A caller is on a voice phone call.\n"
            f"Analyze the caller's utterance: '{user_input}'.\n"
            f"Based on this utterance, choose the most appropriate next step from the following JSON list of options:\n"
            f"{json.dumps(options)}\n"
            "Return ONLY the exact target 'id' of the chosen option. Do not include any explanation, prefix, or extra characters."
        )

        try:
            target_id = await self.llm.generate(
                system_prompt=system_prompt,
                messages=[{"role": "user", "content": user_input}],
                model="gpt-4o-mini",
                temperature=0.0,
                max_tokens=20
            )
            target_id = target_id.strip().strip("'\"")
            if any(opt["id"] == target_id for opt in options):
                logger.info(f"Semantic routing selected target node: {target_id}")
                return target_id
        except Exception as e:
            logger.error(f"Semantic routing failed: {e}")

        return outgoing[0].get("targetId")

    async def _execute_webhook(self, node: dict, variables: Dict[str, Any]) -> Dict[str, Any]:
        """Make external REST API webhook call and merge response in variables"""
        node_id = node.get("id")
        data = node.get("data") or {}
        api_url = data.get("apiUrl", "").strip()
        method = data.get("apiMethod", "POST").upper()
        headers_str = data.get("apiHeaders") or "{}"

        if not api_url:
            logger.warning(f"Webhook node {node_id} has no URL configured")
            return variables

        # Interpolate URL
        interpolated_url = self._interpolate_variables(api_url, variables)
        
        # Parse headers
        try:
            headers = json.loads(self._interpolate_variables(headers_str, variables))
        except Exception as e:
            logger.warning(f"Failed to parse webhook headers JSON: {e}")
            headers = {}

        if "Content-Type" not in headers:
            headers["Content-Type"] = "application/json"

        # Prepare payload
        payload = {
            "caller_phone": variables.get("caller_phone"),
            "call_timestamp": variables.get("call_timestamp"),
            "variables": variables
        }

        logger.info(f"Executing API Webhook: {method} {interpolated_url} with payload {payload}")

        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                if method == "GET":
                    response = await client.get(interpolated_url, headers=headers)
                else:
                    response = await client.post(interpolated_url, headers=headers, json=payload)
                
                logger.info(f"API Webhook response status: {response.status_code}")
                if response.status_code >= 200 and response.status_code < 300:
                    res_json = response.json()
                    logger.info(f"API Webhook response payload: {res_json}")
                    
                    # Merge keys directly to variables
                    if isinstance(res_json, dict):
                        for k, v in res_json.items():
                            variables[k] = v
                        # Keep raw response in context
                        variables["api_response"] = res_json
                else:
                    logger.warning(f"Webhook API returned non-200: {response.status_code}")
        except Exception as e:
            logger.error(f"Error executing API Webhook {node_id}: {e}")

        return variables

    async def _execute_subagent(self, node: dict, variables: Dict[str, Any], user_input: str) -> Tuple[str, bool]:
        """Delegate conversation turn to a specialized subagent"""
        data = node.get("data") or {}
        subagent_id = data.get("subagentId", "billing_bot")

        subagent_prompts = {
            "billing_bot": "You are a Billing Specialist. Answer questions about bills, payments, and invoice disputes. Be brief, clear, and polite.",
            "scheduler_bot": "You are an Appointment Scheduler. Assist in checking slots and scheduling followups. Be brief, direct, and polite.",
            "triage_bot": "You are a Clinical Triage Bot. Ask about symptoms to assess severity and direct patients. Be brief, empathetic, and polite."
        }

        subagent_prompt = subagent_prompts.get(subagent_id, "You are a helpful subagent. Help the customer.")
        
        # Check if subagent conversation history exists
        history_key = f"subagent_history_{subagent_id}"
        sub_history = variables.get(history_key) or []

        if user_input:
            sub_history.append({"role": "user", "content": user_input})
        else:
            user_input = "Hello" # default opening trigger

        logger.info(f"Invoking subagent {subagent_id} with query '{user_input}'")

        try:
            reply = await self.llm.generate(
                system_prompt=subagent_prompt,
                messages=sub_history[-6:], # Last 6 messages
                model="gpt-4o-mini",
                temperature=0.6,
                max_tokens=60
            )
            sub_history.append({"role": "assistant", "content": reply})
            variables[history_key] = sub_history
            
            # Simple semantic exit check
            exit_check = await self.llm.generate(
                system_prompt=(
                    "Check if the subagent has resolved the query and the subagent conversation can end. "
                    "Utterance: '{}'. Reply: '{}'. Return 'true' if the conversation is completed and the subagent can return "
                    "control to the parent agent, or 'false' if it needs to continue. Return ONLY 'true' or 'false'."
                ).format(user_input, reply),
                messages=[],
                model="gpt-4o-mini",
                temperature=0.0,
                max_tokens=5
            )
            
            is_finished = "true" in exit_check.lower()
            if is_finished:
                logger.info(f"Subagent {subagent_id} completed its task.")
                variables[f"{subagent_id}_result"] = reply
            
            return reply, is_finished
        except Exception as e:
            logger.error(f"Error executing subagent {subagent_id}: {e}")
            return "I apologize, I could not contact our specialist bot. Let me transfer you.", True

    async def _execute_variable_extraction(self, node: dict, variables: Dict[str, Any], user_input: str) -> Dict[str, Any]:
        """Extract specific field value from speech transcript using LLM"""
        data = node.get("data") or {}
        var_name = data.get("variableName", "extracted_value")
        var_type = data.get("variableType", "string")
        extract_prompt = data.get("prompt", "")

        if not user_input:
            return variables

        system_prompt = (
            f"You are a variable extractor. Extract the value for '{var_name}' from the user's speech transcript: '{user_input}'.\n"
            f"Expected Data Type: {var_type}.\n"
            f"Instruction prompt: {extract_prompt}.\n"
            "Return ONLY the final extracted value. If not found or unclear, return the string 'null'. Do not explain."
        )

        try:
            extracted_val = await self.llm.generate(
                system_prompt=system_prompt,
                messages=[],
                model="gpt-4o-mini",
                temperature=0.0,
                max_tokens=20
            )
            extracted_val = extracted_val.strip().strip("'\"")
            
            if extracted_val.lower() != "null":
                # Convert type
                if var_type == "number":
                    try:
                        extracted_val = float(extracted_val) if "." in extracted_val else int(extracted_val)
                    except ValueError:
                        pass
                elif var_type == "boolean":
                    extracted_val = extracted_val.lower() in ("true", "yes", "1")

                variables[var_name] = extracted_val
                logger.info(f"Extracted variable '{var_name}': {extracted_val}")
        except Exception as e:
            logger.error(f"Failed to extract variable '{var_name}': {e}")

        return variables

    async def execute_turn(
        self,
        call_id: str,
        agent: dict,
        user_input: Optional[str] = None,
        dtmf_input: Optional[str] = None
    ) -> Tuple[str, dict]:
        """
        Processes a turn of the conversation:
        1. Fetch/restore call session context from database.
        2. Advance state machine if user input is provided.
        3. Sweep through sequential non-input nodes.
        4. Save/update context and return final TeXML instructions.
        """
        
        # 1. Fetch Call Context
        call_result = await asyncio.to_thread(
            self.db.table("calls").select("context, caller_phone_number").eq("id", call_id).execute
        )
        if not call_result.data:
            raise ValueError(f"Call session {call_id} not found")

        call_data = call_result.data[0]
        context = call_data.get("context") or {}
        caller_phone = call_data.get("caller_phone_number") or ""
        
        variables = context.get("variables") or {}
        current_node_id = context.get("current_node_id")
        
        # Initialize variables
        if not variables:
            variables["caller_phone"] = caller_phone
            variables["call_timestamp"] = datetime.now().isoformat()
            variables["call_id"] = call_id

        workflow_data = self._get_workflow_data(agent)
        nodes = workflow_data.get("nodes") or []
        connections = workflow_data.get("connections") or []
        node_map = {n.get("id"): n for n in nodes}

        # 2. Advance state machine on user action
        if current_node_id and (user_input or dtmf_input):
            current_node = node_map.get(current_node_id)
            if current_node:
                node_type = current_node.get("type")
                
                # Update variables based on node type
                if node_type == "extract_variable":
                    variables = await self._execute_variable_extraction(current_node, variables, user_input)
                elif node_type == "press_digit" and dtmf_input:
                    variables["pressed_digit"] = dtmf_input
                elif node_type == "subagent":
                    _, is_finished = await self._execute_subagent(current_node, variables, user_input)
                    # If subagent is NOT finished, we keep the call parked on this node
                    if not is_finished:
                        reply, _ = await self._execute_subagent(current_node, variables, user_input)
                        # Immediately return the subagent's response
                        context["variables"] = variables
                        await asyncio.to_thread(
                            self.db.table("calls").update({"context": context}).eq("id", call_id).execute
                        )
                        texml_instructions = self._build_gather_xml(reply, call_id, agent["id"], agent=agent)
                        return texml_instructions, context

                # Advance to the next node
                next_node_id = None
                if node_type == "logic_split":
                    next_node_id = await self._evaluate_logic_split(current_node, variables, connections)
                else:
                    # Semantic classification if there are multiple outgoing routes
                    next_node_id = await self._execute_semantic_routing(current_node_id, connections, nodes, user_input or "")

                if next_node_id:
                    current_node_id = next_node_id
                else:
                    # Default: get first connection or end call
                    outgoing = [c for c in connections if c.get("sourceId") == current_node_id]
                    if outgoing:
                        current_node_id = outgoing[0].get("targetId")
                    else:
                        current_node_id = None

        # If no current node, start from the beginning
        if not current_node_id:
            start_node = self._find_start_node(workflow_data)
            if start_node:
                current_node_id = start_node.get("id")
            else:
                logger.warning("No nodes found in agent workflow")
                return self._build_hangup_xml("Goodbye.", agent=agent, voice_name=voice_name), {}

        # 3. Sweep Through Sequential Non-blocking Nodes
        accumulated_speech = []
        is_blocking = False
        texml_instructions = ""

        # Avoid infinite loops in misconfigured flows
        loop_counter = 0
        max_loops = 20

        while current_node_id and not is_blocking and loop_counter < max_loops:
            loop_counter += 1
            node = node_map.get(current_node_id)
            if not node:
                logger.warning(f"Target node '{current_node_id}' not found in canvas")
                break

            node_type = node.get("type")
            node_data = node.get("data") or {}
            logger.info(f"Executing node: ID='{current_node_id}' Type='{node_type}' Title='{node_data.get('title')}'")

            if node_type == "conversation":
                prompt = node_data.get("prompt") or ""
                speech = self._interpolate_variables(prompt, variables)
                if speech:
                    accumulated_speech.append(speech)
                
                # Check next nodes
                outgoing = [c for c in connections if c.get("sourceId") == current_node_id]
                if not outgoing:
                    # End of flow
                    current_node_id = None
                elif len(outgoing) == 1:
                    current_node_id = outgoing[0].get("targetId")
                else:
                    # Stop here to wait for user input to route semantically
                    is_blocking = True

            elif node_type == "function":
                variables = await self._execute_webhook(node, variables)
                outgoing = [c for c in connections if c.get("sourceId") == current_node_id]
                current_node_id = outgoing[0].get("targetId") if outgoing else None

            elif node_type == "logic_split":
                current_node_id = await self._evaluate_logic_split(node, variables, connections)

            elif node_type == "subagent":
                # Start subagent dialog
                reply, is_finished = await self._execute_subagent(node, variables, None)
                accumulated_speech.append(reply)
                if is_finished:
                    # Immediately advance to next node
                    outgoing = [c for c in connections if c.get("sourceId") == current_node_id]
                    current_node_id = outgoing[0].get("targetId") if outgoing else None
                else:
                    # Keep parked waiting for subagent answers
                    is_blocking = True

            elif node_type == "call_transfer":
                phone = node_data.get("phoneNumber") or ""
                if phone:
                    speech = self._interpolate_variables(node_data.get("transferReason", ""), variables)
                    if speech:
                        accumulated_speech.append(speech)
                    
                    full_speech = " ".join(accumulated_speech)
                    texml_instructions = self._build_dial_xml(full_speech, phone, agent=agent, voice_name=voice_name)
                    is_blocking = True
                else:
                    logger.warning(f"Call Transfer node {current_node_id} has no phone number")
                    outgoing = [c for c in connections if c.get("sourceId") == current_node_id]
                    current_node_id = outgoing[0].get("targetId") if outgoing else None

            elif node_type == "press_digit":
                # Wait for DTMF input
                is_blocking = True

            elif node_type == "extract_variable":
                prompt = node_data.get("prompt") or ""
                speech = self._interpolate_variables(prompt, variables)
                if speech:
                    accumulated_speech.append(speech)
                is_blocking = True

            elif node_type == "ending":
                full_speech = " ".join(accumulated_speech)
                texml_instructions = self._build_hangup_xml(full_speech, agent=agent, voice_name=voice_name)
                is_blocking = True
                current_node_id = None

            elif node_type == "note":
                # Notes are structural comments, ignore and advance
                outgoing = [c for c in connections if c.get("sourceId") == current_node_id]
                current_node_id = outgoing[0].get("targetId") if outgoing else None
            
            else:
                # General LLM or unknown fallback
                outgoing = [c for c in connections if c.get("sourceId") == current_node_id]
                current_node_id = outgoing[0].get("targetId") if outgoing else None

        # 4. Save and Compile Response
        context["current_node_id"] = current_node_id
        context["variables"] = variables

        await asyncio.to_thread(
            self.db.table("calls").update({
                "context": context,
                "status": "in_progress"
            }).eq("id", call_id).execute
        )

        if not texml_instructions:
            full_speech = " ".join(accumulated_speech)
            texml_instructions = self._build_gather_xml(full_speech, call_id, agent["id"], agent=agent)

        return texml_instructions, context

    # ── TeXML Helpers ──────────────────────────────────────────
    def _build_gather_xml(self, speech_text: str, call_id: str, agent_id: str, agent: dict | None = None) -> str:
        """Returns TeXML response with a Media Stream Connect instead of Gather."""
        root = ET.Element("Response")
        connect = ET.SubElement(root, "Connect")
        stream = ET.SubElement(connect, "Stream")
        stream.set("url", f"wss://voice.example.com/api/v1/voice/ws")
        
        xml_content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return xml_content.decode("utf-8")

    def _build_dial_xml(self, speech_text: str, phone_number: str, agent: dict | None = None, voice_name: str = "alice") -> str:
        """Returns TeXML response that dials/transfers to another number"""
        root = ET.Element("Response")
        dial = ET.SubElement(root, "Dial")
        dial.text = phone_number
        
        xml_content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return xml_content.decode("utf-8")

    def _build_hangup_xml(self, speech_text: str, agent: dict | None = None, voice_name: str = "alice") -> str:
        """Returns TeXML response that hangs up"""
        root = ET.Element("Response")
        ET.SubElement(root, "Hangup")
        
        xml_content = ET.tostring(root, encoding="utf-8", xml_declaration=True)
        return xml_content.decode("utf-8")
