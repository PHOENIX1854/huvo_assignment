import json
import re

from .agent import call_agent
from .pii import _PHONE_RE, redact_line
from .session_store import Session

ANALYTICS_INSTRUCTION = """You are a sales analytics engine for Northstar Homes.
Analyze the conversation transcript and return ONLY a valid JSON object with no markdown,
no code fences, and no extra text. Use exactly these keys and allowed values:

{
  "customer_name": "string or null",
  "language_used": "English | Hindi | Hinglish | Mixed",
  "configuration_interest": "2 BHK | 3 BHK | Both | Undecided | Not discussed",
  "budget_signal": "string summary or null",
  "purpose": "End-use | Investment | Both | Unknown",
  "interest_level": "Hot | Warm | Cold",
  "objections_raised": ["price", "comparing_projects", "family_discussion", "not_serious", "other"],
  "site_visit_status": "Booked | Failed | Not offered | Declined",
  "site_visit_datetime": "string or null",
  "follow_up_required": true,
  "follow_up_notes": "string or null",
  "do_not_contact": false,
  "escalated_to_human": false,
  "escalation_reason": "string or null",
  "conversation_summary": "1-2 sentence summary"
}"""

# ── heuristic extraction (used when the LLM call is unavailable) ─────────────

_DEVANAGARI_RE = re.compile(r"[\u0900-\u097F]")
_LATIN_RE = re.compile(r"[A-Za-z]")
_HINGLISH_RE = re.compile(
    r"\b(ka|kya|hai|haan|nahi|nhi|theek|achha|acha|kab|kitna|kyu|kyon|chahiye|baad|aaj|kal|"
    r"bhai|sir|madam|boliye|karne|dekh|mujhe|aap|lo|na|ji|thik)\b",
    re.IGNORECASE,
)
_BHK2_RE = re.compile(r"\b2\s*bhk\b", re.IGNORECASE)
_BHK3_RE = re.compile(r"\b3\s*bhk\b", re.IGNORECASE)
_BUDGET_RE = re.compile(
    r"\b(?:₹|rs\.?|inr)?\s*(\d+(?:\.\d+)?)\s*(crore|cr|lakh|lac)\b",
    re.IGNORECASE,
)
_INVEST_RE = re.compile(r"\binvest(?:ment|ing)?\b", re.IGNORECASE)
_ENDUSE_RE = re.compile(
    r"\b(live|home|self|own|end[- ]?use|stay|resident|buying for myself)\b",
    re.IGNORECASE,
)
_NOT_INTERESTED_RE = re.compile(
    r"\b(not (?:interested|ready)|busy|maybe later|exploring|just checking|no (?:need|thanks))\b",
    re.IGNORECASE,
)
_PRICE_OBJ_RE = re.compile(r"\b(expensive|too (?:high|much)|costly|out of (?:my )?budget|discount)\b", re.IGNORECASE)
_COMPARE_RE = re.compile(r"\b(comparing?|other projects?|alternatives?|competitors?)\b", re.IGNORECASE)
_FAMILY_RE = re.compile(r"\b(family|spouse|wife|husband|parents?|brother|sister)\b", re.IGNORECASE)
_DND_RE = re.compile(
    r"\b(stop contacting|don'?t (?:call|contact|reach)|do not (?:call|contact|reach)|remove me|no more calls)\b",
    re.IGNORECASE,
)
_NAME_RE = re.compile(
    r"(?:my name is|name is|name:)\s+([A-Za-z][A-Za-z.\s'-]{1,60}?)(?=\s*(?:and|number|phone|[,;.]|\d)|$)",
    re.IGNORECASE,
)

_LLM_KEYS = (
    "customer_name", "language_used", "configuration_interest", "budget_signal",
    "purpose", "interest_level", "objections_raised", "follow_up_required",
    "follow_up_notes", "escalation_reason", "conversation_summary",
)

_UNKNOWN_VALUES = {"", "unknown", "null", "none", "not discussed", "not offered", "cold"}


def _extract_json(content: str) -> dict | None:
    if not content:
        return None
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            return data
    except (json.JSONDecodeError, TypeError):
        pass
    match = re.search(r"\{.*\}", content, re.DOTALL)
    if match:
        try:
            data = json.loads(match.group(0))
            if isinstance(data, dict):
                return data
        except (json.JSONDecodeError, TypeError):
            pass
    return None


def _detect_language(transcript: str) -> str:
    has_devanagari = bool(_DEVANAGARI_RE.search(transcript))
    has_latin = bool(_LATIN_RE.search(transcript))
    if has_devanagari and has_latin:
        return "Hinglish"
    if has_devanagari:
        return "Hindi"
    if _HINGLISH_RE.search(transcript):
        return "Hinglish"
    return "English"


def _extract_name(user_text: str) -> str | None:
    for match in _NAME_RE.finditer(user_text):
        candidate = match.group(1).strip().strip(".,;")
        if len(candidate) >= 2:
            return candidate
    for line in user_text.splitlines():
        phone_match = _PHONE_RE.search(line)
        if phone_match:
            before = line[: phone_match.start()].strip().rstrip(",;")
            before = re.sub(
                r"\b(my name is|name is|name|my|is|and|number|phone|call me|i am|am|on|at|with|for|a|the)\b",
                " ",
                before,
                flags=re.IGNORECASE,
            )
            before = re.sub(r"\s+", " ", before).strip()
            words = before.split()
            if 2 <= len(words) <= 4 and all(re.match(r"^[A-Za-z'.-]+$", w) for w in words):
                return " ".join(words)
    return None


def _heuristic_analytics(session: Session) -> dict:
    transcript = "\n".join(m["content"] for m in session.raw_history)
    user_text = "\n".join(m["content"] for m in session.raw_history if m["role"] == "user")

    configs = []
    if _BHK2_RE.search(user_text):
        configs.append("2 BHK")
    if _BHK3_RE.search(user_text):
        configs.append("3 BHK")
    configuration_interest = "Both" if len(configs) == 2 else (configs[0] if configs else "Not discussed")

    budgets = []
    for match in _BUDGET_RE.finditer(user_text):
        try:
            value = float(match.group(1))
        except ValueError:
            continue
        unit = match.group(2).lower()
        in_crore = value / 100.0 if unit in ("lakh", "lac") else value
        budgets.append(in_crore)
    budget_signal = f"₹{max(budgets):g} crore" if budgets else None

    invest = bool(_INVEST_RE.search(user_text))
    enduse = bool(_ENDUSE_RE.search(user_text))
    if invest and enduse:
        purpose = "Both"
    elif invest:
        purpose = "Investment"
    elif enduse:
        purpose = "End-use"
    else:
        purpose = "Unknown"

    if session.dnd or _DND_RE.search(user_text):
        interest = "Cold"
    elif session.site_visit_status == "booked":
        interest = "Hot"
    elif not _NOT_INTERESTED_RE.search(user_text) and len(session.raw_history) >= 2:
        interest = "Warm"
    else:
        interest = "Cold"

    objections = []
    if _PRICE_OBJ_RE.search(user_text):
        objections.append("price")
    if _COMPARE_RE.search(user_text):
        objections.append("comparing_projects")
    if _FAMILY_RE.search(user_text):
        objections.append("family_discussion")
    if _NOT_INTERESTED_RE.search(user_text):
        objections.append("not_serious")

    name = _extract_name(user_text)

    if session.dnd:
        follow_up_required = False
        follow_up_notes = None
    else:
        follow_up_required = True
        if session.site_visit_status == "booked":
            follow_up_notes = (
                f"Confirm the site visit scheduled for {session.site_visit_datetime} "
                "and share property details."
            )
        else:
            follow_up_notes = "Follow up on the warm lead and offer a site visit."

    if configuration_interest != "Not discussed" or budget_signal or purpose != "Unknown":
        purpose_word = {
            "Both": "end-use and investment",
            "End-use": "end-use",
            "Investment": "investment",
            "Unknown": "a home",
        }[purpose]
        summary = (
            f"Customer interested in {configuration_interest} with a budget of "
            f"{budget_signal or 'unknown'} for {purpose_word}. "
            f"Site visit {'booked for ' + session.site_visit_datetime if session.site_visit_status == 'booked' else 'not booked'}. "
            f"Contact details {'captured' if session.contact_captured else 'not captured'}."
        )
    else:
        summary = "Conversation did not reach the qualification stage."

    return {
        "customer_name": name,
        "customer_phone": session.contact_phone,
        "customer_email": session.contact_email,
        "language_used": _detect_language(transcript),
        "configuration_interest": configuration_interest,
        "budget_signal": budget_signal,
        "purpose": purpose,
        "interest_level": interest,
        "objections_raised": objections,
        "site_visit_status": {
            "not_offered": "Not offered",
            "offered": "Offered",
            "booked": "Booked",
            "failed": "Failed",
            "declined": "Declined",
        }.get(session.site_visit_status, "Not offered"),
        "site_visit_datetime": session.site_visit_datetime,
        "follow_up_required": follow_up_required,
        "follow_up_notes": follow_up_notes,
        "do_not_contact": session.dnd,
        "escalated_to_human": session.escalated,
        "escalation_reason": None,
        "conversation_summary": summary,
    }


def generate_analytics(session: Session) -> dict:
    transcript = "\n".join(
        f"{m['role'].upper()}: {redact_line(m['content'])}" for m in session.raw_history
    )
    facts = (
        f"Session facts from the booking system (trust these over the transcript):\n"
        f"- site_visit_status={session.site_visit_status}\n"
        f"- site_visit_datetime={session.site_visit_datetime}\n"
        f"- booking_attempts={session.booking_attempts}\n"
        f"- do_not_contact={session.dnd}\n"
        f"- escalated_to_human={session.escalated}\n"
        f"- customer_phone={session.contact_phone}\n"
        f"- customer_email={session.contact_email}"
    )

    result = _heuristic_analytics(session)
    try:
        content = call_agent(
            f"{ANALYTICS_INSTRUCTION}\n\n{facts}",
            [{"role": "user", "content": f"Conversation transcript:\n\n{transcript}"}],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        data = _extract_json(content)
    except Exception:
        data = None

    if data:
        for key in _LLM_KEYS:
            if key in data and data[key] is not None:
                value = data[key]
                if key in ("language_used", "configuration_interest", "purpose", "interest_level"):
                    if str(value).strip().lower() in _UNKNOWN_VALUES:
                        continue
                if isinstance(value, str) and not value.strip():
                    continue
                result[key] = value
    return result