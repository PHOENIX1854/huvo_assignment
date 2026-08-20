import json
import os

from datetime import datetime, timezone

DATA_DIR = os.path.join(os.path.dirname(__file__), "..", "data")
ANALYTICS_DIR = os.path.join(DATA_DIR, "analytics")


def analytics_path(session_id: str) -> str:
    return os.path.join(ANALYTICS_DIR, f"{session_id}.json")


def save_analytics(session_id: str, analytics: dict) -> str:
    os.makedirs(ANALYTICS_DIR, exist_ok=True)
    payload = {
        "session_id": session_id,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "analytics": analytics,
    }
    path = analytics_path(session_id)
    tmp_path = path + ".tmp"
    with open(tmp_path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, ensure_ascii=False)
    os.replace(tmp_path, path)
    return path


def load_analytics(session_id: str) -> dict | None:
    path = analytics_path(session_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None