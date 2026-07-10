#!/usr/bin/env python3
"""Music overlay module - adds background music to reel segments."""
import os
import json
import random
import subprocess
import tempfile
import logging
from pathlib import Path

log = logging.getLogger(__name__)

APP_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = APP_DIR / "music_config.json"

DEFAULT_CONFIG = {
    "enabled": False,
    "mode": "all",
    "categories": {
        "default": {"folder": str(APP_DIR / "Default_Music"), "word_count": 5, "volume": 50, "clip_mode": "highlight", "song_selection": "random", "specific_song": ""},
        "adventure": {"folder": str(APP_DIR / "Adventure_Music"), "word_count": 5, "volume": 50, "clip_mode": "highlight", "song_selection": "random", "specific_song": ""},
        "action_sport": {"folder": str(APP_DIR / "Action_Sport_Music"), "word_count": 5, "volume": 50, "clip_mode": "highlight", "song_selection": "random", "specific_song": ""}
    }
}

# NOTE: Adventure takes priority on ties (for hiking Instagram account).
# Future YouTube project should swap priority to action_sport.
ADVENTURE_KEYWORDS = [
    "hik","trail","mountain","forest","nature","scenic","view","landscape",
    "sunrise","sunset","camp","lake","river","valley","cliff","waterfall",
    "beach","ocean","sky","cloud","meadow","field","canyon","desert",
    "plateau","ridge","summit","peak","glacier","fjord","horizon","wildflower",
    "tree","stream","pond","creek","grove","prairie","dune","savanna",
    "jungle","rainforest","island","coast","peninsula","harbor","fishing",
    "walking","strolling","exploring","drone","aerial","panoram","vista",
    "overlook","bluff","hill","countryside","woodland","wildlife","birdwatch"
]
ACTION_SPORT_KEYWORDS = [
    "ski","snowboard","skate","surf","bike","cycl","climb","dive","jump",
    "raft","kayak","board","ramp","trick","flip","race","wakeboard",
    "paddle","snowmobile","atv","motocross","bmx","scooter","longboard",
    "sandboard","kitesurf","windsurf","parachu","hang gli","bungee",
    "zip line","zipline","abseil","bouldering","sport climb","free climb",
    "parkour","slackline","skimboard","bodyboard","jetski","jet ski",
    "snorkel","scuba","spearfish","spear fish","bow fish","rod","reel",
    "sail","kite board","tubing","rope swing","cliff jump","cliff div",
    "downhill","freeride","freestyle","cross country","enduro","gravel ride",
    "mountain bike","mtb","unicycle","trampoline","gymnastic","tumble"
]

def load_config():
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            for k in DEFAULT_CONFIG:
                if k not in cfg:
                    cfg[k] = DEFAULT_CONFIG[k]
            for cat in DEFAULT_CONFIG["categories"]:
                if cat not in cfg["categories"]:
                    cfg["categories"][cat] = DEFAULT_CONFIG["categories"][cat]
            return cfg
        except Exception:
            pass
    return DEFAULT_CONFIG.copy()

def detect_category(vision_text):
    text = vision_text.lower()
    adv_score = sum(1 for kw in ADVENTURE_KEYWORDS if kw in text)
    act_score = sum(1 for kw in ACTION_SPORT_KEYWORDS if kw in text)
    if adv_score >= act_score and adv_score > 0:
        return 'adventure'
    if act_score > 0:
        return 'action_sport'
    return 'default'

def should_add_music(transcript, config, category="default"):
    if not config.get('enabled', False):
        return False
    if config.get('mode', 'all') == 'all':
        return True
    if config.get('mode', 'all') == 'no_talking':
        words = transcript.strip().split() if transcript else []
        return len(words) < config.get('categories', {}).get(category, {}).get('word_count', 5)
    return False

def select_song(cat_config):
    folder = Path(cat_config.get('folder', ''))
    if not folder.exists():
        return None
    exts = {'.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac'}
    songs = [f for f in folder.iterdir() if f.is_file() and f.suffix.lower() in exts]
    if not songs:
        return None
    if cat_config.get('song_selection', 'random') == 'specific' and cat_config.get('specific_song'):
        for s in songs:
            if s.name == cat_config['specific_song']:
                return s
    return random.choice(songs)

def get_duration(file_path):
    try:
        result = subprocess.run(
            ['ffprobe', '-v', 'quiet', '-show_entries', 'format=duration', '-of', 'csv=p=0', str(file_path)],
            capture_output=True, text=True, timeout=10
        )
        return float(result.stdout.strip())
    except Exception:
        return 0.0

def create_highlight_clip(song_path, target_duration, volume_pct, clip_mode):
    song_dur = get_duration(song_path)
    if song_dur <= 0:
        return None
    vol = volume_pct / 100.0
    tmp = Path(tempfile.mktemp(suffix='.m4a'))
    if clip_mode == 'beginning':
        start = 0
        end = min(target_duration, song_dur)
    else:
        mid = song_dur / 2
        start = max(0, mid - target_duration / 2)
        end = start + min(target_duration, song_dur - start)
        start = max(0, start - 3)
    ramp_dur = max(3.0, min(5.0, target_duration * 0.15))
    ramp_end = min(ramp_dur, end - start)
    af = 'atrim=start=' + str(start) + ':duration=' + str(end - start) + ',asetpts=PTS-STARTPTS,'
    if clip_mode == 'highlight':
        af += "volume=" + str(vol) + ",afade=t=in:st=0:d=" + str(ramp_end) + ","
        af += 'aformat=sample_rates=44100:channel_layouts=stereo'
    else:
        af += 'volume=' + str(vol) + ',aformat=sample_rates=44100:channel_layouts=stereo'
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-i', str(song_path), '-af', af, '-t', str(end - start), str(tmp)],
            capture_output=True, timeout=120
        )
        if tmp.exists() and tmp.stat().st_size > 0:
            return tmp
        return None
    except Exception:
        if tmp.exists():
            tmp.unlink()
        return None

def overlay_music(video_path, music_clip_path):
    tmp = Path(tempfile.mktemp(suffix='.mp4'))
    amix = '[0:a]volume=1.0[va];[1:a]volume=1.0[ma];[va][ma]amix=inputs=2:duration=first:dropout_transition=0[aout]'
    try:
        subprocess.run(
            ['ffmpeg', '-y', '-i', str(video_path), '-i', str(music_clip_path),
             '-filter_complex', amix, '-map', '0:v', '-map', '[aout]',
             '-c:v', 'copy', '-c:a', 'aac', '-b:a', '192k', '-shortest', str(tmp)],
            capture_output=True, timeout=120
        )
        if tmp.exists() and tmp.stat().st_size > 0:
            return tmp
        return None
    except Exception:
        if tmp.exists():
            tmp.unlink()
        return None

def add_music_to_video(video_path, vision_text, transcript):
    config = load_config()
    category = detect_category(vision_text)
    if not should_add_music(transcript, config, category):
        return video_path, None
    cat_config = config['categories'].get(category, config['categories']['default'])
    song = select_song(cat_config)
    if song is None:
        log.warning('No songs found in category: ' + category)
        return video_path, None
    video_dur = get_duration(video_path)
    if video_dur <= 0:
        log.warning('Could not get video duration')
        return video_path, None
    music_clip = create_highlight_clip(song, video_dur, cat_config['volume'], cat_config['clip_mode'])
    if music_clip is None:
        log.warning('Failed to create music clip from ' + song.name)
        return video_path, None
    result = overlay_music(video_path, music_clip)
    if music_clip.exists():
        music_clip.unlink()
    if result is not None:
        log.info('Music overlay added: ' + song.name + ' (category: ' + category + ')')
        return result, song.name
    else:
        log.warning('Music overlay failed')
        return video_path, None
