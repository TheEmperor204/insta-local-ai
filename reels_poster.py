#!/usr/bin/env python3
"""
Reels Auto-Poster — Independent video pipeline.
Scans videos_to_upload/, splits long videos, analyzes frames + audio,
generates captions, and uploads as Instagram Reels.
Runs on a separate timer from the photo poster.
"""

import os
import sys
import json
import time
import logging
import subprocess
import shutil
import signal
import atexit
import glob
import math
import tempfile
import base64
from pathlib import Path
from datetime import datetime
from music_overlay import add_music_to_video
from progress_writer import update_progress, clear_progress, add_error, clear_error, get_approval_for_video, remove_approval_for_video, save_on_hold_video, remove_on_hold_video, get_on_hold_videos, save_skip_segments, get_skip_segments, clear_skip_segments, send_notification, signal_explicit_detected, clear_explicit_trigger

from dotenv import load_dotenv
load_dotenv(override=True)

from explicit_filter import check_explicit

try:
    from caption_persona import PERSONA_REEL
except ImportError:
    PERSONA_REEL = ""

try:
    import keyring
    KEYRING_AVAILABLE = True
except ImportError:
    KEYRING_AVAILABLE = False

KEYRING_SERVICE = "insta-poster"
KEYRING_KEY = "ig_password"

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
log = logging.getLogger("reels-poster")

# =============================================================================
# CONFIGURATION
# =============================================================================

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
VISION_MODEL = os.getenv("VISION_MODEL", "llava:7b")
CAPTION_MODEL = os.getenv("CAPTION_MODEL", "qwen2.5:7b")
VISION_PROMPT = os.getenv("VISION_PROMPT", "Describe this image in detail.")
IG_USERNAME = os.getenv("IG_USERNAME", "")

IG_PASSWORD = ""
if KEYRING_AVAILABLE:
    _kr_pw = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY)
    if _kr_pw:
        IG_PASSWORD = _kr_pw
if not IG_PASSWORD:
    IG_PASSWORD = os.getenv("IG_PASSWORD", "")

VIDEO_FOLDER_PATH = Path(os.getenv("VIDEO_FOLDER", "videos_to_upload"))
POSTED_REELS_DIR = Path(os.getenv("POSTED_REELS_DIR", "insta_posted_youtube_ready"))
TEMP_SEGMENTS_DIR = Path(os.getenv("TEMP_SEGMENTS_DIR", "temp_segments"))
MAX_REEL_DURATION = int(os.getenv("MAX_REEL_DURATION_SECONDS", "60"))
MIN_SEGMENT_DURATION = int(os.getenv("MIN_SEGMENT_SECONDS", "30"))
REELS_LOG_PATH = Path(os.getenv("REELS_LOG", "posted_reels.json"))

EXPLICIT_VIDEOS_DIR = Path(os.getenv("EXPLICIT_VIDEOS_DIR", "explicit_videos"))
VIDEO_DUPLICATES_DIR = Path(os.getenv("VIDEO_DUPLICATES_DIR", "video_duplicates"))
POSTED_VIDEOS_TXT = Path(os.getenv("POSTED_VIDEOS_TXT", "posted_videos.txt"))
BLEEP_CONFIG_FILE = Path("bleep_words.json")
def load_bleep_config():
    try:
        data = json.loads(BLEEP_CONFIG_FILE.read_text())
        return data.get("words", []), data.get("enabled", True)
    except Exception:
        return ["fuck","fucking","fucked"], True

BLEEP_WORDS, BLEEP_ENABLED = load_bleep_config()

DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
DRY_RUN_DIR = Path.home() / "Desktop" / "INSTAI_TEST_OUTPUT"

# Stricter prompt for video frame analysis — prevents speculation
VIDEO_FRAME_PROMPT = "Describe visible actions, objects, and equipment. Format: A person [action]. Objects: [concrete items]. Equipment/Activity: [specific if visible]. Setting: [brief]. Identify recognizable gear like tubes, skis, boats, ropes. Avoid guessing emotions, thoughts, or events before/after. If unclear, write action unclear. 3 sentences max."

# Ensure required folders exist
for _d in [VIDEO_FOLDER_PATH, POSTED_REELS_DIR, TEMP_SEGMENTS_DIR, EXPLICIT_VIDEOS_DIR, VIDEO_DUPLICATES_DIR]:
    _d.mkdir(parents=True, exist_ok=True)

VIDEO_EXTS = {".mp4", ".mov", ".avi"}

PYTHON312 = "python3.12"
TRANSCRIBE_HELPER = str(Path(__file__).resolve().parent / "transcribe_helper.py")

try:
    import requests
except ImportError:
    log.error("requests not installed")
    add_error("requests not installed")
    sys.exit(1)

try:
    from instagrapi import Client
except ImportError:
    log.error("instagrapi not installed")
    add_error("instagrapi not installed")
    sys.exit(1)

try:
    import psutil
except ImportError:
    log.warning("psutil not installed - load monitoring disabled")
    psutil = None

_ollama_started_by_us = False
_ollama_process = None

# =============================================================================
# OLLAMA LIFECYCLE
# =============================================================================

def is_ollama_running():
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return resp.status_code == 200
    except requests.exceptions.ConnectionError:
        return False

def start_ollama_if_needed():
    global _ollama_started_by_us, _ollama_process
    if is_ollama_running():
        log.info("Ollama already running - leaving it alone")
        return False
    log.info("Ollama not running - starting temporarily...")
    _ollama_process = subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    _ollama_started_by_us = True
    for i in range(30):
        if is_ollama_running():
            log.info("Ollama started successfully")
            return True
        time.sleep(1)
    log.error("Ollama failed to start within 30 seconds")
    add_error("Ollama failed to start within 30 seconds")
    _ollama_started_by_us = False
    return False

def stop_ollama_if_started():
    global _ollama_started_by_us, _ollama_process
    if not _ollama_started_by_us:
        return
    log.info("Stopping Ollama (we started it)...")
    if _ollama_process:
        _ollama_process.terminate()
        try:
            _ollama_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _ollama_process.kill()
            _ollama_process.wait()
    try:
        import psutil
        if _ollama_process:
            try:
                parent = psutil.Process(_ollama_process.pid)
                for child in parent.children(recursive=True):
                    child.terminate()
                gone, alive = psutil.wait_procs(parent.children(recursive=True), timeout=5)
                for p in alive:
                    p.kill()
            except (psutil.NoSuchProcess, Exception):
                pass
    except ImportError:
        pass
    _ollama_started_by_us = False
    _ollama_process = None
    log.info("Ollama stopped - GPU/CPU resources released")

atexit.register(stop_ollama_if_started)
signal.signal(signal.SIGTERM, lambda s, f: (stop_ollama_if_started(), sys.exit(1)))
signal.signal(signal.SIGINT, lambda s, f: (stop_ollama_if_started(), sys.exit(1)))

# =============================================================================
# SYSTEM LOAD CHECKING
# =============================================================================

def get_system_uptime_seconds():
    try:
        with open("/proc/uptime") as f:
            return float(f.read().split()[0])
    except Exception:
        return 0

def is_gpu_busy(threshold_percent=60):
    gpu_paths = glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")
    for path in gpu_paths:
        try:
            with open(path) as f:
                gpu_load = int(f.read().strip())
                if gpu_load >= threshold_percent:
                    log.info(f"GPU busy ({gpu_load}% on {path}), deferring")
                    return True
        except Exception:
            continue
    return False

def is_cpu_busy(threshold_percent=80):
    if not psutil:
        return False
    try:
        cpu_usage = psutil.cpu_percent(interval=1)
        if cpu_usage >= threshold_percent:
            log.info(f"CPU busy ({cpu_usage}%), deferring")
            return True
        return False
    except Exception:
        return False

def wait_if_busy(max_wait_minutes=30):
    waited = 0
    while waited < max_wait_minutes * 60:
        if not is_gpu_busy() and not is_cpu_busy():
            return True
        log.info("System busy, waiting 30s...")
        time.sleep(30)
        waited += 30
    log.warning("Timeout waiting for system to become idle")
    return False

# =============================================================================
# VIDEO SCANNING
# =============================================================================

def get_video_creation_date(video_path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format_tags=creation_time", "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, timeout=10
        )
        ct = result.stdout.strip()
        if ct:
            return ct
    except Exception:
        pass
    return datetime.fromtimestamp(video_path.stat().st_mtime).isoformat()

def get_oldest_video(folder_path):
    if not folder_path.exists():
        log.error(f"Video folder not found: {folder_path}")
        add_error(f"Video folder not found: {folder_path}")
        return None
    all_videos = [p for p in folder_path.iterdir()
              if p.is_file() and p.suffix.lower() in VIDEO_EXTS]
    if not all_videos:
        log.info("No videos found in videos_to_upload/")
        return None

    if DRY_RUN:
        log.info("DRY RUN: bypassing duplicate detection")
        new_videos = all_videos.copy()
        duplicates = []
    else:
        # Filter out already-posted videos
        new_videos = [v for v in all_videos if not is_video_already_posted(v)]
        duplicates = [v for v in all_videos if is_video_already_posted(v)]

    for dup in duplicates:
        log.warning(f"Duplicate detected: {dup.name} — moving to video_duplicates/")
        move_to_duplicates(dup)

    if not new_videos:
        if duplicates:
            log.info(f"All {len(duplicates)} video(s) were duplicates — moved to video_duplicates/")
        else:
            log.info("No videos found in videos_to_upload/")
        return None

    on_hold = get_on_hold_videos()
    new_videos = [v for v in new_videos if str(v) not in on_hold or get_approval_for_video(v)]
    if not new_videos:
        log.info("All videos filtered out (on_hold or duplicates). Waiting for new videos.")
        return None
    sort_order = os.getenv("SORT_ORDER", "oldest")
    if sort_order == "name_asc":
        new_videos.sort(key=lambda p: p.name.lower())
        selected = new_videos[0]
        sel_info = "sorted A-Z"
    elif sort_order == "name_desc":
        new_videos.sort(key=lambda p: p.name.lower(), reverse=True)
        selected = new_videos[0]
        sel_info = "sorted Z-A"
    elif sort_order == "newest":
        videos_with_dates = [(get_video_creation_date(v), v) for v in new_videos]
        videos_with_dates.sort(key=lambda x: x[0], reverse=True)
        selected = videos_with_dates[0][1]
        sel_info = f"created {videos_with_dates[0][0]}"
    else:  # oldest (default)
        videos_with_dates = [(get_video_creation_date(v), v) for v in new_videos]
        videos_with_dates.sort(key=lambda x: x[0])
        selected = videos_with_dates[0][1]
        sel_info = f"created {videos_with_dates[0][0]}"
    log.info(f"Found {len(new_videos)} new video(s) ({len(duplicates)} duplicate(s) removed). "
             f"Selected: {selected.name} ({sel_info})")
    return selected

def get_video_duration(video_path):
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "format=duration", "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except Exception as e:
        log.error(f"Failed to get duration for {video_path.name}: {e}")
        add_error(f"Failed to get duration for {video_path.name}: {e}")
        return 0.0

def is_video_vertical(video_path):
    """Check if video is already vertical (portrait). Returns True if height >= width."""
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
             "-show_entries", "stream=width,height", "-of", "csv=p=0", str(video_path)],
            capture_output=True, text=True, timeout=10
        )
        dims = result.stdout.strip().split(",")
        if len(dims) >= 2:
            w, h = int(dims[0]), int(dims[1])
            return h >= w
    except Exception:
        pass
    # Fallback: try getting dimensions from the file path
    try:
        result = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries",
             "stream=width,height", "-of", "json", str(video_path)],
            capture_output=True, text=True, timeout=10
        )
        import json as _json
        info = _json.loads(result.stdout)
        streams = info.get("streams", [])
        if streams:
            w = int(streams[0].get("width", 0))
            h = int(streams[0].get("height", 0))
            if w > 0 and h > 0:
                return h >= w
    except Exception:
        pass
    log.warning(f"Could not determine orientation for {video_path.name} — treating as horizontal")
    return False

# =============================================================================
# FRAME EXTRACTION & ANALYSIS
# =============================================================================

def extract_frames(video_path, max_frames=24):
    duration = get_video_duration(video_path)
    if duration <= 0:
        return []
    interval = 2 if duration <= 15 else (3 if duration <= 30 else 3)
    num_frames = min(int(duration / interval), max_frames)
    if num_frames < 2:
        num_frames = min(2, int(duration))
    if num_frames < 1:
        return []
    log.info(f"Extracting {num_frames} frames from {video_path.name} ({duration:.1f}s)")
    frames = []
    temp_dir = Path(tempfile.mkdtemp(prefix="reels_frames_"))
    for i in range(num_frames):
        timestamp = (i * duration) / num_frames
        frame_path = temp_dir / f"frame_{i:03d}.jpg"
        try:
            subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{timestamp}", "-i", str(video_path),
                 "-frames:v", "1", "-vf", "scale=1280:-2", "-q:v", "2", str(frame_path)],
                capture_output=True, timeout=30
            )
            if frame_path.exists():
                frames.append(frame_path)
        except Exception:
            continue
    log.info(f"  Extracted {len(frames)} frames to {temp_dir.name}/")
    return frames

def analyze_frame_with_vision(frame_path):
    with open(frame_path, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")
    payload = {
        "model": VISION_MODEL,
        "prompt": VIDEO_FRAME_PROMPT,
        "images": [image_b64],
        "stream": False
    }
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()

def analyze_video_frames(video_path):
    frames = extract_frames(video_path)
    if not frames:
        log.error("No frames extracted")
        add_error("No frames extracted")
        return ""
    log.info(f"Analyzing {len(frames)} frames through LLaVA...")
    descriptions = []
    temp_dir = frames[0].parent
    duration = get_video_duration(video_path)
    try:
        for i, frame in enumerate(frames):
            ts = (i * duration) / len(frames)
            log.info(f"  Frame {i+1}/{len(frames)} (t={ts:.0f}s)...")
            try:
                desc = analyze_frame_with_vision(frame)
                if desc:
                    descriptions.append(f"[t={ts:.0f}s]: {desc}")
            except Exception as e:
                log.warning(f"  Failed to analyze frame {i+1}: {e}")
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
    if not descriptions:
        return ""
    combined = "\n\n".join(descriptions)
    log.info(f"Combined {len(descriptions)} frame descriptions ({len(combined)} chars)")
    log.info(f"FRAME ANALYSIS OUTPUT:\n{combined[:1000]}")
    return combined

# =============================================================================
# AUDIO EXTRACTION & TRANSCRIPTION
# =============================================================================

def extract_audio(video_path):
    audio_path = Path(tempfile.mktemp(suffix=".wav", prefix="reels_audio_"))
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-vn", "-ac", "1",
             "-ar", "16000", "-f", "wav", str(audio_path)],
            capture_output=True, timeout=60
        )
        if result.returncode != 0 or not audio_path.exists():
            log.info("  No audio track found in video")
            return None
        log.info(f"  Audio extracted to {audio_path.name}")
        return audio_path
    except Exception as e:
        log.warning(f"  Audio extraction failed: {e}")
        if audio_path.exists():
            audio_path.unlink()
        return None

def transcribe_audio(audio_path):
    try:
        result = subprocess.run(
            [PYTHON312, TRANSCRIBE_HELPER, str(audio_path)],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0:
            log.warning(f"  Transcription failed: {result.stderr.strip()}")
            return "", []
        raw = result.stdout.strip()
        if not raw:
            log.info("  No speech detected in audio")
            return "", []
        try:
            data = json.loads(raw)
            transcript = data.get("text", "")
            words = data.get("words", [])
        except json.JSONDecodeError:
            transcript = raw
            words = []
        if transcript:
            log.info(f"  Transcript ({len(transcript)} chars): {transcript[:100]}...")
        else:
            log.info("  No speech detected in audio")
        return transcript, words
    except Exception as e:
        log.warning(f"  Transcription error: {e}")
        return "", []



def analyze_video_audio(video_path):
    audio_path = extract_audio(video_path)
    if audio_path is None:
        return "", []
    try:
        return transcribe_audio(audio_path)
    finally:
        if audio_path and audio_path.exists():
            audio_path.unlink()

# =============================================================================

# =============================================================================
# AUDIO BLEEP
# =============================================================================

def bleep_audio(video_path, word_times):
    """Mute audio at timestamps where bleep words appear. Returns path to bleeped video, or original if no bleeps needed."""
    if not word_times or not BLEEP_WORDS or not BLEEP_ENABLED:
        return str(video_path)

    # Find timestamps for bleep words
    mute_ranges = []
    for w in word_times:
        word_lower = w["word"].lower().strip(".,!?;:\"'")
        if word_lower in BLEEP_WORDS:
            # Add small padding (0.1s before, 0.1s after) for natural cutoff
            start = max(0, w["start"] - 0.1)
            end = w["end"] + 0.1
            mute_ranges.append((start, end))
            log.info(f"  Bleeping '{w["word"]}' at {w["start"]:.1f}s-{w["end"]:.1f}s")

    if not mute_ranges:
        return str(video_path)

    # Build ffmpeg audio filter for muting
    enable_parts = "+".join([f"between(t\,{s:.2f}\,{e:.2f})" for s, e in mute_ranges])
    output_path = str(video_path).replace(video_path.suffix, f"_bleeped{video_path.suffix}")

    cmd = [
        "ffmpeg", "-y", "-i", str(video_path),
        "-af", f"volume=0:enable={enable_parts}",
        "-c:v", "copy", "-c:a", "aac",
        "-movflags", "+faststart",
        output_path
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
    if result.returncode != 0:
        log.warning(f"  Bleep failed: {result.stderr[-200:]}")
        return str(video_path)

    log.info(f"  Audio bleeped ({len(mute_ranges)} word(s) muted)")
    return output_path


# EXPLICIT CONTENT HANDLING
# =============================================================================

def generate_thumbnail(video_path, output_dir=None):
    if output_dir:
        thumb_dir = Path(output_dir)
    else:
        thumb_dir = EXPLICIT_VIDEOS_DIR / "thumbnails"
    thumb_dir.mkdir(parents=True, exist_ok=True)
    thumb_path = thumb_dir / f"{video_path.stem}_thumb.jpg"
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-frames:v", "1",
             "-vf", "scale=640:-2", "-q:v", "2", str(thumb_path)],
            capture_output=True, timeout=30
        )
        if thumb_path.exists():
            return str(thumb_path)
    except Exception:
        pass
    return ""

def handle_explicit_content(video_path, transcript, segment_context="", flagged_segments={}):
    is_exp, matched_word, category, timestamp_hint = check_explicit(transcript)
    if not is_exp:
        return False
    log.warning(f"EXPLICIT CONTENT DETECTED: '{matched_word}' ({category}) at {timestamp_hint}")
    log.warning(f"Moving {video_path.name} to explicit_videos/ for review")
    EXPLICIT_VIDEOS_DIR.mkdir(parents=True, exist_ok=True)
    dest = EXPLICIT_VIDEOS_DIR / video_path.name
    counter = 1
    while dest.exists():
        stem = video_path.stem
        suffix = video_path.suffix
        dest = EXPLICIT_VIDEOS_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    try:
        shutil.move(str(video_path), str(dest))
    except Exception as e:
        log.error(f"Failed to move explicit video: {e}")
        add_error(f"Failed to move explicit video: {e}")
        dest = video_path
    thumb_path = generate_thumbnail(dest)
    data = get_reels_log()
    data.setdefault("explicit_videos", []).append({
        "original_name": video_path.name,
        "moved_to": str(dest),
        "thumbnail": thumb_path,
        "matched_word": matched_word,
        "category": category,
        "timestamp_hint": timestamp_hint,
        "transcript": transcript[:500],
"segment_context": segment_context,
            "flagged_segments": flagged_segments,
        "detected_at": datetime.now().isoformat(),
        "status": "pending_review"
    })
    data["last_post_time"] = datetime.now().isoformat()
    save_reels_log(data)
    log.info(f"Logged for review in Explicit tab. Video moved to: {dest}")
    return True

# =============================================================================
# DUPLICATE DETECTION
# =============================================================================

def is_video_already_posted(video_path):
    """Check if a video has already been posted by name or path.
    Returns True if duplicate detected.
    """
    data = get_reels_log()
    video_name = video_path.name
    video_resolved = str(video_path.resolve())

    for vkey, vdata in data.get("videos", {}).items():
        # Match by resolved path
        if vkey == video_resolved:
            return True
        # Match by filename
        if vdata.get("video_name") == video_name:
            return True
        # Check archived path
        if vdata.get("archived_to") and video_name in vdata["archived_to"]:
            return True

    # Also check the txt log (catches anything that might have been manually logged)
    if POSTED_VIDEOS_TXT.exists():
        try:
            posted_names = POSTED_VIDEOS_TXT.read_text().splitlines()
            if video_name in posted_names:
                return True
        except Exception:
            pass

    return False


def move_to_duplicates(video_path):
    """Move a duplicate video to video_duplicates/ folder."""
    VIDEO_DUPLICATES_DIR.mkdir(parents=True, exist_ok=True)
    dest = VIDEO_DUPLICATES_DIR / video_path.name

    counter = 1
    while dest.exists():
        stem = video_path.stem
        suffix = video_path.suffix
        dest = VIDEO_DUPLICATES_DIR / f"{stem}_{counter}{suffix}"
        counter += 1

    try:
        shutil.move(str(video_path), str(dest))
        log.info(f"Moved duplicate video to: {dest}")
    except Exception as e:
        log.error(f"Failed to move duplicate: {e}")
        add_error(f"Failed to move duplicate: {e}")


def log_to_posted_txt(video_name, details=""):
    """Append video name to posted_videos.txt for human-readable tracking."""
    from datetime import datetime
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"{timestamp} | {video_name}"
    if details:
        line += f" | {details}"
    try:
        with open(POSTED_VIDEOS_TXT, "a") as f:
            f.write(line + "\n")
    except Exception as e:
        log.warning(f"Could not write to posted_videos.txt: {e}")


# =============================================================================
# CAPTION GENERATION
# =============================================================================

def get_segment_info(segment_path):
    name = segment_path.stem
    if "_part" not in name:
        return None, None
    try:
        part_section = name.split("_part")[1]
        part_num = int(part_section.split("of")[0])
        total_parts = int(part_section.split("of")[1])
        return part_num, total_parts
    except (IndexError, ValueError):
        return None, None

def generate_reel_caption(description, segment_path, transcript_text=""):
    part_num, total_parts = get_segment_info(segment_path)
    part_suffix = ""
    teaser = ""
    if part_num and total_parts and total_parts > 1:
        part_suffix = f"\n\nPart {part_num} of {total_parts}"
        if part_num < total_parts:
            teaser = f"\n- This is Part {part_num} of {total_parts}. End with a tease for the next part like \"Stay tuned for Part {part_num + 1}!\" or \"More coming in Part {part_num + 1}...\""
        else:
            teaser = f"\n- This is the final part (Part {part_num} of {total_parts}). Briefly mention this concludes the series."

    prompt = f"""Write a short Instagram Reel caption in a casual, outdoorsy voice — like texting a friend about what you just did.

First, read this analysis of the video and UNDERSTAND what is happening:
"VISUAL ANALYSIS:
{description}

AUDIO TRANSCRIPT:
{transcript_text if transcript_text else "(no clear audio)"}"

Based on what is happening above, write a caption. Rules:
- PRIORITY: Read the VISUAL ANALYSIS first. This shows what people are DOING. SUMMARIZE what you SEE in your own words. Do NOT quote the dialogue.
- Describe the ACTION plainly — what are people physically doing in the video? Use simple verbs.
- You may add ONE descriptive detail about the setting (forest, trail, etc).
- Do NOT invent emotions, physical sensations, or backstory beyond what the analysis shows.
- Only mention activities EXPLICITLY named in the VISUAL ANALYSIS. If multiple activities are mentioned, pick the most frequent one. Do NOT add activities you merely infer.
- Do NOT mention cameras, GoPros, or filming equipment.
- 2-3 sentences MAX. Short and casual.
- End with one quick question about the activity.
- You MUST include exactly 3 hashtags at the end, formatted as #word1 #word2 #word3. Two is not acceptable. Four is not acceptable. Three only.
- No profanity. No quotation marks.
{teaser}

Write the caption now:"""

    payload = {
        "model": CAPTION_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.6}
    }
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=600)
    resp.raise_for_status()
    caption = resp.json().get("response", "").strip()
    if part_suffix and part_suffix not in caption:
        caption = caption + part_suffix
    return caption

# =============================================================================
# SEGMENT CALCULATION & SPLITTING
# =============================================================================

def calculate_segments(duration):
    if duration <= MAX_REEL_DURATION:
        return 1, duration
    num_segments = math.ceil(duration / MAX_REEL_DURATION)
    segment_length = duration / num_segments
    log.info(f"Splitting {duration:.1f}s into {num_segments} segments of {segment_length:.1f}s each")
    return num_segments, segment_length


def identify_flagged_segments(word_times, num_segments, segment_length):
    """Map banned word timestamps to segment numbers. Returns dict {seg_num: [words]}."""
    flagged = {}
    for w in word_times:
        is_exp, matched, cat, hint = check_explicit(w["word"])
        if is_exp:
            seg_num = int(w["start"] // segment_length) + 1
            if seg_num > num_segments:
                seg_num = num_segments
            flagged.setdefault(seg_num, []).append({"word": w["word"], "start": w["start"], "end": w["end"]})
    return flagged
def split_video(video_path, num_segments, segment_length):
    TEMP_SEGMENTS_DIR.mkdir(parents=True, exist_ok=True)
    stem = video_path.stem
    suffix = video_path.suffix
    segments = []
    for i in range(num_segments):
        start_time = i * segment_length
        part_num = i + 1
        seg_name = f"{stem}_part{part_num}of{num_segments}{suffix}"
        seg_path = TEMP_SEGMENTS_DIR / seg_name
        log.info(f"  Creating segment {part_num}/{num_segments}: {seg_name} (start={start_time:.1f}s)")
        try:
            result = subprocess.run(
                ["ffmpeg", "-y", "-ss", f"{start_time}", "-i", str(video_path),
                 "-t", f"{segment_length}", "-c", "copy", "-avoid_negative_ts", "make_zero",
                 str(seg_path)],
                capture_output=True, text=True, timeout=60
            )
            if result.returncode != 0:
                log.error(f"  ffmpeg failed for segment {part_num}")
                add_error(f"  ffmpeg failed for segment {part_num}")
                return None
            if not seg_path.exists() or seg_path.stat().st_size < 1000:
                log.error(f"  Segment {part_num} too small or missing")
                add_error(f"  Segment {part_num} too small or missing")
                return None
            segments.append(seg_path)
        except Exception as e:
            log.error(f"  Error creating segment {part_num}: {e}")
            add_error(f"  Error creating segment {part_num}: {e}")
            return None
    log.info(f"  Successfully created {len(segments)} segments")
    return segments

def register_segments_in_log(video_path, segments, duration):
    data = get_reels_log()
    key = str(video_path.resolve())
    data["videos"][key] = {
        "video_name": video_path.name,
        "status": "posting",
        "segments_total": len(segments),
        "segments_posted": 0,
        "segments": [
            {"name": seg.name, "path": str(seg.resolve()), "status": "pending"}
            for seg in segments
        ],
        "duration": round(duration, 1),
        "date_created": get_video_creation_date(video_path),
        "first_posted_at": None,
        "completed_at": None
    }
    save_reels_log(data)
    log.info(f"  Registered {len(segments)} segments in posted_reels.json")

# =============================================================================
# VIDEO PREPARATION (VERTICAL PADDING)
# =============================================================================

def prepare_vertical_video(video_path):
    video_path = Path(video_path)
    """Convert horizontal video to 9:16 vertical with blurred background.
    Original file is NEVER modified. Creates a temp padded copy.
    Returns path to padded video (or original if already vertical).
    """
    if is_video_vertical(video_path):
        log.info(f"  Video is already vertical — no padding needed")
        return video_path

    log.info(f"  Converting to vertical (blurred background padding)")
    padded_path = Path(str(video_path).replace(video_path.suffix, "_padded.mp4"))

    vf = (
        "[0:v]split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        "crop=1080:1920,gblur=sigma=20[bg];"
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fg];"
        "[bg][fg]overlay=(W-w)/2:(H-h)/2"
    )

    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path),
             "-vf", vf,
             "-c:a", "copy",
             "-c:v", "libx264", "-preset", "slow", "-crf", "18",
             "-movflags", "+faststart",
             str(padded_path)],
            capture_output=True, text=True, timeout=600
        )
        if result.returncode != 0 or not padded_path.exists():
            log.warning(f"  Padding failed, using original: {result.stderr[-200:]}")
            if padded_path.exists():
                padded_path.unlink()
            return video_path
        size_mb = padded_path.stat().st_size / (1024 * 1024)
        log.info(f"  Padded video created ({size_mb:.1f}MB): {padded_path.name}")
        return padded_path
    except subprocess.TimeoutExpired:
        log.warning("  Padding timed out, using original")
        if padded_path.exists():
            padded_path.unlink()
        return video_path
    except Exception as e:
        log.warning(f"  Padding error: {e}")
        if padded_path.exists():
            padded_path.unlink()
        return video_path

# =============================================================================
# REEL UPLOAD & SEGMENT LIFECYCLE (skipped in DRY RUN)
# =============================================================================

def upload_reel_to_instagram(video_path, caption):
    log.info(f"Uploading Reel: {Path(video_path).name}")
    client = Client()
    session_file = Path("ig_session.json")
    if session_file.exists():
        try:
            client.load_settings(session_file)
        except Exception:
            pass
    if not IG_USERNAME or not IG_PASSWORD:
        log.error("Instagram credentials missing")
        add_error("Instagram credentials missing")
        return False
    try:
        client.login(IG_USERNAME, IG_PASSWORD)
        client.dump_settings(session_file)
    except Exception as e:
        log.error(f"Login failed: {e}")
        add_error(f"Login failed: {e}")
        return False

    # Generate thumbnail with ffmpeg
    thumb_path = Path(tempfile.mktemp(suffix=".jpg", prefix="reel_thumb_"))
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-i", str(video_path), "-frames:v", "1",
             "-vf", "scale=1080:1920:force_original_aspect_ratio=increase",
             "-crop", "1080:1920", "-q:v", "2", str(thumb_path)],
            capture_output=True, timeout=30
        )
        if not thumb_path.exists():
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(video_path), "-frames:v", "1",
                 "-q:v", "2", str(thumb_path)],
                capture_output=True, timeout=30
            )
        if thumb_path.exists():
            log.info(f"Thumbnail generated: {thumb_path.name}")
    except Exception as e:
        log.warning(f"Thumbnail error: {e}")

    # Prepare vertical version (padded copy, original untouched)
    upload_video = prepare_vertical_video(video_path)
    is_padded = str(upload_video) != str(video_path)

    try:
        if hasattr(client, "clip_upload"):
            client.clip_upload(str(upload_video), caption, thumbnail=str(thumb_path) if thumb_path.exists() else None)
        elif hasattr(client, "reel_upload"):
            client.reel_upload(str(upload_video), caption, thumbnail=str(thumb_path) if thumb_path.exists() else None)
        else:
            client.video_upload(str(upload_video), caption, thumbnail=str(thumb_path) if thumb_path.exists() else None)
        log.info("Successfully uploaded Reel to Instagram!")
        return True
    except Exception as e:
        log.error(f"Reel upload failed: {e}")
        add_error(f"Reel upload failed: {e}")
        return False
    finally:
        if thumb_path.exists():
            thumb_path.unlink()
        if is_padded and upload_video.exists():
            upload_video.unlink()
            log.info(f"Cleaned up padded temp: {upload_video.name}")

def update_segment_status(segment_path, status="posted"):
    data = get_reels_log()
    seg_name = segment_path.name
    video_key = None
    for vkey, vdata in data.get("videos", {}).items():
        for seg in vdata.get("segments", []):
            if seg.get("name") == seg_name or seg.get("path") == str(segment_path.resolve()):
                seg["status"] = status
                if status == "posted":
                    seg["posted_at"] = datetime.now().isoformat()
                video_key = vkey
                vdata["segments_posted"] = sum(
                    1 for s in vdata.get("segments", []) if s.get("status") == "posted"
                )
                if not vdata.get("first_posted_at") and status == "posted":
                    vdata["first_posted_at"] = datetime.now().isoformat()
                break
        if video_key:
            break
    if video_key:
        vdata = data["videos"][video_key]
        if vdata["segments_posted"] >= vdata["segments_total"]:
            vdata["status"] = "complete"
            vdata["completed_at"] = datetime.now().isoformat()
    data["last_post_time"] = datetime.now().isoformat()
    save_reels_log(data)
    return video_key, data

def archive_original_video(video_key):
    if not video_key:
        return
    src = Path(video_key)
    if not src.exists():
        log.warning(f"Original video not found: {src}")
        return
    POSTED_REELS_DIR.mkdir(parents=True, exist_ok=True)
    dest = POSTED_REELS_DIR / src.name
    counter = 1
    while dest.exists():
        stem = src.stem
        suffix = src.suffix
        dest = POSTED_REELS_DIR / f"{stem}_{counter}{suffix}"
        counter += 1
    try:
        shutil.move(str(src), str(dest))
        log.info(f"Original video archived to: {dest}")
        data = get_reels_log()
        if video_key in data.get("videos", {}):
            vdata = data["videos"][video_key]
            vdata["archived_to"] = str(dest)
            save_reels_log(data)
            # Log to human-readable txt file
            details = f"{vdata.get('duration', 0)}s, {vdata.get('segments_total', 1)} segment(s)"
            log_to_posted_txt(vdata.get("video_name", dest.name), details)
    except Exception as e:
        log.error(f"Failed to archive original video: {e}")
        add_error(f"Failed to archive original video: {e}")

def handle_completed_segments(video_key, data):
    if not video_key:
        return
    vdata = data.get("videos", {}).get(video_key)
    if not vdata:
        return
    if vdata.get("status") == "complete":
        log.info(f"All {vdata['segments_total']} segments posted! Archiving original...")
        archive_original_video(video_key)

def delete_segment_file(segment_path):
    try:
        if segment_path.exists():
            segment_path.unlink()
            log.info(f"Deleted segment: {segment_path.name}")
    except Exception as e:
        log.warning(f"Could not delete segment file: {e}")

# =============================================================================
# REELS LOG
# =============================================================================

def get_reels_log():
    if REELS_LOG_PATH.exists():
        try:
            return json.loads(REELS_LOG_PATH.read_text())
        except json.JSONDecodeError:
            log.warning("Corrupt reels log; starting fresh")
    return {"videos": {}, "last_post_time": None}

def save_reels_log(data):
    REELS_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    REELS_LOG_PATH.write_text(json.dumps(data, indent=2))

# =============================================================================
# MAIN
# =============================================================================

def run_once():
    log.info("=" * 60)
    log.info("Starting Reels auto-poster cycle")
    log.info("=" * 60)

    if not wait_if_busy(max_wait_minutes=30):
        log.warning("Aborting - system remained too busy")
        return False

    skip_ban_check = False
    clear_progress()
    clear_error()

    # Check for pending segments first (priority)
    current_segment = None
    if TEMP_SEGMENTS_DIR.exists():
        pending_segments = sorted([p for p in TEMP_SEGMENTS_DIR.iterdir()
                                   if p.is_file() and p.suffix.lower() in VIDEO_EXTS])
        if pending_segments:
            current_segment = pending_segments[0]
            parent_name_tmp = current_segment.name.rsplit("_part", 1)[0] if "_part" in current_segment.name else current_segment.name
            skip_ban_check = bool(get_skip_segments(parent_name_tmp))
            log.info(f"Found {len(pending_segments)} pending segment(s). Processing: {current_segment.name}")
            parent_name = current_segment.name.rsplit("_part", 1)[0] if "_part" in current_segment.name else current_segment.name
            seg_num = ""
            if "_part" in current_segment.name:
                seg_num = current_segment.name.split("_part")[1].split("of")[0].strip()
            skip_list = get_skip_segments(parent_name)
            if skip_list and seg_num in [str(s) for s in skip_list]:
                log.info(f"Skipping flagged segment {seg_num} of {parent_name}")
                current_segment.unlink()
                return True

    if current_segment is None:
        video_path = get_oldest_video(VIDEO_FOLDER_PATH)
        if not video_path:
            log.info("No videos to post")
            return None
        duration = get_video_duration(video_path)
        needs_split = duration > MAX_REEL_DURATION
        log.info(f"Video: {video_path.name}")
        update_progress("analyzing", "Pre-screening audio")
        log.info(f"  Duration: {duration:.1f}s")
        log.info(f"  Orientation: {'vertical' if is_video_vertical(video_path) else 'horizontal'}")
        log.info(f"  Needs splitting: {'YES' if needs_split else 'NO'}")

        # Check if video was approved via GUI
        approval = get_approval_for_video(video_path)
        if approval:
            action = approval.get("action", "")
            log.info(f"Approved via review panel: {action}")
            remove_approval_for_video(video_path)
            remove_on_hold_video(video_path)
            if action == "discard":
                if video_path.exists(): video_path.unlink()
                return False
            skip_ban_check = True
            if action == "bleep":
                try:
                    ban_data = json.loads(Path("ban_words.json").read_text())
                    global BLEEP_WORDS
                    BLEEP_WORDS = list(set(BLEEP_WORDS + ban_data.get("words", [])))
                except Exception: pass
                if action == "skip_flagged":
                    segs = approval.get("segments_to_skip", [])
                    if segs:
                        save_skip_segments(video_path.name, segs)

        # Pre-screen: transcribe whole video and check for banned words before splitting
        log.info("Pre-screening whole video audio for banned content...")
        full_transcript, full_word_times = analyze_video_audio(video_path)
        if full_transcript and not skip_ban_check:
            is_exp, matched_word, category, timestamp_hint = check_explicit(full_transcript)
            if is_exp:
                log.warning(f"BANNED WORD detected in pre-screen: {matched_word!r} ({category}) at {timestamp_hint}")
                update_progress("quarantined", "Banned word detected")
                signal_explicit_detected(video_path, matched_word)
                send_notification("Video Flagged", f"{video_path.name}: {matched_word}", "high")
                save_on_hold_video(video_path, video_path.name)
                flagged_segments = {}
                if needs_split:
                    num_segs, seg_len = calculate_segments(duration)
                    flagged_segments = identify_flagged_segments(full_word_times, num_segs, seg_len)
                    log.warning(f"Flagged segments: {flagged_segments}")
                if handle_explicit_content(video_path, full_transcript, flagged_segments=flagged_segments):
                    log.warning("Video moved for review. Skipping to next video.")
                    return False
        log.info("Pre-screen complete - no banned content found")

        if needs_split:
            num_segments, segment_length = calculate_segments(duration)
            segments = split_video(video_path, num_segments, segment_length)
            if segments is None:
                log.error("Failed to split video")
                add_error("Failed to split video")
                return False
            if DRY_RUN:
                skip_list = get_skip_segments(video_path.name)
                current_segment = None
                for seg in segments:
                    seg_num = seg.name.split("_part")[1].split("of")[0].strip() if "_part" in seg.name else ""
                    if skip_list and seg_num in [str(s) for s in skip_list]:
                        log.info(f"Skipping flagged segment {seg_num}")
                        seg.unlink()
                        continue
                    current_segment = seg
                    break
                if current_segment is None:
                    log.info("All segments were flagged for skipping")
                    clear_skip_segments(video_path.name)
                    return True
            else:
                register_segments_in_log(video_path, segments, duration)
                log.info("Video split into segments. Next cycle will post Part 1.")
                return True
        else:
            current_segment = video_path
            log.info(f"Processing {video_path.name} as single Reel")

    # Start Ollama for AI work
    we_started_ollama = start_ollama_if_needed()

    try:
        # Frame extraction + LLaVA analysis
        visual_description = analyze_video_frames(current_segment)
        update_progress("frames", "Extracting frames")
        if not visual_description:
            log.error("Failed to analyze video frames")
            add_error("Failed to analyze video frames")
            return False
        log.info(f"Visual analysis complete ({len(visual_description)} chars)")

        # Audio transcription
        transcript, word_times = analyze_video_audio(current_segment)
        update_progress("transcribing", "Whisper transcription")

        if transcript:
            combined_description = f"VISUAL ANALYSIS:\n{visual_description}\n\nAUDIO TRANSCRIPT:\n{transcript}"
        else:
            combined_description = visual_description

        log.info(f"Combined analysis ({len(combined_description)} chars)")
        log.info(f"Preview: {combined_description[:200]}...")

        # Explicit content check
        if not skip_ban_check and handle_explicit_content(current_segment, transcript):
            log.warning("Posting aborted due to explicit content. Video moved for review.")
            signal_explicit_detected(current_segment, "explicit detected")
            send_notification("Segment Flagged", f"{current_segment.name}: explicit detected", "high")
            save_on_hold_video(current_segment, current_segment.name)


            return False

        # Apply audio bleeping if needed
        bleeped_video_path = bleep_audio(current_segment, word_times)
        update_progress("bleeping", "Muting words")
        video_to_use = Path(bleeped_video_path)

        # Generate caption
        caption = generate_reel_caption(combined_description, current_segment, transcript or "")
        update_progress("captioning", "Generating caption")
        if not caption:
            log.error("Failed to generate caption")
            add_error("Failed to generate caption")
            return False
        log.info(f"Generated caption ({len(caption)} chars):")
        log.info(caption)

        orig_name = video_to_use.name
        # Music overlay (safe-wrapped)
        try:
            music_video, song_name = add_music_to_video(str(video_to_use), combined_description, transcript or chr(0))
            if music_video != str(video_to_use):
                if video_to_use != current_segment and video_to_use.exists():
                    video_to_use.unlink()
                video_to_use = Path(music_video)
                log.info(f"Using music-enhanced video: {video_to_use.name}")
        except Exception as e:
            log.warning(f"Music overlay failed: {e}")
        # Upload Reel
        if DRY_RUN:
            DRY_RUN_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(video_to_use), str(DRY_RUN_DIR / orig_name))
            (DRY_RUN_DIR / f"{Path(orig_name).stem}_caption.txt").write_text(caption)
            (DRY_RUN_DIR / f"{Path(orig_name).stem}_transcript.txt").write_text(transcript or "(no audio)")
            (DRY_RUN_DIR / f"{Path(orig_name).stem}_debug.txt").write_text(
                f"=== FRAME ANALYSIS ===\n{combined_description}\n\n=== TRANSCRIPT ===\n{transcript or '(no audio)'}\n\n=== CAPTION ===\n{caption}"
            )
            log.info(f"DRY RUN: saved {orig_name} + caption + transcript to {DRY_RUN_DIR}")
            send_notification("Reel Posted (DRY)", caption[:80])
        # Clean up segment in dry run so next cycle picks up next part
        is_segment = "_part" in current_segment.name
        if is_segment:
            current_segment.unlink()
            log.info(f"DRY RUN: deleted segment {current_segment.name} from temp")
            remaining = [p for p in TEMP_SEGMENTS_DIR.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS] if TEMP_SEGMENTS_DIR.exists() else []
            if not remaining:
                parent = current_segment.name.rsplit("_part", 1)[0] if "_part" in current_segment.name else current_segment.name
                clear_skip_segments(parent)

        return True
        try:
            success = upload_reel_to_instagram(str(video_to_use), caption)
        except Exception as e:
            log.error(f"Unexpected upload error: {e}")
            add_error(f"Unexpected upload error: {e}")
            success = False

        # Clean up bleeped temp file if one was created
        if video_to_use != current_segment and video_to_use.exists():
            video_to_use.unlink()
            log.info(f"  Cleaned up bleeped temp: {video_to_use.name}")

        if success:
            is_segment = "_part" in current_segment.name
            if is_segment:
                # This is a split segment in temp_segments/ — delete after posting
                video_key, data = update_segment_status(current_segment, "posted")
                delete_segment_file(current_segment)
                handle_completed_segments(video_key, data)
            remaining = [p for p in TEMP_SEGMENTS_DIR.iterdir() if p.is_file() and p.suffix.lower() in VIDEO_EXTS] if TEMP_SEGMENTS_DIR.exists() else []
            if not remaining:
                parent = current_segment.name.rsplit("_part", 1)[0] if "_part" in current_segment.name else current_segment.name
                clear_skip_segments(parent)
            else:
                # Single video in videos_to_upload/ — archive to YouTube-ready folder
                seg_duration = get_video_duration(current_segment)
                archive_original_video(str(current_segment))
                log_to_posted_txt(current_segment.name,
                                  f"{seg_duration:.1f}s, single Reel")
                log.info(f"Single video archived to {POSTED_REELS_DIR}")
            log.info("Reel cycle complete!")
            clear_failed_upload(current_segment.name)
            send_notification("Reel Posted", caption[:80])
        else:
            log.error("Upload failed - tracking retry")
            add_error("Upload failed - tracking retry")
            retry_count = increment_retry(current_segment.name)
            if retry_count >= 3:
                log.error(f"Max retries ({retry_count}) reached for {current_segment.name} - moving to failed_uploads/")
                add_error(f"Max retries reached for {current_segment.name}")
                failed_dir = Path("failed_uploads")
                failed_dir.mkdir(exist_ok=True)
                shutil.move(str(current_segment), str(failed_dir / current_segment.name))
                send_notification("Upload Failed", f"{current_segment.name} failed after {retry_count} retries", "high")
                clear_failed_upload(current_segment.name)
                return False
            log.info(f"Retry {retry_count}/3 for {current_segment.name} - will try again next cycle")

        return success
    finally:
        stop_ollama_if_started()

if __name__ == "__main__":
    try:
        result = run_once()
        if result is True:
            sys.exit(0)
        elif result is None:
            sys.exit(2)
        else:
            sys.exit(1)
    except Exception as e:
        log.error(f"Unexpected error: {e}", exc_info=True)
        add_error(f"Unexpected error: {e}")
        stop_ollama_if_started()
        sys.exit(1)
