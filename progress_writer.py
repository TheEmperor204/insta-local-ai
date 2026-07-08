#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime

PROGRESS_STATUS = Path("progress_status.json")
APPROVAL_QUEUE = Path("approval_queue.json")
ON_HOLD_FILE = Path("on_hold_videos.json")

_stage_start = {}

def update_progress(stage, details=""):
    """Write progress update to JSON file for dashboard."""
    now = datetime.now()
    data = {"stage": stage, "details": details}
    data["updated_at"] = now.isoformat()
    times = {}
    if _stage_start:
        prev_stage = list(_stage_start.keys())[-1]
        prev_time = _stage_start[prev_stage]
        elapsed = (now - prev_time).total_seconds()
        times[prev_stage] = round(elapsed, 1)
    _stage_start[stage] = now
    prev_file = PROGRESS_STATUS if PROGRESS_STATUS.exists() else None
    if prev_file:
        try:
            old_data = json.loads(prev_file.read_text())
            old_times = old_data.get("times", {})
            old_times.update(times)
            times = old_times
        except Exception:
            pass
    data["times"] = times
    PROGRESS_STATUS.write_text(json.dumps(data, indent=2))

def add_error(error_msg):
    """Log an error to the progress dashboard."""
    if PROGRESS_STATUS.exists():
        try:
            data = json.loads(PROGRESS_STATUS.read_text())
            data["error"] = error_msg
            PROGRESS_STATUS.write_text(json.dumps(data, indent=2))
        except Exception:
            pass
    else:
        data = {"stage": "error", "error": error_msg, "updated_at": datetime.now().isoformat()}
        PROGRESS_STATUS.write_text(json.dumps(data, indent=2))

def clear_error():
    """Clear the error message."""
    if PROGRESS_STATUS.exists():
        try:
            data = json.loads(PROGRESS_STATUS.read_text())
            if "error" in data:
                del data["error"]
                PROGRESS_STATUS.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

def clear_progress():
    """Remove progress status file."""
    if PROGRESS_STATUS.exists():
        PROGRESS_STATUS.unlink()

def load_approval_queue():
    """Load approval decisions from GUI."""
    if APPROVAL_QUEUE.exists():
        try:
            return json.load(open(APPROVAL_QUEUE))
        except Exception:
            pass
    return []

def get_approval_for_video(video_path):
    """Find matching approval decision for a video by name."""
    queue = load_approval_queue()
    for q in queue:
        approved_to = q.get("approved_to", "")
        if approved_to and Path(approved_to).name == Path(video_path).name:
            return q
    return None

def remove_approval_for_video(video_path):
    """Remove processed approval entry."""
    queue = load_approval_queue()
    remaining = [q for q in queue if q.get("approved_to", "") != str(video_path)]
    APPROVAL_QUEUE.write_text(json.dumps(remaining, indent=2))

def save_on_hold_video(video_path, name):
    """Add video to on_hold list so poster skips it until approved."""
    entries = []
    if ON_HOLD_FILE.exists():
        try:
            entries = json.loads(ON_HOLD_FILE.read_text())
        except Exception:
            pass
    if not any(e.get("video_path") == str(video_path) for e in entries):
        entries.append({"video_path": str(video_path), "name": name, "held_at": datetime.now().isoformat()})
    ON_HOLD_FILE.write_text(json.dumps(entries, indent=2))

def remove_on_hold_video(video_path):
    """Remove video from on_hold list."""
    if not ON_HOLD_FILE.exists():
        return
    try:
        entries = json.loads(ON_HOLD_FILE.read_text())
        remaining = [e for e in entries if e.get("video_path") != str(video_path)]
        ON_HOLD_FILE.write_text(json.dumps(remaining, indent=2))
    except Exception:
        pass

def get_on_hold_videos():
    """Return list of on-hold video paths."""
    if not ON_HOLD_FILE.exists():
        return []
    try:
        entries = json.loads(ON_HOLD_FILE.read_text())
        return [e.get("video_path") for e in entries]
    except Exception:
        return []

SKIP_SEGMENTS_FILE = Path("skip_segments.json")

def save_skip_segments(video_name, segments_to_skip):
    """Store which segments to skip for a video."""
    data = {}
    if SKIP_SEGMENTS_FILE.exists():
        try:
            data = json.loads(SKIP_SEGMENTS_FILE.read_text())
        except Exception:
            pass
    data[video_name] = list(segments_to_skip)
    SKIP_SEGMENTS_FILE.write_text(json.dumps(data, indent=2))

def get_skip_segments(video_name):
    """Return list of segment numbers to skip, or empty list."""
    if not SKIP_SEGMENTS_FILE.exists():
        return []
    try:
        data = json.loads(SKIP_SEGMENTS_FILE.read_text())
        return data.get(video_name, [])
    except Exception:
        return []

def clear_skip_segments(video_name):
    """Remove skip segments entry after all segments processed."""
    if not SKIP_SEGMENTS_FILE.exists():
        return
    try:
        data = json.loads(SKIP_SEGMENTS_FILE.read_text())
        if video_name in data:
            del data[video_name]
            SKIP_SEGMENTS_FILE.write_text(json.dumps(data, indent=2))
    except Exception:
        pass

def send_notification(title, message, priority="default"):
    """Send push notification via ntfy."""
    import requests
    import os
    topic = os.getenv("NTFY_TOPIC", "")
    if not topic:
        return
    try:
        requests.post(
            f"https://ntfy.sh/{topic}",
            data=message.encode(),
            headers={"Title": title, "Priority": priority},
            timeout=10
        )
    except Exception:
        pass

EXPLICIT_TRIGGER = Path("explicit_trigger.json")

def signal_explicit_detected(video_path, matched_word):
    """Create marker file to trigger explicit tab refresh."""
    EXPLICIT_TRIGGER.write_text(json.dumps({
        "video": str(video_path),
        "word": matched_word,
        "timestamp": datetime.now().isoformat()
    }))

def clear_explicit_trigger():
    """Remove trigger marker after refresh."""
    if EXPLICIT_TRIGGER.exists():
        EXPLICIT_TRIGGER.unlink()

# Failed upload tracking
FAILED_UPLOADS_FILE = Path("failed_uploads.json")

def load_failed_uploads():
    if FAILED_UPLOADS_FILE.exists():
        try:
            return json.loads(FAILED_UPLOADS_FILE.read_text())
        except Exception:
            pass
    return {}

def save_failed_uploads(data):
    FAILED_UPLOADS_FILE.write_text(json.dumps(data, indent=2))

def increment_retry(video_name):
    data = load_failed_uploads()
    if video_name not in data:
        data[video_name] = {"retries": 0, "first_attempt": datetime.now().isoformat()}
    data[video_name]["retries"] += 1
    data[video_name]["last_attempt"] = datetime.now().isoformat()
    save_failed_uploads(data)
    return data[video_name]["retries"]

def clear_failed_upload(video_name):
    data = load_failed_uploads()
    if video_name in data:
        del data[video_name]
        save_failed_uploads(data)

def get_retry_count(video_name):
    data = load_failed_uploads()
    if video_name in data:
        return data[video_name]["retries"]
    return 0
