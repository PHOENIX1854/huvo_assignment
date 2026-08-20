import json
import re

from .agent import get_client, get_model
from .pii import scrub_contact
from .session_store import Session

ANALYTICS_INSTRUCTION = """You are a sales analytics engine for Northstar Homes.
Analyze the conversation transcript and return ONLY a valid JSON object with no markdown,
no code fences, and no extra text. Use exactly these keys and allowed values:

{
  "customer_name": "string or null",
  "language_used": "English | Hindi | Hinglish | Mixed",
  "configuration_interest": "2 BHK | 3 BHK | Undecided | Not discussed",
  "budget_signal": "string summary or null",
  "purpose": "End-use | Investment | Unknown",
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


def _defaults(session: Session) -> dict:
    return {
        "customer_name": None,
        "customer_phone": session.contact_phone,
        "customer_email": session.contact_email,
        "language_used": "Unknown",
        "configuration_interest": "Not discussed",
        "budget_signal": None,
        "purpose": "Unknown",
        "interest_level": "Cold",
        "objections_raised": [],
        "site_visit_status": {
            "not_offered": "Not offered",
            "offered": "Offered",
            "booked": "Booked",
            "failed": "Failed",
            "declined": "Declined",
        }.get(session.site_visit_status, "Not offered"),
        "site_visit_datetime": session.site_visit_datetime,
        "follow_up_required": False,
        "follow_up_notes": None,
        "do_not_contact": session.dnd,
        "escalated_to_human": session.escalated,
        "escalation_reason": None,
        "conversation_summary": "",
    }


def generate_analytics(session: Session) -> dict:
    transcript = "\n".join(
        f"{m['role'].upper()}: {m['content']}" for m in session.raw_history
    )
    scrubbed_transcript, _, _ = scrub_contact(transcript)
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
    messages = [
        {"role": "system", "content": f"{ANALYTICS_INSTRUCTION}\n\n{facts}"},
        {"role": "user", "content": f"Conversation transcript:\n\n{scrubbed_transcript}"},
    ]
    try:
        response = get_client().chat.completions.create(
            model=get_model(),
            messages=messages,
            temperature=0.0,
            response_format={"type": "json_object"},
        )
        data = _extract_json(response.choices[0].message.content or "")
    except Exception:
        data = None

    result = _defaults(session)
    if data:
        for key in ("customer_name", "language_used", "configuration_interest",
                    "budget_signal", "purpose", "interest_level", "objections_raised",
                    "follow_up_required", "follow_up_notes", "escalation_reason",
                    "conversation_summary"):
            if key in data and data[key] is not None:
                result[key] = data[key]
    return result