#!/usr/bin/env python3
import json
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QListWidget, QListWidgetItem
from PyQt6.QtCore import Qt, QTimer

PROGRESS_FILE = Path(__file__).parent.resolve() / "progress_status.json"
VIDEOS_FOLDER = Path(__file__).parent.resolve() / "videos_to_upload"

STAGE_ICONS = {"analyzing":"🔍","quarantined":"🚫","frames":"🎬","transcribing":"🎙️","bleeping":"🔇","captioning":"✍️","posted":"✅","error":"❌"}
STAGE_COLORS = {"analyzing":"#3498db","quarantined":"#e74c3c","frames":"#9b59b6","transcribing":"#f39c12","bleeping":"#e67e22","captioning":"#1abc9c","posted":"#27ae60","error":"#c0392b"}

class ProgressTab(QWidget):
    def __init__(self):
        super().__init__()
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(8, 8, 8, 8)
        sl = QLabel("CURRENT STATUS")
        sl.setStyleSheet("font-size: 12px; font-weight: bold; color: #666; margin-top: 10px;")
        self.layout.addWidget(sl)
        self.status_display = QLabel("Idle - no pipeline running")
        self.status_display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.status_display.setStyleSheet("font-size: 14px; color: #888; padding: 20px; border: 1px solid #444; border-radius: 4px;")
        self.status_display.setMinimumHeight(60)
        self.layout.addWidget(self.status_display)
        tl = QLabel("TIMING")
        tl.setStyleSheet("font-size: 12px; font-weight: bold; color: #666; margin-top: 10px;")
        self.layout.addWidget(tl)
        self.times_display = QLabel("No timing data yet")
        self.times_display.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.times_display.setStyleSheet("font-size: 11px; color: #aaa; padding: 10px; border: 1px solid #444; border-radius: 4px;")
        self.times_display.setMinimumHeight(40)
        self.layout.addWidget(self.times_display)
        el = QLabel("ERRORS")
        el.setStyleSheet("font-size: 12px; font-weight: bold; color: #666; margin-top: 10px;")
        self.layout.addWidget(el)
        self.error_display = QLabel("No errors")
        self.error_display.setAlignment(Qt.AlignmentFlag.AlignLeft)
        self.error_display.setStyleSheet("font-size: 11px; color: #e74c3c; padding: 10px; border: 1px solid #444; border-radius: 4px;")
        self.error_display.setMinimumHeight(40)
        self.layout.addWidget(self.error_display)
        ql = QLabel("PENDING VIDEOS QUEUE")
        ql.setStyleSheet("font-size: 12px; font-weight: bold; color: #666; margin-top: 10px;")
        self.layout.addWidget(ql)
        self.queue_list = QListWidget()
        self.queue_list.setStyleSheet("QListWidget { border: 1px solid #444; border-radius: 4px; background-color: #1a1a2e; color: #eee; font-size: 11px; } QListWidget::item:selected { background-color: #4a4a6a; }")
        self.queue_list.itemDoubleClicked.connect(self.on_item_double_click)
        self.layout.addWidget(self.queue_list)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(2000)
        self.refresh()
    def on_item_double_click(self, item):
        vp = item.data(Qt.ItemDataRole.UserRole)
        if vp is None: return
        ss = self.format_size(vp.stat().st_size)
        dt = datetime.fromtimestamp(vp.stat().st_ctime).strftime("%Y-%m-%d %H:%M")
        msg = "Selected: " + vp.name + "\nSize: " + ss + "\nCreated: " + dt
        self.status_display.setText(msg)
        self.status_display.setStyleSheet("font-size: 11px; color: #bbb; padding: 15px; border: 1px solid #444; border-radius: 4px; text-align: left;")
    
    def format_size(self, sz):
        for u in ["B","KB","MB","GB"]:
            if sz < 1024: return str(round(sz,1)) + " " + u
            sz /= 1024
        return str(round(sz,1)) + " TB"
    
    def refresh(self):
        self.refresh_status_and_timing()
        self.refresh_queue()
    def refresh_status_and_timing(self):
        if PROGRESS_FILE.exists():
            try:
                data = json.loads(PROGRESS_FILE.read_text())
                stage = data.get("stage", "unknown")
                details = data.get("details", "")
                updated = data.get("updated_at", "")
                error_msg = data.get("error", "")
                stage_times = data.get("times", {})
                icon = STAGE_ICONS.get(stage, "X")
                color = STAGE_COLORS.get(stage, "#888")
                time_str = ""
                if updated:
                    try:
                        dt = datetime.fromisoformat(updated)
                        time_str = dt.strftime("%I:%M:%S %p")
                    except Exception:
                        time_str = updated
                html = "<div style=text-align:center>"
                html += "<span style=font-size:28px;>" + icon + "</span><br>"
                html += "<span style=font-size:16px;font-weight:bold;color:" + color + ";>" + stage.upper() + "</span><br>"
                html += "<span style=font-size:12px;color:#aaa;>" + details + "</span><br>"
                html += "<span style=font-size:11px;color:#666;>Updated: " + time_str + "</span></div>"
                self.status_display.setText(html)
                self.status_display.setTextFormat(Qt.TextFormat.RichText)
                self.status_display.setStyleSheet("padding: 20px; border: 1px solid #444; border-radius: 4px;")
                if stage_times:
                    lines = []
                    for s, t in stage_times.items():
                        lines.append(s + ": " + str(t) + "s")
                    self.times_display.setText(" | ".join(lines))
                else:
                    self.times_display.setText("No timing data yet")
                if error_msg:
                    self.error_display.setText("Warning: " + error_msg)
                    self.error_display.setStyleSheet("font-size: 11px; color: #e74c3c; padding: 10px; border: 1px solid #e74c3c; border-radius: 4px; font-weight: bold;")
                else:
                    self.error_display.setText("No errors")
                    self.error_display.setStyleSheet("font-size: 11px; color: #aaa; padding: 10px; border: 1px solid #444; border-radius: 4px;")
            except Exception:
                self.status_display.setText("Error reading progress")
                self.status_display.setStyleSheet("padding: 20px; border: 1px solid #444; border-radius: 4px;")
        else:
            self.status_display.setText("Idle - no pipeline running")
            self.status_display.setStyleSheet("font-size: 14px; color: #888; padding: 20px; border: 1px solid #444; border-radius: 4px;")
            self.times_display.setText("No timing data yet")
            self.error_display.setText("No errors")

    def refresh_queue(self):
        self.queue_list.clear()
        if VIDEOS_FOLDER.exists():
            try:
                videos = sorted([f for f in VIDEOS_FOLDER.iterdir() if f.is_file() and f.suffix.lower() in {".mp4", ".mov", ".avi", ".mkv", ".webm"}], key=lambda x: x.stat().st_mtime)
                if videos:
                    for v in videos:
                        item = QListWidgetItem()
                        item.setText(v.name + " (" + self.format_size(v.stat().st_size) + ")")
                        item.setData(Qt.ItemDataRole.UserRole, v)
                        self.queue_list.addItem(item)
                else:
                    item = QListWidgetItem("Queue empty - no videos waiting")
                    item.setFlags(Qt.ItemFlag.NoItemFlags)
                    self.queue_list.addItem(item)
            except Exception as e:
                item = QListWidgetItem("Error reading queue: " + str(e))
                item.setFlags(Qt.ItemFlag.NoItemFlags)
                self.queue_list.addItem(item)
        else:
            item = QListWidgetItem("Videos folder not found")
            item.setFlags(Qt.ItemFlag.NoItemFlags)
            self.queue_list.addItem(item)
