from datetime import datetime, timedelta, timezone

IST = timezone(timedelta(hours=5, minutes=30))

UNAVAILABLE_TIMES = {"11:00"}

BOOKING_ATTEMPT_PATTERN = r"\[BOOK_ATTEMPT date=(\d{4}-\d{2}-\d{2}) time=(\d{2}:\d{2})\]"


def is_slot_available(date_str: str, time_str: str) -> tuple[bool, str]:
    try:
        dt = datetime.fromisoformat(f"{date_str}T{time_str}")
    except ValueError:
        return False, "invalid"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=IST)
    if dt < datetime.now(IST):
        return False, "past"
    if time_str in UNAVAILABLE_TIMES:
        return False, "unavailable"
    return True, "available"