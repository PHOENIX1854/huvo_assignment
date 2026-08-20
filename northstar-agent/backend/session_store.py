import threading
import time
from dataclasses import dataclass, field

SESSIONS: dict[str, "Session"] = {}
_LOCK = threading.Lock()


@dataclass
class Session:
    session_id: str
    history: list[dict] = field(default_factory=list)
    raw_history: list[dict] = field(default_factory=list)
    contact_phone: str | None = None
    contact_email: str | None = None
    site_visit_status: str = "not_offered"
    site_visit_datetime: str | None = None
    booking_attempts: int = 0
    created_at: float = field(default_factory=time.time)
    last_active: float = field(default_factory=time.time)
    ended: bool = False
    analytics: dict | None = None
    dnd: bool = False
    escalated: bool = False


def get_session(session_id: str, create: bool = True) -> Session:
    with _LOCK:
        session = SESSIONS.get(session_id)
        if session is None and create:
            session = Session(session_id=session_id)
            SESSIONS[session_id] = session
    if session is not None:
        session.last_active = time.time()
    return session


def reset_session(session_id: str) -> None:
    with _LOCK:
        SESSIONS.pop(session_id, None)


def cleanup_idle(max_idle_seconds: float = 3600) -> int:
    now = time.time()
    stale = [sid for sid, s in SESSIONS.items() if now - s.last_active > max_idle_seconds]
    with _LOCK:
        for sid in stale:
            SESSIONS.pop(sid, None)
    return len(stale)