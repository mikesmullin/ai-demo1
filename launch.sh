#!/usr/bin/env bash
set -euo pipefail

# ── Local Lab Launcher ──────────────────────────────────────────────
# Builds and starts all services in correct dependency order.
#
# Usage:
#   ./launch.sh              # start all services + containers
#   ./launch.sh oauth-idp    # start only oauth-idp
#   ./launch.sh stop         # stop all services + containers
#
# Services (startup order):
#   1. tempo      :3200  (container — trace backend)
#   2. grafana    :3000  (container — dashboards)
#   3. oauth-idp  :9000
#   4. chat-back  :8100
#   5. mcp-gw     :8200
#   6. chat-front :8300
# ────────────────────────────────────────────────────────────────────

ROOT="$(cd "$(dirname "$0")" && pwd)"
PIDS_DIR="$ROOT/.pids"
LOGS_DIR="$ROOT/.logs"
mkdir -p "$PIDS_DIR" "$LOGS_DIR"

# Colors
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'

log()  { echo -e "${GREEN}[lab]${NC} $*"; }
warn() { echo -e "${YELLOW}[lab]${NC} $*"; }
err()  { echo -e "${RED}[lab]${NC} $*" >&2; }
link() { echo -e "${CYAN}[lab]${NC} $*"; }

# ── Container runtime ───────────────────────────────────────────────

CONTAINER_RT=""
if command -v podman &>/dev/null; then
    CONTAINER_RT=podman
elif command -v docker &>/dev/null; then
    CONTAINER_RT=docker
fi

# ── Container helpers ───────────────────────────────────────────────

container_running() {
    [[ -n "$CONTAINER_RT" ]] && $CONTAINER_RT inspect -f '{{.State.Running}}' "$1" 2>/dev/null | grep -q true
}

start_container() {
    local name=$1; shift
    if container_running "$name"; then
        warn "$name container already running"
        return 0
    fi
    # Remove any stopped container with the same name
    $CONTAINER_RT rm -f "$name" &>/dev/null || true
    log "Starting $name container ..."
    $CONTAINER_RT run -d --name "$name" "$@" >/dev/null
}

stop_container() {
    local name=$1
    if [[ -z "$CONTAINER_RT" ]]; then return 0; fi
    if $CONTAINER_RT inspect "$name" &>/dev/null; then
        $CONTAINER_RT rm -f "$name" &>/dev/null || true
        log "Stopped $name container"
    fi
}

wait_for_url() {
    local url=$1 name=$2 timeout=${3:-30}
    local elapsed=0
    while ! curl -sf "$url" > /dev/null 2>&1; do
        sleep 1
        elapsed=$((elapsed + 1))
        if [[ $elapsed -ge $timeout ]]; then
            err "$name not ready at $url (timeout ${timeout}s)"
            return 1
        fi
    done
}

# ── Tempo + Grafana ─────────────────────────────────────────────────

TEMPO_IMAGE="grafana/tempo:2.10.3"
GRAFANA_IMAGE="grafana/grafana:latest"

start_tempo() {
    start_container tempo --network host \
        -v "$ROOT/tempo/tempo.yaml:/etc/tempo/tempo.yaml:ro" \
        "$TEMPO_IMAGE" \
        -config.file=/etc/tempo/tempo.yaml

    log "Waiting for Tempo to be ready ..."
    wait_for_url "http://localhost:3200/ready" "tempo" 30
    log "Tempo is up on :3200  (OTLP gRPC :4317)"
}

start_grafana() {
    start_container grafana --network host \
        -e GF_AUTH_ANONYMOUS_ENABLED=true \
        -e GF_AUTH_ANONYMOUS_ORG_ROLE=Admin \
        -e GF_AUTH_DISABLE_LOGIN_FORM=true \
        -v "$ROOT/tempo/grafana-datasources.yaml:/etc/grafana/provisioning/datasources/datasources.yaml:ro" \
        "$GRAFANA_IMAGE"

    wait_for_url "http://localhost:3000/api/health" "grafana" 20
    log "Grafana is up on :3000"
}

# ── Helpers ─────────────────────────────────────────────────────────

wait_for_port() {
    local port=$1 name=$2 timeout=${3:-15}
    local elapsed=0
    while ! curl -sf "http://localhost:${port}/health" > /dev/null 2>&1; do
        sleep 0.5
        elapsed=$((elapsed + 1))
        if [[ $elapsed -ge $((timeout * 2)) ]]; then
            err "$name failed to start on :$port (timeout ${timeout}s)"
            err "Check logs: $LOGS_DIR/${name}.log"
            return 1
        fi
    done
    log "$name is up on :$port"
}

start_service() {
    local name=$1 dir=$2 port=$3
    local pidfile="$PIDS_DIR/${name}.pid"
    local logfile="$LOGS_DIR/${name}.log"

    # Skip if already running
    if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
        warn "$name already running (pid $(cat "$pidfile"))"
        return 0
    fi

    log "Building $name ..."
    (cd "$dir" && uv sync --quiet 2>&1)

    log "Starting $name on :$port ..."
    (cd "$dir" && uv run uvicorn "${name//-/_}.app:app" --port "$port" --host 0.0.0.0) \
        > "$logfile" 2>&1 &
    local pid=$!
    echo "$pid" > "$pidfile"

    wait_for_port "$port" "$name"
}

stop_service() {
    local name=$1
    local pidfile="$PIDS_DIR/${name}.pid"
    if [[ -f "$pidfile" ]]; then
        local pid
        pid=$(cat "$pidfile")
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null
            log "Stopped $name (pid $pid)"
        fi
        rm -f "$pidfile"
    fi
}

# ── Service definitions (order matters) ─────────────────────────────

declare -a SERVICES=("oauth-idp" "chat-back" "mcp-gw" "chat-front")
declare -A DIRS=( ["oauth-idp"]="$ROOT/oauth-idp" ["chat-back"]="$ROOT/chat-back" ["mcp-gw"]="$ROOT/mcp-gw" ["chat-front"]="$ROOT/chat-front" )
declare -A PORTS=( ["oauth-idp"]=9000 ["chat-back"]=8100 ["mcp-gw"]=8200 ["chat-front"]=8300 )

# ── Commands ────────────────────────────────────────────────────────

cmd_start_all() {
    log "Starting local lab ..."

    # Containers first (tempo must be up before chat-back exports spans)
    if [[ -n "$CONTAINER_RT" ]]; then
        start_tempo
        start_grafana
    else
        warn "No container runtime (podman/docker) — skipping Tempo & Grafana"
    fi

    # Python services
    for svc in "${SERVICES[@]}"; do
        start_service "$svc" "${DIRS[$svc]}" "${PORTS[$svc]}"
    done
    echo ""
    log "All services running:"
    if [[ -n "$CONTAINER_RT" ]]; then
        log "  tempo      →  http://localhost:3200"
        log "  grafana    →  http://localhost:3000"
    fi
    for svc in "${SERVICES[@]}"; do
        log "  $svc  →  http://localhost:${PORTS[$svc]}"
    done
    echo ""
    link "  ✦ Grafana Explore (traces): http://localhost:3000/explore"
}

cmd_start_one() {
    local svc=$1
    if [[ -z "${DIRS[$svc]+x}" ]]; then
        err "Unknown service: $svc"
        err "Available: ${SERVICES[*]}"
        exit 1
    fi
    start_service "$svc" "${DIRS[$svc]}" "${PORTS[$svc]}"
}

cmd_stop() {
    log "Stopping all services ..."
    # Python services (reverse order)
    for (( i=${#SERVICES[@]}-1; i>=0; i-- )); do
        stop_service "${SERVICES[$i]}"
    done
    # Containers
    stop_container grafana
    stop_container tempo
    log "All stopped."
}

cmd_status() {
    # Containers
    if [[ -n "$CONTAINER_RT" ]]; then
        for ctr in tempo grafana; do
            if container_running "$ctr"; then
                log "$ctr  running (container)"
            else
                warn "$ctr  stopped (container)"
            fi
        done
    fi
    # Python services
    for svc in "${SERVICES[@]}"; do
        local pidfile="$PIDS_DIR/${svc}.pid"
        if [[ -f "$pidfile" ]] && kill -0 "$(cat "$pidfile")" 2>/dev/null; then
            log "$svc  :${PORTS[$svc]}  running (pid $(cat "$pidfile"))"
        else
            warn "$svc  :${PORTS[$svc]}  stopped"
        fi
    done
}

cmd_logs() {
    local svc=${1:-}
    if [[ -n "$svc" && -f "$LOGS_DIR/${svc}.log" ]]; then
        tail -f "$LOGS_DIR/${svc}.log"
    else
        tail -f "$LOGS_DIR"/*.log
    fi
}

# ── Main ────────────────────────────────────────────────────────────

case "${1:-start}" in
    start)   cmd_start_all ;;
    stop)    cmd_stop ;;
    status)  cmd_status ;;
    logs)    cmd_logs "${2:-}" ;;
    oauth-idp|chat-back|mcp-gw|chat-front)
             cmd_start_one "$1" ;;
    *)
        echo "Usage: $0 {start|stop|status|logs [service]|<service-name>}"
        exit 1
        ;;
esac
