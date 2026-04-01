#!/usr/bin/env bash
# Ensure Colima VM is running and Docker socket is available.
# Safe to run even when already healthy — exits 0 if everything is fine.
set -euo pipefail

COLIMA_PROFILE="${COLIMA_PROFILE:-default}"
COLIMA_CPU="${COLIMA_CPU:-8}"
COLIMA_MEMORY="${COLIMA_MEMORY:-32}"
COLIMA_DISK="${COLIMA_DISK:-200}"
DOCKER_SOCK="${HOME}/.colima/${COLIMA_PROFILE}/docker.sock"

log()  { echo "▸ $*"; }
ok()   { echo "  ✓ $*"; }
warn() { echo "  ⚠ $*"; }

# ── 1. Check if Docker is already responsive ────────────────
if docker info &>/dev/null; then
  ok "Colima/Docker already running"
  # Ensure fallback DNS is configured in Colima VM (survives restarts)
  colima ssh -- sh -c '
    if [ ! -f /etc/systemd/resolved.conf.d/fallback.conf ]; then
      mkdir -p /etc/systemd/resolved.conf.d
      echo -e "[Resolve]\nFallbackDNS=8.8.8.8 8.8.4.4" > /etc/systemd/resolved.conf.d/fallback.conf
      systemctl restart systemd-resolved 2>/dev/null
    fi
  ' 2>/dev/null || true
  # Ensure Docker daemon has public DNS fallback (critical for k3d image pulls)
  colima ssh -- sudo sh -c '
    if ! grep -q "8.8.8.8" /etc/docker/daemon.json 2>/dev/null; then
      python3 -c "
import json
try:
    cfg = json.load(open(\"/etc/docker/daemon.json\"))
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}
cfg[\"dns\"] = [\"8.8.8.8\", \"8.8.4.4\"]
json.dump(cfg, open(\"/etc/docker/daemon.json\", \"w\"), indent=2)
"
      systemctl restart docker
    fi
  ' 2>/dev/null || true
  exit 0
fi

# ── 2. Check Colima status ───────────────────────────────────
COLIMA_STATUS=$(colima list --json 2>/dev/null | python3 -c "
import sys, json
for p in json.load(sys.stdin):
    if p.get('profile') == '${COLIMA_PROFILE}':
        print(p.get('status', 'unknown'))
        break
else:
    print('not-found')
" 2>/dev/null || echo "unknown")

log "Colima status: ${COLIMA_STATUS}"

case "$COLIMA_STATUS" in
  Running)
    # VM is "running" but Docker is not responding — stuck state, need restart
    warn "Colima reports Running but Docker is unresponsive — forcing restart"
    colima stop "$COLIMA_PROFILE" 2>/dev/null || true
    # Kill any stuck Lima/hostagent processes
    pkill -f "limactl hostagent" 2>/dev/null || true
    pkill -f "colima daemon" 2>/dev/null || true
    sleep 3
    ;;
  Stopped|not-found)
    log "Colima is stopped, starting..."
    ;;
  *)
    warn "Unexpected Colima status '${COLIMA_STATUS}', attempting start anyway"
    ;;
esac

# ── 3. Start Colima ──────────────────────────────────────────
log "Starting Colima (${COLIMA_CPU} CPU, ${COLIMA_MEMORY}GB RAM, ${COLIMA_DISK}GB disk)..."
colima start \
  --cpu "$COLIMA_CPU" \
  --memory "$COLIMA_MEMORY" \
  --disk "$COLIMA_DISK" \
  --profile "$COLIMA_PROFILE"

# ── 4. Configure fallback DNS ──────────────────────────────
colima ssh -- sh -c '
  mkdir -p /etc/systemd/resolved.conf.d
  echo -e "[Resolve]\nFallbackDNS=8.8.8.8 8.8.4.4" > /etc/systemd/resolved.conf.d/fallback.conf
  systemctl restart systemd-resolved 2>/dev/null
' 2>/dev/null || true

# ── 4b. Configure Docker daemon DNS ─────────────────────────
# k3d node containers inherit Docker daemon DNS. After restart, Colima VM
# DNS (192.168.65.254) may be unreachable — ensure public fallback is set.
colima ssh -- sudo sh -c '
  if ! grep -q "8.8.8.8" /etc/docker/daemon.json 2>/dev/null; then
    python3 -c "
import json, sys
try:
    cfg = json.load(open(\"/etc/docker/daemon.json\"))
except (FileNotFoundError, json.JSONDecodeError):
    cfg = {}
cfg[\"dns\"] = [\"8.8.8.8\", \"8.8.4.4\"]
json.dump(cfg, open(\"/etc/docker/daemon.json\", \"w\"), indent=2)
"
    systemctl restart docker
  fi
' 2>/dev/null || true

# ── 5. Verify Docker is responsive ──────────────────────────
log "Waiting for Docker daemon..."
for i in $(seq 1 30); do
  if docker info &>/dev/null; then
    ok "Docker is ready"
    exit 0
  fi
  sleep 2
done

echo "✗ Docker did not become ready after 60s" >&2
exit 1
