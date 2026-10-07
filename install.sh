#!/usr/bin/env bash
# Installs the audio tools, a Python venv with pychromecast and a `sinkcast` command in ~/.local/bin
set -euo pipefail
cd "$(dirname "$(readlink -f "$0")")"

if command -v apt-get >/dev/null; then
    sudo apt-get install -y python3-venv pulseaudio-utils flac lame
elif command -v dnf >/dev/null; then
    sudo dnf install -y python3 pulseaudio-utils flac lame
elif command -v pacman >/dev/null; then
    sudo pacman -S --needed --noconfirm python libpulse flac lame
elif command -v zypper >/dev/null; then
    sudo zypper install -y python3 pulseaudio-utils flac lame
else
    echo "Unknown package manager - install pactl/parec, flac and lame yourself." >&2
fi

python3 -m venv .venv
.venv/bin/pip install -q -r requirements.txt

mkdir -p ~/.local/bin
cat > ~/.local/bin/sinkcast <<WRAPPER
#!/bin/sh
exec "$PWD/.venv/bin/python" "$PWD/sinkcast.py" "\$@"
WRAPPER
chmod +x ~/.local/bin/sinkcast
echo "Done. Try: sinkcast --list   (make sure ~/.local/bin is in your PATH)"
