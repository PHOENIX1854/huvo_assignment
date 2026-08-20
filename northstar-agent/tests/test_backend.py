import re
import time

import pytest
from fastapi.testclient import TestClient

from backend import agent, analytics_store, main, session_store
from backend.constants import is_slot_available
from backend.pii import has_contact, is_moderation_output, redact_line, scrub_contact
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
    assert "snag" in res.json()["reply"]
    assert "representative" in res.json()["reply"]


def test_chat_rep_request_while_model_down(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(main, "call_agent", boom)
    res = client.post("/chat", json={"session_id": "s1", "message": "northstar representative"})
    assert "representative should contact you" in res.json()["reply"]
    assert "share the best contact number" in res.json()["reply"]


def test_chat_rep_request_with_contact_while_model_down(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(main, "call_agent", boom)
    session = session_store.get_session("s1")
    session.contact_phone = "9876543210"
    session.contact_captured = True
    res = client.post("/chat", json={"session_id": "s1", "message": "northstar representative"})
    assert "They'll reach out shortly" in res.json()["reply"]
    assert "share the best contact number" not in res.json()["reply"]


def test_chat_rep_request_captures_number_without_model(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(main, "call_agent", boom)
    client.post("/chat", json={"session_id": "s1", "message": "northstar representative"})
    session = session_store.get_session("s1")
    assert session.contact_captured is False

    res = client.post("/chat", json={"session_id": "s1", "message": "my number is 9876543210"})
    session = session_store.get_session("s1")
    assert session.contact_phone == "9876543210"
    assert session.contact_captured is True
    assert "representative will reach out shortly" in res.json()["reply"]
    assert "9876543210" not in res.json()["reply"]


def test_chat_degraded_message_changes_after_first_failure(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(main, "call_agent", boom)
    first = client.post("/chat", json={"session_id": "s1", "message": "2bhk"})
    assert "temporary snag" in first.json()["reply"]
    second = client.post("/chat", json={"session_id": "s1", "message": "any discount?"})
    assert "still unable" in second.json()["reply"]


def test_chat_fallback_uses_session_facts(client, monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("llm down")

    monkeypatch.setattr(main, "call_agent", boom)
    session = session_store.get_session("s1")
    session.site_visit_status = "booked"
    session.site_visit_datetime = f"{FUTURE} 10:30"
    res = client.post("/chat", json={"session_id": "s1", "message": "what was my visit time"})
    assert f"confirmed for {FUTURE} 10:30" in res.json()["reply"]


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
    assert "representative will reach out" in res.json()["reply"]


def test_end_conversation_sets_ended_and_saves_analytics(client, monkeypatch, tmp_path):
    fake = {"customer_name": "Rahul", "interest_level": "Hot"}
    monkeypatch.setattr(main, "generate_analytics", lambda s: fake)
    monkeypatch.setattr(analytics_store, "ANALYTICS_DIR", str(tmp_path))
    res = client.post("/end/s1")
    assert res.status_code == 200
    assert res.json()["ok"] is True
    assert session_store.get_session("s1").ended is True

    saved = analytics_store.load_analytics("s1")
    assert saved["session_id"] == "s1"
    assert saved["analytics"] == fake


def test_analytics_not_available_before_end(client):
    res = client.get("/analytics/s1")
    assert res.status_code == 404


def test_analytics_available_after_end(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "generate_analytics", lambda s: {"customer_name": "Rahul"})
    monkeypatch.setattr(analytics_store, "ANALYTICS_DIR", str(tmp_path))
    client.post("/end/s1")
    res = client.get("/analytics/s1")
    assert res.status_code == 200
    assert res.json()["customer_name"] == "Rahul"


def test_analytics_survive_session_restart(client, monkeypatch, tmp_path):
    monkeypatch.setattr(main, "generate_analytics", lambda s: {"customer_name": "Priya"})
    monkeypatch.setattr(analytics_store, "ANALYTICS_DIR", str(tmp_path))
    client.post("/end/s1")
    session_store.reset_session("s1")
    assert session_store.get_session("s1", create=False) is None
    res = client.get("/analytics/s1")
    assert res.status_code == 200
    assert res.json()["customer_name"] == "Priya"


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


def test_redact_line():
    assert redact_line("lala lajpat rai 123456789") == "[CUSTOMER_DETAILS]"
    assert redact_line("call me on 9876543210 please") == "[CUSTOMER_DETAILS]"
    assert redact_line("plain message") == "plain message"


def test_build_system_prompt_includes_session_state():
    session = Session(session_id="s1")
    session.site_visit_status = "booked"
    session.site_visit_datetime = f"{FUTURE} 10:30"
    session.contact_captured = True
    prompt = agent.build_system_prompt(session=session)
    assert f"- site_visit_datetime: {FUTURE} 10:30" in prompt
    assert "- contact_captured: yes" in prompt
    assert "do not repeat the full number in chat" in prompt


def test_call_agent_retries_transient_error(monkeypatch):
    calls = {"n": 0}

    class RateLimitError(RuntimeError):
        pass

    class StubCompletions:
        def create(self, **kwargs):
            calls["n"] += 1
            if calls["n"] == 1:
                raise RateLimitError("rate limited")
            return type("R", (), {"choices": [type("C", (), {"message": type("M", (), {"content": "ok"})})()]})()

    class StubChat:
        completions = StubCompletions()

    class StubClient:
        chat = StubChat()

    monkeypatch.setattr(agent, "get_client", lambda: StubClient())
    assert agent.call_agent("sys", [], temperature=0.0) == "ok"
    assert calls["n"] == 2


def test_call_agent_does_not_retry_non_transient(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("hard failure")

    monkeypatch.setattr(agent, "get_client", lambda: type("C", (), {"chat": type("Ch", (), {"completions": type("Co", (), {"create": staticmethod(boom)})})()})())
    with pytest.raises(RuntimeError):
        agent.call_agent("sys", [], temperature=0.0)


def test_is_transient_daily_limit_not_retried():
    class DailyLimitError(RuntimeError):
        status_code = 429

    exc = DailyLimitError("Rate limit exceeded: free-models-per-day")
    assert agent._is_transient(exc) is False


def test_call_agent_cooldown_skips_calls(monkeypatch):
    calls = {"n": 0}

    class TransientError(RuntimeError):
        status_code = 503

    class StubCompletions:
        def create(self, **kwargs):
            calls["n"] += 1
            raise TransientError("boom")

    class StubChat:
        completions = StubCompletions()

    class StubClient:
        chat = StubChat()

    monkeypatch.setattr(agent, "get_client", lambda: StubClient())
    monkeypatch.setattr(agent, "_last_model_failure", None)
    with pytest.raises(TransientError):
        agent.call_agent("sys", [], temperature=0.0, retries=0)
    assert calls["n"] == 1
    with pytest.raises(agent.ModelUnavailableError):
        agent.call_agent("sys", [], temperature=0.0, retries=0)
    assert calls["n"] == 1
    monkeypatch.setattr(agent, "_last_model_failure", None)


def test_full_conversation_recalls_session_facts(client, monkeypatch):
    def fake_agent(system_prompt, history, temperature=0.4):
        last_user = history[-1]["content"].lower()
        if "timing" in last_user or "visit time" in last_user:
            m = re.search(r"site_visit_datetime: (\S+ \S+)", system_prompt)
            if m:
                return f"Your visit is confirmed for {m.group(1)} at Sector 79, Gurugram."
        if "name and phone" in last_user or "my number" in last_user:
            return "Your details are safely captured — a Northstar representative will confirm them with you."
        if "book" in last_user:
            return f"[BOOK_ATTEMPT date={FUTURE} time=10:30]"
        return "ok"

    monkeypatch.setattr(main, "call_agent", fake_agent)

    client.post("/chat", json={"session_id": "s1", "message": "book me a visit"})
    session = session_store.get_session("s1")
    assert session.site_visit_datetime == f"{FUTURE} 10:30"

    res = client.post("/chat", json={"session_id": "s1", "message": "lala lajpat rai 1234567890"})
    assert session.contact_captured is True
    assert session.history[-2]["content"] == "[CUSTOMER_DETAILS]"

    res = client.post("/chat", json={"session_id": "s1", "message": "ok what was my timing for visit"})
    assert f"confirmed for {FUTURE} 10:30" in res.json()["reply"]
    assert res.json()["booking"]["datetime"] == f"{FUTURE} 10:30"

    res = client.post("/chat", json={"session_id": "s1", "message": "tell me the name and phone no. i just gave you"})
    assert "representative will confirm" in res.json()["reply"]
    assert "1234567890" not in res.json()["reply"]

    model_visible = " ".join(m["content"] for m in session.history)
    assert "1234567890" not in model_visible
    assert "lala" not in model_visible


def test_chat_contact_short_circuits_model(client, monkeypatch):
    def should_not_call(*a, **k):
        raise AssertionError("model must not be called for contact messages")

    monkeypatch.setattr(main, "call_agent", should_not_call)
    res = client.post("/chat", json={"session_id": "s1", "message": "lala lajpat rai 123456789"})
    session = session_store.get_session("s1")
    assert res.status_code == 200
    assert session.contact_phone == "123456789"
    assert session.contact_captured is True
    assert res.json()["contact"] == {"phone": "123456789", "email": None}
    assert session.history[0]["content"] == "[CUSTOMER_DETAILS]"
    assert "lala" not in session.history[0]["content"]
    assert session.raw_history[0]["content"] == "lala lajpat rai 123456789"
    assert "representative will reach out" in res.json()["reply"]


def test_chat_response_includes_booking(client):
    session = session_store.get_session("s1")
    session.site_visit_status = "booked"
    session.site_visit_datetime = f"{FUTURE} 10:30"
    res = client.post("/chat", json={"session_id": "s1", "message": "hi"})
    assert res.json()["booking"] == {"status": "booked", "datetime": f"{FUTURE} 10:30"}


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

    def boom(*a, **k):
        raise RuntimeError("no key")

    monkeypatch.setattr(analytics, "call_agent", boom)
    session = Session(session_id="s1", contact_phone="9876543210", contact_email="a@b.com")
    result = analytics.generate_analytics(session)
    assert result["customer_phone"] == "9876543210"
    assert result["customer_email"] == "a@b.com"


def test_analytics_transcript_scrubbed(monkeypatch):
    from backend import analytics

    captured = {}

    def fake_call_agent(system_prompt, history, **kwargs):
        captured["content"] = history[0]["content"]
        raise RuntimeError("stop")

    monkeypatch.setattr(analytics, "call_agent", fake_call_agent)
    session = Session(session_id="s1")
    session.raw_history = [
        {"role": "user", "content": "my name is lala lajpat rai, number 9876543210"},
        {"role": "assistant", "content": "ok"},
    ]
    analytics.generate_analytics(session)
    assert "[CUSTOMER_DETAILS]" in captured["content"]
    assert "9876543210" not in captured["content"]
    assert "lala" not in captured["content"]


def test_analytics_heuristic_full_report(monkeypatch):
    from backend import analytics

    def boom(*a, **k):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(analytics, "call_agent", boom)
    session = Session(session_id="s1")
    session.raw_history = [
        {"role": "user", "content": "i want 2 bhk to invest and 3 bhk to live"},
        {"role": "assistant", "content": "what budget do you have in mind?"},
        {"role": "user", "content": "my budget is 4 cr and i would like to move in 2 months"},
        {"role": "assistant", "content": "which config first?"},
        {"role": "user", "content": "my name is lala lajpat rai and number is 9876543210"},
    ]
    session.contact_phone = "9876543210"
    session.contact_captured = True
    session.site_visit_status = "booked"
    session.site_visit_datetime = f"{FUTURE} 10:30"

    result = analytics.generate_analytics(session)
    assert result["configuration_interest"] == "Both"
    assert result["budget_signal"] == "₹4 crore"
    assert result["purpose"] == "Both"
    assert result["interest_level"] == "Hot"
    assert result["language_used"] == "English"
    assert result["customer_name"] == "lala lajpat rai"
    assert result["site_visit_status"] == "Booked"
    assert result["site_visit_datetime"] == f"{FUTURE} 10:30"
    assert result["follow_up_required"] is True
    assert result["conversation_summary"]


def test_analytics_heuristic_name_from_phone_message():
    from backend import analytics

    session = Session(session_id="s1")
    session.raw_history = [{"role": "user", "content": "lala lajpat rai 1234567890"}]
    assert analytics._heuristic_analytics(session)["customer_name"] == "lala lajpat rai"


def test_analytics_heuristic_language_detection():
    from backend import analytics

    assert analytics._detect_language("hello, kya price hai?") == "Hinglish"
    assert analytics._detect_language("नमस्ते, कीमत क्या है?") == "Hindi"
    assert analytics._detect_language("नमस्ते sir, price kya hai?") == "Hinglish"
    assert analytics._detect_language("hello, what is the price?") == "English"