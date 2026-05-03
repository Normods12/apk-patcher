import json
from pathlib import Path
from threading import Lock
import time


from automation.config import BASE_DIR


RUNTIME_DIR = BASE_DIR / "runtime"
CONTROL_FILE = RUNTIME_DIR / "control.json"
STATUS_FILE = RUNTIME_DIR / "status.json"
_LOCK = Lock()



DEFAULT_STATE = {
    "stop_requested": False,
    "paused": False,
    "last_action": "init",
}


def _ensure_file() -> None:
    RUNTIME_DIR.mkdir(parents=True, exist_ok=True)
    if not CONTROL_FILE.exists():
        CONTROL_FILE.write_text(json.dumps(DEFAULT_STATE, indent=2), encoding="utf-8")


def get_state() -> dict:
    _ensure_file()
    with _LOCK:
        try:
            data = json.loads(CONTROL_FILE.read_text(encoding="utf-8"))
            for k, v in DEFAULT_STATE.items():
                data.setdefault(k, v)
            return data
        except Exception:
            return dict(DEFAULT_STATE)


def set_state(**updates) -> dict:
    _ensure_file()
    with _LOCK:
        try:
            state = json.loads(CONTROL_FILE.read_text(encoding="utf-8"))
        except Exception:
            state = dict(DEFAULT_STATE)
        for k, v in DEFAULT_STATE.items():
            state.setdefault(k, v)
        state.update(updates)
        CONTROL_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
        return state


def request_stop() -> dict:
    return set_state(stop_requested=True, paused=False, last_action="force_stop")


def clear_stop() -> dict:
    return set_state(stop_requested=False, paused=False, last_action="resume")


def mark_paused() -> dict:
    return set_state(paused=True, last_action="paused")


def update_current_status(activity: str, details: dict = None) -> None:
    _ensure_file()
    try:
        data = {
            "activity": activity,
            "details": details or {},
            "timestamp": time.time(),
            "readable_time": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        STATUS_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")
    except Exception:
        pass


def get_current_status() -> dict:
    if not STATUS_FILE.exists():
        return {"activity": "Unknown", "details": {}, "timestamp": 0}
    try:
        return json.loads(STATUS_FILE.read_text(encoding="utf-8"))
    except Exception:
        return {"activity": "Unknown", "details": {}, "timestamp": 0}

