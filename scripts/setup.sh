#!/usr/bin/env bash
# One-time setup of DevTeam AI on Linux or macOS (the Windows script is setup.ps1).
#   bash scripts/setup.sh              # backend and dashboard
#   bash scripts/setup.sh --skip-frontend
set -euo pipefail
cd "$(dirname "$0")/.."

skip_frontend=false
[[ "${1:-}" == "--skip-frontend" ]] && skip_frontend=true

step() { printf '\n==> %s\n' "$1"; }
fail() { printf '\nSetup stopped: %s\n' "$1" >&2; exit 1; }

step "Checking tools"
python=""
for candidate in python3.14 python3.13 python3.12 python3 python; do
  if command -v "$candidate" >/dev/null &&
     "$candidate" -c 'import sys; sys.exit(sys.version_info < (3, 12))' 2>/dev/null; then
    python="$candidate"; break
  fi
done
[[ -n "$python" ]] || fail "Python 3.12 or newer is required."
echo "    $("$python" --version)"
command -v git >/dev/null || fail "git is required: generated projects are committed with it."
echo "    $(git --version)"
if ! $skip_frontend; then
  command -v node >/dev/null || fail "Node.js 22 or newer is required (or use --skip-frontend)."
  major=$(node --version | sed 's/^v//; s/\..*//')
  (( major >= 22 )) || fail "Node.js 22 or newer is required (found $(node --version))."
  echo "    Node.js $(node --version)"
fi

step "Python virtual environment (.venv)"
[[ -x .venv/bin/python ]] || "$python" -m venv .venv
.venv/bin/python -m pip install --quiet --upgrade pip
.venv/bin/python -m pip install --quiet -e "backend[dev]"
echo "    installed"

step "Configuration (.env)"
if [[ -f .env ]]; then
  echo "    kept your existing .env"
else
  cp .env.example .env
  echo "    created .env from .env.example"
fi
for key in LLM_API_KEY E2B_API_KEY; do
  grep -Eq "^${key}=\S+" .env || echo "    fill in ${key} in .env"
done

if ! $skip_frontend; then
  step "Dashboard dependencies (npm ci)"
  (cd frontend && npm ci --no-audit --no-fund --loglevel=error)
fi

step "Done"
echo "    API:        cd backend && ../.venv/bin/python -m app.api"
echo "    Dashboard:  cd frontend && npm run dev   (http://localhost:5173)"
echo "    Tests:      cd backend && ../.venv/bin/python -m pytest"
