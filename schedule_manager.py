import json
import random
from pathlib import Path
from datetime import datetime, timedelta

APP_DIR = Path(__file__).parent
CONFIG_PATH = APP_DIR / "schedule_config.json"

DEFAULT_CONFIG = {
    "scheduling_enabled": False,
    "random_interval_enabled": True,
    "time_windows": [
        {"name": "Morning", "start": "09:00", "end": "12:00", "enabled": True},
        {"name": "Afternoon", "start": "14:00", "end": "17:00", "enabled": False},
        {"name": "Evening", "start": "18:00", "end": "21:00", "enabled": True}
    ]
}

def load_schedule_config():
    if CONFIG_PATH.exists():
        try:
            return json.loads(CONFIG_PATH.read_text())
        except Exception:
            pass
    save_schedule_config(DEFAULT_CONFIG)
    return DEFAULT_CONFIG.copy()

def save_schedule_config(config):
    CONFIG_PATH.write_text(json.dumps(config, indent=2))

def _parse_time(t_str):
    parts = t_str.strip().split(":")
    return int(parts[0]), int(parts[1])

def _in_window(now, start_str, end_str):
    sh, sm = _parse_time(start_str)
    eh, em = _parse_time(end_str)
    now_min = now.hour * 60 + now.minute
    start_min = sh * 60 + sm
    end_min = eh * 60 + em
    return start_min <= now_min < end_min

def _minutes_until_next_window(now, windows):
    now_min = now.hour * 60 + now.minute
    best = None
    for w in windows:
        if not w.get("enabled", True):
            continue
        sh, sm = _parse_time(w["start"])
        start_min = sh * 60 + sm
        if start_min > now_min:
            diff = start_min - now_min
            if best is None or diff < best:
                best = diff
    if best is None:
        tomorrow_open = None
        for w in windows:
            if not w.get("enabled", True):
                continue
            sh, sm = _parse_time(w["start"])
            diff = (24 * 60 - now_min) + (sh * 60 + sm)
            if tomorrow_open is None or diff < tomorrow_open:
                tomorrow_open = diff
        return tomorrow_open
    return best

def calculate_wait(base_min_h, base_max_h, pipeline="reel"):
    cfg = load_schedule_config()
    now = datetime.now()
    enabled_windows = [w for w in cfg.get("time_windows", []) if w.get("enabled", True)]
    if not cfg.get("scheduling_enabled", False) or not enabled_windows:
        if cfg.get("random_interval_enabled", True):
            wait_h = random.uniform(base_min_h, base_max_h)
        else:
            wait_h = base_min_h
        return wait_h
    in_any_window = any(_in_window(now, w["start"], w["end"]) for w in enabled_windows)
    if in_any_window:
        if cfg.get("random_interval_enabled", True):
            wait_h = random.uniform(base_min_h, base_max_h)
        else:
            wait_h = base_min_h
        return wait_h
    mins = _minutes_until_next_window(now, enabled_windows)
    if mins is None:
        wait_h = base_min_h
    else:
        wait_h = mins / 60.0
        if cfg.get("random_interval_enabled", True):
            wait_h += random.uniform(0, 0.5)
    return wait_h

def get_next_post_description(pipeline="reel"):
    cfg = load_schedule_config()
    if not cfg.get("scheduling_enabled", False):
        if cfg.get("random_interval_enabled", True):
            return "Random interval"
        return "Fixed interval"
    now = datetime.now()
    enabled_windows = [w for w in cfg.get("time_windows", []) if w.get("enabled", True)]
    if not enabled_windows:
        return "No windows enabled"
    in_any = any(_in_window(now, w["start"], w["end"]) for w in enabled_windows)
    if in_any:
        names = [w["name"] for w in enabled_windows if _in_window(now, w["start"], w["end"])]
        return "In window: " + ", ".join(names)
    mins = _minutes_until_next_window(now, enabled_windows)
    if mins:
        return "Outside window - next opens in " + str(mins) + " min"
    return "Unknown"
