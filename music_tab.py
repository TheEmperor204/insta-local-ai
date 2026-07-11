#!/usr/bin/env python3
import json
from pathlib import Path
from PyQt6.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel, QCheckBox, QComboBox, QSpinBox, QPushButton, QGroupBox, QMessageBox, QFileDialog)
from PyQt6.QtCore import Qt

APP_DIR = Path(__file__).parent.resolve()
CONFIG_FILE = APP_DIR / "music_config.json"

CATEGORIES = ["default", "adventure", "action_sport"]

DEFAULT_CONFIG = {
    "enabled": False, "mode": "all",
    "categories": {
        "default": {"folder": str(APP_DIR / "Default_Music"), "word_count": 5, "volume": 50, "clip_mode": "highlight", "song_selection": "random", "specific_song": ""},
        "adventure": {"folder": str(APP_DIR / "Adventure_Music"), "word_count": 5, "volume": 50, "clip_mode": "highlight", "song_selection": "random", "specific_song": ""},
        "action_sport": {"folder": str(APP_DIR / "Action_Sport_Music"), "word_count": 5, "volume": 50, "clip_mode": "highlight", "song_selection": "random", "specific_song": ""}
    }
}

def load_config():
    if CONFIG_FILE.exists():
        try:
            cfg = json.loads(CONFIG_FILE.read_text())
            for k in DEFAULT_CONFIG:
                if k not in cfg: cfg[k] = DEFAULT_CONFIG[k]
            for cat in CATEGORIES:
                if cat not in cfg["categories"]: cfg["categories"][cat] = DEFAULT_CONFIG["categories"][cat]
            return cfg
        except Exception:
            pass
    return json.loads(json.dumps(DEFAULT_CONFIG))

def save_config(cfg):
    CONFIG_FILE.write_text(json.dumps(cfg, indent=2))

class MusicTab(QWidget):
    def __init__(self):
        super().__init__()
        self.config = load_config()
        self.current_category = "default"
        self.init_ui()

    def init_ui(self):
        layout = QVBoxLayout(self)
        
        # === GLOBAL SETTINGS ===
        grp_global = QGroupBox('Global Music Settings')
        gl = QVBoxLayout(grp_global)
        
        cb = QHBoxLayout()
        self.enable_cb = QCheckBox('Enable music overlay')
        self.enable_cb.setChecked(self.config.get('enabled', False))
        cb.addWidget(self.enable_cb)
        cb.addStretch()
        gl.addLayout(cb)
        
        # Mode
        mlbl = QLabel('Music mode:')
        gl.addWidget(mlbl)
        self.mode_cb = QComboBox()
        self.mode_cb.addItem('All videos', 'all')
        self.mode_cb.addItem('Only videos without talking', 'no_talking')
        idx = self.mode_cb.findData(self.config.get('mode', 'all'))
        if idx >= 0: self.mode_cb.setCurrentIndex(idx)
        gl.addWidget(self.mode_cb)
        
        # Min word count
        
        layout.addWidget(grp_global)

        # === CATEGORY SETTINGS ===
        self.grp_cat = QGroupBox('Category Settings')
        cl = QVBoxLayout(self.grp_cat)
        
        # Category selector
        cs = QHBoxLayout()
        cs.addWidget(QLabel('Editing category:'))
        self.cat_cb = QComboBox()
        for c in CATEGORIES:
            self.cat_cb.addItem(c.replace('_', ' ').title(), c)
        self.cat_cb.currentIndexChanged.connect(self.on_category_change)
        cs.addWidget(self.cat_cb)
        cl.addLayout(cs)
        
        # Folder selection
        fl = QHBoxLayout()
        fl.addWidget(QLabel('Music folder:'))
        self.folder_lbl = QLabel('')
        self.folder_lbl.setStyleSheet('color: #aaa; font-size: 11px;')
        fl.addWidget(self.folder_lbl, 1)
        btn_browse = QPushButton('Browse...')
        btn_browse.clicked.connect(self.browse_folder)
        fl.addWidget(btn_browse)
        cl.addLayout(fl)
        
        # Song selection
        sl = QHBoxLayout()
        sl.addWidget(QLabel('Song selection:'))
        self.song_cb = QComboBox()
        self.song_cb.addItem('Random', 'random')
        self.song_cb.addItem('Specific song', 'specific')
        self.song_cb.currentIndexChanged.connect(self.on_song_mode_change)
        sl.addWidget(self.song_cb)
        cl.addLayout(sl)
        
        # Specific song dropdown
        ssl = QHBoxLayout()
        ssl.addWidget(QLabel('Select song:'))
        self.specific_cb = QComboBox()
        ssl.addWidget(self.specific_cb, 1)
        cl.addLayout(ssl)
        
        # Volume
        vl = QHBoxLayout()
        vl.addWidget(QLabel('Volume:'))
        self.vol_cb = QComboBox()
        for i in [10,20,30,40,50,60,70,80,90,100]:
            self.vol_cb.addItem(str(i) + '%', i)
        vl.addWidget(self.vol_cb)
        cl.addLayout(vl)
        
        # Clip mode
        cml = QHBoxLayout()
        cml.addWidget(QLabel('Clip start:'))
        self.clip_cb = QComboBox()
        self.clip_cb.addItem('Beginning', 'beginning')
        self.clip_cb.addItem('Highlight (middle to chorus)', 'highlight')
        cml.addWidget(self.clip_cb)
        cl.addLayout(cml)
        
        wcl = QHBoxLayout()
        wcl.addWidget(QLabel("Word count threshold:"))
        self.word_spin = QSpinBox()
        self.word_spin.setRange(1, 50)
        wcl.addWidget(self.word_spin)
        cl.addLayout(wcl)

        layout.addWidget(self.grp_cat)

        # Save button
        layout.addStretch()
        btnsave = QPushButton('Save Settings')
        btnsave.clicked.connect(self.save_settings)
        layout.addWidget(btnsave)
        
        self.load_category_settings()
    
    def on_category_change(self):
        cat = self.cat_cb.currentData()
        if cat:
            self.current_category = cat
            self.load_category_settings()
    
    def load_category_settings(self):
        cc = self.config['categories'][self.current_category]
        self.folder_lbl.setText(cc.get('folder', ''))
        idx = self.song_cb.findData(cc.get('song_selection', 'random'))
        if idx >= 0: self.song_cb.setCurrentIndex(idx)
        self.refresh_song_list()
        vi = self.vol_cb.findData(cc.get('volume', 50))
        if vi >= 0: self.vol_cb.setCurrentIndex(vi)
        ci = self.clip_cb.findData(cc.get('clip_mode', 'highlight'))
        self.word_spin.setValue(cc.get("word_count", 5))
        if ci >= 0: self.clip_cb.setCurrentIndex(ci)
    
    def refresh_song_list(self):
        self.specific_cb.clear()
        folder = Path(self.folder_lbl.text())
        exts = {'.mp3', '.wav', '.m4a', '.flac', '.ogg', '.aac'}
        if folder.exists():
            songs = [f.name for f in folder.iterdir() if f.is_file() and f.suffix.lower() in exts]
            for s in sorted(songs):
                self.specific_cb.addItem(s)
        cc = self.config['categories'][self.current_category]
        si = self.specific_cb.findText(cc.get('specific_song', ''))
        if si >= 0: self.specific_cb.setCurrentIndex(si)
    
    def browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Select Music Folder')
        if folder:
            self.folder_lbl.setText(folder)
            self.refresh_song_list()
    
    def on_song_mode_change(self):
        is_specific = self.song_cb.currentData() == 'specific'
        self.specific_cb.setEnabled(is_specific)
    
    def save_settings(self):
        self.config['enabled'] = self.enable_cb.isChecked()
        self.config['mode'] = self.mode_cb.currentData()
        cc = self.config['categories'][self.current_category]
        cc['folder'] = self.folder_lbl.text()
        cc['volume'] = self.vol_cb.currentData()
        cc['clip_mode'] = self.clip_cb.currentData()
        cc['word_count'] = self.word_spin.value()
        cc['song_selection'] = self.song_cb.currentData()
        cc['specific_song'] = self.specific_cb.currentText() if self.song_cb.currentData() == 'specific' else ''
        save_config(self.config)
        QMessageBox.information(self, 'Saved', 'Music settings saved!')
