import asyncio
import pytest
import re
from typing import List, Set

# Chunker Config Mock (Matches Settings class)
class MockSettings:
    STREAMING_TTS_MODE = "safe_sentence"
    ADVANCED_CHUNKER = False
    PUNCTUATION_RESTORE = False
    FIRST_CHUNK_TIMEOUT_MS = 0
    NEXT_CHUNK_TIMEOUT_MS = 1200
    DISABLE_STREAMING_TTS = False
    TTS_PREBUFFER_MS = 1500
    MIN_AUDIO_CHUNKS_BEFORE_PLAYBACK = 2

settings = MockSettings()

PROTECTED_WORDS: Set[str] = {
    "hai", "hoon", "ka", "ki", "ke", "ko", "se", "aur", "lekin", "because", 
    "that", "to", "of", "raha", "rahi", "kyunki"
}

GREETING_WORDS: Set[str] = {
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

class PipelineTester:
    def __init__(self):
        self.released_chunks: List[str] = []

    async def run_pipeline(self, tokens_with_delays: List[tuple]) -> List[str]:
        self.released_chunks = []
        token_queue = asyncio.Queue()
        sentence_queue = asyncio.Queue()

        # Shared states
        is_first_chunk = True

        # LLM Reader Mock
        async def llm_reader():
            full_response = ""
            for token, delay in tokens_with_delays:
                if delay > 0:
                    await asyncio.sleep(delay)
                full_response += token
                if not settings.DISABLE_STREAMING_TTS:
                    await token_queue.put(token)
            
            if settings.DISABLE_STREAMING_TTS:
                await token_queue.put(full_response)
            await token_queue.put(None)

        def should_release(words_list: List[str], is_first_chunk: bool) -> bool:
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

            # Fallback limit
            if num_words >= 28 and not is_protected_word(last_word):
                return True

            return False

        # Speech Chunker Task
        async def speech_chunker():
            nonlocal is_first_chunk
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
                        await sentence_queue.put((sentence_idx, chunk_text))
                        sentence_idx += 1
                        words_list = []
                        is_first_chunk = False

            if token_buffer.strip():
                words_list.append(token_buffer.strip())

            if words_list:
                chunk_text = ' '.join(words_list)
                if chunk_text.strip():
                    await sentence_queue.put((sentence_idx, chunk_text))
            
            await sentence_queue.put(None)

        # Mock Playback Worker
        async def mock_playback():
            while True:
                item = await sentence_queue.get()
                if item is None:
                    break
                idx, text = item
                self.released_chunks.append(text)

        await asyncio.gather(llm_reader(), speech_chunker(), mock_playback())
        return self.released_chunks

# =====================================================================
# Test Cases for safe_sentence mode
# =====================================================================

@pytest.mark.anyio
async def test_safe_sentence_first_chunk():
    print("Running test_safe_sentence_first_chunk...")
    settings.DISABLE_STREAMING_TTS = False
    tester = PipelineTester()

    # Streams: "Hello, kaise ho aap? Main aur hum sath milkar kaam karenge."
    # First chunk is only greeting ("Hello, kaise ho aap?"), so it should NOT release.
    # Second part completes sentence: "Main aur hum sath milkar kaam karenge."
    # The whole sentence should release together.
    tokens = [
        ("Hello, ", 0), ("kaise ", 0), ("ho ", 0), ("aap? ", 0.8),
        ("Main ", 0), ("aur ", 0), ("hum ", 0), ("sath ", 0), ("milkar ", 0), ("kaam ", 0), ("karenge.", 0)
    ]
    chunks = await tester.run_pipeline(tokens)
    print("Released Chunks:", chunks)
    assert len(chunks) == 1
    assert chunks[0] == "Hello, kaise ho aap? Main aur hum sath milkar kaam karenge."
    print("SUCCESS\n")

@pytest.mark.anyio
async def test_no_split_on_aggressive_words():
    print("Running test_no_split_on_aggressive_words...")
    settings.DISABLE_STREAMING_TTS = False
    tester = PipelineTester()

    # Sentence has a pause at "lekin" or "aur", and has >= 18 words:
    # "Hum aapko is business me support karna chahte hain aur aapka revenue double kar sakte hain, lekin"
    # Word count at "," is 18. The word is "lekin" (aggressive split word).
    # Chunker should NOT split at "lekin," even though it has >= 18 words and ends with comma.
    tokens = [
        ("Hum ", 0), ("aapko ", 0), ("is ", 0), ("business ", 0), ("me ", 0),
        ("support ", 0), ("karna ", 0), ("chahte ", 0), ("hain ", 0), ("aur ", 0),
        ("aapka ", 0), ("revenue ", 0), ("double ", 0), ("kar ", 0), ("sakte ", 0),
        ("hain, ", 0), ("lekin ", 0), # 17 words, last is "lekin" (aggressive split)
        ("aapko ", 0), ("kuch ", 0), ("changes ", 0), ("karne ", 0), ("honge.", 0)
    ]
    chunks = await tester.run_pipeline(tokens)
    print("Released Chunks:", chunks)
    assert len(chunks) == 1
    assert chunks[0] == "Hum aapko is business me support karna chahte hain aur aapka revenue double kar sakte hain, lekin aapko kuch changes karne honge."
    print("SUCCESS\n")

@pytest.mark.anyio
async def test_disable_streaming_tts():
    print("Running test_disable_streaming_tts...")
    settings.DISABLE_STREAMING_TTS = True
    tester = PipelineTester()

    # Even with sentences split, everything should accumulate and release as one big chunk!
    tokens = [
        ("Hello, ", 0), ("kaise ", 0), ("ho ", 0), ("aap? ", 0),
        ("Main ", 0), ("aapka ", 0), ("help ", 0), ("karunga.", 0)
    ]
    chunks = await tester.run_pipeline(tokens)
    print("Released Chunks:", chunks)
    assert len(chunks) == 1
    assert chunks[0] == "Hello, kaise ho aap? Main aapka help karunga."
    print("SUCCESS\n")

async def main():
    await test_safe_sentence_first_chunk()
    await test_no_split_on_aggressive_words()
    await test_disable_streaming_tts()
    print("ALL SAFE SENTENCE TESTS PASSED SUCCESSFULLY!")

if __name__ == "__main__":
    asyncio.run(main())
