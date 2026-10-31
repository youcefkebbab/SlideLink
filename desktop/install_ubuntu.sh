#!/usr/bin/env bash
# SlideLink Desktop – Ubuntu installer. Run once:  bash install_ubuntu.sh
set -e
cd "$(dirname "$0")"
echo "Installing system packages (asks for your password once)..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-venv python3-tk bluez vlc libgirepository1.0-dev >/dev/null
sudo systemctl enable --now bluetooth || true
sudo rfkill unblock bluetooth || true
python3 -m venv .venv
.venv/bin/pip install -q --upgrade pip
.venv/bin/pip install -q -r requirements.txt
mkdir -p ~/.local/share/applications
cat > ~/.local/share/applications/slidelink.desktop <<EOT
[Desktop Entry]
Type=Application
Name=SlideLink
Exec=$PWD/.venv/bin/python $PWD/run.py
Path=$PWD
Terminal=false
Categories=Utility;
EOT
echo "Done! Open 'SlideLink' from your applications menu. Starting now..."
if [ "$XDG_SESSION_TYPE" = "wayland" ]; then
  echo "NOTE: You are on Wayland. Keystrokes to OTHER apps (PowerPoint/Okular...) may be blocked."
  echo "      The built-in PDF presenter and VLC still work. For other apps choose 'Ubuntu on Xorg' at login."
fi
nohup .venv/bin/python run.py >/dev/null 2>&1 &
