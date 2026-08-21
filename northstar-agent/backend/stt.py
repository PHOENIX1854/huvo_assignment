import io
import os
import re
from functools import lru_cache

from openai import OpenAI


class SttUnavailableError(Exception):
    pass


@lru_cache
def get_stt_client() -> OpenAI | None:
    key = os.environ.get("GROQ_API_KEY", "")
    if key:
        return OpenAI(api_key=key, base_url="https://api.groq.com/openai/v1")
    key = os.environ.get("OPENROUTER_API_KEY", "")
    if key:
        return OpenAI(api_key=key, base_url="https://openrouter.ai/api/v1")
    return None


def get_stt_model() -> str:
    if os.environ.get("GROQ_API_KEY", ""):
        return os.environ.get("GROQ_STT_MODEL", "whisper-large-v3-turbo")
    return os.environ.get("OPENROUTER_STT_MODEL", "openai/whisper-1")


def transcribe_audio(audio_bytes: bytes, fmt: str = "webm") -> str:
    client = get_stt_client()
    if client is None:
        raise SttUnavailableError("no STT API key configured (GROQ_API_KEY or OPENROUTER_API_KEY)")
    filename = f"audio.{fmt}"
    mime = f"audio/{fmt}"
    response = client.audio.transcriptions.create(
        model=get_stt_model(),
        file=(filename, io.BytesIO(audio_bytes), mime),
    )
    text = (response.text or "").strip()
    if not text:
        raise SttUnavailableError("empty transcription")
    # Filter out common Whisper silence hallucinations
    cleaned = re.sub(r"[^\w]", "", text.lower())
    if cleaned in ("thankyou", "thankyouverymuch", "thankyouforwatching", "pleasesubscribe", "you", "go"):
        raise SttUnavailableError("empty transcription")
    return text