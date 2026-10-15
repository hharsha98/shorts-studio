#!/bin/bash
# voice-de/run.sh {start|stop|status}: the German narrator (Thorsten, voice-de/server.py) as a background program.
#
#   voice-de/run.sh start    start it (waits until it answers), safe to run twice
#   voice-de/run.sh stop     stop it
#   voice-de/run.sh status   is it running, does it answer?
#
# The program's process number lives in voice-de/server.pid and everything it prints in voice-de/server.log.
# It listens on 127.0.0.1:3910 only (this computer, nobody else).

set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
PY="$HERE/.venv/bin/python"
PORT=3910
URL="http://127.0.0.1:$PORT"
PID_FILE="$HERE/server.pid"
LOG_FILE="$HERE/server.log"
START_WAIT_SECONDS=90
STOP_WAIT_SECONDS=15

# Does the program answer GET /health with status ok? (checked with the venv's Python: no curl needed)
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

# The process number from the pid file, if that process is alive AND is our server.py (a recycled number is not ours).
running_pid() {
    [ -f "$PID_FILE" ] || return 1
    local pid
    pid="$(tr -dc '0-9' < "$PID_FILE")"
    [ -n "$pid" ] || return 1
    kill -0 "$pid" 2>/dev/null || return 1
    ps -p "$pid" -o command= 2>/dev/null | grep -q "server.py" || return 1
    echo "$pid"
}

do_start() {
    local pid
    if pid="$(running_pid)"; then
        if answers; then
            echo "The German voice (Thorsten) is already running (process $pid) at $URL."
            return 0
        fi
        echo "The German voice is already starting (process $pid); waiting for it..."
    else
        rm -f "$PID_FILE"
        if [ ! -x "$PY" ]; then
            echo "Cannot start: the Python environment voice-de/.venv is missing."
            echo "Create it again with the steps in voice-de/README.md (uv venv + uv pip install -r voice-de/requirements.txt)."
            return 1
        fi
        if answers; then
            echo "Something already answers at $URL, but it was not started by this script (no $PID_FILE)."
            echo "If it is the German voice, nothing to do. If not, stop that program first."
            return 0
        fi
        local needed
        for needed in model/config.json model/model.pth model/voices/thorsten.pt; do
            if [ ! -f "$HERE/$needed" ]; then
                echo "Cannot start: the model file voice-de/$needed is missing."
                echo "See voice-de/README.md: it lists the three files the model needs and where to download them."
                return 1
            fi
        done
        echo "Starting the German voice (Thorsten)... loading the model takes a few seconds."
        # Start in the background, detached from this terminal; a fresh log for this run.
        nohup "$PY" "$HERE/server.py" --port "$PORT" > "$LOG_FILE" 2>&1 < /dev/null &
        pid=$!
        echo "$pid" > "$PID_FILE"
    fi
    local waited=0
    while [ "$waited" -lt "$START_WAIT_SECONDS" ]; do
        if ! kill -0 "$pid" 2>/dev/null; then
            rm -f "$PID_FILE"
            echo "The German voice stopped while starting. The last lines of voice-de/server.log:"
            tail -n 15 "$LOG_FILE" | sed 's/^/    /'
            return 1
        fi
        if answers; then
            echo "Ready: the German voice (Thorsten) answers at $URL (process $pid)."
            return 0
        fi
        sleep 1
        waited=$((waited + 1))
    done
    echo "The German voice did not answer within $START_WAIT_SECONDS seconds, so it was stopped. The last lines of voice-de/server.log:"
    tail -n 15 "$LOG_FILE" | sed 's/^/    /'
    kill "$pid" 2>/dev/null
    rm -f "$PID_FILE"
    return 1
}

do_stop() {
    local pid
    if ! pid="$(running_pid)"; then
        rm -f "$PID_FILE"
        echo "The German voice is not running; nothing to stop."
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
    echo "Stopped the German voice (process $pid)."
    return 0
}

do_status() {
    local pid
    if pid="$(running_pid)"; then
        if answers; then
            echo "Running: the German voice (Thorsten) answers at $URL (process $pid)."
            return 0
        fi
        echo "The process ($pid) is running but does not answer yet (still loading the model?). See voice-de/server.log."
        return 1
    fi
    if [ -x "$PY" ] && answers; then
        echo "Something answers at $URL, but it was not started by this script (no process number in $PID_FILE)."
        return 0
    fi
    echo "Not running. Start it: voice-de/run.sh start"
    return 3
}

case "${1:-}" in
    start) do_start ;;
    stop) do_stop ;;
    status) do_status ;;
    *)
        echo "Usage: voice-de/run.sh {start|stop|status}"
        echo "  start   start the German voice (Thorsten) in the background and wait until it answers"
        echo "  stop    stop it"
        echo "  status  say whether it is running and answering"
        exit 2
        ;;
esac
