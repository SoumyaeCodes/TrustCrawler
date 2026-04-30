#!/usr/bin/env bash
# TrustCrawler entrypoint — boots uvicorn (FastAPI) on 8000 and streamlit
# (UI) on 8501 in the same container. CLAUDE.md §8 / plan.txt P8.
#
# Why this isn't just two `&` invocations:
#
# 1. SIGNAL FORWARDING — bash, when running as PID 1 inside a container,
#    does not by default forward SIGTERM/SIGINT to its background children.
#    `docker stop` sends SIGTERM to PID 1; without our trap, the children
#    keep running until docker's grace period (default 10s) expires and
#    SIGKILL hits everyone. We trap TERM/INT explicitly and forward to
#    both PIDs so `docker stop` returns in well under 2s.
#
# 2. EITHER-DIES-WE-DIE — `wait -n` returns the moment the FIRST background
#    child exits. We treat any child dying as a fatal container failure
#    rather than running half-degraded (API up, UI dead, or vice versa);
#    docker's restart policy then handles reboots cleanly.
#
# 3. ENV-FILE PLUMBING — uvicorn supports `--env-file` natively. When the
#    project's `.env` is mounted into /app (as docker-compose does), we
#    pass `--env-file ./.env` so PUBMED_EMAIL etc. land in the FastAPI
#    process env. When it's NOT present (e.g. raw `docker run --env-file`
#    where envs are already in the container env), we skip the flag rather
#    than have uvicorn error out. The Streamlit UI calls `dotenv.load_dotenv`
#    inside app.py for the same reason — neither boot path is brittle.
#
# 4. NO `set -e` — `wait -n` returning the dying child's non-zero status
#    is the EXPECTED control-flow signal here, not an error to abort on.

set -uo pipefail

ENV_FILE="${ENV_FILE:-./.env}"

UVICORN_ARGS=(
  src.api:app
  --host 0.0.0.0
  --port 8000
)
if [[ -f "$ENV_FILE" ]]; then
  UVICORN_ARGS+=(--env-file "$ENV_FILE")
fi

uvicorn "${UVICORN_ARGS[@]}" &
UVICORN_PID=$!

streamlit run "Task 1 Multi-Source Scraper/ui/app.py" \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.headless true \
  --browser.gatherUsageStats false &
STREAMLIT_PID=$!

shutdown() {
  trap - TERM INT
  kill -TERM "$UVICORN_PID" "$STREAMLIT_PID" 2>/dev/null || true
  wait "$UVICORN_PID" 2>/dev/null || true
  wait "$STREAMLIT_PID" 2>/dev/null || true
}
trap shutdown TERM INT

# Block until either child exits, then tear down the survivor and exit
# with the dying child's status. If a signal arrives, the trap fires,
# `wait -n` unblocks with 128+SIG, and we exit promptly.
wait -n
EXIT=$?
shutdown
exit "$EXIT"
