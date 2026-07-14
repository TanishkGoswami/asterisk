import io
import wave
import base64
import logging
import warnings
from typing import Tuple, List

logger = logging.getLogger(__name__)

# soxr: high-quality production resampler with proper sinc anti-aliasing filter.
# Required on Python 3.13+ where audioop was removed from the stdlib.
# Install: pip install soxr
try:
    import soxr
    _SOXR_AVAILABLE = True
except ImportError:
    _SOXR_AVAILABLE = False
    warnings.warn(
        'soxr is not installed. PCM resampling will be low-quality (aliased). '
        'Run: pip install soxr',
        ImportWarning
    )
    logger.warning('soxr not available — install it with: pip install soxr')

# audioop was removed in Python 3.13. Keep as a last-resort fallback for older envs.
audioop = None
try:
    import audioop
except ImportError:
    try:
        import audioop_lts as audioop
    except ImportError:
        pass  # Will rely on soxr instead


def resample_pcm16(input_bytes: bytes, from_rate: int, to_rate: int) -> bytes:
    """
    Resample raw 16-bit signed mono PCM bytes from from_rate to to_rate.

    Uses soxr (preferred) which applies a proper sinc anti-aliasing low-pass
    filter before decimation, eliminating frequency fold-back/aliasing artifacts.
    Falls back to audioop.ratecv() (Python <=3.12) if soxr is unavailable.

    NOTE: The previous a[::2] array-slicing shortcut was intentionally removed.
    It skips anti-aliasing entirely and causes audible pitch/clarity distortion.
    """
    if not input_bytes:
        return b''
    if from_rate == to_rate:
        return input_bytes

    # Ensure even byte length (each 16-bit sample = 2 bytes)
    if len(input_bytes) % 2 != 0:
        input_bytes = input_bytes[: len(input_bytes) - 1]

    if _SOXR_AVAILABLE:
        try:
            import numpy as np
            # soxr expects float32 input; convert from int16, resample, convert back
            pcm_int16 = np.frombuffer(input_bytes, dtype=np.int16)
            pcm_float = pcm_int16.astype(np.float32) / 32768.0
            resampled_float = soxr.resample(pcm_float, from_rate, to_rate, quality='HQ')
            resampled_int16 = np.clip(resampled_float * 32768.0, -32768, 32767).astype(np.int16)
            return resampled_int16.tobytes()
        except Exception as e:
            logger.error(f'soxr resample failed ({from_rate}->{to_rate}): {e} — falling back')

    # Fallback: audioop.ratecv (available on Python <=3.12)
    if audioop is not None:
        try:
            resampled, _ = audioop.ratecv(input_bytes, 2, 1, from_rate, to_rate, None)
            return resampled
        except Exception as e:
            logger.error(f'audioop.ratecv failed ({from_rate}->{to_rate}): {e}')
            return input_bytes

    logger.error('No resampler available (soxr missing, audioop missing). Returning raw bytes.')
    return input_bytes


def wav_to_pcm16(wav_bytes: bytes) -> Tuple[bytes, int]:
    try:
        with wave.open(io.BytesIO(wav_bytes), 'rb') as wav_file:
            n_channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            frame_rate = wav_file.getframerate()
            n_frames = wav_file.getnframes()
            raw_frames = wav_file.readframes(n_frames)

        if n_channels > 1:
            if audioop:
                raw_frames = audioop.tomono(raw_frames, sample_width, 0.5, 0.5)
            else:
                mono_frames = bytearray()
                for i in range(0, len(raw_frames), sample_width * n_channels):
                    mono_frames.extend(raw_frames[i:i + sample_width])
                raw_frames = bytes(mono_frames)

        if sample_width != 2:
            if audioop:
                raw_frames = audioop.lin2lin(raw_frames, sample_width, 2)
            else:
                logger.warning('audioop missing; cannot change WAV sample width.')

        return raw_frames, frame_rate

    except Exception as e:
        logger.error(f'Failed to parse WAV audio header: {e}')
        # Fallback parsing
        if wav_bytes.startswith(b'RIFF') and b'WAVE' in wav_bytes[:16]:
            data_idx = wav_bytes.find(b'data')
            if data_idx != -1:
                return wav_bytes[data_idx + 8:], 16000
            else:
                return wav_bytes[44:], 16000
        else:
            return wav_bytes, 16000


def mp3_to_pcm16(mp3_bytes: bytes) -> bytes:
    if not mp3_bytes:
        return b''

    try:
        from pydub import AudioSegment
        segment = AudioSegment.from_file(io.BytesIO(mp3_bytes), format='mp3')
        segment = segment.set_channels(1).set_frame_rate(8000).set_sample_width(2)
        return segment.raw_data
    except Exception as pydub_err:
        try:
            import subprocess
            process = subprocess.Popen(
                ['ffmpeg', '-i', 'pipe:0', '-f', 's16le', '-acodec', 'pcm_s16le', '-ar', '8000', '-ac', '1', 'pipe:1'],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE
            )
            stdout, _ = process.communicate(input=mp3_bytes, timeout=5)
            if process.returncode == 0:
                return stdout
        except Exception as ffmpeg_err:
            logger.debug(f'ffmpeg subprocess fallback failed: {ffmpeg_err}')

        logger.warning(f'MP3 decoding failed. No pydub or ffmpeg decoders succeeded: {pydub_err}')
        return b''


def ensure_pcm16_mono_8khz(input_audio: bytes, input_format: str = None, input_sample_rate: int = None) -> bytes:
    if not input_audio:
        return b''

    if not input_format:
        if input_audio.startswith(b'RIFF') and b'WAVE' in input_audio[:16]:
            input_format = 'wav'
        elif input_audio.startswith(b'\xff\xfb') or input_audio.startswith(b'ID3') or input_audio.startswith(b'\xff\xf3'):
            input_format = 'mp3'
        else:
            input_format = 'pcm'

    if input_format == 'wav':
        pcm_bytes, sample_rate = wav_to_pcm16(input_audio)
        return resample_pcm16(pcm_bytes, sample_rate, 8000)
    elif input_format == 'mp3':
        return mp3_to_pcm16(input_audio)
    else:
        sample_rate = input_sample_rate or 16000
        return resample_pcm16(input_audio, sample_rate, 8000)


def chunk_pcm_for_telephony(pcm_bytes: bytes, chunk_size: int = 320) -> List[bytes]:
    chunks = []
    if not pcm_bytes:
        return chunks

    for i in range(0, len(pcm_bytes), chunk_size):
        chunk = pcm_bytes[i:i + chunk_size]
        if len(chunk) < chunk_size:
            chunk = chunk + b'\x00' * (chunk_size - len(chunk))
        chunks.append(chunk)
    return chunks
