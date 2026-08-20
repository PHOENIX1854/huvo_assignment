import os
import re

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .agent import build_system_prompt, call_agent
from .analytics import generate_analytics
from .analytics_store import load_analytics, save_analytics
from .constants import BOOKING_ATTEMPT_PATTERN, is_slot_available
from .pii import has_contact, is_moderation_output, redact_line, scrub_contact
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

_REP_REQUEST_RE = re.compile(
    r"\b(representative|human|real person|someone|call me|contact me|reach out to me)\b",
    re.IGNORECASE,
)

FALLBACK_AFTER_BOOKING = "I've noted your request — a Northstar team member will reach out shortly to confirm your visit."


class ChatRequest(BaseModel):
    session_id: str = Field(min_length=1)
    message: str = Field(min_length=1)


def handoff_reply(session: Session) -> str:
    if session.site_visit_datetime:
        return (
            "Thanks! I've noted your details — a Northstar representative will call or WhatsApp "
            f"you shortly to confirm your visit for {session.site_visit_datetime}. "
            "Anything else I can help with?"
        )
    return (
        "Thanks! I've noted your details — a Northstar representative will reach out shortly "
        "to help with your request. Anything else I can help with?"
    )


def rep_handoff_reply(session: Session) -> str:
    if session.contact_captured:
        return (
            "Understood — I've noted that a Northstar representative should contact you. "
            "They'll reach out shortly to help. Anything else I can help with?"
        )
    return (
        "Understood — I've noted that a Northstar representative should contact you. "
        "To make sure they can reach you, could you please share the best contact number "
        "or WhatsApp? Anything else you'd like me to note for them?"
    )


def graceful_fallback(session: Session, first_failure: bool) -> str:
    if session.site_visit_datetime:
        return (
            "I've hit a temporary snag with my language service, but here's what we have: your "
            f"site visit is confirmed for {session.site_visit_datetime} at Sector 79, Gurugram, "
            "and your contact details are captured. A Northstar representative will reach out to "
            "confirm. Anything else you'd like me to note for them?"
        )
    contact_note = (
        " To make sure they can reach you, please share the best contact number or WhatsApp."
        if not session.contact_captured
        else ""
    )
    if first_failure:
        return (
            "I've hit a temporary snag — my language service is unavailable right now. I've noted "
            "your message for a Northstar representative, who will reach out to help."
            + contact_note
            + " Is there anything else you'd like me to note for them?"
        )
    return (
        "I'm still unable to reach my language service. I've noted your message for the Northstar "
        "team and a representative will reach out."
        + contact_note
        + " Anything else you'd like me to note for them?"
    )


def _clean_reply(reply: str, session: Session) -> str:
    if is_moderation_output(reply):
        return handoff_reply(session)
    return reply


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
                "and ask for their name and best contact number. Do not emit another booking tag."
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
            reply = call_agent(build_system_prompt(note=note, session=session), session.history)
        except Exception:
            first_failure = not session.model_failed
            session.model_failed = True
            return graceful_fallback(session, first_failure)

        reply = _clean_reply(reply, session)

    return _BOOKING_RE.sub("", reply).strip()


@app.post("/chat")
def chat(req: ChatRequest) -> dict:
    cleanup_idle()
    session = get_session(req.session_id)
    if session.ended:
        raise HTTPException(status_code=409, detail="Conversation already ended. Use /reset to start a new one.")

    _, phone, email = scrub_contact(req.message)
    session.raw_history.append({"role": "user", "content": req.message})
    if phone:
        session.contact_phone = phone
        session.contact_captured = True
    if email:
        session.contact_email = email
        session.contact_captured = True
    session.history.append({"role": "user", "content": redact_line(req.message)})

    if has_contact(req.message):
        reply = handoff_reply(session)
    else:
        first_failure = not session.model_failed
        try:
            reply = call_agent(build_system_prompt(session=session), session.history)
            session.model_failed = False
        except Exception:
            session.model_failed = True
            if _REP_REQUEST_RE.search(req.message):
                reply = rep_handoff_reply(session)
            else:
                reply = graceful_fallback(session, first_failure)
        reply = _handle_booking(reply, session)
        reply = _clean_reply(reply, session)

    session.history.append({"role": "assistant", "content": reply})
    return {
        "reply": reply,
        "contact": {
            "phone": session.contact_phone,
            "email": session.contact_email,
        },
        "booking": {
            "status": session.site_visit_status,
            "datetime": session.site_visit_datetime,
        },
    }


@app.post("/end/{session_id}")
def end_conversation(session_id: str) -> dict:
    session = get_session(session_id)
    session.ended = True
    if session.analytics is None:
        session.analytics = generate_analytics(session)
    path = save_analytics(session_id, session.analytics)
    return {"ok": True, "saved_to": os.path.relpath(path)}


@app.get("/analytics/{session_id}")
def get_analytics(session_id: str) -> dict:
    record = load_analytics(session_id)
    if record is not None:
        return record["analytics"]
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


for _page in ("about", "privacy", "terms", "contact"):

    def _serve_page(page: str = _page) -> FileResponse:
        return FileResponse(os.path.join(FRONTEND_DIR, f"{page}.html"))

    app.add_api_route(
        f"/{_page}",
        _serve_page,
        methods=["GET"],
        include_in_schema=False,
        name=_page,
    )


app.mount("/", StaticFiles(directory=FRONTEND_DIR, html=True), name="frontend")