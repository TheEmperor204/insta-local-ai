#!/usr/bin/env python3
import json
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QSpinBox, QPushButton, QGroupBox, QMessageBox, QLineEdit, QTimeEdit)
from PyQt6.QtCore import Qt, QTime
from schedule_manager import load_schedule_config, save_schedule_config

class ScheduleTab(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_schedule_config()
        layout = QVBoxLayout(self)

        # Master toggle
        self.sched_cb = QCheckBox("Enable Time Window Scheduling")
        self.sched_cb.setChecked(self.config.get("scheduling_enabled", False))
        layout.addWidget(self.sched_cb)

        self.random_cb = QCheckBox("Enable Random Interval (adds randomness to wait times)")
        self.random_cb.setChecked(self.config.get("random_interval_enabled", True))
        layout.addWidget(self.random_cb)

        # Time windows group
        wg = QGroupBox("Time Windows")
        wg_layout = QVBoxLayout(wg)
        self.window_widgets = []
        for i, w in enumerate(self.config.get("time_windows", [])):
            row = QHBoxLayout()
            en_cb = QCheckBox(w.get("name", "Window"))
            en_cb.setChecked(w.get("enabled", True))
            row.addWidget(en_cb)
            name_edit = QLineEdit(w.get("name", ""))
            name_edit.setMaximumWidth(100)
            row.addWidget(QLabel("Name:"))
            row.addWidget(name_edit)
            start_te = QTimeEdit(QTime(int(w["start"].split(":")[0]), int(w["start"].split(":")[1])))
            start_te.setDisplayFormat("HH:mm")
            row.addWidget(QLabel("Start:"))
            row.addWidget(start_te)
            end_te = QTimeEdit(QTime(int(w["end"].split(":")[0]), int(w["end"].split(":")[1])))
            end_te.setDisplayFormat("HH:mm")
            row.addWidget(QLabel("End:"))
            row.addWidget(end_te)
            row.addStretch()
            wg_layout.addLayout(row)
            self.window_widgets.append((en_cb, name_edit, start_te, end_te))
        wg.setLayout(wg_layout)
        layout.addWidget(wg)

        # Status
        from schedule_manager import get_next_post_description
        self.status_lbl = QLabel(get_next_post_description())
        layout.addWidget(self.status_lbl)

        layout.addStretch()
        btn = QPushButton("Save Schedule Settings")
        btn.clicked.connect(self.save)
        layout.addWidget(btn)

    def save(self):
        self.config["scheduling_enabled"] = self.sched_cb.isChecked()
        self.config["random_interval_enabled"] = self.random_cb.isChecked()
        new_windows = []
        for en_cb, name_edit, start_te, end_te in self.window_widgets:
            new_windows.append({
                "name": name_edit.text() or "Window",
                "start": start_te.time().toString("HH:mm"),
                "end": end_te.time().toString("HH:mm"),
                "enabled": en_cb.isChecked()
            })
        self.config["time_windows"] = new_windows
        save_schedule_config(self.config)
        from schedule_manager import get_next_post_description
        self.status_lbl.setText(get_next_post_description())
        QMessageBox.information(self, "Saved", "Schedule settings saved!")
