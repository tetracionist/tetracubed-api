#!/usr/bin/env bash
# Launcher for the systemd --user service.
# Puts the per-user uv and pulumi on PATH, then runs uvicorn from the repo root
# so load_dotenv() picks up ./.env. Lives inside the repo, so it travels with
# the rsync deploy — nothing to install separately.
set -euo pipefail

export PATH="$HOME/.local/bin:$HOME/.pulumi/bin:$PATH"

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

exec uv run uvicorn main:app --host 0.0.0.0 --port 8000
