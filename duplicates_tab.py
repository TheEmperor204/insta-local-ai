"""
DuplicatesTab — GUI widget for reviewing suspected duplicate images.
Users can confirm (keep skipped) or reject (move back to posting queue).
"""
import json
import shutil
from pathlib import Path
from datetime import datetime
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QScrollArea, QFrame
)
from PyQt6.QtCore import Qt


class DuplicatesTab(QWidget):
    def __init__(self, project_root=None):
        super().__init__()
        if project_root:
            self.root = Path(project_root)
        else:
            self.root = Path(__file__).resolve().parent

        self.json_path = self.root / "posted_images.json"
        self.images_folder = self.root / "images_to_post"
        self.duplicates_folder = self.root / "duplicates"

        layout = QVBoxLayout(self)

        title = QLabel("Duplicate Review")
        title.setStyleSheet("font-size: 14px; font-weight: bold; color: #6d4aff;")
        layout.addWidget(title)

        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self.refresh)
        layout.addWidget(refresh_btn)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll_content = QWidget()
        self.scroll_layout = QVBoxLayout(self.scroll_content)
        self.scroll.setWidget(self.scroll_content)
        layout.addWidget(self.scroll)

        self.refresh()

    def load_json(self):
        if not self.json_path.exists():
            return {}
        try:
            with open(self.json_path) as f:
                return json.load(f)
        except Exception:
            return {}

    def save_json(self, data):
        with open(self.json_path, "w") as f:
            json.dump(data, f, indent=2)

    def refresh(self):
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        data = self.load_json()
        pending = [d for d in data.get("pending_duplicates", []) if d.get("status") == "pending"]

        if not pending:
            label = QLabel("No pending duplicates to review")
            label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            label.setStyleSheet("color: #888; padding: 20px;")
            self.scroll_layout.addWidget(label)
            self.scroll_layout.addStretch()
            return

        for dup in pending:
            card = self._make_card(dup, data)
            self.scroll_layout.addWidget(card)

        self.scroll_layout.addStretch()

    def _make_card(self, dup, data):
        frame = QFrame()
        frame.setFrameShape(QFrame.Shape.Box)
        frame.setStyleSheet(
            "QFrame { border: 1px solid #ccc; border-radius: 8px; padding: 10px; margin: 4px; }"
        )
        vlay = QVBoxLayout(frame)

        img_path = dup.get("image_path", "")
        img_name = Path(img_path).name if img_path else "Unknown"

        name_lbl = QLabel(f" {img_name}")
        name_lbl.setStyleSheet("font-weight: bold; font-size: 13px;")
        vlay.addWidget(name_lbl)

        detected = dup.get("detected_at", "?")[:19]
        orig_date = dup.get("original_posted_at", "?")[:19]
        orig_cap = dup.get("original_caption", "")

        info = QLabel(f"Detected: {detected}\nOriginally posted: {orig_date}\nOriginal caption preview: {orig_cap}")
        info.setStyleSheet("color: #666; font-size: 11px;")
        info.setWordWrap(True)
        vlay.addWidget(info)

        fp = dup.get("fingerprint", {})
        if fp:
            exif = fp.get("exif", {})
            cam = f"{exif.get('Make', '').strip()} {exif.get('Model', '').strip()}".strip()
            fp_txt = (
                f"File size: {fp.get('file_size', '?'):,} bytes\n"
                f"Dimensions: {fp.get('dimensions', '?')}\n"
                f"MD5: {fp.get('md5', '?')[:20]}...\n"
                f"Camera: {cam or 'N/A'}\n"
                f"Date taken: {exif.get('DateTimeOriginal', 'N/A')}"
            )
            fp_lbl = QLabel(fp_txt)
            fp_lbl.setStyleSheet("color: #999; font-size: 10px; font-family: monospace;")
            fp_lbl.setWordWrap(True)
            vlay.addWidget(fp_lbl)

        btn_row = QHBoxLayout()

        confirm_btn = QPushButton("Confirm Duplicate")
        confirm_btn.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 8px; "
            "border-radius: 4px; font-weight: bold;"
        )
        confirm_btn.clicked.connect(lambda _, d=dup: self._confirm(d))

        reject_btn = QPushButton("Not Duplicate — Re-queue")
        reject_btn.setStyleSheet(
            "background-color: #6d4aff; color: white; padding: 8px; "
            "border-radius: 4px; font-weight: bold;"
        )
        reject_btn.clicked.connect(lambda _, d=dup: self._reject(d))

        btn_row.addWidget(confirm_btn)
        btn_row.addWidget(reject_btn)
        vlay.addLayout(btn_row)

        return frame

    def _confirm(self, dup):
        data = self.load_json()
        img_path = dup.get("image_path", "")

        for d in data.get("pending_duplicates", []):
            if d.get("image_path") == img_path:
                d["status"] = "confirmed"
                d["confirmed_at"] = datetime.now().isoformat()
                break

        orig_path = dup.get("original_path", "")
        if orig_path in data.get("posted", {}):
            data["posted"][orig_path]["status"] = "confirmed_duplicate"
            data["posted"][orig_path]["caption"] = "[CONFIRMED DUPLICATE — skipped]"

        self.save_json(data)
        self.refresh()

    def _reject(self, dup):
        data = self.load_json()
        img_path = dup.get("image_path", "")
        orig_path = dup.get("original_path", "")

        if Path(img_path).exists():
            self.images_folder.mkdir(parents=True, exist_ok=True)
            dest = self.images_folder / Path(img_path).name
            counter = 1
            while dest.exists():
                stem = Path(img_path).stem
                suffix = Path(img_path).suffix
                dest = self.images_folder / f"{stem}_{counter}{suffix}"
                counter += 1
            shutil.move(str(img_path), str(dest))

        data["pending_duplicates"] = [
            d for d in data.get("pending_duplicates", [])
            if d.get("image_path") != img_path
        ]

        if orig_path in data.get("posted", {}):
            del data["posted"][orig_path]

        self.save_json(data)
        self.refresh()
