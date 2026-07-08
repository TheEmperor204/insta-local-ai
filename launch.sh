#!/bin/bash
cd "$(dirname "$0")"
if [ -f firejail.profile ] && command -v firejail &>/dev/null; then
    exec firejail --profile="$(pwd)/firejail.profile" ./insta-env/bin/python tray_app.py
else
    exec ./insta-env/bin/python tray_app.py
fi
