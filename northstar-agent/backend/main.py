import os
import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import build_system_prompt, call_agent
from .analytics import generate_analytics
from .constants import BOOKING_ATTEMPT_PATTERN, is_slot_available
from .session_store import Session, cleanup_idle, get_session, reset_session

FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = FastAPI(title="Northstar Homes AI Sales Agent")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

_BOOKING_RE = re.compile(BOOKING_ATTEMPT_PATTERN)

FALLBACK_REPLY = "I'm sorry, I'm having a small technical hiccup right now. Please try that again in a moment."
FALLBACK_AFTER_BOOKING = "I've noted your request — a Northstar team member will reach out shortly to confirm your visit."


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


def _handle_booking(reply: str, session: Session) -> str:
    for _ in range(3):
        match = _BOOKING_RE.search(reply)
        if match is None:
            break

        date_str, time_str = match.groups()
        reply = _BOOKING_RE.sub("", reply).strip()

        session.booking_attempts += 1
        available, reason = is_slot_available(date_str, time_str)
        if available:
            session.site_visit_status = "booked"
            session.site_visit_datetime = f"{date_str} {time_str}"
            note = (
                f"The requested site-visit slot {date_str} at {time_str} is CONFIRMED. "
                "Reply to the customer confirming the booking (date, time, Sector 79, Gurugram) "
                "and ask for/confirm their name and best contact number. Do not emit another booking tag."
            )
        else:
            if session.booking_attempts >= 2:
                session.escalated = True
            note = (
                f"The requested site-visit slot {date_str} at {time_str} is UNAVAILABLE ({reason}). "
                "Do NOT claim it was booked. Apologize briefly, offer 2-3 alternative slots or ask "
                "for another preferred time. If the customer prefers, offer to have a human team "
                "member call them to coordinate."
            )

        try:
            reply = call_agent(build_system_prompt(note=note), session.history)
        except Exception:
            return FALLBACK_AFTER_BOOKING

    return _BOOKING_RE.sub("", reply).strip()


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    cleanup_idle()
    session = get_session(req.session_id)
    if session.ended:
        raise HTTPException(status_code=409, detail="Conversation already ended. Use /reset to start a new one.")

    session.history.append({"role": "user", "content": req.message})

    try:
        reply = call_agent(build_system_prompt(), session.history)
    except Exception:
        reply = FALLBACK_REPLY

    reply = _handle_booking(reply, session)
    session.history.append({"role": "assistant", "content": reply})
    return {"reply": reply}


@app.post("/end/{session_id}")
def end_conversation(session_id: str) -> dict:
    session = get_session(session_id)
    session.ended = True
    if session.analytics is None:
        session.analytics = generate_analytics(session)
    return session.analytics


@app.get("/analytics/{session_id}")
def get_analytics(session_id: str) -> dict:
    session = get_session(session_id, create=False)
    if session is None or session.analytics is None:
        raise HTTPException(status_code=404, detail="Analytics not available yet. End the conversation first.")
    return session.analytics


@app.post("/reset/{session_id}")
def reset(session_id: str) -> dict:
    reset_session(session_id)
    return {"ok": True}


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")