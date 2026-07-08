# Insta Local AI

A fully local, privacy-first Instagram auto-poster for photos and reels. Uses local AI models (LLaVA + Qwen via Ollama) for vision analysis and caption generation. No cloud APIs, no monthly fees, no data leaving your machine.

## Features

### Photos
- Local AI vision analysis (LLaVA) and caption generation (Qwen) via Ollama
- EXIF rotation fix for vertical phone photos
- Duplicate detection (perceptual hashing) to prevent reposts
- Smart scheduling with randomized intervals
- Posted images archived automatically

### Reels / Videos
- Automatic video splitting for clips over 60 seconds (zero quality loss via ffmpeg)
- Frame extraction and vision analysis for each segment
- Audio transcription (faster-whisper) to understand spoken content
- Audio bleeping of flagged words (muting, video still posts)
- Banned word detection with manual review workflow
- Per-segment content screening (flag, hold, skip, or bleep individual parts)
- Combined visual + audio analysis for accurate captions
- Anti-hallucination caption rules (only describe what is explicitly detected)

### Content Control (Two-List System)
- Bleep List: Words muted in audio. Video still posts automatically.
- Ban List: Words that flag the video for manual human review before posting.
- Both lists are editable via the GUI (Bleep Words tab + Explicits tab)
- Word variant support for catching plurals and alternate spellings

### Music Overlay
- Auto-overlay background music on videos
- Category detection from visual analysis (adventure, action sport, default)
- Per-category song folders with specific song or random selection
- Volume control (10 percent to 100 percent)
- Clip modes: beginning or highlight (quiet intro with fade-in ramp)
- Trigger modes: all videos, or only videos without talking (by word count threshold)

### GUI Dashboard
- System tray icon with tabbed popup interface
- Progress tab: live pipeline status, stage timing, error display, pending queue
- Last Post and History tabs
- Settings tab: scheduling, sort order, dry run mode, Instagram credentials, phone notifications
- Explicit review panel: 4 actions (Post Bleeped, Skip Flagged Parts, Discard, Dismiss) with auto-refresh
- Bleep Words tab: add or remove bleep words
- Duplicates tab: review flagged duplicate images
- Music tab: configure categories, songs, volume, trigger mode
- Schedule tab: time windows, random intervals, on/off toggles

### Safety and Notifications
- Phone push notifications via ntfy.sh (configurable topic in Settings)
- Dry Run mode: full pipeline runs but saves locally instead of uploading
- Failed upload tracking with 3-retry limit before giving up
- Firejail sandbox support (noroot, seccomp, caps drop all)
- Instagram password stored in system keyring (KDE Wallet on Linux), never in plaintext

## Requirements

- Linux (tested on Arch / KDE Plasma 6 / Wayland)
- Python 3.10+
- Ollama with models: llava:7b (vision) and qwen2.5:7b (captions)
- ffmpeg (for video splitting, audio bleeping, music overlay)
- faster-whisper (for speech-to-text transcription)
- GPU: AMD ROCm or NVIDIA CUDA (for Ollama model inference)
- firejail (optional, recommended for sandboxing)
- ~10GB disk space for AI models

## Quick Start

Clone the repo, copy the example config, and install dependencies:

    git clone https://github.com/TheEmperor204/insta-local-ai.git
    cd insta-local-ai
    cp .env.example .env
    pip install -r requirements.txt

Then:
1. Install Ollama from https://ollama.com and pull models:
   ollama pull llava:7b
   ollama pull qwen2.5:7b
2. Launch the GUI:
   python3 tray_app.py
3. Open Settings tab and enter your Instagram credentials
4. Set up phone notifications (optional): enter your ntfy topic name
5. Drop images into images_to_post/ and videos into videos_to_upload/
6. The app handles the rest

### Dry Run (Test Mode)

Enable Dry Run in Settings to run the full pipeline without posting to Instagram. Outputs are saved to a local test folder. Recommended for first-time setup.

## Project Structure

    tray_app.py          GUI (PyQt6 tray icon + tabbed popup)
    poster.py            Photo pipeline (vision, caption, upload)
    reels_poster.py      Reel pipeline (split, transcribe, bleep, caption, upload)
    transcribe_helper.py Whisper speech-to-text integration
    explicit_filter.py   Ban word checker
    explicit_tab.py      Quarantine review panel
    progress_writer.py   Shared functions (progress, notifications, queues)
    progress_tab.py      Progress dashboard widget
    music_overlay.py     Music overlay backend
    music_tab.py         Music settings GUI tab
    schedule_manager.py  Upload scheduling backend
    schedule_tab.py      Scheduling GUI tab
    duplicates_tab.py    Duplicate image review
    caption_persona.py   Persona templates (gitignored, copy from .example)
    server.py            Flask web server (optional)

## Configuration

All settings are managed through the GUI Settings tab and saved to .env. Key options:

- DRY_RUN (default: true) - Save outputs locally instead of uploading
- MIN_INTERVAL_HOURS (default: 4) - Minimum hours between posts
- MAX_INTERVAL_HOURS (default: 6) - Maximum hours between posts
- VISION_MODEL (default: llava:7b) - Ollama model for image/video analysis
- CAPTION_MODEL (default: qwen2.5:7b) - Ollama model for caption generation
- MAX_REEL_DURATION_SECONDS (default: 60) - Videos longer than this get split
- SORT_ORDER (default: oldest) - Processing order for media files
- NTFY_TOPIC (default: empty) - ntfy.sh topic for phone notifications

Copy .env.example to .env to get started, then customize via the GUI.

## Security

- Firejail sandbox: noroot, nonewprivs, seccomp, caps.drop all, private-tmp
- Instagram password encrypted in system keyring (KDE Wallet), never in plaintext
- Ollama runs on localhost only, no network exposure
- ntfy notifications are one-way (computer to phone), no inbound channel
- Dry Run mode prevents accidental uploads during testing

## Disclaimer

Instagram Terms of Service generally prohibit automated posting through unofficial APIs. This tool uses instagrapi which simulates a real client. Use at your own risk.

## License

MIT License. See LICENSE file for details.
