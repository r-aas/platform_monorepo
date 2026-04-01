#!/usr/bin/env bash
set -euo pipefail

# Pre-flight checks — verify all external dependencies before platform bootstrap.
# Exit 0 if all checks pass, exit 1 with details on first failure.
#
# Usage:
#   bash scripts/preflight.sh          # full check
#   bash scripts/preflight.sh --quick  # skip Ollama (for teardown)

QUICK="${1:-}"
PASS=0
FAIL=0

ok()   { echo "  ✓ $*"; PASS=$((PASS + 1)); }
fail() { echo "  ✗ $*" >&2; FAIL=$((FAIL + 1)); }
warn() { echo "  ⚠ $*"; }

echo "Pre-flight checks"
echo ""

# ── Required CLI tools ──────────────────────────────────────
echo "Tools:"
for cmd in docker kubectl helm helmfile k3d jq git curl; do
  if command -v "$cmd" &>/dev/null; then
    ok "$cmd ($(command -v "$cmd"))"
  else
    fail "$cmd not found — install with: brew install $cmd"
  fi
done
echo ""

# ── Docker / Colima ─────────────────────────────────────────
echo "Docker runtime:"
if docker info &>/dev/null; then
  ok "Docker daemon reachable"
  # Check Colima specifically
  if docker context inspect colima &>/dev/null 2>&1 || [ -S "$HOME/.colima/default/docker.sock" ]; then
    ok "Colima socket exists"
  else
    warn "Not using Colima — may be fine if Docker Desktop is running"
  fi
  # Check resources
  DOCKER_CPUS=$(docker info --format '{{.NCPU}}' 2>/dev/null || echo "?")
  DOCKER_MEM=$(docker info --format '{{.MemTotal}}' 2>/dev/null || echo "0")
  DOCKER_MEM_GB=$(( DOCKER_MEM / 1073741824 ))
  if [ "$DOCKER_MEM_GB" -lt 16 ] 2>/dev/null; then
    warn "Docker VM has ${DOCKER_MEM_GB}GB RAM — recommend 32GB+ for full stack"
  else
    ok "Docker VM: ${DOCKER_CPUS} CPUs, ${DOCKER_MEM_GB}GB RAM"
  fi
else
  fail "Docker daemon not reachable — start Colima: colima start"
fi
echo ""

# ── Ollama ──────────────────────────────────────────────────
if [ "$QUICK" != "--quick" ]; then
  echo "Ollama:"
  # Ensure OLLAMA_HOST is set for GUI app (persists until reboot)
  launchctl setenv OLLAMA_HOST "0.0.0.0:11434" 2>/dev/null || true

  if curl -sf http://localhost:11434/api/version &>/dev/null; then
    VERSION=$(curl -sf http://localhost:11434/api/version | jq -r '.version' 2>/dev/null)
    ok "Ollama running (v${VERSION})"

    # Check binding — must be 0.0.0.0 for k3d pods to reach host
    OLLAMA_IPV4=$(lsof -i4TCP -P -n 2>/dev/null | grep ":11434.*LISTEN" | awk '{print $9}' | cut -d: -f1 || true)
    if [ "$OLLAMA_IPV4" = "*" ] || [ "$OLLAMA_IPV4" = "0.0.0.0" ]; then
      ok "Ollama bound to 0.0.0.0 (reachable from k3d)"
    elif [ -n "$OLLAMA_IPV4" ]; then
      warn "Ollama bound to ${OLLAMA_IPV4} — k3d pods can't reach it"
      warn "Restart Ollama: pkill ollama && OLLAMA_HOST=0.0.0.0:11434 ollama serve &"
    fi

    # Check performance env vars
    FLASH_ATN=$(launchctl getenv OLLAMA_FLASH_ATTENTION 2>/dev/null || echo "")
    if [ "$FLASH_ATN" = "1" ]; then
      ok "Flash attention enabled"
    else
      warn "OLLAMA_FLASH_ATTENTION not set — run: launchctl setenv OLLAMA_FLASH_ATTENTION 1"
    fi

    # Check if a model is available
    MODEL_COUNT=$(curl -sf http://localhost:11434/api/tags | jq '.models | length' 2>/dev/null || echo "0")
    if [ "$MODEL_COUNT" -gt 0 ]; then
      ok "${MODEL_COUNT} model(s) available"
    else
      warn "No models pulled — run: ollama pull glm-4.7-flash"
    fi
  else
    warn "Ollama not running — genai workloads will timeout"
    warn "Start with: OLLAMA_HOST=0.0.0.0:11434 ollama serve"
  fi
  echo ""
fi

# ── Disk space ──────────────────────────────────────────────
echo "Disk:"
AVAIL_GB=$(df -g "$HOME/work" 2>/dev/null | awk 'NR==2{print $4}' || echo "?")
if [ "$AVAIL_GB" != "?" ] && [ "$AVAIL_GB" -lt 20 ] 2>/dev/null; then
  warn "${AVAIL_GB}GB free — recommend 20GB+ for images and PVs"
else
  ok "${AVAIL_GB}GB available on ~/work volume"
fi
echo ""

# ── Summary ─────────────────────────────────────────────────
echo "Result: ${PASS} passed, ${FAIL} failed"
if [ "$FAIL" -gt 0 ]; then
  echo ""
  echo "Fix the failures above before running 'task up'."
  exit 1
fi
