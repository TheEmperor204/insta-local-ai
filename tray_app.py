#!/usr/bin/env python3
from schedule_manager import calculate_wait, get_next_post_description, load_schedule_config, save_schedule_config
"""
Instagram Auto-Poster Tray Widget
Dual pipelines: Photos + Reels on independent timers.
Dropdown popup with tabs: Last Post, History, Settings, Duplicates
"""

import os
import sys
import json
import random
from pathlib import Path
from datetime import datetime, timedelta

from dotenv import load_dotenv
import keyring
from duplicates_tab import DuplicatesTab
from explicit_tab import ExplicitTab
from music_tab import MusicTab
from schedule_tab import ScheduleTab
from progress_tab import ProgressTab

KEYRING_SERVICE = "insta-poster"
KEYRING_KEY = "ig_password"
from PyQt6.QtWidgets import (
    QApplication, QSystemTrayIcon, QMenu, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QSpinBox, QFileDialog, QGroupBox,
    QFormLayout, QMessageBox, QTabWidget, QScrollArea, QFrame, QCheckBox, QTextEdit
)
from PyQt6.QtCore import QTimer, Qt, QProcess, QPointF, QEvent
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QPen

APP_DIR = Path(__file__).parent.resolve()
ENV_FILE = APP_DIR / ".env"
POSTER_SCRIPT = str(APP_DIR / "poster.py")
REELS_POSTER_SCRIPT = str(APP_DIR / "reels_poster.py")
VENV_PYTHON = str(APP_DIR / "insta-env" / "bin" / "python")


class ConfigManager:
    def __init__(self):
        self.path = ENV_FILE
        self.load()

    def load(self):
        self.settings = {}
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                line = line.strip()
                if line and not line.startswith("#") and "=" in line:
                    key, val = line.split("=", 1)
                    self.settings[key.strip()] = val.strip()

    def get(self, key, default=""):
        return self.settings.get(key, default)

    def save(self, updates):
        self.settings.update({k: str(v) for k, v in updates.items()})
        lines = []
        written = set()
        if self.path.exists():
            for line in self.path.read_text().splitlines():
                s = line.strip()
                if s and not s.startswith("#") and "=" in s:
                    key = s.split("=", 1)[0].strip()
                    if key in updates:
                        lines.append(f"{key}={updates[key]}")
                        written.add(key)
                    elif key in self.settings:
                        lines.append(f"{key}={self.settings[key]}")
                        written.add(key)
                    else:
                        lines.append(line)
                else:
                    lines.append(line)
        for key, val in updates.items():
            if key not in written:
                lines.append(f"{key}={val}")
        self.path.write_text("\n".join(lines) + "\n")
        self.load()


def create_instagram_icon():
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    p = QPainter(pixmap)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(220, 39, 67)
    pen = QPen(color)
    pen.setWidth(4)
    p.setPen(pen)
    p.setBrush(Qt.GlobalColor.transparent)
    rect = pixmap.rect().adjusted(8, 8, -8, -8)
    p.drawRoundedRect(rect, 14, 14)
    p.drawEllipse(QPointF(rect.center()), 12, 12)
    p.setBrush(color)
    p.setPen(Qt.PenStyle.NoPen)
    p.drawEllipse(QPointF(rect.right() - 10, rect.top() + 10), 3, 3)
    p.end()
    return QIcon(pixmap)


class TrayPopup(QWidget):
    def __init__(self, config):
        super().__init__()
        self.config = config
        self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Tool)
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, False)
        self.setMinimumSize(440, 520)
        self.setMaximumHeight(660)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        header = QFrame()
        header.setFixedHeight(36)
        header.setStyleSheet("background-color: #C13584; border-radius: 8px 8px 0 0;")
        hl = QHBoxLayout(header)
        hl.setContentsMargins(12, 0, 8, 0)
        title = QLabel("Instagram Auto-Poster")
        title.setStyleSheet("color: white; font-size: 13px; font-weight: bold;")
        hl.addWidget(title)
        hl.addStretch()
        close_btn = QPushButton("X")
        close_btn.setFixedSize(24, 24)
        close_btn.setStyleSheet(
            "QPushButton { background: transparent; color: white; border: none; font-size: 14px; }"
            "QPushButton:hover { background: rgba(255,255,255,0.2); border-radius: 4px; }"
        )
        close_btn.clicked.connect(self.hide)
        hl.addWidget(close_btn)
        layout.addWidget(header)

        self.tabs = QTabWidget()
        self.last_post_widget = self._build_last_post_tab()
        self.tabs.addTab(ProgressTab(), "📊 Progress")
        self.tabs.addTab(self.last_post_widget, "Last Post")
        self.tabs.addTab(self._build_history_tab(), "History")
        self.tabs.addTab(self._build_settings_tab(), "Settings")
        self.tabs.addTab(DuplicatesTab(), "Duplicates")
        self.tabs.addTab(ExplicitTab(), "🚫 Explicits")
        self.tabs.addTab(BleepWordManager(), "Bleep Words")
        self.tabs.addTab(MusicTab(), "Music")
        self.tabs.addTab(ScheduleTab(), "Schedule")
        layout.addWidget(self.tabs)

    def _build_last_post_tab(self):
        widget = QWidget()
        self.last_post_layout = QVBoxLayout(widget)
        self.last_post_layout.setContentsMargins(8, 8, 8, 8)
        self.last_post_layout.addStretch()
        return widget

    def _build_history_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll_content = QWidget()
        self.history_layout = QVBoxLayout(scroll_content)
        self.history_layout.addStretch()
        scroll.setWidget(scroll_content)
        layout.addWidget(scroll)
        return widget

    def _build_settings_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        grp_folder = QGroupBox("Image Folder")
        fl = QHBoxLayout(grp_folder)
        self.folder_input = QLineEdit(self.config.get("IMAGE_FOLDER", ""))
        btn_browse = QPushButton("Browse")
        btn_browse.clicked.connect(self._browse)
        fl.addWidget(self.folder_input)
        fl.addWidget(btn_browse)
        layout.addWidget(grp_folder)

        grp_sched = QGroupBox("Photo Posting Schedule")
        sl = QFormLayout(grp_sched)
        self.boot_delay = QSpinBox()
        self.boot_delay.setRange(0, 30)
        self.boot_delay.setValue(int(self.config.get("DELAY_AFTER_BOOT_MINUTES", "12")))
        self.boot_delay.setSuffix(" min")
        self.min_hours = QSpinBox()
        self.min_hours.setRange(1, 24)
        self.min_hours.setValue(int(self.config.get("MIN_INTERVAL_HOURS", "5")))
        self.min_hours.setSuffix(" hr")
        self.max_hours = QSpinBox()
        self.max_hours.setRange(1, 24)
        self.max_hours.setValue(int(self.config.get("MAX_INTERVAL_HOURS", "7")))
        self.max_hours.setSuffix(" hr")
        sl.addRow("Delay after boot:", self.boot_delay)
        sl.addRow("Min interval:", self.min_hours)
        sl.addRow("Max interval:", self.max_hours)
        layout.addWidget(grp_sched)

        grp_reel_sched = QGroupBox("Reel Posting Schedule")
        rl = QFormLayout(grp_reel_sched)
        self.reel_boot_delay = QSpinBox()
        self.reel_boot_delay.setRange(0, 60)
        self.reel_boot_delay.setValue(int(self.config.get("REEL_DELAY_AFTER_BOOT_MINUTES", "2")))
        self.reel_boot_delay.setSuffix(" min")
        self.reel_min_hours = QSpinBox()
        self.reel_min_hours.setRange(1, 24)
        self.reel_min_hours.setValue(int(self.config.get("REEL_MIN_INTERVAL_HOURS", "4")))
        self.reel_min_hours.setSuffix(" hr")
        self.reel_max_hours = QSpinBox()
        self.reel_max_hours.setRange(1, 48)
        self.reel_max_hours.setValue(int(self.config.get("REEL_MAX_INTERVAL_HOURS", "8")))
        self.reel_max_hours.setSuffix(" hr")
        rl.addRow("Delay after boot:", self.reel_boot_delay)
        rl.addRow("Min interval:", self.reel_min_hours)
        rl.addRow("Max interval:", self.reel_max_hours)
        layout.addWidget(grp_reel_sched)

        from PyQt6.QtWidgets import QComboBox
        grp_sort = QGroupBox("Media Sort Order")
        sol = QFormLayout(grp_sort)
        self.sort_combo = QComboBox()
        self.sort_combo.addItem("Oldest first (by date created)", "oldest")
        self.sort_combo.addItem("Newest first (by date created)", "newest")
        self.sort_combo.addItem("Alphabetical A-Z", "name_asc")
        self.sort_combo.addItem("Alphabetical Z-A", "name_desc")
        current_sort = self.config.get("SORT_ORDER", "oldest")
        for i in range(self.sort_combo.count()):
            if self.sort_combo.itemData(i) == current_sort:
                self.sort_combo.setCurrentIndex(i)
                break
        sol.addRow("Order:", self.sort_combo)
        layout.addWidget(grp_sort)

        # === DRY RUN / TEST MODE ===
        grp_dry = QGroupBox("Test Mode (Dry Run)")
        dl = QVBoxLayout(grp_dry)
        self.dry_run_checkbox = QCheckBox("Enable Dry Run — save outputs locally instead of uploading")
        self.dry_run_checkbox.setChecked(self.config.get("DRY_RUN", "false").lower() == "true")
        dl.addWidget(self.dry_run_checkbox)
        hint = QLabel("When ON: full pipeline runs but nothing posts to Instagram.\nDuplicate detection is bypassed.\nOutputs saved to ~/Desktop/INSTAI_TEST_OUTPUT/")
        hint.setStyleSheet("font-size: 10px; color: #aaa;")
        hint.setWordWrap(True)
        dl.addWidget(hint)
        layout.addWidget(grp_dry)
        # === PHONE NOTIFICATIONS ===
        grp_ntfy = QGroupBox("Phone Notifications (ntfy.sh)")
        nl = QVBoxLayout(grp_ntfy)
        self.ntfy_enable = QCheckBox("Enable phone notifications")
        self.ntfy_enable.setChecked(bool(self.config.get("NTFY_TOPIC", "")))
        nl.addWidget(self.ntfy_enable)
        nl.addWidget(QLabel("ntfy topic name:"))
        self.ntfy_topic = QLineEdit(self.config.get("NTFY_TOPIC", ""))
        self.ntfy_topic.setPlaceholderText("Your ntfy topic name")
        nl.addWidget(self.ntfy_topic)
        ntfy_hint = QLabel("Install the ntfy app on your phone and subscribe to this topic name.")
        ntfy_hint.setStyleSheet("font-size: 10px; color: #aaa;")
        ntfy_hint.setWordWrap(True)
        nl.addWidget(ntfy_hint)
        layout.addWidget(grp_ntfy)


        grp_cred = QGroupBox("Instagram Credentials")
        cl = QFormLayout(grp_cred)
        self.username_input = QLineEdit(self.config.get("IG_USERNAME", ""))
        _stored_pw = keyring.get_password(KEYRING_SERVICE, KEYRING_KEY) or ""
        self.password_input = QLineEdit(_stored_pw)
        self.password_input.setEchoMode(QLineEdit.EchoMode.Password)
        cl.addRow("Username:", self.username_input)
        cl.addRow("Password:", self.password_input)
        layout.addWidget(grp_cred)

        btn_save = QPushButton("Save Settings")
        btn_save.clicked.connect(self._save_settings)
        layout.addWidget(btn_save)
        layout.addStretch()
        return widget

    def _browse(self):
        folder = QFileDialog.getExistingDirectory(self, "Select Image Folder")
        if folder:
            self.folder_input.setText(folder)

    def _save_settings(self):
        if self.max_hours.value() < self.min_hours.value():
            QMessageBox.warning(self, "Invalid", "Photo max interval must be >= min interval")
            return
        if self.reel_max_hours.value() < self.reel_min_hours.value():
            QMessageBox.warning(self, "Invalid", "Reel max interval must be >= min interval")
            return
        if self.password_input.text():
            keyring.set_password(KEYRING_SERVICE, KEYRING_KEY, self.password_input.text())
        self.config.save({
            "IMAGE_FOLDER": self.folder_input.text(),
            "DELAY_AFTER_BOOT_MINUTES": str(self.boot_delay.value()),
            "MIN_INTERVAL_HOURS": str(self.min_hours.value()),
            "MAX_INTERVAL_HOURS": str(self.max_hours.value()),
            "REEL_DELAY_AFTER_BOOT_MINUTES": str(self.reel_boot_delay.value()),
            "REEL_MIN_INTERVAL_HOURS": str(self.reel_min_hours.value()),
            "REEL_MAX_INTERVAL_HOURS": str(self.reel_max_hours.value()),
            "SORT_ORDER": self.sort_combo.currentData(),
            "DRY_RUN": "true" if self.dry_run_checkbox.isChecked() else "false",
            "IG_USERNAME": self.username_input.text(),
            "NTFY_TOPIC": self.ntfy_topic.text() if self.ntfy_enable.isChecked() else "",
        })
        QMessageBox.information(self, "Saved", "Settings saved!")
        self.config.load()

    def refresh_data(self):
        self._clear_layout(self.last_post_layout)
        self._clear_layout(self.history_layout)

        # --- PHOTOS ---
        log_path = APP_DIR / self.config.get("POSTED_LOG", "posted_images.json")
        data = {"posted": {}, "last_post_time": None}
        if log_path.exists():
            try:
                data = json.loads(log_path.read_text())
            except Exception:
                pass

        posted = data.get("posted", {})
        entries = []
        for key, entry in posted.items():
            try:
                t = datetime.fromisoformat(entry["posted_at"])
                entries.append((t, key, entry))
            except (KeyError, ValueError):
                continue
        entries.sort(key=lambda x: x[0], reverse=True)

        image_folder = Path(self.config.get("IMAGE_FOLDER", ""))
        exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        remaining_photos = 0
        if image_folder.exists():
            remaining_photos = sum(1 for f in image_folder.iterdir()
                           if f.is_file() and f.suffix.lower() in exts)

        # --- REELS ---
        reels_log_path = APP_DIR / "posted_reels.json"
        reels_data = {"videos": {}, "last_post_time": None}
        if reels_log_path.exists():
            try:
                reels_data = json.loads(reels_log_path.read_text())
            except Exception:
                pass

        video_folder = Path(self.config.get("VIDEO_FOLDER", "videos_to_upload"))
        remaining_videos = 0
        if video_folder.exists():
            remaining_videos = sum(1 for f in video_folder.iterdir()
                          if f.is_file() and f.suffix.lower() in {".mp4", ".mov", ".avi"})

        # Count segments in temp
        temp_seg = Path(self.config.get("TEMP_SEGMENTS_DIR", "temp_segments"))
        remaining_segments = 0
        if temp_seg.exists():
            remaining_segments = sum(1 for f in temp_seg.iterdir()
                            if f.is_file() and f.suffix.lower() in {".mp4", ".mov", ".avi"})

        # Stats banner
        stats_text = (f"📸 Photos: {len(entries)} posted | {remaining_photos} in queue")
        stats_text += (f"\n🎬 Reels: {len(reels_data.get('videos', {}))} processed | {remaining_videos} in queue")
        if remaining_segments > 0:
            stats_text += f" | {remaining_segments} segments pending"
        stats = QLabel(stats_text)
        stats.setStyleSheet("font-size: 12px; font-weight: bold; padding: 6px;")
        self.last_post_layout.addWidget(stats)

        # Next post times
        next_times = []
        if "next_post_time" in data:
            try:
                next_dt = datetime.fromisoformat(data["next_post_time"])
                next_times.append(("📸 Photo", next_dt))
            except (ValueError, KeyError):
                pass
        if "next_reel_time" in reels_data:
            try:
                next_dt = datetime.fromisoformat(reels_data["next_reel_time"])
                next_times.append(("🎬 Reel", next_dt))
            except (ValueError, KeyError):
                pass

        for label, dt in next_times:
            next_str = dt.strftime("%B %d at %I:%M %p")
            nl = QLabel(f"{label} next: {next_str}")
            nl.setStyleSheet("font-size: 12px; padding: 2px 6px; color: #C13584;")
            self.last_post_layout.addWidget(nl)

        # Show latest reel post if available
        reel_entries = []
        for vkey, vdata in reels_data.get("videos", {}).items():
            if vdata.get("first_posted_at"):
                try:
                    t = datetime.fromisoformat(vdata["first_posted_at"])
                    reel_entries.append((t, vkey, vdata))
                except (ValueError, KeyError):
                    pass
        reel_entries.sort(key=lambda x: x[0], reverse=True)

        # Determine which is more recent: latest photo or latest reel
        latest_photo = entries[0] if entries else None
        latest_reel = reel_entries[0] if reel_entries else None

        if latest_reel and (not latest_photo or latest_reel[0] > latest_photo[0]):
            self._populate_last_reel(latest_reel[2])
        elif latest_photo:
            self._populate_last_post(latest_photo[2])
        else:
            ph = QLabel("No posts yet.")
            ph.setAlignment(Qt.AlignmentFlag.AlignCenter)
            ph.setStyleSheet("font-size: 14px; color: #888; padding: 30px;")
            self.last_post_layout.addWidget(ph)

        self.last_post_layout.addStretch()

        # History — combine photos + reels, sort by date
        all_history = []
        for t, key, entry in entries[:10]:
            all_history.append((t, "photo", entry))
        for t, vkey, vdata in reel_entries[:10]:
            all_history.append((t, "reel", vdata))
        all_history.sort(key=lambda x: x[0], reverse=True)

        if not all_history:
            if remaining_photos == 0 and remaining_videos == 0:
                nh = QLabel("No photos or videos in queue.\nAdd files to upload folders to get started.")
            else:
                nh = QLabel("No posts yet \u2014 waiting for first upload.")
            nh.setStyleSheet("padding: 20px; color: #888;")
            self.history_layout.addWidget(nh)
        else:
            for t, media_type, entry in all_history[:8]:
                if media_type == "photo":
                    self._add_history_item(t, entry)
                else:
                    self._add_reel_history_item(t, entry)

        self.history_layout.addStretch()

    def _populate_last_post(self, entry):
        type_label = QLabel("📸 PHOTO")
        type_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #C13584; padding: 2px;")
        self.last_post_layout.addWidget(type_label)

        img_path = None
        if "moved_to" in entry:
            img_path = Path(entry["moved_to"])
        elif "image_name" in entry:
            candidate = APP_DIR / "posted_images" / entry["image_name"]
            if candidate.exists():
                img_path = candidate

        if img_path and img_path.exists():
            pixmap = QPixmap(str(img_path))
            if not pixmap.isNull():
                scaled = pixmap.scaledToWidth(380, Qt.TransformationMode.SmoothTransformation)
                if scaled.height() > 280:
                    scaled = pixmap.scaledToHeight(280, Qt.TransformationMode.SmoothTransformation)
                img_label = QLabel()
                img_label.setPixmap(scaled)
                img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
                self.last_post_layout.addWidget(img_label)

        name_label = QLabel(f"File: {entry.get('image_name', 'Unknown')}")
        name_label.setStyleSheet("font-size: 11px; color: #aaa; padding: 2px;")
        self.last_post_layout.addWidget(name_label)

        try:
            t = datetime.fromisoformat(entry["posted_at"])
            time_str = t.strftime("%B %d, %Y at %I:%M %p")
        except Exception:
            time_str = entry.get("posted_at", "Unknown")
        time_label = QLabel(f"Posted: {time_str}")
        time_label.setStyleSheet("font-size: 12px; padding: 2px;")
        self.last_post_layout.addWidget(time_label)

        cap_title = QLabel("Caption:")
        cap_title.setStyleSheet("font-size: 12px; font-weight: bold; padding-top: 6px;")
        self.last_post_layout.addWidget(cap_title)

        cap_label = QLabel(entry.get("caption", "(none)"))
        cap_label.setWordWrap(True)
        cap_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        cap_label.setStyleSheet(
            "font-size: 12px; padding: 6px; "
            "background: rgba(255,255,255,0.05); border-radius: 4px;"
        )
        self.last_post_layout.addWidget(cap_label)

    def _populate_last_reel(self, vdata):
        type_label = QLabel("🎬 REEL")
        type_label.setStyleSheet("font-size: 11px; font-weight: bold; color: #C13584; padding: 2px;")
        self.last_post_layout.addWidget(type_label)

        name_label = QLabel(f"Video: {vdata.get('video_name', 'Unknown')}")
        name_label.setStyleSheet("font-size: 11px; color: #aaa; padding: 2px;")
        self.last_post_layout.addWidget(name_label)

        seg_info = f"Segments: {vdata.get('segments_posted', 0)}/{vdata.get('segments_total', 1)}"
        if vdata.get("status") == "complete":
            seg_info += " ✅"
        elif vdata.get("status") == "posting":
            seg_info += " 🔄"
        seg_label = QLabel(seg_info)
        seg_label.setStyleSheet("font-size: 12px; padding: 2px;")
        self.last_post_layout.addWidget(seg_label)

        try:
            t = datetime.fromisoformat(vdata.get("first_posted_at", ""))
            time_str = t.strftime("%B %d, %Y at %I:%M %p")
        except Exception:
            time_str = vdata.get("first_posted_at", "Unknown")
        time_label = QLabel(f"First posted: {time_str}")
        time_label.setStyleSheet("font-size: 12px; padding: 2px;")
        self.last_post_layout.addWidget(time_label)

        dur = vdata.get("duration", 0)
        if dur:
            dur_label = QLabel(f"Duration: {dur:.1f}s")
            dur_label.setStyleSheet("font-size: 12px; color: #aaa; padding: 2px;")
            self.last_post_layout.addWidget(dur_label)

    def _add_history_item(self, timestamp, entry):
        item = QFrame()
        item.setFrameShape(QFrame.Shape.StyledPanel)
        item.setStyleSheet(
            "QFrame { margin: 2px; padding: 4px; border-radius: 4px; "
            "background: rgba(255,255,255,0.03); }"
        )
        il = QHBoxLayout(item)

        img_path = None
        if "moved_to" in entry:
            img_path = Path(entry["moved_to"])
        if img_path and img_path.exists():
            pixmap = QPixmap(str(img_path))
            if not pixmap.isNull():
                thumb = pixmap.scaledToHeight(60, Qt.TransformationMode.SmoothTransformation)
                thumb_label = QLabel()
                thumb_label.setPixmap(thumb)
                il.addWidget(thumb_label)

        info_layout = QVBoxLayout()
        time_str = timestamp.strftime("%b %d, %I:%M %p")
        info_label = QLabel(
            f"📸 <b>{entry.get('image_name', 'Unknown')}</b>"
            f"<br/><span style='color: #aaa; font-size: 11px;'>{time_str}</span>"
        )
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_layout.addWidget(info_label)

        cap_preview = entry.get("caption", "")[:80]
        if len(entry.get("caption", "")) > 80:
            cap_preview += "..."
        cap_label = QLabel(f"<span style='color: #888; font-size: 11px;'>{cap_preview}</span>")
        cap_label.setTextFormat(Qt.TextFormat.RichText)
        cap_label.setWordWrap(True)
        info_layout.addWidget(cap_label)

        il.addLayout(info_layout)
        il.addStretch()
        self.history_layout.addWidget(item)

    def _add_reel_history_item(self, timestamp, vdata):
        item = QFrame()
        item.setFrameShape(QFrame.Shape.StyledPanel)
        item.setStyleSheet(
            "QFrame { margin: 2px; padding: 4px; border-radius: 4px; "
            "background: rgba(193,53,132,0.08); }"
        )
        il = QHBoxLayout(item)

        info_layout = QVBoxLayout()
        time_str = timestamp.strftime("%b %d, %I:%M %p")
        status_icon = "✅" if vdata.get("status") == "complete" else "🔄"
        info_label = QLabel(
            f"🎬 <b>{vdata.get('video_name', 'Unknown')}</b> {status_icon}"
            f"<br/><span style='color: #aaa; font-size: 11px;'>{time_str} • "
            f"{vdata.get('segments_posted', 0)}/{vdata.get('segments_total', 1)} parts</span>"
        )
        info_label.setTextFormat(Qt.TextFormat.RichText)
        info_layout.addWidget(info_label)

        dur = vdata.get("duration", 0)
        dur_label = QLabel(f"<span style='color: #888; font-size: 11px;'>{dur:.0f}s</span>")
        dur_label.setTextFormat(Qt.TextFormat.RichText)
        info_layout.addWidget(dur_label)

        il.addLayout(info_layout)
        il.addStretch()
        self.history_layout.addWidget(item)

    def _clear_layout(self, layout):
        while layout.count():
            item = layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
            elif item.layout():
                self._clear_layout(item.layout())

    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowDeactivate:
            if not QApplication.activeModalWidget():
                self.hide()
        super().changeEvent(event)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape:
            self.hide()

    def show_near_tray(self, tray_icon):
        self.refresh_data()
        self.adjustSize()
        w = max(self.minimumWidth(), self.sizeHint().width())
        h = max(self.minimumHeight(), self.sizeHint().height())
        if w > 500:
            w = 500
        if h > 660:
            h = 660
        self.resize(w, h)

        from PyQt6.QtGui import QCursor
        cursor_pos = QCursor.pos()
        screen = QApplication.screenAt(cursor_pos)
        if not screen:
            screen = QApplication.primaryScreen()
        screen_geo = screen.availableGeometry()

        x = cursor_pos.x() - w + 20
        y = cursor_pos.y() + 8
        if x < screen_geo.left() + 8:
            x = screen_geo.left() + 8
        if x + w > screen_geo.right() - 8:
            x = screen_geo.right() - w - 8
        if y + h > screen_geo.bottom() - 8:
            y = cursor_pos.y() - h - 8
        if y < screen_geo.top() + 8:
            y = screen_geo.top() + 8

        self.move(x, y)
        self.show()
        self.raise_()
        self.activateWindow()



class BleepWordManager(QWidget):
    """UI to manage bleep word list."""
    def __init__(self):
        super().__init__()
        self.load_config()
        self.load_ban_config()
        self.init_ui()

    def load_config(self):
        try:
            data = json.loads(Path("bleep_words.json").read_text())
            self.enabled_state = data.get("enabled", True)
            self.words_list = data.get("words", [])
        except Exception:
            self.enabled_state = True
            self.words_list = []

    def _make_separator(self):
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setFrameShadow(QFrame.Shadow.Sunken)
        return sep
    def save_config(self):
        try:
            data = {"enabled": self.enabled_state, "words": self.words_list}
            Path("bleep_words.json").write_text(json.dumps(data, indent=2))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save: {e}")

    def init_ui(self):
        layout = QVBoxLayout(self)

        # Toggle
        row = QHBoxLayout()
        self.enable_cb = QCheckBox("Enable automatic bleeping")
        self.enable_cb.setChecked(self.enabled_state)
        self.enable_cb.stateChanged.connect(self._on_toggle)
        btn_refresh = QPushButton("Apply to running poster")
        btn_refresh.clicked.connect(lambda: self._reload_for_poster())
        row.addWidget(self.enable_cb)
        row.addStretch()
        row.addWidget(btn_refresh)
        layout.addLayout(row)

        # Word list header
        h = QHBoxLayout()
        h.addWidget(QLabel("Bleep words (one per row):"))
        h.addStretch()
        layout.addLayout(h)

        # Text area for words
        self.word_text = QTextEdit()
        self.word_text.setPlainText(chr(10).join(self.words_list))
        self.word_text.setMaximumHeight(250)
        layout.addWidget(self.word_text)

        # Buttons
        ctrl_row = QHBoxLayout()
        btnSave = QPushButton("Save List")
        btnSave.clicked.connect(self._save_words)
        btnAdd = QPushButton("Add Selected")
        btnAdd.clicked.connect(self._add_selected)
        btnClearSel = QPushButton("Clear Selection")
        btnClearSel.clicked.connect(lambda: self.word_text.clearSelection())
        ctrl_row.addWidget(btnSave)
        ctrl_row.addWidget(btnAdd)
        ctrl_row.addWidget(btnClearSel)
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

        # Instructions
        info = QLabel("Tip: Double-click a line to select it, then click Add Selected. \\nEach line becomes one bleep word.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #666;")
        layout.addWidget(info)

        # ===== BAN LIST SECTION =====
        layout.addWidget(self._make_separator())

        ban_header = QHBoxLayout()
        ban_header.addWidget(QLabel("<b>Ban Words (flag for manual review)</b>"))
        ban_header.addStretch()
        layout.addLayout(ban_header)

        ban_toggle_row = QHBoxLayout()
        self.ban_enable_cb = QCheckBox("Enable ban list checking")
        self.ban_enable_cb.setChecked(self.ban_enabled)
        self.ban_enable_cb.stateChanged.connect(self._on_ban_toggle)
        ban_toggle_row.addWidget(self.ban_enable_cb)
        ban_toggle_row.addStretch()
        layout.addLayout(ban_toggle_row)

        ban_label = QLabel("One word per line. Each line is a banned word.")
        ban_label.setStyleSheet("color: #666;")
        ban_label.setWordWrap(True)
        layout.addWidget(ban_label)

        self.ban_word_text = QTextEdit()
        ban_lines = self.ban_words
        self.ban_word_text.setPlainText(chr(10).join(ban_lines))
        self.ban_word_text.setMinimumHeight(200)
        layout.addWidget(self.ban_word_text)

        ban_btn_row = QHBoxLayout()
        btnBanSave = QPushButton("Save Ban List")
        btnBanSave.clicked.connect(self._save_ban_words)
        ban_btn_row.addWidget(btnBanSave)
        ban_btn_row.addStretch()
        layout.addLayout(ban_btn_row)


    def _on_toggle(self, state):
        self.enabled_state = state == Qt.Checked
        self.save_config()

    def _reload_for_poster(self):
        # Reload config by triggering signal/log message; actual reload happens next cycle
        # config reload handled by next run
        QMessageBox.information(self, "Info", "Config updated. The poster process will pick up changes on next run.")

    def _save_words(self):
        text = self.word_text.toPlainText()
        lines = [l.strip().lower() for l in text.split(chr(10)) if l.strip()]
        seen = set()
        unique_lines = []
        for line in lines:
            if line not in seen:
                seen.add(line)
                unique_lines.append(line)
        self.words_list = unique_lines
        self.save_config()
        QMessageBox.information(self, "Saved", f"{len(unique_lines)} words saved.")

    def _add_selected(self):
        cursor = self.word_text.textCursor()
        sel = cursor.selectedText()
        if not sel.strip():
            QMessageBox.warning(self, "Nothing selected", "Select some text first.")
            return
        # Parse selection as comma-separated or newline-separated words
        import re
        tokens = [t.strip().lower() for t in re.split(r"[,\s+\n]+", sel) if t.strip()]
        added = []
        for tok in tokens:
            if tok and tok not in self.words_list:
                self.words_list.append(tok)
                added.append(tok)
        if added:
            self.save_config()
            self.word_text.setPlainText(chr(10).join(self.words_list))
            QMessageBox.information(self, "Added", f"Added {len(added)} word(s).")
        else:
            QMessageBox.information(self, "No new words", "All selected words already in list.")



    # ===== BAN WORDS SECTION =====
    def load_ban_config(self):
        try:
            data = json.loads(Path("ban_words.json").read_text())
            self.ban_enabled = data.get("enabled", True)
            self.ban_words = data.get("words", [])
        except Exception:
            self.ban_enabled = True
            self.ban_words = []

    def save_ban_config(self):
        try:
            data = {"enabled": self.ban_enabled, "words": self.ban_words}
            Path("ban_words.json").write_text(json.dumps(data, indent=2))
        except Exception as e:
            QMessageBox.critical(self, "Error", f"Failed to save ban list: {e}")

    def _save_ban_words(self):
        text = self.ban_word_text.toPlainText()
        self.ban_words = []
        for line in text.split(chr(10)):
            line = line.strip().lower()
            if line:
                self.ban_words.append(line)
        self.save_ban_config()
        QMessageBox.information(self, "Saved", f"{len(self.ban_words)} ban words saved.")

    def _on_ban_toggle(self, state):
        self.ban_enabled = state == Qt.Checked
        self.save_ban_config()

class TrayApp(QApplication):
    def __init__(self, argv):
        super().__init__(argv)
        self.setApplicationName("Instagram Auto-Poster")
        self.setQuitOnLastWindowClosed(False)
        self.config = ConfigManager()
        self.popup = TrayPopup(self.config)

        # Photo pipeline state
        self.photo_process = None
        self.is_posting_photo = False

        # Reel pipeline state
        self.reel_process = None
        self.is_posting_reel = False

        self.tray = QSystemTrayIcon(create_instagram_icon(), self)
        self.tray.setToolTip("Instagram Auto-Poster")

        menu = QMenu()
        menu.addAction("📸 Post Photo Now", self.post_photo_now)
        menu.addAction("🎬 Post Reel Now", self.post_reel_now)
        menu.addSeparator()
        menu.addAction("Status", self.show_status)
        menu.addSeparator()
        menu.addAction("Quit", self.quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_activated)
        self.tray.show()

        # Boot scheduling: reel fires first, photo 10 min later
        reel_boot_min = int(self.config.get("REEL_DELAY_AFTER_BOOT_MINUTES", "2"))
        photo_boot_min = reel_boot_min + 10

        # Use existing photo boot delay if it's set higher
        configured_photo_delay = int(self.config.get("DELAY_AFTER_BOOT_MINUTES", "12"))
        if configured_photo_delay > photo_boot_min:
            photo_boot_min = configured_photo_delay

        QTimer.singleShot(reel_boot_min * 60 * 1000, self.run_reels_poster)
        QTimer.singleShot(photo_boot_min * 60 * 1000, self.run_photo_poster)

        self._save_next_photo_time(photo_boot_min / 60.0)
        self._save_next_reel_time(reel_boot_min / 60.0)

        self.photo_timer = QTimer(self)
        self.photo_timer.setSingleShot(True)
        self.photo_timer.timeout.connect(self.run_photo_poster)

        self.reel_timer = QTimer(self)
        self.reel_timer.setSingleShot(True)
        self.reel_timer.timeout.connect(self.run_reels_poster)

    def _save_next_photo_time(self, wait_hours):
        next_time = datetime.now() + timedelta(hours=wait_hours)
        log_path = APP_DIR / self.config.get("POSTED_LOG", "posted_images.json")
        try:
            data = {"posted": {}, "last_post_time": None}
            if log_path.exists():
                data = json.loads(log_path.read_text())
            data["next_post_time"] = next_time.isoformat()
            log_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _save_next_reel_time(self, wait_hours):
        next_time = datetime.now() + timedelta(hours=wait_hours)
        log_path = APP_DIR / "posted_reels.json"
        try:
            data = {"videos": {}, "last_post_time": None}
            if log_path.exists():
                data = json.loads(log_path.read_text())
            data["next_reel_time"] = next_time.isoformat()
            log_path.write_text(json.dumps(data, indent=2))
        except Exception:
            pass

    def _update_tooltip(self):
        parts = []
        if self.is_posting_photo:
            parts.append("📸 posting...")
        if self.is_posting_reel:
            parts.append("🎬 posting...")
        if not parts:
            parts.append("Idle")
        self.tray.setToolTip(f"Instagram Auto-Poster ({' | '.join(parts)})")

    def _on_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.popup.isVisible():
                self.popup.hide()
            else:
                self.popup.show_near_tray(self.tray)

    def show_status(self):
        log_path = APP_DIR / self.config.get("POSTED_LOG", "posted_images.json")
        image_folder = Path(self.config.get("IMAGE_FOLDER", ""))
        exts = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
        posted = 0
        total = 0
        if log_path.exists():
            try:
                data = json.loads(log_path.read_text())
                posted = len(data.get("posted", {}))
            except Exception:
                pass
        if image_folder.exists():
            total = sum(1 for f in image_folder.iterdir()
                       if f.is_file() and f.suffix.lower() in exts)

        reels_log = APP_DIR / "posted_reels.json"
        reel_count = 0
        video_folder = Path(self.config.get("VIDEO_FOLDER", "videos_to_upload"))
        video_count = 0
        if reels_log.exists():
            try:
                rdata = json.loads(reels_log.read_text())
                reel_count = len(rdata.get("videos", {}))
            except Exception:
                pass
        if video_folder.exists():
            video_count = sum(1 for f in video_folder.iterdir()
                            if f.is_file() and f.suffix.lower() in {".mp4", ".mov", ".avi"})

        temp_seg = Path(self.config.get("TEMP_SEGMENTS_DIR", "temp_segments"))
        seg_count = 0
        if temp_seg.exists():
            seg_count = sum(1 for f in temp_seg.iterdir()
                          if f.is_file() and f.suffix.lower() in {".mp4", ".mov", ".avi"})

        status = f"Status\n\n"
        status += f"📸 Photos:\n  In queue: {total}\n  Posted: {posted}\n"
        status += f"\n🎬 Reels:\n  In queue: {video_count}\n  Processed: {reel_count}\n  Segments pending: {seg_count}\n"
        if self.is_posting_photo:
            status += "\n📸 Currently posting photo..."
        if self.is_posting_reel:
            status += "\n🎬 Currently posting reel..."
        QMessageBox.information(None, "Instagram Auto-Poster", status)

    def post_photo_now(self):
        if self.is_posting_photo:
            QMessageBox.information(None, "Busy", "A photo post is already in progress.")
            return
        self.run_photo_poster(force=True)

    def post_reel_now(self):
        if self.is_posting_reel:
            QMessageBox.information(None, "Busy", "A reel post is already in progress.")
            return
        self.run_reels_poster(force=True)

    def run_photo_poster(self, force=False):
        if self.is_posting_photo:
            return
        self.is_posting_photo = True
        self._update_tooltip()
        self.tray.showMessage(
            "Instagram Auto-Poster",
            "📸 Starting photo analysis...",
            QSystemTrayIcon.MessageIcon.Information, 5000
        )

        cmd = [VENV_PYTHON, POSTER_SCRIPT]
        if force:
            cmd.append("--force")

        self.photo_process = QProcess(self)
        self.photo_process.setWorkingDirectory(str(APP_DIR))
        self.photo_process.finished.connect(self._on_photo_finished)
        self.photo_process.start(cmd[0], cmd[1:])

    def run_reels_poster(self, force=False):
        if self.is_posting_reel:
            return
        self.is_posting_reel = True
        self._update_tooltip()
        self.tray.showMessage(
            "Instagram Auto-Poster",
            "🎬 Starting reel processing...",
            QSystemTrayIcon.MessageIcon.Information, 5000
        )

        cmd = [VENV_PYTHON, REELS_POSTER_SCRIPT]
        if force:
            cmd.append("--force")

        self.reel_process = QProcess(self)
        self.reel_process.setWorkingDirectory(str(APP_DIR))
        self.reel_process.finished.connect(self._on_reel_finished)
        self.reel_process.start(cmd[0], cmd[1:])

    def _on_photo_finished(self, exit_code, exit_status):
        self.is_posting_photo = False
        self._update_tooltip()
        self.popup.refresh_data()

        if exit_code == 0:
            self.tray.showMessage(
                "Instagram Auto-Poster",
                "📸 Photo uploaded to Instagram!",
                QSystemTrayIcon.MessageIcon.Information, 8000
            )
            min_h = int(self.config.get("MIN_INTERVAL_HOURS", "5"))
            max_h = int(self.config.get("MAX_INTERVAL_HOURS", "7"))
            wait_h = calculate_wait(min_h, max_h)
            self._save_next_photo_time(wait_h)
            self.photo_timer.start(int(wait_h * 3600 * 1000))
            next_dt = datetime.now() + timedelta(hours=wait_h)
            next_str = next_dt.strftime("%B %d at %I:%M %p")
            self.tray.showMessage(
                "Instagram Auto-Poster",
                f"Next photo: {next_str}",
                QSystemTrayIcon.MessageIcon.Information, 5000
            )
        elif exit_code == 2:
            # Silent - no popup for empty folder
            self._save_next_photo_time(1.0)
            self.photo_timer.start(60 * 60 * 1000)
        else:
            self.tray.showMessage(
                "Instagram Auto-Poster",
                "📸 Photo post failed - will retry in 30 min",
                QSystemTrayIcon.MessageIcon.Warning, 5000
            )
            self._save_next_photo_time(0.5)
            self.photo_timer.start(30 * 60 * 1000)

    def _on_reel_finished(self, exit_code, exit_status):
        self.is_posting_reel = False
        self._update_tooltip()
        self.popup.refresh_data()

        if exit_code == 0:
            self.tray.showMessage(
                "Instagram Auto-Poster",
                "🎬 Reel uploaded to Instagram!",
                QSystemTrayIcon.MessageIcon.Information, 8000
            )
            min_h = int(self.config.get("REEL_MIN_INTERVAL_HOURS", "4"))
            max_h = int(self.config.get("REEL_MAX_INTERVAL_HOURS", "8"))
            wait_h = calculate_wait(min_h, max_h)
            self._save_next_reel_time(wait_h)
            self.reel_timer.start(int(wait_h * 3600 * 1000))
            next_dt = datetime.now() + timedelta(hours=wait_h)
            next_str = next_dt.strftime("%B %d at %I:%M %p")
            self.tray.showMessage(
                "Instagram Auto-Poster",
                f"Next reel: {next_str}",
                QSystemTrayIcon.MessageIcon.Information, 5000
            )
        elif exit_code == 2:
            # Silent - no popup for empty folder
            self._save_next_reel_time(1.0)
            self.reel_timer.start(60 * 60 * 1000)
        else:
            self.tray.showMessage(
                "Instagram Auto-Poster",
                "🎬 Reel post failed - will retry in 30 min",
                QSystemTrayIcon.MessageIcon.Warning, 5000
            )
            self._save_next_reel_time(0.5)
            self.reel_timer.start(30 * 60 * 1000)


if __name__ == "__main__":
    app = TrayApp(sys.argv)
    sys.exit(app.exec())
