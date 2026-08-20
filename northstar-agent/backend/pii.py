import re

_PHONE_RE = re.compile(
    r"(?<!\d)(?:\+?91[-\s]?)?(?:\d{5}[-\s]\d{5}|\d{7,15})(?!\d)"
)
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")

_MODERATION_RE = re.compile(
    r"(?m)^\s*(User Safety|Response Safety|Safety Categories|Safety)\s*:",
    re.IGNORECASE,
)

SENSITIVE_MARKER = "[CUSTOMER_DETAILS]"


def scrub_contact(text: str) -> tuple[str, str | None, str | None]:
    phone = None
    email = None
    m = _PHONE_RE.search(text)
    if m:
        phone = m.group(0).strip()
    m = _EMAIL_RE.search(text)
    if m:
        email = m.group(0).strip()
    scrubbed = _EMAIL_RE.sub("[EMAIL]", text)
    scrubbed = _PHONE_RE.sub("[PHONE]", scrubbed)
    return scrubbed, phone, email


def has_contact(text: str) -> bool:
    return _PHONE_RE.search(text) is not None or _EMAIL_RE.search(text) is not None


def redact_line(text: str) -> str:
    if has_contact(text):
        return SENSITIVE_MARKER
    return text


def is_moderation_output(text: str) -> bool:
    return bool(_MODERATION_RE.search(text))