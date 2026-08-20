import os
import time
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from typing import TYPE_CHECKING

from dotenv import load_dotenv
from openai import OpenAI

if TYPE_CHECKING:
    from .session_store import Session

load_dotenv()

IST = timezone(timedelta(hours=5, minutes=30))

PROMPT_PATH = os.path.join(os.path.dirname(__file__), "..", "prompt.md")

_client: OpenAI | None = None


class ModelUnavailableError(Exception):
    pass


_MODEL_COOLDOWN_SECONDS = 30
_last_model_failure: float | None = None


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


def _session_state(session: "Session") -> str:
    lines = [
        "# CURRENT SESSION STATE (authoritative — trust this over your memory)",
        f"- site_visit_status: {session.site_visit_status}",
        f"- site_visit_datetime: {session.site_visit_datetime or 'none yet'}",
        f"- contact_captured: {'yes' if session.contact_captured else 'no'}",
        f"- booking_attempts: {session.booking_attempts}",
        f"- escalated_to_human: {'yes' if session.escalated else 'no'}",
        f"- do_not_contact: {'yes' if session.dnd else 'no'}",
    ]
    if session.contact_captured:
        lines.append(
            "- The customer's contact details have been captured by the system for the Northstar "
            "team. If the customer asks to confirm their name or number, reassure them their details "
            "are safely captured and a representative will confirm them — do not repeat the full "
            "number in chat."
        )
    return "\n".join(lines)


def build_system_prompt(note: str | None = None, session: "Session | None" = None) -> str:
    prompt = load_system_prompt()
    now = datetime.now(IST)
    context = [f"Today's date and time: {now.strftime('%Y-%m-%d (%A), %I:%M %p IST')}"]
    if session is not None:
        context.append(_session_state(session))
    if note:
        context.append(f"# SYSTEM UPDATE\n{note}")
    return f"{prompt}\n\n# SESSION CONTEXT\n" + "\n\n".join(context)


def _is_transient(exc: Exception) -> bool:
    status = getattr(exc, "status_code", None)
    if status == 429:
        if "free-models-per-day" in str(exc).lower():
            return False
        return True
    if status is not None and status >= 500:
        return True
    name = type(exc).__name__
    return any(
        token in name
        for token in ("RateLimit", "APIConnection", "APITimeout", "InternalServerError", "ServiceUnavailable")
    )


def call_agent(
    system_prompt: str,
    history: list[dict],
    temperature: float = 0.4,
    retries: int = 1,
    **kwargs,
) -> str:
    global _last_model_failure
    if _last_model_failure is not None and time.monotonic() - _last_model_failure < _MODEL_COOLDOWN_SECONDS:
        raise ModelUnavailableError("model call skipped during failure cooldown")
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            response = get_client().chat.completions.create(
                model=get_model(),
                messages=[{"role": "system", "content": system_prompt}, *history],
                temperature=temperature,
                **kwargs,
            )
            _last_model_failure = None
            return response.choices[0].message.content or ""
        except Exception as exc:
            last_exc = exc
            if _is_transient(exc):
                _last_model_failure = time.monotonic()
                if attempt == retries:
                    raise
            else:
                raise
    raise last_exc  # type: ignore[misc]