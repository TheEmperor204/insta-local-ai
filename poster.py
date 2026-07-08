#!/usr/bin/env python3
"""
Instagram Auto-Poster (Local AI Edition)
Fully local image captioning and automated posting with intelligent scheduling.
"""

import os
import sys
import json
import time
import logging
import random
import subprocess
import glob
import shutil
import signal
import atexit
import hashlib
import shutil
from pathlib import Path
from datetime import datetime

from dotenv import load_dotenv

try:
    from caption_persona import PERSONA_PHOTO
except ImportError:
    PERSONA_PHOTO = ""
load_dotenv()

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
log = logging.getLogger("instagram-poster")

# =============================================================================
# CONFIGURATION
# =============================================================================

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
VISION_MODEL = os.getenv("VISION_MODEL", "llava:7b")
CAPTION_MODEL = os.getenv("CAPTION_MODEL", "qwen2.5:7b")
VISION_PROMPT = os.getenv("VISION_PROMPT", "Describe this image in detail. Include: subject, setting, colors, mood, lighting, objects. Be vivid but concise.")
IG_USERNAME = os.getenv("IG_USERNAME", "")
# Try keyring first, fall back to .env
_IG_PASSWORD = ""
if KEYRING_AVAILABLE:
    _kr_pw = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY)
    if _kr_pw:
        _IG_PASSWORD = _kr_pw
if not _IG_PASSWORD:
    _IG_PASSWORD = os.getenv("IG_PASSWORD", "")
IG_PASSWORD = _IG_PASSWORD
POSTED_LOG_PATH = Path(os.getenv("POSTED_LOG", "posted_images.json"))
IMAGE_FOLDER_PATH = Path(os.getenv("IMAGE_FOLDER", "."))
POSTED_IMAGES_DIR = Path(os.getenv("POSTED_IMAGES_DIR", str(Path(os.getenv("IMAGE_FOLDER", ".")) / ".." / "posted_images")))
POSTED_REELS_DIR = Path(os.getenv("POSTED_REELS_DIR", str(Path(os.getenv("IMAGE_FOLDER", ".")) / ".." / "posted_reels")))
DELAY_AFTER_BOOT_MINUTES = int(os.getenv("DELAY_AFTER_BOOT_MINUTES", "2"))
MIN_INTERVAL_HOURS = int(os.getenv("MIN_INTERVAL_HOURS", "5"))
MAX_INTERVAL_HOURS = int(os.getenv("MAX_INTERVAL_HOURS", "7"))
DRY_RUN = os.getenv("DRY_RUN", "false").lower() == "true"
DRY_RUN_DIR = Path.home() / "Desktop" / "INSTAI_TEST_OUTPUT"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
VIDEO_EXTS = {".mp4", ".mov", ".avi"}
MEDIA_EXTS = IMAGE_EXTS | VIDEO_EXTS

try:
    import requests
except ImportError:
    log.error("requests not installed")
    sys.exit(1)

try:
    from instagrapi import Client
except ImportError:
    log.error("instagrapi not installed")
    sys.exit(1)

try:
    import psutil
except ImportError:
    log.warning("psutil not installed - system load monitoring disabled")
    psutil = None

# Track if WE started Ollama (so we know if we can stop it)
_ollama_started_by_us = False
_ollama_process = None

# =============================================================================
# OLLAMA LIFECYCLE MANAGEMENT
# =============================================================================

def is_ollama_running():
    """Check if Ollama is already running."""
    try:
        resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=2)
        return resp.status_code == 200
    except requests.exceptions.ConnectionError:
        return False

def start_ollama_if_needed():
    """Start Ollama only if it's not already running. Returns True if we started it."""
    global _ollama_started_by_us, _ollama_process

    if is_ollama_running():
        log.info("Ollama already running (another program may be using it) - leaving it alone")
        return False

    log.info("Ollama not running - starting it temporarily...")
    _ollama_process = subprocess.Popen(
        ["ollama", "serve"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    _ollama_started_by_us = True

    # Wait for Ollama to be ready (up to 30 seconds)
    for i in range(30):
        if is_ollama_running():
            log.info("Ollama started successfully")
            return True
        time.sleep(1)

    log.error("Ollama failed to start within 30 seconds")
    _ollama_started_by_us = False
    return False

def stop_ollama_if_started():
    """Stop Ollama ONLY if we started it. Never touch Ollama started by another program."""
    global _ollama_started_by_us, _ollama_process

    if not _ollama_started_by_us:
        return

    log.info("Stopping Ollama (we started it, so it's safe to shut down)...")

    if _ollama_process:
        _ollama_process.terminate()
        try:
            _ollama_process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            _ollama_process.kill()
            _ollama_process.wait()

    # Only kill the specific Ollama process we started (by PID)
    if _ollama_process and _ollama_process.poll() is None:
        try:
            os.kill(_ollama_process.pid, signal.SIGTERM)
            _ollama_process.wait(timeout=5)
        except (ProcessLookupError, subprocess.TimeoutExpired):
            try:
                os.kill(_ollama_process.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    
    # Also clean up child processes spawned by our ollama
    try:
        # Find child processes of our ollama PID
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

# Register cleanup to run even if poster.py crashes or gets killed
atexit.register(stop_ollama_if_started)
signal.signal(signal.SIGTERM, lambda s, f: (stop_ollama_if_started(), sys.exit(1)))
signal.signal(signal.SIGINT, lambda s, f: (stop_ollama_if_started(), sys.exit(1)))

# =============================================================================
# SYSTEM MONITORING
# =============================================================================

def get_system_uptime_seconds():
    try:
        with open("/proc/uptime", "r") as f:
            return float(f.read().split()[0])
    except Exception:
        return 0

def is_gpu_busy(threshold_percent=60):
    """Check ALL GPU cards (card0, card1, etc.) for busy percentage."""
    gpu_paths = glob.glob("/sys/class/drm/card*/device/gpu_busy_percent")
    for path in gpu_paths:
        try:
            with open(path, "r") as f:
                gpu_load = int(f.read().strip())
                if gpu_load >= threshold_percent:
                    log.info(f"GPU busy ({gpu_load}% on {path}), deferring post")
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
            log.info(f"CPU busy ({cpu_usage}%), deferring post")
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
# HELPER FUNCTIONS
# =============================================================================

def is_video(file_path):
    """Check if a file is a video based on extension."""
    return Path(file_path).suffix.lower() in VIDEO_EXTS

# =============================================================================
# AI INFERENCE
# =============================================================================

def analyze_image_with_vision(image_path_str):
    log.info(f"Analyzing image: {Path(image_path_str).name}")
    import base64
    with open(image_path_str, "rb") as f:
        image_b64 = base64.b64encode(f.read()).decode("utf-8")
    payload = {
        "model": VISION_MODEL,
        "prompt": VISION_PROMPT,
        "images": [image_b64],
        "stream": False
    }
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=300)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()

def generate_caption(description):
    log.info("Generating caption and hashtags...")
    persona = PERSONA_PHOTO if PERSONA_PHOTO else ""

    if persona:
        prompt = f"""{persona}

Image description:
{description}

Write the caption now:"""
    else:
        prompt = f"""You write captions for a travel/adventure Instagram photo. CASUAL TONE ONLY.

ABSOLUTE RULES:
- 2-3 sentences only.
- DESCRIBE ONLY WHAT THE CAMERA SEEES IN THIS IMAGE. If the description mentions walking, say you walked. If mountains are visible, mention mountains. NOTHING ELSE.
- DO NOT invent feelings ("feeling the strength"), intentions ("let us keep pushing"), tools ("GoPro"), backstory, or speculation ("Part 2").
- DO NOT infer emotions, motivations, effort levels, or difficulty unless explicitly stated in the input.
- DO NOT reference equipment, filming methods, future plans, or sequels.
- 1-2 emojis max.
- One engagement question based strictly on visible scenery/activity.
- Exactly 3 hashtags based on visible landscape/activity.
- No quotation marks, no prefixes.

Image description:
{description}

Write the caption now:"""
    payload = {
        "model": CAPTION_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.6}
    }
    resp = requests.post(f"{OLLAMA_URL}/api/generate", json=payload, timeout=120)
    resp.raise_for_status()
    return resp.json().get("response", "").strip()

def compute_image_fingerprint(image_path):
    """Compute a unique fingerprint for an image using multiple data points."""
    fingerprint = {}

    # File size in bytes
    fingerprint["file_size"] = os.path.getsize(str(image_path))

    # MD5 hash of file contents (most reliable — different photos = different hash)
    hasher = hashlib.md5()
    with open(image_path, "rb") as f:
        # Read in chunks for large files
        for chunk in iter(lambda: f.read(8192), b""):
            hasher.update(chunk)
    fingerprint["md5"] = hasher.hexdigest()

    # Image dimensions + EXIF data via PIL
    try:
        from PIL import Image
        from PIL.ExifTags import TAGS
        img = Image.open(str(image_path))
        fingerprint["dimensions"] = f"{img.width}x{img.height}"

        # Extract EXIF data (camera model, date taken)
        exif_data = img._getexif() if hasattr(img, "_getexif") else None
        if exif_data:
            exif_dict = {}
            for tag_id, value in exif_data.items():
                tag = TAGS.get(tag_id, tag_id)
                if tag in ("Make", "Model", "DateTime", "DateTimeOriginal"):
                    exif_dict[tag] = str(value)
            fingerprint["exif"] = exif_dict
        else:
            fingerprint["exif"] = {}
        img.close()
    except Exception as e:
        log.debug(f"EXIF extraction failed for {image_path}: {e}")
        fingerprint["dimensions"] = "unknown"
        fingerprint["exif"] = {}

    return fingerprint


def is_duplicate(image_path, log_data):
    """Check if an image has already been posted by comparing fingerprints."""
    new_fp = compute_image_fingerprint(image_path)

    for posted_path, entry in log_data.get("posted", {}).items():
        stored_fp = entry.get("fingerprint")
        if not stored_fp:
            # Old entries without fingerprints — skip comparison
            continue

        # Compare MD5 hash first (fastest and most reliable)
        if stored_fp.get("md5") == new_fp.get("md5"):
            log.info(f"DUPLICATE detected (MD5 match): {image_path.name}")
            return True, entry

        # If MD5 differs but file_size + dimensions match, check further
        if (stored_fp.get("file_size") == new_fp.get("file_size") and
            stored_fp.get("dimensions") == new_fp.get("dimensions")):

            # Same size AND same dimensions — very likely the same photo
            # Double-check EXIF date + camera if available
            stored_exif = stored_fp.get("exif", {})
            new_exif = new_fp.get("exif", {})

            if (stored_exif.get("DateTimeOriginal") == new_exif.get("DateTimeOriginal") and
                stored_exif.get("Model") == new_exif.get("Model") and
                stored_exif.get("Model")):  # Make sure Model isn't empty
                log.info(f"DUPLICATE detected (EXIF match): {image_path.name}")
                return True, entry

    return False, None


def skip_duplicate(image_path, log_data, original_entry):
    """Move a duplicate image to duplicates/ folder for manual review."""
    dup_dir = IMAGE_FOLDER_PATH.parent / "duplicates"
    dup_dir.mkdir(parents=True, exist_ok=True)

    dest = dup_dir / Path(image_path).name
    counter = 1
    while dest.exists():
        stem = Path(image_path).stem
        suffix = Path(image_path).suffix
        dest = dup_dir / f"{stem}_{counter}{suffix}"
        counter += 1

    try:
        import shutil
        shutil.move(str(image_path), str(dest))
        log.info(f"Duplicate moved to duplicates/: {dest.name}")
    except Exception as e:
        log.warning(f"Could not move duplicate: {e}")
        dest = image_path

    # Mark as pending_review (not confirmed duplicate yet)
    log_data.setdefault("pending_duplicates", [])
    log_data["pending_duplicates"].append({
        "image_path": str(dest.resolve()),
        "original_path": str(Path(image_path).resolve()),
        "detected_at": datetime.now().isoformat(),
        "original_posted_at": original_entry.get("posted_at", "unknown"),
        "original_caption": original_entry.get("caption", "")[:100],
        "fingerprint": compute_image_fingerprint(dest) if dest.exists() else None,
        "status": "pending"
    })

    # Also mark in posted dict so it doesn't get rescanned
    log_data["posted"][str(Path(image_path).resolve())] = {
        "caption": "[PENDING DUPLICATE REVIEW]",
        "posted_at": datetime.now().isoformat(),
        "image_name": Path(image_path).name,
        "moved_to": str(dest),
        "fingerprint": compute_image_fingerprint(dest) if dest.exists() else None,
        "status": "pending_duplicate"
    }
    save_uploaded_log(log_data)


# =============================================================================
# POSTED IMAGES LOG
# =============================================================================

def get_uploaded_log():
    if POSTED_LOG_PATH.exists():
        try:
            return json.loads(POSTED_LOG_PATH.read_text())
        except json.JSONDecodeError:
            log.warning("Corrupt log file; starting fresh")
    return {"posted": {}, "last_post_time": None}

def save_uploaded_log(data):
    POSTED_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
    POSTED_LOG_PATH.write_text(json.dumps(data, indent=2))

def mark_as_posted(image_path, caption):
    data = get_uploaded_log()

    # Route to posted_reels/ for videos, posted_images/ for photos
    if is_video(image_path):
        posted_dir = IMAGE_FOLDER_PATH.parent / "posted_reels"
    else:
        posted_dir = IMAGE_FOLDER_PATH.parent / "posted_images"
    posted_dir.mkdir(parents=True, exist_ok=True)
    dest = posted_dir / Path(image_path).name
    
    # Handle duplicate filenames
    counter = 1
    while dest.exists():
        stem = Path(image_path).stem
        suffix = Path(image_path).suffix
        dest = posted_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    
    try:
        shutil.move(str(image_path), str(dest))
        log.info(f"Moved image to: {dest}")
    except Exception as e:
        log.warning(f"Could not move image: {e}")
        dest = image_path  # fallback to original path
    
    data["posted"][str(Path(image_path).resolve())] = {
        "caption": caption,
        "posted_at": datetime.now().isoformat(),
        "image_name": Path(image_path).name,
        "moved_to": str(dest),
        "fingerprint": compute_image_fingerprint(dest) if dest.exists() else compute_image_fingerprint(image_path)
    }
    data["last_post_time"] = datetime.now().isoformat()
    save_uploaded_log(data)

# =============================================================================
# SCHEDULING
# =============================================================================

def should_post_now():
    data = get_uploaded_log()
    boot_seconds = DELAY_AFTER_BOOT_MINUTES * 60

    if not data.get("last_post_time"):
        uptime = get_system_uptime_seconds()
        if uptime < boot_seconds:
            remaining = int((boot_seconds - uptime) / 60)
            log.info(f"First post pending - waiting {remaining} more minutes after boot")
            return False
        log.info("Ready for first post (boot delay complete)")
        return True

    last_post = datetime.fromisoformat(data["last_post_time"])
    elapsed_hours = (datetime.now() - last_post).total_seconds() / 3600
    target_interval = random.uniform(MIN_INTERVAL_HOURS, MAX_INTERVAL_HOURS)

    log.info(f"Hours since last post: {elapsed_hours:.1f} | Target interval: {target_interval:.1f}h")

    if elapsed_hours >= target_interval:
        log.info("Scheduled interval reached - ready to post")
        return True

    remaining_hours = target_interval - elapsed_hours
    log.info(f"Not yet - {remaining_hours:.1f} hours remaining")
    return False

def get_next_unposted_image(folder_path):
    if not folder_path.exists():
        log.error(f"Image folder not found: {folder_path}")
        return None
    sort_order = os.getenv("SORT_ORDER", "oldest")
    all_images = [p for p in folder_path.iterdir() if p.is_file() and p.suffix.lower() in IMAGE_EXTS]
    if DRY_RUN:
        log.info("DRY RUN: bypassing duplicate detection")
        if not all_images:
            return None
        if sort_order == "newest":
            all_images.sort(key=lambda p: p.stat().st_mtime, reverse=True)
        elif sort_order == "name_asc":
            all_images.sort(key=lambda p: p.name.lower())
        elif sort_order == "name_desc":
            all_images.sort(key=lambda p: p.name.lower(), reverse=True)
        else:
            all_images.sort(key=lambda p: p.stat().st_mtime)
        log.info(f"DRY RUN: selected {all_images[0].name}")
        return all_images[0]
    if sort_order == "newest":
        all_images.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    elif sort_order == "name_asc":
        all_images.sort(key=lambda p: p.name.lower())
    elif sort_order == "name_desc":
        all_images.sort(key=lambda p: p.name.lower(), reverse=True)
    else:  # oldest (default)
        all_images.sort(key=lambda p: p.stat().st_mtime)
    images = all_images
    data = get_uploaded_log()
    # Don't pre-filter by path — check ALL images via fingerprint
    # This catches duplicates even if same filename was reused
    valid_images = []
    for img in images:
        if not img.exists():
            continue
        
        # Check if this exact file (by fingerprint) was already posted
        is_dup, orig_entry = is_duplicate(img, data)
        if is_dup:
            skip_duplicate(img, data, orig_entry)
            # Reload data since skip_duplicate modified it
            data = get_uploaded_log()
            log.info(f"Skipping duplicate {img.name}, looking for next image...")
        else:
            # Also check if this exact path is logged as posted with matching fingerprint
            path_key = str(img.resolve())
            if path_key in data.get("posted", {}):
                entry = data["posted"][path_key]
                stored_fp = entry.get("fingerprint", {})
                # If we have a stored fingerprint and it matches, skip
                if stored_fp and "md5" in stored_fp:
                    new_fp = compute_image_fingerprint(img)
                    if stored_fp.get("md5") == new_fp.get("md5"):
                        log.debug(f"Already posted (exact match): {img.name}")
                        continue
                    else:
                        # Different file at same path — valid to post!
                        valid_images.append(img)
                else:
                    # No fingerprint stored — skip to be safe
                    continue
            else:
                valid_images.append(img)

    if not valid_images:
        log.info("All images have been posted (or were duplicates)!")
        return None
    log.info(f"Found {len(valid_images)} valid images after duplicate check after duplicate check")
    return valid_images[0]

# =============================================================================
# INSTAGRAM UPLOAD
# =============================================================================

def upload_to_instagram(image_path_str, caption):
    log.info(f"Uploading to Instagram: {Path(image_path_str).name}")
    client = Client()
    session_file = Path("ig_session.json")

    if session_file.exists():
        try:
            client.load_settings(session_file)
        except Exception:
            pass

    if not IG_USERNAME or not IG_PASSWORD:
        log.error("Instagram credentials missing in .env")
        return False

    try:
        client.login(IG_USERNAME, IG_PASSWORD)
        client.dump_settings(session_file)
    except Exception as e:
        log.error(f"Login failed: {e}")
        return False

    # Fix EXIF orientation (prevent sideways photos)
    upload_path = image_path_str
    try:
        from PIL import Image, ImageOps
        import tempfile
        img = Image.open(image_path_str)
        exif = img.getexif() if hasattr(img, "getexif") else {}
        orientation = exif.get(0x0112, 1)
        needs_fix = orientation not in (1, None)
        needs_mode_fix = img.mode != "RGB"
        if needs_fix or needs_mode_fix:
            img = ImageOps.exif_transpose(img)
            if needs_mode_fix:
                img = img.convert("RGB")
            fd, temp_path = tempfile.mkstemp(suffix=".jpg", dir="/tmp")
            os.close(fd)
            img.save(temp_path, "JPEG", quality=100, subsampling=0)
            upload_path = temp_path
            reason = []
            if needs_fix:
                reason.append("EXIF orientation fixed")
            if needs_mode_fix:
                reason.append("mode converted to RGB")
            msg = ", ".join(reason)
            log.info(f"Processed image for upload ({msg})")
        else:
            log.info("No preprocessing needed - uploading original file")
    except Exception as e:
        log.warning(f"Image preprocessing skipped: {e}")


    try:
        client.photo_upload(str(upload_path), caption)
        log.info("Successfully uploaded to Instagram!")
        if upload_path != image_path_str:
            os.remove(upload_path)
        return True
    except Exception as e:
        log.error(f"Upload failed: {e}")
        return False

# =============================================================================
# MAIN
# =============================================================================

def run_once():
    log.info("=" * 60)
    log.info("Starting Instagram auto-poster cycle")
    log.info("=" * 60)

    # Scheduling is handled entirely by tray_app.py's QTimer.
    # poster.py always posts when called (unless no images).
    if '--force' not in sys.argv:
        log.info("Scheduled run triggered by tray app")

    if not wait_if_busy(max_wait_minutes=30):
        log.warning("Aborting - system remained too busy")
        return False

    image_path = get_next_unposted_image(IMAGE_FOLDER_PATH)
    if not image_path:
        log.info("No images left to post")
        return None

    # Start Ollama only for the AI work, then stop it
    we_started_ollama = start_ollama_if_needed()

    try:
        description = analyze_image_with_vision(str(image_path))
        if not description:
            log.error("Failed to analyze image")
            return False

        caption = generate_caption(description)
        if not caption:
            log.error("Failed to generate caption")
            return False

        log.info(f"Generated caption ({len(caption)} chars):\n{caption}")

        if DRY_RUN:
            DRY_RUN_DIR.mkdir(parents=True, exist_ok=True)
            shutil.copy2(str(image_path), str(DRY_RUN_DIR / image_path.name))
            (DRY_RUN_DIR / f"{image_path.stem}_caption.txt").write_text(caption)
            log.info(f"DRY RUN: saved {image_path.name} + caption to {DRY_RUN_DIR}")
            return True

        success = upload_to_instagram(str(image_path), caption)

        if success:
            mark_as_posted(image_path, caption)
            log.info("Cycle complete - image logged and saved")
        else:
            log.error("Upload failed - will retry on next run")

        return success

    finally:
        # ALWAYS stop Ollama if we started it, even if something failed
        stop_ollama_if_started()

if __name__ == "__main__":
    result = run_once()
    if result is True:
        sys.exit(0)
    elif result is None:
        sys.exit(2)
    else:
        sys.exit(1)
