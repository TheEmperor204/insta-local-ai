#!/bin/bash
# ================================================================
#  Insta Local AI - Installer
#  Requirements: Linux, Python 3.10+, Ollama, ffmpeg
# ================================================================

set -e

echo "============================================"
echo "  Insta Local AI - Installer"
echo "============================================"
echo ""

# Get script directory
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# --- 1. Create virtual environment ---
echo "[1/7] Creating virtual environment..."
python3 -m venv insta-env
source insta-env/bin/activate
pip install --upgrade pip

# --- 2. Install packages ---
echo "[2/7] Installing Python packages..."
pip install -r requirements.txt

# --- 3. Check for ffmpeg ---
echo "[3/7] Checking ffmpeg..."
if ! command -v ffmpeg &>/dev/null; then
echo "  WARNING: ffmpeg not found. Install it for video/music features."
echo "  Ubuntu/Debian: sudo apt install ffmpeg"
echo "  Arch: sudo pacman -S ffmpeg"
else
echo "  ffmpeg found: $(ffmpeg -version | head -1)"
fi

# --- 4. Check for Ollama ---
echo "[4/7] Checking Ollama..."
if ! command -v ollama &>/dev/null; then
echo "  WARNING: Ollama not found. Install from https://ollama.com"
echo "  After installing, run: ollama pull llava:7b && ollama pull qwen2.5:7b"
else
echo "  Ollama found: $(ollama --version)"
# --- 5. Pull models ---
echo "[5/7] Pulling AI models (this may take a while)..."
if ! ollama list | grep -q "llava:7b"; then
echo "  Pulling llava:7b (vision model, ~4.7GB)..."
ollama pull llava:7b
else
echo "  llava:7b already installed"
fi
if ! ollama list | grep -q "qwen2.5:7b"; then
echo "  Pulling qwen2.5:7b (caption model, ~4.7GB)..."
ollama pull qwen2.5:7b
else
echo "  qwen2.5:7b already installed"
fi
fi

# --- 6. Create directories ---
echo "[6/7] Creating directories..."
mkdir -p images_to_post posted_images
mkdir -p videos_to_upload insta_posted_youtube_ready
mkdir -p temp_segments explicit_videos
mkdir -p duplicates video_duplicates
mkdir -p Default_Music Adventure_Music Action_Sport_Music

# --- 7. Create config if not exists ---
echo "[7/7] Creating default config..."
if [ ! -f .env ]; then
cp .env.example .env
echo "  Created .env from .env.example"
else
echo "  .env already exists, skipping"
fi

# --- Copy default persona if not exists ---
if [ ! -f caption_persona.py ]; then
cp caption_persona.example.py caption_persona.py
echo "  Created caption_persona.py from example"
else
echo "  caption_persona.py already exists, skipping"
fi

# --- Autostart setup ---
if [ -d "$HOME/.config/autostart" ] || mkdir -p "$HOME/.config/autostart"; then
mkdir -p "$HOME/.local/bin"
cat << WRAPEOF > "$HOME/.local/bin/insta-poster-launch.sh"
#!/bin/bash
cd "SCRIPT_DIR_PLACEHOLDER"
exec ./launch.sh
WRAPEOF
sed -i "s|SCRIPT_DIR_PLACEHOLDER|$SCRIPT_DIR|" "$HOME/.local/bin/insta-poster-launch.sh"
chmod +x "$HOME/.local/bin/insta-poster-launch.sh"

cat << DESKTOPEOF > "$HOME/.config/autostart/insta-poster.desktop"
[Desktop Entry]
Type=Application
Exec=HOMEBIN_PLACEHOLDER/insta-poster-launch.sh
StartupNotify=false
X-KDE-autostart-after=panel
Hidden=false
Name=Insta Local AI
DESKTOPEOF
sed -i "s|HOMEBIN_PLACEHOLDER|$HOME/.local/bin|" "$HOME/.config/autostart/insta-poster.desktop"
echo "  Autostart configured!"
fi

# --- Firejail ---
if command -v firejail &>/dev/null; then
echo "  Firejail detected - sandbox will be active"
chmod +x launch.sh firejail.profile
else
echo "  Firejail not found - app will run unsandboxed"
echo "  Install with: sudo pacman -S firejail  (or your distro equivalent)"
fi

deactivate

echo ""
echo "============================================"
echo "  Installation complete!"
echo "============================================"
echo ""
echo "  Next steps:"
echo "    1. Launch the app: ./launch.sh"
echo "    2. Open Settings tab, enter your Instagram username"
echo "    3. Enter your Instagram password (stored in system keyring)"
echo "    4. Optionally set up phone notifications (ntfy topic)"
echo "    5. Drop images in images_to_post/ and videos in videos_to_upload/"
echo "    6. Dry Run mode is ON by default - test before going live"
echo ""
echo "  Manual launch: ./launch.sh"
echo ""
