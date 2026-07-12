#!/usr/bin/env bash
# Tetracubed API — no-sudo, per-user setup for a fresh box.
#
# Run as the unprivileged service user (the same user your CI/CD deploys as):
#   curl -fsSL https://raw.githubusercontent.com/tetracionist/tetracubed-api/main/setup-user.sh | bash
#
# Installs uv, Pulumi, a uv-managed Python 3.13 (no deadsnakes/apt), and a
# systemd --user service. No root required for any step except (optionally)
# enabling linger — see the note at the end.
set -euo pipefail

REPO_URL="https://github.com/tetracionist/tetracubed-api.git"
APP_DIR="$HOME/tetracubed-api"
SERVICE="tetracubed-api"

echo "== Tetracubed API — per-user setup (no sudo) =="

# --- PATH for per-user binaries -------------------------------------------
mkdir -p "$HOME/.local/bin"
grep -q '.local/bin' "$HOME/.bashrc" 2>/dev/null \
  || echo 'export PATH="$HOME/.local/bin:$HOME/.pulumi/bin:$PATH"' >> "$HOME/.bashrc"
export PATH="$HOME/.local/bin:$HOME/.pulumi/bin:$PATH"

# --- uv --------------------------------------------------------------------
if ! command -v uv >/dev/null 2>&1; then
  echo "-> installing uv"
  curl -LsSf https://astral.sh/uv/install.sh | sh
fi

# --- Pulumi CLI ------------------------------------------------------------
if ! command -v pulumi >/dev/null 2>&1; then
  echo "-> installing pulumi"
  curl -fsSL https://get.pulumi.com | sh
fi

# --- Python 3.13 (uv-managed standalone build, no deadsnakes/sudo) ---------
uv python install 3.13

# --- Code ------------------------------------------------------------------
if [ -d "$APP_DIR/.git" ]; then
  echo "-> updating $APP_DIR"
  git -C "$APP_DIR" pull --ff-only
else
  echo "-> cloning into $APP_DIR"
  git clone "$REPO_URL" "$APP_DIR"
fi
cd "$APP_DIR"
chmod +x deploy/run.sh
uv sync --frozen

# --- .env ------------------------------------------------------------------
if [ ! -f "$APP_DIR/.env" ]; then
  cp "$APP_DIR/.env.example" "$APP_DIR/.env"
  echo "!! created $APP_DIR/.env from the example — edit it with your credentials"
fi

# --- systemd --user service ------------------------------------------------
export XDG_RUNTIME_DIR="${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"
mkdir -p "$HOME/.config/systemd/user"
cp "$APP_DIR/deploy/$SERVICE.service" "$HOME/.config/systemd/user/$SERVICE.service"
systemctl --user daemon-reload
systemctl --user enable "$SERVICE"

# --- keep running after logout / across reboot -----------------------------
if loginctl enable-linger "$USER" 2>/dev/null || sudo -n loginctl enable-linger "$USER" 2>/dev/null; then
  echo "-> linger enabled (service survives logout + reboot, and CI restarts work)"
else
  echo "!! could not enable linger without privileges."
  echo "   Ask an admin to run once:  sudo loginctl enable-linger $USER"
  echo "   Without it the service stops on logout and CI deploys cannot restart it."
fi

cat <<EOF

Done. Next:
  1) edit $APP_DIR/.env  (USERS_DB, JWT_SECRET_KEY, PULUMI_ACCESS_TOKEN, PULUMI_STACK_NAME, AWS_REGION)
  2) set -a; . $APP_DIR/.env; set +a; pulumi login
  3) systemctl --user start $SERVICE
  4) journalctl --user -u $SERVICE -f
EOF
