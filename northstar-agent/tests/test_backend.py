import time

import pytest
from fastapi.testclient import TestClient

from backend import main, session_store
from backend.constants import is_slot_available
from backend.pii import has_contact, is_moderation_output, scrub_contact
from backend.session_store import Session

FUTURE = "2099-01-01"
PAST = "2000-01-01"


@pytest.fixture
def client():
    session_store.SESSIONS.clear()
    return TestClient(main.app)


@pytest.fixture(autouse=True)
def _reset_sessions():
    session_store.SESSIONS.clear()
    yield
    session_store.SESSIONS.clear()


# ── constants ────────────────────────────────────────────────────────────────


def test_slot_available():
    assert is_slot_available(FUTURE, "10:30") == (True, "available")


def test_slot_unavailable_at_1100():
    assert is_slot_available(FUTURE, "11:00") == (False, "unavailable")


def test_slot_past():
    assert is_slot_available(PAST, "10:30") == (False, "past")


def test_slot_invalid_format():
    assert is_slot_available("not-a-date", "10:30") == (False, "invalid")
    assert is_slot_available(FUTURE, "not-a-time") == (False, "invalid")


# ── session store ────────────────────────────────────────────────────────────


def test_get_session_creates():
    session = session_store.get_session("s1")
    assert isinstance(session, Session)
    assert session.session_id == "s1"


def test_get_session_returns_existing():
    session_store.get_session("s1")
    assert session_store.get_session("s1").session_id == "s1"


def test_get_session_no_create():
    assert session_store.get_session("nope", create=False) is None


def test_reset_session():
    session_store.get_session("s1")
    session_store.reset_session("s1")
    assert session_store.get_session("s1", create=False) is None


def test_cleanup_idle():
    session = session_store.get_session("s1")
    session.last_active = time.time() - 10_000
    assert session_store.cleanup_idle(max_idle_seconds=3600) == 1
    assert session_store.get_session("s1", create=False) is None


# ── HTTP endpoints ───────────────────────────────────────────────────────────


def test_health(client):
    assert client.get("/health").json() == {"status": "ok"}


def test_chat_returns_reply(client, monkeypatch):
    monkeypatch.setattr(main, "call_agent", lambda *a, **k: "Hello! How can I help?")
    res = client.post("/chat", json={"session_id": "s1", "message": "hi"})
    assert res.status_code == 200
    assert res.json()["reply"] == "Hello! How can I help?"


def test_chat_rejects_empty_message(client):
    res = client.post("/chat", json={"session_id": "s1", "message": ""})
    assert res.status_code == 422


def test_chat_rejects_empty_session_id(client):
    res = client.post("/chat", json={"session_id": "", "message": "hi"})
    assert res.status_code == 422


def test_chat_rejects_ended_session(client, monkeypatch):
    monkeypatch.setattr(main, "call_agent", lambda *a, **k: "ok")
    session_store.get_session("s1").ended = True
    res = client.post("/chat", json={"session_id": "s1", "message": "hi"})
    assert res.status_code == 409


def test_chat_fallback_on_error(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(main, "call_agent", boom)
    res = client.post("/chat", json={"session_id": "s1", "message": "hi"})
    assert res.status_code == 200
    assert "technical hiccup" in res.json()["reply"]


def test_chat_records_history(client, monkeypatch):
    monkeypatch.setattr(main, "call_agent", lambda *a, **k: "ok")
    client.post("/chat", json={"session_id": "s1", "message": "hello"})
    session = session_store.get_session("s1")
    assert [m["content"] for m in session.history] == ["hello", "ok"]


def test_booking_success_flow(client, monkeypatch):
    replies = iter([
        f"Great choice! [BOOK_ATTEMPT date={FUTURE} time=10:30]",
        "Perfect, I've noted your visit for 2099-01-01 at 10:30 AM at Sector 79, Gurugram. Can I get your name and number?",
    ])
    monkeypatch.setattr(main, "call_agent", lambda *a, **k: next(replies))
    res = client.post("/chat", json={"session_id": "s1", "message": "Book me a visit"})
    session = session_store.get_session("s1")
    assert res.status_code == 200
    assert session.site_visit_status == "booked"
    assert session.site_visit_datetime == f"{FUTURE} 10:30"
    assert "[BOOK_ATTEMPT" not in res.json()["reply"]


def test_booking_failure_then_escalation(client, monkeypatch):
    def queued(*a, **k):
        return next(replies)

    replies = iter([
        "[BOOK_ATTEMPT date=2099-01-01 time=11:00]",
        "Sorry, that slot isn't available. Would another time work?",
        "[BOOK_ATTEMPT date=2099-01-02 time=11:00]",
        "Apologies again — may I have a human colleague call you instead?",
    ])
    monkeypatch.setattr(main, "call_agent", queued)

    client.post("/chat", json={"session_id": "s1", "message": "book at 11"})
    session = session_store.get_session("s1")
    assert session.booking_attempts == 1
    assert session.escalated is False

    client.post("/chat", json={"session_id": "s1", "message": "ok 11 again"})
    session = session_store.get_session("s1")
    assert session.booking_attempts == 2
    assert session.escalated is True
    assert session.site_visit_status == "not_offered"


def test_booking_fallback_when_recheck_fails(client, monkeypatch):
    def failing(*a, **k):
        if "SYSTEM UPDATE" in a[0]:
            raise RuntimeError("llm down")
        return "[BOOK_ATTEMPT date=2099-01-01 time=10:30]"

    monkeypatch.setattr(main, "call_agent", failing)
    res = client.post("/chat", json={"session_id": "s1", "message": "book it"})
    assert res.status_code == 200
    assert "team member will reach out" in res.json()["reply"]


def test_end_conversation_sets_ended_and_analytics(client, monkeypatch):
    fake = {"customer_name": "Rahul", "interest_level": "Hot"}
    monkeypatch.setattr(main, "generate_analytics", lambda s: fake)
    res = client.post("/end/s1")
    assert res.status_code == 200
    assert res.json() == fake
    assert session_store.get_session("s1").ended is True


def test_analytics_not_available_before_end(client):
    res = client.get("/analytics/s1")
    assert res.status_code == 404


def test_analytics_available_after_end(client, monkeypatch):
    monkeypatch.setattr(main, "generate_analytics", lambda s: {"customer_name": "Rahul"})
    client.post("/end/s1")
    res = client.get("/analytics/s1")
    assert res.status_code == 200
    assert res.json()["customer_name"] == "Rahul"


def test_reset(client):
    client.post("/chat", json={"session_id": "s1", "message": "hi"})
    assert client.post("/reset/s1").json() == {"ok": True}
    assert session_store.get_session("s1", create=False) is None


# ── PII handling ─────────────────────────────────────────────────────────────


def test_scrub_phone():
    scrubbed, phone, email = scrub_contact("call me 9876543210 ok")
    assert scrubbed == "call me [PHONE] ok"
    assert phone == "9876543210"
    assert email is None


def test_scrub_short_phone():
    scrubbed, phone, email = scrub_contact("lala lajpat rai 123456789")
    assert scrubbed == "lala lajpat rai [PHONE]"
    assert phone == "123456789"
    assert email is None


def test_scrub_spaced_phone():
    scrubbed, phone, email = scrub_contact("+91 98765 43210")
    assert scrubbed == "[PHONE]"
    assert phone == "+91 98765 43210"
    assert email is None


def test_scrub_email():
    scrubbed, phone, email = scrub_contact("mail me at john.doe@example.com please")
    assert scrubbed == "mail me at [EMAIL] please"
    assert email == "john.doe@example.com"
    assert phone is None


def test_scrub_does_not_match_dates():
    scrubbed, phone, email = scrub_contact("visit on 2099-01-01 at 10:30")
    assert scrubbed == "visit on 2099-01-01 at 10:30"
    assert phone is None
    assert email is None


def test_has_contact():
    assert has_contact("my number 123456789")
    assert has_contact("email me at a@b.com")
    assert not has_contact("no contact here")


def test_moderation_output_detection():
    assert is_moderation_output("User Safety: unsafe\nResponse Safety: unsafe\nSafety Categories: PII/Privacy")
    assert is_moderation_output("Safety: unsafe")
    assert not is_moderation_output("normal reply")


def test_chat_contact_short_circuits_model(client, monkeypatch):
    def should_not_call(*a, **k):
        raise AssertionError("model must not be called for contact messages")

    monkeypatch.setattr(main, "call_agent", should_not_call)
    res = client.post("/chat", json={"session_id": "s1", "message": "lala lajpat rai 123456789"})
    session = session_store.get_session("s1")
    assert res.status_code == 200
    assert session.contact_phone == "123456789"
    assert res.json()["contact"] == {"phone": "123456789", "email": None}
    assert "[PHONE]" in session.history[0]["content"]
    assert "123456789" not in session.history[0]["content"]
    assert session.raw_history[0]["content"] == "lala lajpat rai 123456789"
    assert "representative will reach out" in res.json()["reply"]


def test_chat_contact_handoff_references_booked_slot(client):
    session = session_store.get_session("s1")
    session.site_visit_status = "booked"
    session.site_visit_datetime = f"{FUTURE} 10:30"
    res = client.post("/chat", json={"session_id": "s1", "message": "my number is 9876543210"})
    assert f"confirm your visit for {FUTURE} 10:30" in res.json()["reply"]


def test_chat_filters_moderation_output(client, monkeypatch):
    monkeypatch.setattr(
        main, "call_agent",
        lambda *a, **k: "User Safety: unsafe\nResponse Safety: unsafe\nSafety Categories: PII/Privacy",
    )
    res = client.post("/chat", json={"session_id": "s1", "message": "book me"})
    session = session_store.get_session("s1")
    assert res.status_code == 200
    assert "User Safety" not in res.json()["reply"]
    assert "representative will reach out" in res.json()["reply"]
    assert "User Safety" not in " ".join(m["content"] for m in session.history)


def test_analytics_contact_fields(monkeypatch):
    from backend import analytics

    monkeypatch.setattr(analytics, "get_client", lambda: (_ for _ in ()).throw(RuntimeError("no key")))
    session = Session(session_id="s1", contact_phone="9876543210", contact_email="a@b.com")
    result = analytics.generate_analytics(session)
    assert result["customer_phone"] == "9876543210"
    assert result["customer_email"] == "a@b.com"


def test_analytics_transcript_scrubbed(monkeypatch):
    from backend import analytics

    captured = {}

    class StubCompletions:
        def create(self, **kwargs):
            captured["content"] = kwargs["messages"][1]["content"]
            raise RuntimeError("stop")

    class StubChat:
        completions = StubCompletions()

    class StubClient:
        chat = StubChat()

    monkeypatch.setattr(analytics, "get_client", StubClient)
    session = Session(session_id="s1")
    session.raw_history = [
        {"role": "user", "content": "my number is 9876543210"},
        {"role": "assistant", "content": "ok"},
    ]
    analytics.generate_analytics(session)
    assert "[PHONE]" in captured["content"]
    assert "9876543210" not in captured["content"]