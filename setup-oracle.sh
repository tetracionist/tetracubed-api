#!/bin/bash
# Tetracubed API — Oracle Cloud Setup Script
# Run once on a fresh Oracle Cloud Ubuntu instance as the `ubuntu` user.
#
#   curl -fsSL https://raw.githubusercontent.com/tetracionist/tetracubed-api/main/setup-oracle.sh | bash
#
# After this, code updates flow through .github/workflows/deploy.yml.

set -e

APP_DIR="/home/ubuntu/tetracubed-api"
SERVICE_NAME="tetracubed-api"

echo "========================================="
echo "Tetracubed API — Oracle Cloud Setup"
echo "========================================="

# --- System packages ---
echo "📦 Updating apt + installing system deps..."
sudo apt update
sudo apt install -y curl git software-properties-common ca-certificates

# --- Python 3.13 (via deadsnakes) ---
if ! command -v python3.13 &> /dev/null; then
  echo "📦 Installing Python 3.13 (deadsnakes)..."
  sudo add-apt-repository -y ppa:deadsnakes/ppa
  sudo apt update
  sudo apt install -y python3.13 python3.13-venv python3.13-dev
else
  echo "✅ Python 3.13 already installed: $(python3.13 --version)"
fi

# --- uv (Python package/runtime manager) ---
if [ ! -x "/home/ubuntu/.local/bin/uv" ]; then
  echo "📦 Installing uv..."
  curl -LsSf https://astral.sh/uv/install.sh | sh
else
  echo "✅ uv already installed: $(/home/ubuntu/.local/bin/uv --version)"
fi

# --- Pulumi CLI ---
if [ ! -x "/home/ubuntu/.pulumi/bin/pulumi" ]; then
  echo "📦 Installing Pulumi CLI..."
  curl -fsSL https://get.pulumi.com | sh
else
  echo "✅ Pulumi already installed: $(/home/ubuntu/.pulumi/bin/pulumi version)"
fi

# --- Application directory ---
echo "📁 Ensuring app directory: $APP_DIR"
mkdir -p "$APP_DIR"

# --- systemd service ---
echo "🔧 Installing systemd unit..."
# Workflow rsyncs the unit file into the repo dir; install from there if present,
# otherwise drop a copy that matches the repo's tetracubed-api.service.
if [ -f "$APP_DIR/tetracubed-api.service" ]; then
  sudo cp "$APP_DIR/tetracubed-api.service" "/etc/systemd/system/$SERVICE_NAME.service"
else
  echo "⚠️  $APP_DIR/tetracubed-api.service not found yet — run the GitHub Actions deploy"
  echo "   first to populate $APP_DIR, then re-run this script."
fi
sudo systemctl daemon-reload
sudo systemctl enable "$SERVICE_NAME" 2>/dev/null || true

# --- sudoers entry so the deploy workflow can restart the service ---
SUDOERS_FILE="/etc/sudoers.d/$SERVICE_NAME"
if [ ! -f "$SUDOERS_FILE" ]; then
  echo "🔧 Adding NOPASSWD sudoers entry for systemctl..."
  sudo tee "$SUDOERS_FILE" > /dev/null <<EOF
ubuntu ALL=(ALL) NOPASSWD: /bin/systemctl restart $SERVICE_NAME, /bin/systemctl status $SERVICE_NAME, /bin/journalctl -u $SERVICE_NAME*
EOF
  sudo chmod 0440 "$SUDOERS_FILE"
fi

echo ""
echo "========================================="
echo "✅ Setup Complete!"
echo "========================================="
echo ""
echo "Next steps:"
echo "1. Configure GitHub repo secrets (see .github/workflows/deploy.yml):"
echo "     SSH_HOST, SSH_USER, SSH_PRIVATE_KEY"
echo "     USERS_DB, JWT_SECRET_KEY"
echo "     PULUMI_ACCESS_TOKEN, AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_DEFAULT_REGION"
echo ""
echo "2. Push to main (or run the workflow manually) to deploy."
echo ""
echo "3. Open inbound TCP 8000 in your Oracle VCN security list."
echo ""
echo "4. Useful commands:"
echo "     sudo systemctl status $SERVICE_NAME"
echo "     sudo journalctl -u $SERVICE_NAME -f"
echo "========================================="
