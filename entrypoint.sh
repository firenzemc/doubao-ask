#!/bin/bash
# doubao-ask container entrypoint: Xvfb + Chromium (Browser Bridge ext) + API wrapper.
# Both Xvfb and Chromium run under restart loops; everything logs to stdout
# so `vin logs doubao-ask` shows the full picture.
set -u

export DISPLAY=:99
PROFILE_DIR="${CHROME_PROFILE_DIR:-/data/chrome-profile}"
EXT_DIR=/opt/opencli-extension
PORT="${PORT:-8080}"

mkdir -p "$PROFILE_DIR"

# Stale singleton locks survive in the persisted volume whenever a previous
# container didn't shut down cleanly — and Chromium refuses to start at all
# ("profile in use ... on another computer", since the hostname changed).
# Exactly one chromium ever uses this profile, so dropping the locks is safe.
rm -f "$PROFILE_DIR/SingletonLock" "$PROFILE_DIR/SingletonSocket" "$PROFILE_DIR/SingletonCookie"

(
  while true; do
    Xvfb :99 -screen 0 1440x900x24 2>&1 | sed 's/^/[xvfb] /'
    echo "[entrypoint] Xvfb exited ($?), restarting in 3s" >&2
    sleep 3
  done
) &

# Wait for the X display before launching Chromium.
sleep 2

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
      --disable-crash-reporter \
      --user-data-dir="$PROFILE_DIR" \
      --load-extension="$EXT_DIR" \
      --disable-extensions-except="$EXT_DIR" \
      --window-size=1440,900 \
      --start-maximized \
      https://www.doubao.com/chat 2>&1 | sed 's/^/[chromium] /'
    echo "[entrypoint] chromium exited ($?), restarting in 5s" >&2
    sleep 5
  done
) &

# Give the browser a head start so the extension can connect when the
# opencli daemon comes up on first use.
sleep 5

exec uvicorn app:app --host 0.0.0.0 --port "$PORT"
