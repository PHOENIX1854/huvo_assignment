import os
from datetime import datetime, timedelta, timezone
from functools import lru_cache

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

IST = timezone(timedelta(hours=5, minutes=30))

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompt.md")

_client: OpenAI | None = None


def get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(
            api_key=os.environ.get("OPENROUTER_API_KEY", ""),
            base_url="https://openrouter.ai/api/v1",
        )
    return _client


def get_model() -> str:
    return os.environ.get("OPENROUTER_MODEL", "openrouter/free")


@lru_cache
def load_system_prompt() -> str:
    with open(PROMPT_PATH, encoding="utf-8") as f:
        return f.read().strip()


def build_system_prompt(note: str | None = None) -> str:
    prompt = load_system_prompt()
    now = datetime.now(IST)
    session_context = f"Today's date and time: {now.strftime('%Y-%m-%d (%A), %I:%M %p IST')}"
    if note:
        session_context += f"\n# SYSTEM UPDATE\n{note}"
    return f"{prompt}\n\n# SESSION CONTEXT\n{session_context}"


def call_agent(
    system_prompt: str,
    history: list[dict],
    temperature: float = 0.4,
) -> str:
    response = get_client().chat.completions.create(
        model=get_model(),
        messages=[{"role": "system", "content": system_prompt}, *history],
        temperature=temperature,
    )
    return response.choices[0].message.content or ""