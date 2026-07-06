from fastapi import APIRouter, Depends, HTTPException
from typing import Dict, Any
from app.db.client import get_db, Client
import logging

router = APIRouter()
logger = logging.getLogger(__name__)


@router.get("/{workspace_id}/phone-numbers")
async def list_phone_numbers(workspace_id: str, db: Client = Depends(get_db)):
    # Fetch from legacy phone_numbers table
    pn_result = (
        db.table("phone_numbers")
        .select("*, agents(id, name)")
        .eq("workspace_id", workspace_id)
        .neq("status", "deleted")
        .order("created_at", desc=True)
        .execute()
    )

    # Also fetch from did_numbers (managed by admin panel)
    did_result = (
        db.table("did_numbers")
        .select("*, agents(id, name)")
        .eq("workspace_id", workspace_id)
        .neq("status", "deleted")
        .order("created_at", desc=True)
        .execute()
    )

    # Normalise did_numbers rows to match phone_numbers shape
    did_ids = {row["id"] for row in pn_result.data}  # avoid duplicates if somehow present in both
    normalised_dids = []
    for d in (did_result.data or []):
        if d["id"] not in did_ids:
            normalised_dids.append({
                **d,
                "friendly_name": d.get("label") or d.get("phone_number"),
                "provider_id": d.get("id"),
                "inbound_enabled": d.get("inbound_enabled", False),
                "outbound_enabled": d.get("outbound_enabled", True),
                "source": "did_numbers",   # hint for frontend if needed
            })

    return pn_result.data + normalised_dids


@router.post("/{workspace_id}/phone-numbers")
async def add_phone_number(workspace_id: str, body: Dict[str, Any], db: Client = Depends(get_db)):
    phone_number: str = (body.get("phone_number") or "").strip()
    if not phone_number:
        raise HTTPException(status_code=400, detail="phone_number is required")

    # provider_id must be unique; use phone_number itself if not provided
    provider_id = (body.get("provider_id") or phone_number).strip()

    # Detect country code from E.164 if not supplied
    country_code = (body.get("country_code") or "").strip()
    if not country_code and phone_number.startswith("+1"):
        country_code = "US"
    elif not country_code:
        country_code = "US"

    payload = {
        "workspace_id": workspace_id,
        "phone_number": phone_number,
        "country_code": country_code,
        "friendly_name": body.get("friendly_name") or phone_number,
        "provider": body.get("provider") or "telnyx",
        "provider_id": provider_id,
        "agent_id": body.get("agent_id") or None,
        "inbound_enabled": body.get("inbound_enabled", True),
        "outbound_enabled": body.get("outbound_enabled", True),
        "status": "active",
    }

    try:
        result = db.table("phone_numbers").insert(payload).execute()
    except Exception as e:
        err = str(e)
        if "unique" in err.lower() or "duplicate" in err.lower():
            raise HTTPException(status_code=409, detail="Phone number already exists in this workspace")
        logger.error("Failed to insert phone number: %s", e)
        raise HTTPException(status_code=500, detail=str(e))

    return result.data[0]


@router.patch("/{workspace_id}/phone-numbers/{phone_number_id}")
async def update_phone_number(
    workspace_id: str,
    phone_number_id: str,
    body: Dict[str, Any],
    db: Client = Depends(get_db),
):
    # Try public.phone_numbers first
    existing = (
        db.table("phone_numbers")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("id", phone_number_id)
        .execute()
    )
    
    if existing.data:
        allowed_fields = {"agent_id", "friendly_name", "inbound_enabled", "outbound_enabled"}
        update_payload = {k: v for k, v in body.items() if k in allowed_fields}
        if not update_payload:
            raise HTTPException(status_code=400, detail="No updatable fields provided")
        if "agent_id" in body and not body["agent_id"]:
            update_payload["agent_id"] = None

        result = (
            db.table("phone_numbers")
            .update(update_payload)
            .eq("workspace_id", workspace_id)
            .eq("id", phone_number_id)
            .execute()
        )
        return result.data[0]

    # Try public.did_numbers next
    existing_did = (
        db.table("did_numbers")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("id", phone_number_id)
        .execute()
    )

    if existing_did.data:
        # Map fields to did_numbers schema
        did_payload = {}
        if "agent_id" in body:
            did_payload["agent_id"] = body["agent_id"] or None
        if "friendly_name" in body:
            did_payload["label"] = body["friendly_name"] or None
        if "inbound_enabled" in body:
            did_payload["inbound_enabled"] = bool(body["inbound_enabled"])
        if "outbound_enabled" in body:
            did_payload["outbound_enabled"] = bool(body["outbound_enabled"])

        result = (
            db.table("did_numbers")
            .update(did_payload)
            .eq("workspace_id", workspace_id)
            .eq("id", phone_number_id)
            .execute()
        )
        updated = result.data[0]
        return {
            **updated,
            "friendly_name": updated.get("label") or updated.get("phone_number"),
            "provider_id": updated.get("id"),
        }

    raise HTTPException(status_code=404, detail="Phone number or DID not found in this workspace")


@router.delete("/{workspace_id}/phone-numbers/{phone_number_id}")
async def delete_phone_number(
    workspace_id: str,
    phone_number_id: str,
    db: Client = Depends(get_db),
):
    # Try public.phone_numbers first
    existing = (
        db.table("phone_numbers")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("id", phone_number_id)
        .execute()
    )
    if existing.data:
        db.table("phone_numbers").update({"status": "deleted", "agent_id": None}).eq("id", phone_number_id).execute()
        return {"status": "deleted"}

    # Try public.did_numbers next. For DIDs, delete/release from workspace means unassigning.
    existing_did = (
        db.table("did_numbers")
        .select("id")
        .eq("workspace_id", workspace_id)
        .eq("id", phone_number_id)
        .execute()
    )
    if existing_did.data:
        db.table("did_numbers").update({"workspace_id": None, "agent_id": None}).eq("id", phone_number_id).execute()
        return {"status": "deleted", "unassigned": True}

    raise HTTPException(status_code=404, detail="Phone number or DID not found in this workspace")

