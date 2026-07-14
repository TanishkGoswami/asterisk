import asyncio
import json
import logging
import re
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

import traceback

from app.core.config import settings
from app.db.client import get_supabase_client
from app.services.llm_service import LLMService
from app.services.stt_service import (
    STTService,
    EVT_SPEECH_STARTED,
    EVT_INTERIM,
    EVT_FINAL,
    EVT_SPEECH_FINAL,
    EVT_UTTERANCE_END,
    EVT_ERROR
)
from app.services.tts_service import WarmTTSConnection
from app.services.sarvam_tts import WarmSarvamConnection
from app.services.tts_router import route_tts
from app.utils.audio_conversion import ensure_pcm16_mono_8khz, chunk_pcm_for_telephony
from app.voice_config import voice_cfg
from app.core.logging_config import get_structured_logger
from app.api.v1.diagnostics import diagnostics

logger = get_structured_logger("asterisk.audiosocket")


async def read_packet(reader: asyncio.StreamReader) -> tuple[int, bytes]:
    """
    Reads a framed AudioSocket packet.
    Format: 1-byte message type, 2-byte payload length (big-endian), payload bytes.
    Raises ConnectionError on incomplete reads/disconnections.
    """
    try:
        header = await reader.readexactly(3)
    except asyncio.IncompleteReadError as e:
        raise ConnectionError(f"AudioSocket EOF before packet header: {e}")

    msg_type = header[0]
    payload_len = int.from_bytes(header[1:3], byteorder='big')
    if payload_len > 0:
        try:
            payload = await reader.readexactly(payload_len)
        except asyncio.IncompleteReadError as e:
            raise ConnectionError(f"AudioSocket EOF before payload: {e}")
    else:
        payload = b''
    return msg_type, payload


def format_packet(msg_type: int, payload: bytes) -> bytes:
    """
    Formats payload into an AudioSocket framed packet.
    """
    payload_len = len(payload)
    header = bytes([msg_type]) + payload_len.to_bytes(2, byteorder='big')
    return header + payload


class AsteriskVoiceSession:
    """
    Handles a single active call session over raw TCP AudioSocket.
    Integrates with STT, LLM, and TTS pipelines.
    """

    def __init__(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        call_uuid: str,
        context: dict
    ) -> None:
        self.reader = reader
        self.writer = writer
        self.call_uuid = call_uuid
        self.context = context
        self.config = context.get('agent_config') or {}
        self.audio_queue = asyncio.Queue(maxsize=400)
        self.messages = []
        self.llm_tts_task = None
        self.tts_tasks = []
        self.tts_conn = None
        self.sarvam_tts_conn = None
        self.barge_in_event = asyncio.Event()
        self._state = 'idle'
        self.speaking_started_at = 0.0
        self.message_sequence = 0
        self.stt_task = None
        self.greeting_active = False     # True while initial greeting is playing
        self.greeting_protected = False  # True during initial greeting playback to guard against barge-in
        # Serialises all writer.write()+drain() calls across pipeline tasks.
        # Prevents interleaved packets if a new pipeline starts while an old
        # drain() is still in flight after barge-in cancellation.
        self._writer_lock = asyncio.Lock()

        import inspect
        filepath = inspect.getfile(inspect.currentframe())
        logger.info(
            f"[Startup Check] asterisk_audiosocket.py running from: {filepath}\n"
            f"  DISABLE_STREAMING_TTS={settings.DISABLE_STREAMING_TTS}\n"
            f"  STREAMING_TTS_MODE={settings.STREAMING_TTS_MODE}\n"
            f"  TTS_PREBUFFER_MS={settings.TTS_PREBUFFER_MS}\n"
            f"  MIN_AUDIO_CHUNKS_BEFORE_PLAYBACK={settings.MIN_AUDIO_CHUNKS_BEFORE_PLAYBACK}"
        )

    def is_speaking(self) -> bool:
        return self._state == 'speaking'

    def set_state(self, state: str) -> None:
        self._state = state

    def close_from_manager(self, call_uuid: str) -> None:
        """
        Callback triggered by CallSessionManager to close the session from outside.
        """
        logger.info(f'[AsteriskVoiceSession] close_from_manager called for {call_uuid}')
        try:
            self.writer.close()
        except Exception:
            pass

    async def _send_test_beep(self, freq_hz: float = 440.0, duration_s: float = 10.0, sample_rate: int = 8000) -> None:
        """
        Send a sine wave tone through AudioSocket to verify packet framing works.
        If caller hears this beep, AudioSocket write path is correct.
        If caller hears nothing, the problem is at the Asterisk AudioSocket app layer.
        """
        import math
        import struct
        num_samples = int(sample_rate * duration_s)
        amplitude = 16000  # 16-bit range is -32768..32767
        pcm_samples = bytearray()
        for i in range(num_samples):
            sample = int(amplitude * math.sin(2 * math.pi * freq_hz * i / sample_rate))
            pcm_samples.extend(struct.pack('<h', sample))  # little-endian signed 16-bit

        pcm_bytes = bytes(pcm_samples)
        logger.info(f'[TestBeep] Sending {freq_hz}Hz sine for {duration_s}s: {len(pcm_bytes)} bytes PCM')
        await self._send_pcm_8k_to_audiosocket(pcm_bytes)

    async def pre_warm_connections(self) -> None:
        """
        Pre-warms the connections to Deepgram/Sarvam TTS servers.
        """
        voice_id = self.config.get('voice_id') or 'aura-asteria-en'
        tts_provider = self.config.get('tts_provider') or 'deepgram'
        language = self.config.get('language') or 'hi-IN'

        routed_provider = route_tts('', tts_provider, language, voice_id)
        if routed_provider == 'sarvam':
            from app.api.v1.voice_ws import _map_sarvam_speaker
            speaker = _map_sarvam_speaker(voice_id, self.config.get('voice_gender'))
            speed = float(self.config.get('voice_speed') or 0.95)
            speed = max(0.5, min(2.0, speed))
            self.sarvam_tts_conn = WarmSarvamConnection(
                api_key=settings.sarvam_api_key or '',
                speaker=speaker,
                language='hi-IN',
                output_audio_codec='pcm_8k',  # Fix B: must match _synthesize_to_pcm_8k (8kHz direct)
                pace=speed
            )
            logger.info('[AsteriskVoiceSession] Pre-warming Sarvam TTS WS for telephony (8kHz direct)...')
            asyncio.create_task(self.sarvam_tts_conn.connect())
            return
        else:
            from app.api.v1.voice_ws import _resolve_deepgram_voice
            dg_voice = _resolve_deepgram_voice(voice_id, self.config.get('voice_gender'))
            self.tts_conn = WarmTTSConnection(
                api_key=settings.deepgram_api_key or '',
                voice_id=dg_voice,
                encoding='linear16',
                sample_rate=8000
            )
            logger.info('[AsteriskVoiceSession] Pre-warming Deepgram TTS WS for telephony (8kHz)...')
            asyncio.create_task(self.tts_conn.connect())
            return

    async def cancel_llm_tts(self) -> None:
        """
        Cancels any ongoing LLM or TTS tasks (Interruption/Barge-in).
        """
        logger.info(f'[AsteriskVoiceSession] Cancelling response tasks for call {self.call_uuid}')
        if self.llm_tts_task and not self.llm_tts_task.done():
            self.llm_tts_task.cancel()
            try:
                await self.llm_tts_task
            except asyncio.CancelledError:
                pass
            except Exception as e:
                logger.error(f'[Pipeline] Error awaiting cancelled task: {e}')

        for task in self.tts_tasks:
            if not task.done():
                task.cancel()

        self.tts_tasks = []

        if self.tts_conn:
            await self.tts_conn.cancel()

        # Lock barrier: if the cancelled task was mid write+drain when it got
        # the CancelledError, that write+drain holds _writer_lock. Acquiring
        # and immediately releasing here blocks until that lock is fully
        # released — guaranteeing the socket buffer has settled before the
        # caller spins up a new pipeline task that writes fresh frames.
        async with self._writer_lock:
            pass

        self.barge_in_event.clear()
        self._state = 'idle'
        self.speaking_started_at = 0.0

    def _build_system_prompt(self) -> str:
        base = (self.config.get('agent_system_prompt') or self.config.get('system_prompt') or 'You are a helpful voice assistant.').strip()
        kb = (self.config.get('knowledge_base') or '').strip()
        voice_id = self.config.get('voice_id')
        voice_gender = self.config.get('voice_gender')

        from app.utils.post_processor import detect_voice_gender
        if voice_gender:
            gender = voice_gender.lower()
        else:
            gender = detect_voice_gender(voice_id)

        # Determine language (Hinglish/English vs pure Hindi)
        language = (self.config.get('language') or 'en-US').lower()
        is_hindi = language.startswith('hi') or (self.config.get('tts_provider') == 'sarvam')

        from app.api.v1.voice_ws import _get_male_persona_block, _get_female_persona_block
        if '--- Voice Agent Persona ---' in base:
            parts = base.split('--- Voice Agent Persona ---')
            header = parts[0].strip()
            persona_block = _get_male_persona_block() if gender == 'male' else _get_female_persona_block()
            base = f"{header}\n\n{persona_block}"
        else:
            # Fallback override if the block is not structured
            if is_hindi:
                if gender == 'male':
                    base += "\n\nOVERRIDE: आप एक पुरुष (male) भारतीय वॉयस असिस्टेंट हैं। बातचीत में पुल्लिंग हिंदी व्याकरण नियमों का उपयोग करें, जैसे: 'सकता हूँ', 'गया', 'लेता हूँ', 'देता हूँ'। स्त्रीलिंग शब्द या क्रियाओं का उपयोग न करें।"
                else:
                    base += "\n\nOVERRIDE: आप एक महिला (female) भारतीय वॉयस असिस्टेंट हैं। बातचीत में स्त्रीलिंग हिंदी व्याकरण नियमों का उपयोग करें, जैसे: 'सकती हूँ', 'गई', 'लेती हूँ', 'देती हूँ'। पुल्लिंग शब्द या क्रियाओं का उपयोग न करें।"
            else:
                if gender == 'male':
                    base += "\n\nOVERRIDE: You are a male Indian voice assistant. Use male Hinglish grammar rules: 'sakta hoon', 'gaya', 'leta hoon', 'deta hoon'. Do NOT use female phrases."
                else:
                    base += "\n\nOVERRIDE: You are a female Indian voice assistant. Use female Hinglish grammar rules: 'sakti hoon', 'gayi', 'leti hoon', 'deti hoon'. Do NOT use male phrases."

        # Strict prompt instructions based on the selected language
        if is_hindi:
            voice_prefix = (
                "You are a real-time voice assistant on a phone call. You MUST answer in short, natural Hindi (Devanagari script). "
                "Do NOT use Roman Hinglish. Speak and reply using clean, conversational Hindi. "
                "Maximum response length: 1–2 sentences. Avoid long explanations. "
                "Keep replies brief, direct, and conversational."
            )
        else:
            voice_prefix = (
                "You are a real-time voice assistant on a phone call. You MUST answer in short Hinglish. "
                "Maximum response length: 1–2 sentences. Avoid long explanations. "
                "Use natural spoken language. Never generate paragraphs for voice calls. "
                "Keep replies brief, direct, and conversational."
            )

        full = f"{voice_prefix}\n\n{base}"
        if kb:
            full += f"\n\nKnowledge base:\n{kb}"
        return full

    async def trigger_initial_greeting(self) -> None:
        """
        Triggers the initial welcome greeting asynchronously.
        """
        logger.info(f'[AsteriskVoiceSession] Triggering initial greeting for call {self.call_uuid}')
        self.greeting_active = True
        self.greeting_protected = True
        self.llm_tts_task = asyncio.create_task(
            self.run_llm_tts_pipeline('', is_greeting=True)
        )

    async def send_audio(self, audio_data: bytes, pcm_already_8khz: bool = False) -> None:
        """
        Normalizes and streams audio bytes back to Asterisk via TCP AudioSocket.
        Input may be raw PCM at any sample rate - always resampled to 8kHz 16-bit mono.
        If pcm_already_8khz=True, skip conversion (data already at 8kHz 16-bit mono).
        """
        if not audio_data:
            return

        start_time = time.time()

        # --- Diagnostic: log raw chunk info ---
        raw_len = len(audio_data)
        first_bytes_hex = audio_data[:32].hex()
        is_wav = audio_data.startswith(b'RIFF') and b'WAVE' in audio_data[:16]
        is_mp3 = audio_data.startswith(b'\xff\xfb') or audio_data.startswith(b'ID3')
        detected_fmt = 'wav' if is_wav else ('mp3' if is_mp3 else 'pcm')
        logger.info(
            f'[Audio] raw input: fmt={detected_fmt}, bytes={raw_len}, '
            f'already_8khz={pcm_already_8khz}, first32={first_bytes_hex}'
        )

        # --- Convert to 8kHz 16-bit mono PCM ---
        if pcm_already_8khz:
            pcm_8k = audio_data
        else:
            pcm_8k = ensure_pcm16_mono_8khz(audio_data)
        if not pcm_8k:
            logger.error('[Audio] ensure_pcm16_mono_8khz returned empty bytes - dropping chunk')
            return

        logger.info(f'[Audio] converted pcm: bytes={len(pcm_8k)}, rate=8000, mono=True, sample_width=2')
        await self._send_pcm_8k_to_audiosocket(pcm_8k)

    async def _send_pcm_8k_to_audiosocket(self, pcm_bytes: bytes) -> None:
        """
        Sends raw 8kHz 16-bit mono little-endian PCM bytes over AudioSocket.
        Splits into 320-byte chunks (20ms payload) and builds packet format:
        1 byte packet type (0x10), 2 bytes payload length (big-endian), payload PCM.
        Paces transmission using asyncio.sleep(0.02) to match real-time playback.
        """
        if not pcm_bytes:
            return

        start_time = time.time()
        chunks = chunk_pcm_for_telephony(pcm_bytes, chunk_size=320)
        chunk_num = 0
        offset = 0
        write_errors = 0
        total_chunks = len(chunks)

        for chunk in chunks:
            if self.writer.is_closing():
                logger.info(f'[AudioSocket] Writer closed mid-playback at chunk {chunk_num}')
                break
            packet = bytes([0x10]) + len(chunk).to_bytes(2, "big") + chunk
            async with self._writer_lock:
                self.writer.write(packet)
                try:
                    await self.writer.drain()
                except Exception as e:
                    write_errors += 1
                    logger.error(f'[AudioSocket] Drain error at chunk {chunk_num}: {e}')
                    break
            
            chunk_num += 1
            logger.info(
                f'[AudioSocket] sending chunk {chunk_num} payload={len(chunk)} '
                f'packet={len(packet)}'
            )
            offset += len(chunk)
            await asyncio.sleep(0.02)

        duration_ms = int((time.time() - start_time) * 1000)
        logger.info(f'[AudioSocket] playback send complete: total_pcm_bytes={offset}, chunks={chunk_num}')

        diagnostics.record_audio_send(
            status='success' if write_errors == 0 else 'error',
            chunks_sent=chunk_num,
            bytes_sent=offset,
            duration_ms=duration_ms
        )
        diagnostics.update_session_state(
            self.call_uuid,
            state=self._state,
            audio_sent=offset
        )

    async def _synthesize_to_pcm_8k(self, text: str, chunk_idx: int) -> bytes:
        """
        Synthesize text to 8kHz 16-bit mono PCM using whichever TTS provider
        is configured. Returns empty bytes on failure.
        """
        routed_provider = 'unknown'
        start = time.time()
        try:
            from app.utils.post_processor import apply_hinglish_post_processing
            v_gender = self.config.get('voice_gender') or self.config.get('voice_id') or 'female'
            text = apply_hinglish_post_processing(text, v_gender)

            routed_provider = route_tts(
                text,
                self.config.get('tts_provider'),
                self.config.get('language'),
                self.config.get('voice_id')
            )
            logger.info(f'[TTS] chunk #{chunk_idx} provider={routed_provider}')

            if routed_provider == 'sarvam':
                if self.sarvam_tts_conn is None:
                    from app.api.v1.voice_ws import _map_sarvam_speaker
                    speaker = _map_sarvam_speaker(self.config.get('voice_id'), self.config.get('voice_gender'))
                    speed = float(self.config.get('voice_speed') or 0.95)
                    speed = max(0.5, min(2.0, speed))
                    # Request 8kHz PCM directly from Sarvam to avoid any local resampling.
                    # Sarvam's linear16 codec accepts speech_sample_rate=8000, returning
                    # 8kHz 16-bit mono PCM which is exactly what AudioSocket needs.
                    self.sarvam_tts_conn = WarmSarvamConnection(
                        api_key=settings.sarvam_api_key or '',
                        speaker=speaker,
                        language='hi-IN',
                        output_audio_codec='pcm_8k',  # triggers 8kHz request in WarmSarvamConnection
                        pace=speed
                    )
                    logger.info('[TTS] Sarvam WS created at 8kHz (lazy init, no resample needed)')
                    await self.sarvam_tts_conn.connect()

                logger.info(f'[TTS] Sarvam speak() -> "{text[:80]}"')
                raw_chunks: list[bytes] = []
                async for audio_chunk in self.sarvam_tts_conn.speak(text):
                    if audio_chunk:
                        raw_chunks.append(audio_chunk)

                if not raw_chunks:
                    logger.warning(f'[TTS] Sarvam returned zero bytes for chunk #{chunk_idx}')
                    return b''

                pcm_8k = b''.join(raw_chunks)
                logger.info(
                    f'[TTS] Sarvam raw 8kHz: bytes={len(pcm_8k)}, '
                    f'first32={pcm_8k[:32].hex()}'
                )

                # Strip WAV header if Sarvam returned WAV instead of raw PCM
                if pcm_8k.startswith(b'RIFF') and b'WAVE' in pcm_8k[:16]:
                    logger.info('[TTS] Sarvam returned WAV - stripping RIFF header')
                    data_idx = pcm_8k.find(b'data')
                    pcm_8k = pcm_8k[data_idx + 8:] if data_idx != -1 else pcm_8k[44:]

                # No resampling needed: Sarvam returned 8kHz PCM directly

            else:
                # Deepgram streams 8kHz 16-bit linear PCM directly
                if self.tts_conn is None:
                    from app.api.v1.voice_ws import _resolve_deepgram_voice
                    dg_voice = _resolve_deepgram_voice(self.config.get('voice_id'), self.config.get('voice_gender'))
                    self.tts_conn = WarmTTSConnection(
                        api_key=settings.deepgram_api_key or '',
                        voice_id=dg_voice,
                        encoding='linear16',
                        sample_rate=8000
                    )
                    logger.info('[TTS] Deepgram WS created (lazy init)')
                    await self.tts_conn.connect()

                logger.info(f'[TTS] Deepgram speak() -> "{text[:80]}"')
                dg_chunks: list[bytes] = []
                async for audio_chunk in self.tts_conn.speak(text):
                    if audio_chunk:
                        dg_chunks.append(audio_chunk)

                pcm_8k = b''.join(dg_chunks)
                logger.info(f'[TTS] Deepgram raw: bytes={len(pcm_8k)}, first32={pcm_8k[:32].hex()}')

            ms = int((time.time() - start) * 1000)
            logger.info(
                f'[TTS] chunk #{chunk_idx} synthesized in {ms}ms, pcm_8k_bytes={len(pcm_8k)}, '
                f'rate=8000, mono=True, sample_width=2'
            )
            diagnostics.record_tts_generation(
                status='success', provider=routed_provider,
                duration_ms=ms, output_bytes=len(pcm_8k), text=text
            )
            return pcm_8k

        except Exception as e:
            logger.error(
                f'[TTS] chunk #{chunk_idx} FAILED: {type(e).__name__}: {e}\n{traceback.format_exc()}'
            )
            diagnostics.record_tts_generation(
                status='error', provider=routed_provider,
                duration_ms=int((time.time() - start) * 1000),
                output_bytes=0, text=text, error_message=str(e)
            )
            return b''

    async def run_llm_tts_pipeline(self, transcript: str, is_greeting: bool = False) -> None:
        """
        Processes the AI pipeline: LLM stream -> TTS -> PCM resample -> AudioSocket.
        """
        pipeline_start = time.time()
        pipeline_type = 'greeting' if is_greeting else 'response'
        logger.info(f'[Pipeline] STARTED {pipeline_type.upper()} for call {self.call_uuid}')

        self.set_state('processing')
        self.barge_in_event.clear()

        if not is_greeting and transcript.strip():
            user_seq = self.message_sequence + 1
            assistant_seq = self.message_sequence + 2
            self.message_sequence = assistant_seq
        else:
            user_seq = None
            assistant_seq = self.message_sequence + 1
            self.message_sequence = assistant_seq

        if not is_greeting and transcript.strip():
            self.messages.append({'role': 'user', 'content': transcript})
            logger.info(f'[Pipeline] User transcript: "{transcript[:120]}"')
            if user_seq:
                try:
                    def _insert_user_msg(seq: int):
                        db = get_supabase_client()
                        db.table('call_messages').insert({
                            'call_id': self.call_uuid,
                            'role': 'user',
                            'content': transcript,
                            'sequence_number': seq,
                            'started_at': datetime.now(timezone.utc).isoformat()
                        }).execute()
                    asyncio.create_task(asyncio.to_thread(_insert_user_msg, user_seq))
                except Exception as e:
                    logger.error(f'Failed to log user message: {e}')

        if is_greeting:
            language = self.config.get('language') or 'hi-IN'
            prompt_instruction = 'Generate a short, friendly, conversational welcome greeting for the caller to start the call.'
            if language.lower().startswith('hi'):
                prompt_instruction += ' Speak in Roman Hinglish (mix of Hindi/English).'
            else:
                prompt_instruction += ' Speak in English.'
            compressed_history = [{'role': 'user', 'content': prompt_instruction}]
            logger.info(f'[Pipeline] Greeting prompt language: {language}')
        else:
            compressed_history = self.messages[-10:]

        # --- If diagnostic beep mode is ON, bypass TTS entirely ---
        if settings.asterisk_test_beep_on_connect:
            logger.info('[Pipeline] ASTERISK_TEST_BEEP=true - bypassing TTS, sending 440Hz sine')
            await self._send_test_beep()
            self.set_state('idle')
            if is_greeting:
                self.greeting_active = False
                self.greeting_protected = False
            return

        def _insert_assist_msg(seq: int, response_text: str, model_name: str):
            """DB write - runs in a thread, all args passed explicitly."""
            try:
                db = get_supabase_client()
                db.table('call_messages').insert({
                    'call_id': self.call_uuid,
                    'role': 'assistant',
                    'content': response_text,
                    'sequence_number': seq,
                    'started_at': datetime.now(timezone.utc).isoformat(),
                    'model_used': model_name
                }).execute()
            except Exception as db_err:
                logger.error(f'[Pipeline] Failed to persist assistant message: {db_err}')

        def ends_with_punctuation(w: str) -> bool:
            return len(w) > 0 and w[-1] in ('.', '!', '?', '\u0964')

        # ----------------------------------------------------------------
        # Collect ALL text chunks from LLM first, then synthesize in order.
        # This eliminates the queue race condition where stream_finished_event
        # could fire before playback_worker has registered chunk_queues[0].
        # ----------------------------------------------------------------
        llm = LLMService(
            openai_key=settings.openai_api_key,
            anthropic_key=settings.anthropic_api_key
        )
        model = self.config.get('model') or voice_cfg.OPENAI_VOICE_MODEL
        logger.info(f'[Pipeline] OpenAI request -> model={model}, max_tokens={voice_cfg.OPENAI_MAX_OUTPUT_TOKENS}')

        try:
            full_response = ''
            first_token_logged = False
            llm_first_token_time = None

            if settings.DISABLE_STREAMING_TTS:
                logger.info(f'[Pipeline] MODE_USED=FULL_RESPONSE_TTS for call {self.call_uuid}')
                llm_stream = llm.generate_stream(
                    system_prompt=self._build_system_prompt(),
                    messages=compressed_history,
                    model=model,
                    temperature=0.7,
                    max_tokens=voice_cfg.OPENAI_MAX_OUTPUT_TOKENS
                )
                async for token in llm_stream:
                    if self.barge_in_event.is_set():
                        logger.info(f'[Pipeline] Barge-in during LLM stream for call {self.call_uuid}')
                        break
                    if not first_token_logged:
                        first_token_logged = True
                        llm_first_token_time = time.time()
                        logger.info(f'[Pipeline] LLM First Token Time: {int((llm_first_token_time - pipeline_start) * 1000)}ms')
                    full_response += token

                if not self.barge_in_event.is_set():
                    tts_call_count = 0
                    tts_call_count += 1
                    if tts_call_count > 1:
                        raise AssertionError('DISABLE_STREAMING_TTS is True but more than one TTS call happened!')

                    logger.info(f'[Pipeline] calling TTS: FULL_TEXT_LENGTH={len(full_response)}')
                    pcm_8k = await self._synthesize_to_pcm_8k(full_response, 0)
                    pcm_bytes = len(pcm_8k)
                    duration_ms = int(pcm_bytes / 16)

                    logger.info(
                        f'[Pipeline] TTS complete:\n'
                        f'  FULL_TEXT_LENGTH={len(full_response)}\n'
                        f'  TTS_CALL_COUNT={tts_call_count}\n'
                        f'  FULL_PCM_BYTES={pcm_bytes}\n'
                        f'  FULL_AUDIO_DURATION_MS={duration_ms}'
                    )

                    import wave
                    try:
                        with wave.open('debug_full_response.wav', 'wb') as wav_file:
                            wav_file.setnchannels(1)
                            wav_file.setsampwidth(2)
                            wav_file.setframerate(8000)
                            wav_file.writeframes(pcm_8k)
                        logger.info('[Pipeline] Saved WAV to debug_full_response.wav')
                    except Exception as wav_err:
                        logger.error(f'Failed to save WAV: {wav_err}')

                    offset = 0
                    frame_count = 0
                    underflow_count = 0

                    logger.info(f'[Pipeline] Playback Start [Playback Buffer Size: {pcm_bytes} bytes ({duration_ms}ms)]')
                    playback_start_t = time.time()
                    logger.info(f'[Pipeline] Playback Start: {int((playback_start_t - pipeline_start) * 1000)}ms')

                    # Absolute-deadline pacing: each frame must be sent at a fixed
                    # 20ms interval. Using monotonic clock avoids drift caused by
                    # the non-zero time that writer.drain() takes on each iteration.
                    next_send_time = time.monotonic()

                    while offset < pcm_bytes and not self.barge_in_event.is_set():
                        chunk = pcm_8k[offset:offset+320]
                        offset += 320
                        frame_count += 1

                        if self._state != 'speaking':
                            self.set_state('speaking')
                            self.speaking_started_at = time.time()
                            logger.info(f'[Pipeline] Speaking started for call {self.call_uuid}')

                        if self.writer.is_closing():
                            logger.info(f'[AudioSocket] Writer closed mid-playback')
                            break

                        packet = bytes([0x10]) + len(chunk).to_bytes(2, 'big') + chunk
                        async with self._writer_lock:
                            self.writer.write(packet)
                            try:
                                await self.writer.drain()
                            except Exception as e:
                                logger.error(f'[AudioSocket] Drain error in flat playback: {e}')
                                break

                        next_send_time += 0.02
                        remaining = next_send_time - time.monotonic()
                        if remaining > 0:
                            await asyncio.sleep(remaining)
                        else:
                            # We've fallen behind (drain took longer than 20ms).
                            # Resync deadline to now rather than burst-sending frames.
                            next_send_time = time.monotonic()

                    logger.info(
                        f'[Pipeline] Playback finished:\n'
                        f'  PLAYBACK_FRAME_COUNT={frame_count}\n'
                        f'  UNDERFLOW_COUNT={underflow_count}'
                    )

                self.set_state('idle')
                self.messages.append({'role': 'assistant', 'content': full_response})
                elapsed = int((time.time() - pipeline_start) * 1000)
                logger.info(f'[Pipeline] COMPLETED {pipeline_type.upper()} in {elapsed}ms for call {self.call_uuid}')
                try:
                    asyncio.create_task(
                        asyncio.to_thread(_insert_assist_msg, assistant_seq, full_response, model)
                    )
                except Exception as e:
                    logger.error(f'Failed to schedule assistant message DB write: {e}')
                return

            else:
                logger.info(f'[Pipeline] MODE_USED=STREAMING_TTS for call {self.call_uuid}')
                token_queue = asyncio.Queue()
                sentence_queue = asyncio.Queue()

                # Shared State Variables
                full_response = ''
                first_token_logged = False
                llm_first_token_time = None
                is_first_chunk = True
                max_built_idx = -1

                sentences_tts_started = 0
                sentences_tts_finished = 0

                playback_buffer = bytearray()
                playback_offset = 0

                # Dictionary mapping sentence_idx -> synthesized PCM bytes
                synthesized_audio = {}

                # Metrics timestamps
                sentence_ready_time = {}
                tts_start_time = {}
                tts_finish_time = {}
                sentence_played_time = {}

                # Protected / Conjunction Words
                PROTECTED_WORDS = {
                    "hai", "hoon", "ka", "ki", "ke", "ko", "se", "aur", "lekin", "because", 
                    "that", "to", "of", "raha", "rahi", "kyunki"
                }

                # Greetings list to prevent greeting-only first chunk
                GREETING_WORDS = {
                    "hello", "hi", "hey", "namaste", "namaskar", "satsriakal", "pranam", "adaab", "ola", "halo", 
                    "kaise", "ho", "aap", "tum", "kya", "haal", "hai", "sab", "theek", "ji", "haanji", "haan", 
                    "good", "morning", "afternoon", "evening", "welcome", "swagat"
                }

                def is_only_greeting(text: str) -> bool:
                    clean_text = re.sub(r'[^\w\s]', ' ', text).lower()
                    words_list = clean_text.split()
                    if not words_list:
                        return True
                    return all(w in GREETING_WORDS for w in words_list)

                def ends_with_sentence_punc(word: str) -> bool:
                    return len(word) > 0 and word[-1] in ('.', '?', '!', '\u0964')

                def ends_with_pause_punc(word: str) -> bool:
                    return len(word) > 0 and word[-1] in (',', ';', ':')

                def is_protected_word(word: str) -> bool:
                    return word.lower().strip(".,?!:;।") in PROTECTED_WORDS

                # Sentence Builder release check
                def should_release(words_list: list[str], is_first_chunk: bool) -> bool:
                    num_words = len(words_list)
                    if num_words == 0:
                        return False

                    text = ' '.join(words_list)
                    if is_first_chunk and is_only_greeting(text):
                        return False

                    last_word = words_list[-1]
                    if ends_with_sentence_punc(last_word):
                        return True

                    if ends_with_pause_punc(last_word) and num_words > 18 and not is_protected_word(last_word):
                        return True

                    # Upper safety fallback limit
                    if num_words >= 28 and not is_protected_word(last_word):
                        return True

                    return False

                # 1. LLM Reader Task
                async def llm_reader():
                    nonlocal first_token_logged, full_response, llm_first_token_time
                    try:
                        llm_stream = llm.generate_stream(
                            system_prompt=self._build_system_prompt(),
                            messages=compressed_history,
                            model=model,
                            temperature=0.7,
                            max_tokens=voice_cfg.OPENAI_MAX_OUTPUT_TOKENS
                        )
                        async for token in llm_stream:
                            if self.barge_in_event.is_set():
                                logger.info(f'[Pipeline] Barge-in during LLM stream for call {self.call_uuid}')
                                break
                            if not first_token_logged:
                                first_token_logged = True
                                llm_first_token_time = time.time()
                                logger.info(f'[Pipeline] LLM First Token Time: {int((llm_first_token_time - pipeline_start) * 1000)}ms')

                            full_response += token
                            if not settings.DISABLE_STREAMING_TTS:
                                await token_queue.put(token)

                        if settings.DISABLE_STREAMING_TTS and not self.barge_in_event.is_set():
                            await token_queue.put(full_response)
                    finally:
                        await token_queue.put(None)

                # 2. Sentence Builder Task
                async def speech_chunker():
                    nonlocal is_first_chunk, max_built_idx
                    words_list = []
                    token_buffer = ""
                    sentence_idx = 0

                    while True:
                        token = await token_queue.get()
                        if token is None:
                            break

                        token_buffer += token
                        temp_words = token_buffer.split()
                        if not token.endswith(' ') and temp_words:
                            completed_words = temp_words[:-1]
                            token_buffer = temp_words[-1]
                        else:
                            completed_words = temp_words
                            token_buffer = ''

                        for word in completed_words:
                            words_list.append(word)

                            if should_release(words_list, is_first_chunk):
                                chunk_text = ' '.join(words_list)
                                sentence_ready_time[sentence_idx] = time.time()
                                logger.info(f"[Pipeline] Sentence {sentence_idx} Ready: '{chunk_text[:50]}'")

                                await sentence_queue.put((sentence_idx, chunk_text))
                                max_built_idx = sentence_idx

                                sentence_idx += 1
                                words_list = []
                                is_first_chunk = False

                    if token_buffer.strip():
                        words_list.append(token_buffer.strip())

                    if words_list:
                        chunk_text = ' '.join(words_list)
                        if chunk_text.strip():
                            sentence_ready_time[sentence_idx] = time.time()
                            logger.info(f"[Pipeline] Sentence {sentence_idx} Ready (Flush): '{chunk_text[:50]}'")
                            await sentence_queue.put((sentence_idx, chunk_text))
                            max_built_idx = sentence_idx
                            sentence_idx += 1

                    await sentence_queue.put(None)

                # 3. TTS Worker Pool Task
                async def tts_worker(worker_id: int):
                    nonlocal sentences_tts_started, sentences_tts_finished
                    while True:
                        item = await sentence_queue.get()
                        if item is None:
                            await sentence_queue.put(None)
                            break

                        idx, text = item

                        tts_start_time[idx] = time.time()
                        wait_time_ms = int((tts_start_time[idx] - sentence_ready_time[idx]) * 1000)
                        logger.info(f"[Pipeline] Sentence {idx} TTS Start (Worker {worker_id}) [TTS Queue Wait Time: {wait_time_ms}ms]")
                        sentences_tts_started += 1

                        # High Water Mark buffering protection (> 3 seconds worth of audio)
                        while len(playback_buffer) - playback_offset > 48000 and not self.barge_in_event.is_set():
                            await asyncio.sleep(0.1)

                        pcm_8k = await self._synthesize_to_pcm_8k(text, idx)

                        tts_finish_time[idx] = time.time()
                        duration_ms = int((tts_finish_time[idx] - tts_start_time[idx]) * 1000)
                        logger.info(f"[Pipeline] Sentence {idx} TTS Finish in {duration_ms}ms (Worker {worker_id})")

                        sentences_tts_finished += 1
                        synthesized_audio[idx] = pcm_8k

                # 4. Playback Task
                async def playback_worker():
                    nonlocal playback_offset, playback_buffer

                    lwm_800ms = int(8000 * 2 * 0.8) # 12,800 bytes
                    lwm_400ms = int(8000 * 2 * 0.4) # 6,400 bytes

                    logger.info(f"[AudioSocket] Playback buffering: waiting for LWM conditions...")

                    playback_started_logged = False
                    next_playback_idx = 0

                    while not self.barge_in_event.is_set():
                        if next_playback_idx in synthesized_audio:
                            pcm = synthesized_audio[next_playback_idx]

                            if next_playback_idx not in sentence_played_time:
                                sentence_played_time[next_playback_idx] = time.time()
                                wait_ms = int((sentence_played_time[next_playback_idx] - tts_finish_time[next_playback_idx]) * 1000)
                                logger.info(f"[Pipeline] Sentence {next_playback_idx} reached Playback [Audio Queue Wait Time: {wait_ms}ms]")

                            playback_buffer.extend(pcm)
                            del synthesized_audio[next_playback_idx]
                            next_playback_idx += 1

                        buffered_available = len(playback_buffer) - playback_offset

                        accumulator_done = (
                            sentence_queue.empty() 
                            and next_playback_idx > max_built_idx
                            and not synthesized_audio
                        )

                        sentence_1_ready = (playback_offset == 0 and len(playback_buffer) > 0)
                        sentence_2_generating = (max_built_idx >= 1)

                        if (
                            buffered_available >= lwm_800ms 
                            or (sentence_1_ready and sentence_2_generating)
                            or (accumulator_done and buffered_available > 0)
                        ):
                            if not playback_started_logged:
                                playback_started_logged = True
                                logger.info(
                                    f"[Pipeline] Playback Start [Playback Buffer Size: {buffered_available} bytes "
                                    f"({int(buffered_available/16)}ms)], sentence_1_ready={sentence_1_ready}, "
                                    f"sentence_2_generating={sentence_2_generating}, accumulator_done={accumulator_done}"
                                )
                            break
                        await asyncio.sleep(0.02)

                    # Absolute-deadline pacing for streaming mode.
                    # Initialize NOW so first frame goes immediately without overshoot.
                    next_send_time = time.monotonic()
                    underflow_count = 0

                    while not self.barge_in_event.is_set():
                        if next_playback_idx in synthesized_audio:
                            pcm = synthesized_audio[next_playback_idx]

                            if next_playback_idx not in sentence_played_time:
                                sentence_played_time[next_playback_idx] = time.time()
                                wait_ms = int((sentence_played_time[next_playback_idx] - tts_finish_time[next_playback_idx]) * 1000)
                                logger.info(f"[Pipeline] Sentence {next_playback_idx} reached Playback [Audio Queue Wait Time: {wait_ms}ms]")

                            playback_buffer.extend(pcm)
                            del synthesized_audio[next_playback_idx]
                            next_playback_idx += 1

                        buffered_available = len(playback_buffer) - playback_offset

                        accumulator_done = (
                            sentence_queue.empty() 
                            and next_playback_idx > max_built_idx
                            and not synthesized_audio
                        )

                        if buffered_available < 320:
                            if accumulator_done:
                                logger.info(f"[Pipeline] Playback complete for call {self.call_uuid}")
                                break
                            else:
                                logger.warning(
                                    f"[Pipeline] Playback Underflow: available={buffered_available} bytes, "
                                    f"next_playback_idx={next_playback_idx}, max_built_idx={max_built_idx}"
                                )
                                # Pause playback and wait for LWM 400ms
                                while not self.barge_in_event.is_set():
                                    if next_playback_idx in synthesized_audio:
                                        pcm = synthesized_audio[next_playback_idx]
                                        playback_buffer.extend(pcm)
                                        del synthesized_audio[next_playback_idx]
                                        next_playback_idx += 1

                                    buffered_available = len(playback_buffer) - playback_offset
                                    accumulator_done = (
                                        sentence_queue.empty() 
                                        and next_playback_idx > max_built_idx
                                        and not synthesized_audio
                                    )
                                    if buffered_available >= lwm_400ms or accumulator_done:
                                        underflow_count += 1
                                        logger.info(
                                            f"[Pipeline] Resuming playback after underflow pause: available={buffered_available} bytes "
                                            f"(total_underflows={underflow_count})"
                                        )
                                        if underflow_count >= 3:
                                            logger.warning(
                                                f"[Pipeline] HIGH UNDERFLOW RATE: {underflow_count} underflows so far — "
                                                f"Sarvam TTS may not be keeping up with real-time. "
                                                f"Consider increasing pre-buffer (lwm_800ms) or checking Sarvam latency."
                                            )
                                        # CRITICAL: reset deadline after waiting to avoid burst-send catch-up
                                        next_send_time = time.monotonic()
                                        break
                                    await asyncio.sleep(0.05)
                                continue

                        chunk = bytes(playback_buffer[playback_offset:playback_offset+320])
                        playback_offset += 320

                        if self._state != 'speaking':
                            self.set_state('speaking')
                            self.speaking_started_at = time.time()
                            logger.info(f'[Pipeline] Speaking started for call {self.call_uuid}')

                        if self.writer.is_closing():
                            logger.info(f'[AudioSocket] Writer closed mid-playback')
                            break

                        packet = bytes([0x10]) + len(chunk).to_bytes(2, "big") + chunk
                        async with self._writer_lock:
                            self.writer.write(packet)
                            try:
                                await self.writer.drain()
                            except Exception as e:
                                logger.error(f'[AudioSocket] Drain error in playback_pacer: {e}')
                                break

                        next_send_time += 0.02
                        remaining = next_send_time - time.monotonic()
                        if remaining > 0:
                            await asyncio.sleep(remaining)
                        else:
                            # Fallen behind: resync to avoid burst-sending on catch-up
                            next_send_time = time.monotonic()

                # 5. Pipeline Visualization Task
                async def pipeline_visualizer():
                    nonlocal playback_offset, playback_buffer
                    start_viz = time.time()
                    while not self.barge_in_event.is_set():
                        await asyncio.sleep(0.2)
                        elapsed = time.time() - start_viz

                        llm_bar = "█" * min(20, int(len(full_response) / 5))
                        sb_bar = "█" * min(20, max_built_idx + 1)
                        tts_bar = "█" * min(20, sentences_tts_finished)

                        buf_bytes = len(playback_buffer) - playback_offset
                        buf_ms = int(buf_bytes / 16)
                        buf_bar = "█" * min(20, int(buf_ms / 100))

                        play_bar = "█" * min(20, int(playback_offset / 1600))

                        tok_q_size = token_queue.qsize()
                        sent_q_size = sentence_queue.qsize()

                        logger.info(
                            f"\n--- Pipeline Visualization ({elapsed:.1f}s) ---\n"
                            f"LLM (Tokens):       {len(full_response):<4} {llm_bar} (Queue Depth: {tok_q_size})\n"
                            f"Sentence Builder:   {max_built_idx + 1:<4} {sb_bar} (Queue Depth: {sent_q_size})\n"
                            f"TTS Finished:       {sentences_tts_finished:<4} {tts_bar}\n"
                            f"Playback Buffer:    {buf_ms:<4}ms {buf_bar}\n"
                            f"Playback Offset:    {playback_offset:<4} bytes {play_bar}\n"
                            f"----------------------------------------"
                        )

                # Start concurrent workers
                reader_task = asyncio.create_task(llm_reader())
                chunker_task = asyncio.create_task(speech_chunker())
                tts_w1 = asyncio.create_task(tts_worker(worker_id=1))
                tts_w2 = asyncio.create_task(tts_worker(worker_id=2))
                playback_task = asyncio.create_task(playback_worker())
                visualizer_task = asyncio.create_task(pipeline_visualizer())

                self.tts_tasks = [reader_task, chunker_task, tts_w1, tts_w2, playback_task, visualizer_task]

                await asyncio.gather(reader_task, chunker_task, tts_w1, tts_w2, playback_task, visualizer_task)
                self.set_state('idle')
                self.messages.append({'role': 'assistant', 'content': full_response})
                elapsed = int((time.time() - pipeline_start) * 1000)
                logger.info(f'[Pipeline] COMPLETED {pipeline_type.upper()} in {elapsed}ms for call {self.call_uuid}')

                # Clean up all spawned worker tasks
                for t in self.tts_tasks:
                    if not t.done():
                        t.cancel()
                self.tts_tasks = []

                try:
                    asyncio.create_task(
                        asyncio.to_thread(_insert_assist_msg, assistant_seq, full_response, model)
                    )
                except Exception as e:
                    logger.error(f'Failed to schedule assistant message DB write: {e}')

        except asyncio.CancelledError:
            logger.info(f'[Pipeline] Cancelled ({pipeline_type}) for call {self.call_uuid}')
        except Exception as e:
            logger.error(
                f'[Pipeline] EXCEPTION in {pipeline_type} for call {self.call_uuid}: '
                f'{type(e).__name__}: {e}\n{traceback.format_exc()}'
            )
        finally:
            self.barge_in_event.clear()
            self.set_state('idle')
            if is_greeting:
                self.greeting_active = False
                self.greeting_protected = False
                logger.info(f'[Pipeline] Greeting protection lifted for call {self.call_uuid}')

    async def stt_loop(self) -> None:
        """
        Background listener task streaming incoming raw AudioSocket PCM to Deepgram STT.
        """
        stt = STTService(api_key=settings.deepgram_api_key or '')
        language = self.config.get('language') or 'hi-IN'

        try:
            async for event_type, payload in stt.stream_live(
                audio_queue=self.audio_queue,
                language=language,
                endpointing=voice_cfg.STT_ENDPOINTING_MS,
                model=voice_cfg.STT_MODEL,
                encoding='linear16',
                sample_rate='8000'
            ):
                if event_type == EVT_SPEECH_STARTED:
                    continue

                elif event_type in (EVT_INTERIM, EVT_FINAL):
                    # Do NOT barge-in while greeting is active or state is not 'speaking'
                    if self.greeting_active:
                        continue
                    transcript = payload.get('transcript', '').strip()
                    if not self.is_speaking():
                        continue
                    if not transcript:
                        continue

                    clean_text = re.sub(r'[^\w\s]', '', transcript).strip()
                    if not clean_text:
                        continue

                    elapsed_speaking = time.time() - self.speaking_started_at
                    # Guard: require at least 3 seconds before barge-in is allowed
                    if elapsed_speaking > 3.0:
                        logger.info(f'[Barge-In] Interrupting after {elapsed_speaking:.1f}s: "{transcript}"')
                        self.barge_in_event.set()
                        await self.cancel_llm_tts()

                elif event_type == EVT_SPEECH_FINAL:
                    # Do NOT process caller speech during greeting
                    if self.greeting_active:
                        logger.info(f'[STT] Speech final received during greeting, ignoring: "{payload.get("transcript", "")}"')
                        continue
                    transcript = payload.get('transcript', '').strip()
                    if not transcript:
                        continue
                    logger.transcript_final(transcript, 1.0, 0)
                    await self.cancel_llm_tts()
                    self.llm_tts_task = asyncio.create_task(
                        self.run_llm_tts_pipeline(transcript)
                    )

                elif event_type == EVT_UTTERANCE_END:
                    continue

                elif event_type == EVT_ERROR:
                    logger.error(f'[STT error] {payload}')
                    diagnostics.add_error("warning", "stt", f"STT error event: {payload}")

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.error(f'[STT loop exception] {e}', exc_info=True)
            return
        finally:
            logger.info('[stt_loop] Telephony STT loop exited')

    async def run(self) -> None:
        """
        Main runner executing the socket read loop.
        """
        await self.pre_warm_connections()

        # Diagnostic: bypass TTS entirely if ASTERISK_TEST_BEEP_ON_CONNECT=true
        # This sends a 440Hz sine wave to verify AudioSocket framing works independently
        if settings.asterisk_test_beep_on_connect:
            logger.info('[AudioSocket] TEST BEEP mode - sending 440Hz tone, skipping greeting')
            await self._send_test_beep()
        else:
            await self.trigger_initial_greeting()

        self.stt_task = asyncio.create_task(self.stt_loop())

        try:
            while True:
                msg_type, payload = await read_packet(self.reader)
                if msg_type in (0, 2):
                    logger.audiosocket_connection_closed("hangup")
                    break
                elif msg_type in (255, 3):
                    logger.error(f'[AudioSocket] Error packet received ({msg_type}) for {self.call_uuid}: {payload}')
                    diagnostics.add_error("error", "audiosocket", f"AudioSocket error packet received: {payload}")
                    break
                elif msg_type == 4:
                    continue
                elif msg_type in (16, 1):
                    if len(payload) > 0:
                        if self.stt_task is None or self.stt_task.done():
                            logger.warning('[AudioSocket] STT task was done/dead - restarting')
                            self.stt_task = asyncio.create_task(self.stt_loop())
                        try:
                            self.audio_queue.put_nowait(payload)
                            diagnostics.update_session_state(
                                self.call_uuid,
                                state=self._state,
                                audio_received=len(payload)
                            )
                        except asyncio.QueueFull:
                            pass
                else:
                    logger.warning(f'[AudioSocket] Unknown packet type {msg_type}')
        except (asyncio.IncompleteReadError, ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.audiosocket_connection_closed(f"eof: {e}")
        except Exception as e:
            logger.audiosocket_connection_error(e, "read_loop")
            diagnostics.add_error("error", "audiosocket", f"Read loop error: {str(e)}")
        finally:
            await self.cleanup()

    async def cleanup(self) -> None:
        """
        Shutdown hooks clearing active connections and background pipeline tasks.
        """
        logger.info(f'[AsteriskVoiceSession] Performing cleanup for call {self.call_uuid}')
        if self.stt_task and not self.stt_task.done():
            self.stt_task.cancel()
        await self.cancel_llm_tts()
        if self.tts_conn:
            await self.tts_conn.close()
        if self.sarvam_tts_conn:
            await self.sarvam_tts_conn.close()
        try:
            self.audio_queue.put_nowait(None)
        except Exception:
            pass


class AsteriskAudioSocketServer:
    """
    Asynchronous TCP server accepting Asterisk AudioSocket connections.
    """

    def __init__(self, host: str = '127.0.0.1', port: int = 9092) -> None:
        self.host = host
        self.port = port
        self.server = None
        self.active_connections = {}

    async def start(self) -> None:
        self.server = await asyncio.start_server(
            self.handle_connection,
            self.host,
            self.port
        )
        logger.info(f'Asterisk AudioSocket server listening on {self.host}:{self.port}')

    async def handle_connection(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        peer = writer.get_extra_info('peername')
        logger.set_context(session_uuid="unknown")
        logger.audiosocket_connection_accepted(peer[0], peer[1])
        call_uuid = None
        session = None
        try:
            logger.uuid_read_started()
            msg_type, payload = await read_packet(reader)
            try:
                import uuid
                if len(payload) == 16:
                    call_uuid = str(uuid.UUID(bytes=payload))
                else:
                    call_uuid = payload.decode('utf-8').strip()
            except Exception:
                logger.uuid_invalid(len(payload))
                writer.close()
                await writer.wait_closed()
                return

            if not call_uuid or len(call_uuid) < 3:
                logger.uuid_invalid(len(call_uuid))
                writer.close()
                await writer.wait_closed()
                return

            logger.uuid_received(call_uuid)
            logger.set_context(session_uuid=call_uuid)
            
            from app.services.call_session_manager import call_session_manager
            context = await call_session_manager.get_call_context(call_uuid)
            if not context:
                logger.agent_not_found(call_uuid)
                diagnostics.add_error("error", "audiosocket", f"Failed to find registered call details for {call_uuid}")
                writer.close()
                await writer.wait_closed()
                return

            direction = context.get("direction", "inbound")
            caller = context.get("caller_id") or ""
            callee = context.get("dialed_number") or ""
            agent_id = context.get("agent_id") or ""
            
            logger.set_context(session_uuid=call_uuid, caller=caller)
            logger.call_direction_detected(direction)
            logger.caller_info(caller, callee, agent_id)
            
            diagnostics.record_session_start(
                session_uuid=call_uuid,
                direction=direction,
                caller=caller,
                callee=callee,
                agent_id=agent_id
            )

            session = AsteriskVoiceSession(reader, writer, call_uuid, context)
            call_session_manager.register_cleanup_callback(call_uuid, session.close_from_manager)
            call_session_manager.start_audio_session(call_uuid)
            self.active_connections[call_uuid] = asyncio.current_task()
            
            from app.services.call_admission_control import run_live_call_monitor
            async def hangup_callback(reason: str):
                logger.warning(f"[AudioSocket] Hangup triggered by monitor for call {call_uuid}: reason={reason}")
                try:
                    db = get_supabase_client()
                    db.table("calls").update({
                        "hangup_reason": reason,
                        "status": "failed"
                    }).eq("call_uuid", call_uuid).execute()
                except Exception as e:
                    logger.error(f"[AudioSocket] Failed to update hangup reason in DB: {e}")
                session.close_from_manager(call_uuid)

            monitor_task = asyncio.create_task(run_live_call_monitor(call_uuid, hangup_callback))
            try:
                try:
                    await session.run()
                finally:
                    monitor_task.cancel()
            except asyncio.CancelledError:
                logger.audiosocket_connection_closed("cancelled")
            except (asyncio.IncompleteReadError, ConnectionError, BrokenPipeError, ConnectionResetError) as e:
                logger.info(f"[AudioSocket] Client disconnected normally during session: {e}")
            except Exception as e:
                logger.audiosocket_connection_error(e, "session_run")
                diagnostics.add_error("error", "audiosocket", f"Session run error: {str(e)}")

        except (asyncio.IncompleteReadError, ConnectionError, BrokenPipeError, ConnectionResetError) as e:
            logger.info(f"[AudioSocket] Client disconnected normally during handshake: {e}")
        except Exception as e:
            logger.error(f"[AudioSocket] Unexpected error in handle_connection: {e}", exc_info=True)
            diagnostics.add_error("error", "audiosocket", f"Unexpected connection error: {str(e)}")
        finally:
            if call_uuid:
                self.active_connections.pop(call_uuid, None)
                from app.services.call_session_manager import call_session_manager
                call_session_manager.end_call(call_uuid, 'hangup')
                call_session_manager.cleanup_call(call_uuid)
                diagnostics.record_session_end(call_uuid, "call_ended")
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass
            logger.audiosocket_connection_closed("finished")

    async def stop(self) -> None:
        """
        Gracefully shuts down the TCP server and closes concurrent call loops.
        """
        if self.server:
            self.server.close()
            await self.server.wait_closed()
            logger.info('Asterisk AudioSocket server stopped successfully.')

        for call_uuid, task in list(self.active_connections.items()):
            if not task.done():
                task.cancel()

        self.active_connections.clear()


# Global helper functions referenced in app/main.py

_audiosocket_server: Optional[AsteriskAudioSocketServer] = None

async def start_audiosocket_server(host: str, port: int) -> None:
    global _audiosocket_server
    _audiosocket_server = AsteriskAudioSocketServer(host, port)
    await _audiosocket_server.start()

async def stop_audiosocket_server() -> None:
    global _audiosocket_server
    if _audiosocket_server:
        await _audiosocket_server.stop()
        _audiosocket_server = None

def get_audiosocket_stats() -> dict:
    global _audiosocket_server
    if _audiosocket_server:
        return {
            "status": "running",
            "host": _audiosocket_server.host,
            "port": _audiosocket_server.port,
            "active_connections_count": len(_audiosocket_server.active_connections),
            "active_connections": list(_audiosocket_server.active_connections.keys())
        }
    return {"status": "stopped"}
