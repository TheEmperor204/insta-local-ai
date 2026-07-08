#!/usr/bin/env python3
"""
Explicit Content Review Tab (Enhanced v2)
Displays flagged videos with thumbnails, per-segment breakdown,
and provides Post Bleeped / Post Uncensored / Skip Flagged / Don't Post.
Writes decisions to approval_queue.json for reels_poster.py to consume.
"""

import os
import json
import shutil
from pathlib import Path
from datetime import datetime

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame, QMessageBox, QTextEdit
)
from PyQt6.QtCore import Qt, QTimer
from PyQt6.QtGui import QPixmap
from progress_writer import clear_explicit_trigger, EXPLICIT_TRIGGER

APP_DIR = Path(__file__).parent.resolve()
REELS_LOG = APP_DIR / "posted_reels.json"
VIDEO_UPLOAD_DIR = APP_DIR / "videos_to_upload"
APPROVAL_QUEUE = APP_DIR / "approval_queue.json"


class ExplicitTab(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        self.refresh()
        self._trigger_timer = QTimer(self)
        self._trigger_timer.timeout.connect(self._check_trigger)
        self._trigger_timer.start(20000)

    def _check_trigger(self):
        if EXPLICIT_TRIGGER.exists():
            clear_explicit_trigger()
            self.refresh()

    def _load_explicit(self):
        if REELS_LOG.exists():
            try:
                data = json.loads(REELS_LOG.read_text())
                return data.get("explicit_videos", [])
            except Exception:
                pass
        return []

    def _save_explicit(self, entries):
        if REELS_LOG.exists():
            try:
                data = json.loads(REELS_LOG.read_text())
            except Exception:
                data = {"videos": {}, "last_post_time": None}
        else:
            data = {"videos": {}, "last_post_time": None}
        data["explicit_videos"] = entries
        REELS_LOG.write_text(json.dumps(data, indent=2))

    def _write_approval(self, entry, action, segments_to_skip=None, approved_to=None):
        queue = []
        if APPROVAL_QUEUE.exists():
            try:
                queue = json.loads(APPROVAL_QUEUE.read_text())
            except Exception:
                queue = []
        queue.append({
            "video_path": entry.get("moved_to", ""),
            "approved_to": approved_to or "",
            "original_name": entry.get("original_name", ""),
            "action": action,
            "segments_to_skip": segments_to_skip or [],
            "matched_word": entry.get("matched_word", ""),
            "flagged_segments": entry.get("flagged_segments", {}),
            "decided_at": datetime.now().isoformat()
        })
        APPROVAL_QUEUE.write_text(json.dumps(queue, indent=2))

    def refresh(self):
        while self.layout.count():
            item = self.layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

        entries = self._load_explicit()
        pending = [e for e in entries if e.get("status") == "pending_review"]

        if not pending:
            ph = QLabel("No flagged videos pending review.")
            ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setStyleSheet("font-size: 14px; color: #888; padding: 30px;")
            self.layout.addWidget(ph)
            self.layout.addStretch()
            return

        count_label = QLabel(f"Flagged: {len(pending)} video(s) for review")
        count_label.setStyleSheet("font-size: 13px; font-weight: bold; padding: 4px 6px; color: #e74c3c;")
        self.layout.addWidget(count_label)

        btn_refresh = QPushButton("Refresh List")
        btn_refresh.setStyleSheet(
            "QPushButton { background: #6d4aff; color: white; border: none; padding: 4px 12px; "
            "border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #5d3aef; }"
        )
        btn_refresh.clicked.connect(self.refresh)
        self.layout.addWidget(btn_refresh)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)
        scroll_layout.setSpacing(8)

        for i, entry in enumerate(pending):
            scroll_layout.addWidget(self._build_entry_card(entry, i))

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        self.layout.addWidget(scroll)

    def _build_entry_card(self, entry, index):
        card = QFrame()
        card.setFrameShape(QFrame.Shape.StyledPanel)
        card.setStyleSheet(
            "QFrame { background: rgba(231, 76, 60, 0.08); border-radius: 8px; padding: 8px; }"
        )
        cl = QVBoxLayout(card)

        # Top row: thumbnail + info
        top_row = QHBoxLayout()

        thumb_path = entry.get("thumbnail", "")
        if thumb_path and Path(thumb_path).exists():
            pixmap = QPixmap(thumb_path)
            if not pixmap.isNull():
                thumb = pixmap.scaledToHeight(100, Qt.TransformationMode.SmoothTransformation)
                thumb_label = QLabel()
                thumb_label.setPixmap(thumb)
                top_row.addWidget(thumb_label)
            else:
                top_row.addWidget(self._make_thumb_placeholder())
        else:
            top_row.addWidget(self._make_thumb_placeholder())

        info_col = QVBoxLayout()
        filename = QLabel(f"<b>{entry.get('original_name', 'Unknown')}</b>")
        filename.setTextFormat(Qt.TextFormat.RichText)
        filename.setStyleSheet("font-size: 12px;")
        info_col.addWidget(filename)

        word = entry.get("matched_word", "")
        category = entry.get("category", "")
        word_label = QLabel(f'<span style="color: #e74c3c;">Flagged: "{word}" - {category}</span>')
        word_label.setTextFormat(Qt.TextFormat.RichText)
        word_label.setStyleSheet("font-size: 12px;")
        info_col.addWidget(word_label)

        ts_hint = entry.get("timestamp_hint", "")
        if ts_hint:
            ts_label = QLabel(f"<span style='color: #aaa; font-size: 11px;'>@ {ts_hint}</span>")
            ts_label.setTextFormat(Qt.TextFormat.RichText)
            info_col.addWidget(ts_label)

        detected = entry.get("detected_at", "")
        if detected:
            try:
                dt = datetime.fromisoformat(detected)
                det_str = dt.strftime("%b %d at %I:%M %p")
            except Exception:
                det_str = detected
            det_label = QLabel(f"<span style='color: #888; font-size: 11px;'>Detected: {det_str}</span>")
            det_label.setTextFormat(Qt.TextFormat.RichText)
            info_col.addWidget(det_label)

        top_row.addLayout(info_col)
        top_row.addStretch()
        cl.addLayout(top_row)

        # Per-segment breakdown
        flagged = entry.get("flagged_segments", {})
        if flagged:
            seg_label = QLabel("<b>Segment Breakdown:</b>")
            seg_label.setStyleSheet("font-size: 11px; padding-top: 4px;")
            seg_label.setTextFormat(Qt.TextFormat.RichText)
            cl.addWidget(seg_label)
            for seg_num, info in flagged.items():
                if isinstance(info, dict):
                    seg_text = f"  Part {seg_num}: Flagged - word: {info.get('word', '?')} at {info.get('timestamp', '?')}"
                else:
                    seg_text = f"  Part {seg_num}: Flagged - {info}"
                seg_line = QLabel(seg_text)
                seg_line.setStyleSheet("font-size: 11px; color: #e74c3c; padding-left: 12px;")
                cl.addWidget(seg_line)

        # Transcript preview
        transcript = entry.get("transcript", "")
        if transcript:
            tr_label = QLabel("<b>Transcript excerpt:</b>")
            tr_label.setStyleSheet("font-size: 11px; padding-top: 4px;")
            tr_label.setTextFormat(Qt.TextFormat.RichText)
            cl.addWidget(tr_label)
            tr_edit = QTextEdit()
            tr_edit.setPlainText(transcript[:300])
            tr_edit.setReadOnly(True)
            tr_edit.setMaximumHeight(60)
            tr_edit.setStyleSheet("font-size: 11px; color: #999; background: rgba(0,0,0,0.1); border-radius: 4px;")
            cl.addWidget(tr_edit)

        # Action buttons row 1: Post options
        btn_row1 = QHBoxLayout()

        btn_bleep = QPushButton("Post Bleeped")
        btn_bleep.setToolTip("Bleep ban-list words in audio, then post")
        btn_bleep.setStyleSheet(
            "QPushButton { background: #2980b9; color: white; border: none; padding: 6px 12px; "
            "border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #2471a3; }"
        )
        btn_bleep.clicked.connect(lambda checked, e=entry: self._post_bleeped(e))

        btn_uncensored = QPushButton("Post Uncensored")
        btn_uncensored.setToolTip("Post the video as-is, no modifications")
        btn_uncensored.setStyleSheet(
            "QPushButton { background: #27ae60; color: white; border: none; padding: 6px 12px; "
            "border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #219a52; }"
        )
        btn_uncensored.clicked.connect(lambda checked, e=entry: self._post_uncensored(e))

        btn_row1.addWidget(btn_bleep)
        btn_row1.addWidget(btn_uncensored)
        btn_row1.addStretch()
        cl.addLayout(btn_row1)

        # Action buttons row 2: Skip / Discard
        btn_row2 = QHBoxLayout()

        btn_skip = QPushButton("Skip Flagged Parts")
        btn_skip.setToolTip("Post clear segments, skip flagged ones")
        btn_skip.setStyleSheet(
            "QPushButton { background: #f39c12; color: white; border: none; padding: 6px 12px; "
            "border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #d68910; }"
        )
        btn_skip.clicked.connect(lambda checked, e=entry: self._skip_flagged(e))

        btn_discard = QPushButton("Don't Post")
        btn_discard.setToolTip("Archive or delete this video")
        btn_discard.setStyleSheet(
            "QPushButton { background: #e74c3c; color: white; border: none; padding: 6px 12px; "
            "border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #c0392b; }"
        )
        btn_discard.clicked.connect(lambda checked, e=entry: self._dont_post(e))

        btn_row2.addWidget(btn_skip)
        btn_row2.addWidget(btn_discard)
        btn_row2.addStretch()
        cl.addLayout(btn_row2)

        btn_row3 = QHBoxLayout()
        btn_dismiss = QPushButton("X Dismiss")
        btn_dismiss.setToolTip("Clear this notification without taking action")
        btn_dismiss.setStyleSheet(
            "QPushButton { background: #555; color: white; border: none; padding: 6px 12px; "
            "border-radius: 4px; font-size: 11px; }"
            "QPushButton:hover { background: #444; }"
        )
        btn_dismiss.clicked.connect(lambda checked, e=entry: self._dismiss(e))
        btn_row3.addWidget(btn_dismiss)
        btn_row3.addStretch()
        cl.addLayout(btn_row3)

        return card

    def _make_thumb_placeholder(self):
        ph = QLabel("No thumb")
        ph.setFixedSize(130, 100)
        ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
        ph.setStyleSheet("background: rgba(255,255,255,0.05); border-radius: 4px; color: #888; font-size: 10px;")
        return ph

    def _move_to_upload_queue(self, video_path_str):
        if not video_path_str or not Path(video_path_str).exists():
            return None
        VIDEO_UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
        dest = VIDEO_UPLOAD_DIR / Path(video_path_str).name
        counter = 1
        while dest.exists():
            stem = Path(video_path_str).stem
            suffix = Path(video_path_str).suffix
            dest = VIDEO_UPLOAD_DIR / f"{stem}_{counter}{suffix}"
            counter += 1
        try:
            shutil.move(str(video_path_str), str(dest))
            return str(dest)
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Failed to move video: {e}")
            return None

    def _mark_resolved(self, video_path, status, extra_fields=None):
        entries = self._load_explicit()
        entries = [e for e in entries if e.get("moved_to") != video_path]
        self._save_explicit(entries)
        self.refresh()

    def _post_bleeped(self, entry):
        vp = entry.get("moved_to", "")
        reply = QMessageBox.question(
            self, "Confirm: Post Bleeped",
            f"Bleep ban-list words in this video then post?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        dest = self._move_to_upload_queue(vp)
        if not dest:
            QMessageBox.warning(self, "Not Found", "Video file no longer exists.")
            return
        self._write_approval(entry, "bleep", approved_to=dest)
        self._mark_resolved(vp, "approved_bleeped", {"approved_to": dest})
        QMessageBox.information(self, "Queued", f"Video queued for bleeped posting.")

    def _post_uncensored(self, entry):
        vp = entry.get("moved_to", "")
        reply = QMessageBox.question(
            self, "Confirm: Post Uncensored",
            f"Post this video uncensored (as-is)?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        dest = self._move_to_upload_queue(vp)
        if not dest:
            QMessageBox.warning(self, "Not Found", "Video file no longer exists.")
            return
        self._write_approval(entry, "uncensored", approved_to=dest)
        self._mark_resolved(vp, "approved_uncensored", {"approved_to": dest})
        QMessageBox.information(self, "Queued", f"Video queued for uncensored posting.")

    def _skip_flagged(self, entry):
        vp = entry.get("moved_to", "")
        flagged = entry.get("flagged_segments", {})
        if not flagged:
            QMessageBox.information(self, "No Segments", "No per-segment breakdown available for this video.")
            return
        seg_lines = []
        for seg_num, info in flagged.items():
            if isinstance(info, dict):
                seg_lines.append(f"  Part {seg_num}: word: {info.get('word', '?')}")
            else:
                seg_lines.append(f"  Part {seg_num}: {info}")
        msg = (
            f"Skip flagged parts and post only clear segments?\n\n"
            f"Flagged segments:\n" + "\n".join(seg_lines) +
            f"\n\nClear segments will be posted in order."
        )
        reply = QMessageBox.question(
            self, "Confirm: Skip Flagged Parts", msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        dest = self._move_to_upload_queue(vp)
        if not dest:
            QMessageBox.warning(self, "Not Found", "Video file no longer exists.")
            return
        segs_to_skip = [str(k) for k in flagged.keys()] if isinstance(flagged, dict) else []
        self._write_approval(entry, "skip_flagged", segments_to_skip=segs_to_skip, approved_to=dest)
        self._mark_resolved(vp, "approved_skip_flagged", {"approved_to": dest, "skipped_segments": segs_to_skip})
        QMessageBox.information(self, "Queued", f"Video queued - clear segments will be posted.")

    def _dont_post(self, entry):
        reply = QMessageBox.question(
            self, "Confirm: Don't Post",
            f"Permanently delete this video?\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        vp = entry.get("moved_to", "")
        if vp and Path(vp).exists():
            try:
                Path(vp).unlink()
            except Exception:
                pass
        thumb = entry.get("thumbnail", "")
        if thumb and Path(thumb).exists():
            try:
                Path(thumb).unlink()
            except Exception:
                pass
        self._write_approval(entry, "discard")
        self._mark_resolved(vp, "discarded")

    def _dismiss(self, entry):
        vp = entry.get("moved_to", "")
        entries = self._load_explicit()
        entries = [e for e in entries if e.get("moved_to") != vp]
        self._save_explicit(entries)
        self.refresh()

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())
