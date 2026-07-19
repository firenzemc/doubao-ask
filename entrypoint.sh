#!/bin/bash
# doubao-ask container entrypoint: Xvfb + Chromium (Browser Bridge ext) + API wrapper.
set -u

export DISPLAY=:99
PROFILE_DIR="${CHROME_PROFILE_DIR:-/data/chrome-profile}"
EXT_DIR=/opt/opencli-extension
PORT="${PORT:-8080}"

mkdir -p "$PROFILE_DIR"

Xvfb :99 -screen 0 1440x900x24 &
XVFB_PID=$!

# Chromium supervision loop: restart if it crashes/exits.
(
  while true; do
    chromium \
      --no-sandbox \
      --disable-dev-shm-usage \
      --disable-gpu \
      --disable-software-rasterizer \
      --no-first-run \
      --no-default-browser-check \
      --disable-session-crashed-bubble \
      --hide-crash-restore-bubble \
      --user-data-dir="$PROFILE_DIR" \
      --load-extension="$EXT_DIR" \
      --disable-extensions-except="$EXT_DIR" \
      --window-size=1440,900 \
      --start-maximized \
      https://www.doubao.com/chat >/var/log/chromium.log 2>&1
    echo "[entrypoint] chromium exited ($?), restarting in 5s" >&2
    sleep 5
  done
) &

# Give the browser a head start so the extension can connect when the
# opencli daemon comes up on first use.
sleep 5

exec uvicorn app:app --host 0.0.0.0 --port "$PORT"
