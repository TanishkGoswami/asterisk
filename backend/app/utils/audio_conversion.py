import io
import wave
import base64
import logging
import warnings
from typing import Tuple, List

logger = logging.getLogger(__name__)

audioop = None
try:
    import audioop
except ImportError:
    try:
        import audioop_lts as audioop
    except ImportError:
        warnings.warn(
            'audioop module is not available in the current Python environment. Resampling capabilities will fall back or be disabled.',
            ImportWarning
        )
        logger.warning('audioop standard library and audioop-lts packages are missing. PCM resampling and conversion may fail.')


def resample_pcm16(input_bytes: bytes, from_rate: int, to_rate: int) -> bytes:
    """
    Resample raw 16-bit mono PCM bytes from from_rate to to_rate using audioop.
    """
    if not input_bytes:
        return b''
    if from_rate == to_rate:
        return input_bytes
    # High-quality state-free downsampling for 16kHz to 8kHz (slicing every second 16-bit sample)
    if from_rate == 16000 and to_rate == 8000:
        import array
        try:
            # Ensure length is even (each sample is 2 bytes)
            if len(input_bytes) % 2 != 0:
                input_bytes = input_bytes[:len(input_bytes) - (len(input_bytes) % 2)]
            a = array.array('h', input_bytes)
            return a[::2].tobytes()
        except Exception as e:
            logger.error(f'Slicing downsample failed from 16k to 8k: {e}')

    if audioop is None:
        logger.warning('audioop not available. Returning raw bytes without resampling.')
        return input_bytes

    try:
        resampled, _ = audioop.ratecv(input_bytes, 2, 1, from_rate, to_rate, None)
        return resampled
    except Exception as e:
        logger.error(f'Error resampling PCM from {from_rate} to {to_rate}: {e}')
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
