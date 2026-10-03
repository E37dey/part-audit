#!/bin/bash
# PartAudit - start (Linux). First run installs a private Python environment (internet, a few minutes).
cd "$(dirname "$0")" || exit 1
VENV="${XDG_DATA_HOME:-$HOME/.local/share}/partaudit/venv"
fail() { echo; echo "The installation did not finish. Check the internet connection and run this file again."; read -r -p "Press Enter to close"; exit 1; }

export PATH="$HOME/.local/bin:$PATH"
if ! command -v uv >/dev/null 2>&1; then
  echo "First run: installing uv, a small Python installer from astral.sh ..."
  curl -LsSf https://astral.sh/uv/install.sh | sh || fail
  export PATH="$HOME/.local/bin:$PATH"
fi
if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating the PartAudit environment ..."
  uv venv --clear "$VENV" --python 3.12 || uv venv "$VENV" --python 3.12 || uv venv "$VENV" || fail
fi
if ! cmp -s requirements.txt "$VENV/requirements.installed"; then
  echo "Installing PartAudit components - about 150 MB, only on the first run ..."
  uv pip install --python "$VENV/bin/python" -r requirements.txt || fail
  cp requirements.txt "$VENV/requirements.installed"
fi
echo
echo "PartAudit is starting. The browser opens by itself."
echo "Keep this window open while you work; close it to stop PartAudit."
exec "$VENV/bin/python" -m part_audit app "$@"
