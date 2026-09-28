#!/bin/zsh
# Start the AntHosting preview server fully detached from any shell session.
#
# Background jobs launched from a terminal die with that terminal -- which is
# why the preview URLs stop resolving after an agent/shell session exits.
# daemonize.py double-forks + setsid so the server is re-parented to launchd
# (PPID 1) and keeps serving.
#
# usage: ./start-persistent.sh [port]      (default 4173)
set -e
PORT="${1:-4173}"
HERE="${0:A:h}"                       # directory containing this script
ROOT="${ANTHOSTING_ROOT:-${HERE:h}}"

# Python: prefer the venv that has the QA deps, else any python3.  serve.py
# itself is pure stdlib, so the fallback is fine for previewing.
for cand in "${HERE:h}/../work/.venv/bin/python" \
            "$ROOT/work/.venv/bin/python" \
            "$(command -v python3)"; do
  [[ -x "${~cand}" ]] && PY="${~cand}" && break
done
[[ -n "$PY" ]] || { echo "no python3 found" >&2; exit 1 }

PIDFILE="/tmp/anthosting-preview-$PORT.pid"
LOGFILE="/tmp/anthosting-preview-$PORT.log"

# Free the port: kill whatever is listening, then the last pid we recorded.
lsof -nP -iTCP:"$PORT" -sTCP:LISTEN -t 2>/dev/null | xargs -I{} kill {} 2>/dev/null || true
sleep 0.5
[[ -f "$PIDFILE" ]] && kill "$(cat "$PIDFILE")" 2>/dev/null || true
: > "$LOGFILE"

cd "$HERE"
"$PY" daemonize.py "$PIDFILE" "$LOGFILE" "$PY" serve.py "$PORT"

for i in {1..20}; do
  sleep 0.4
  if curl -s -o /dev/null --max-time 3 "http://127.0.0.1:$PORT/"; then
    echo "OK  http://127.0.0.1:$PORT/  pid $(cat "$PIDFILE" 2>/dev/null)  log $LOGFILE"
    exit 0
  fi
done

echo "FAILED to start on port $PORT -- log:" >&2
cat "$LOGFILE" >&2
exit 1
