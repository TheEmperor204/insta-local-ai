#!/usr/bin/env python3.12
"""Helper script to transcribe audio using faster-whisper.
Called as subprocess by reels_poster.py (uses python3.12 env where faster-whisper lives).
Outputs JSON with transcript text + word-level timestamps for bleep support."""
import sys
import json

def main():
    audio_path = sys.argv[1]
    try:
        from faster_whisper import WhisperModel
        model = WhisperModel("medium", device="cpu", compute_type="int8")
        segments, info = model.transcribe(audio_path, beam_size=5, word_timestamps=True)
        
        text_parts = []
        words = []
        for seg in segments:
            text_parts.append(seg.text)
            if seg.words:
                for w in seg.words:
                    words.append({
                        "word": w.word.strip(),
                        "start": round(w.start, 2),
                        "end": round(w.end, 2)
                    })
        
        result = {
            "text": " ".join(text_parts).strip(),
            "words": words
        }
        print(json.dumps(result))
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
