#!/bin/bash
# voice-en/run.sh {start|stop|restart|status}: the English narrator (Kokoro af_heart, voice-en/server.py) as a background program.
#
#   voice-en/run.sh start     start it (waits until it answers), safe to run twice
#   voice-en/run.sh stop      stop it
#   voice-en/run.sh restart   stop it, then start it again
#   voice-en/run.sh status    is it running, does it answer?
#
# It borrows VoiceStudio's Python (that already has mlx-audio) and the Kokoro model VoiceStudio cached; nothing is installed or
# downloaded (HF_HUB_OFFLINE=1). The program's process number lives in voice-en/server.pid and everything it prints in
# voice-en/server.log. It listens on 127.0.0.1:3911 only (this computer, nobody else).

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="${VOICE_EN_PYTHON:-$HOME/Library/Application Support/VoiceStudio/runtime/project/.venv/bin/python}"
PORT=3911
URL="http://127.0.0.1:$PORT"
PID_FILE="$HERE/server.pid"
LOG_FILE="$HERE/server.log"
START_WAIT_SECONDS=90
STOP_WAIT_SECONDS=15
NAME="The English voice (Kokoro af_heart)"

export HF_HUB_OFFLINE=1  # never download anything: the model must already be in the cache

# Does the program answer GET /health with status ok? (checked with the same Python: no curl needed)
answers() {
    "$PY" -I -c '
import json, sys, urllib.request
try:
    answer = json.load(urllib.request.urlopen(sys.argv[1] + "/health", timeout=3))
except Exception:
    sys.exit(1)
sys.exit(0 if answer.get("status") == "ok" else 1)
' "$URL" >/dev/null 2>&1
}

# The process number from the pid file, if that process is alive AND is our voice-en/server.py (a recycled number is not ours).
running_pid() {
    [ -f "$PID_FILE" ] || return 1
    local pid
    pid="$(tr -dc '0-9' < "$PID_FILE")"
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    ps -p "$pid" -o command= 2>/dev/null | grep -q "voice-en/server.py" || return 1
    echo "$pid"
}

do_start() {
    local pid
    if pid="$(running_pid)"; then
        if answers; then
            echo "$NAME is already running (process $pid) at $URL."
            return 0
        fi
        echo "The English voice is already starting (process $pid); waiting for it..."
    else
        rm -f "$PID_FILE"
        if [ ! -x "$PY" ]; then
            echo "Cannot start: VoiceStudio's Python is missing ($PY)."
            echo "The English voice borrows it (it already has the MLX speech libraries), so VoiceStudio must be installed."
            return 1
        fi
        if answers; then
            echo "Something already answers at $URL, but it was not started by this script (no $PID_FILE)."
            echo "If it is the English voice, nothing to do. If not, stop that program first."
            return 0
        fi
        local problem
        if ! problem="$("$PY" -I "$HERE/server.py" --check 2>&1)"; then
            echo "Cannot start: the Kokoro model files are missing."
            echo "$problem" | sed 's/^/    /'
            return 1
        fi
        echo "Starting the English voice (Kokoro af_heart)... loading the model takes a few seconds."
        # Start in the background, detached from this terminal; a fresh log for this run.
        nohup "$PY" "$HERE/server.py" --port "$PORT" > "$LOG_FILE" 2>&1 < /dev/null &
        pid=$!
        echo "$pid" > "$PID_FILE"
    fi
    local waited=0
    while [ "$waited" -lt "$START_WAIT_SECONDS" ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PID_FILE"
            echo "The English voice stopped while starting. The last lines of voice-en/server.log:"
            tail -n 15 "$LOG_FILE" | sed 's/^/    /'
            return 1
        fi
        if answers; then
            echo "Ready: $NAME answers at $URL (process $pid)."
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    echo "The English voice did not answer within $START_WAIT_SECONDS seconds, so it was stopped. The last lines of voice-en/server.log:"
    tail -n 15 "$LOG_FILE" | sed 's/^/    /'
    kill "$pid" 2>/dev/null
    rm -f "$PID_FILE"
    return 1
}

do_stop() {
    local pid
    if ! pid="$(running_pid)"; then
        rm -f "$PID_FILE"
        echo "The English voice is not running; nothing to stop."
        return 0
    fi
    kill "$pid" 2>/dev/null
    local waited=0
    while kill -0 "$pid" 2>/dev/null; do
        if [ "$waited" -ge "$STOP_WAIT_SECONDS" ]; then
            echo "It did not stop politely within $STOP_WAIT_SECONDS seconds; forcing it."
            kill -9 "$pid" 2>/dev/null
            break
        fi
        sleep 1
        waited=$((waited + 1))
    done
    rm -f "$PID_FILE"
    echo "Stopped the English voice (process $pid)."
    return 0
}

do_status() {
    local pid
    if pid="$(running_pid)"; then
        if answers; then
            echo "Running: $NAME answers at $URL (process $pid)."
            return 0
        fi
        echo "The process ($pid) is running but does not answer yet (still loading the model?). See voice-en/server.log."
        return 1
    fi
    if [ -x "$PY" ] && answers; then
        echo "Something answers at $URL, but it was not started by this script (no process number in $PID_FILE)."
        return 0
    fi
    echo "Not running. Start it: voice-en/run.sh start"
    return 3
}

case "${1:-}" in
    start) do_start ;;
    stop) do_stop ;;
    restart) do_stop && do_start ;;
    status) do_status ;;
    *)
        echo "Usage: voice-en/run.sh {start|stop|restart|status}"
        echo "  start    start the English voice (Kokoro af_heart) in the background and wait until it answers"
        echo "  stop     stop it"
        echo "  restart  stop it, then start it again"
        echo "  status   say whether it is running and answering"
        exit 2
        ;;
esac
