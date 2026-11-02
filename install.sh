#!/bin/bash
# Installs hawksight on macOS: checks dependencies, builds the Ollama model, and starts the LaunchAgent.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
STATE="$HOME/.hawksight"
LABEL="com.hawksight.listener"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BASE="mimo-v2.6-distill-9b"
GGUF_REPO="bartowski/MiMo-V2.6-Distill-Qwen-9B-GGUF"
GGUF_FILE="MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf"
PY=/usr/bin/python3

need() { command -v "$1" >/dev/null || { echo "Missing $1. $2"; exit 1; }; }
need git "Install the Xcode command line tools: xcode-select --install"
need openssl "It ships with macOS; check your PATH."
need ollama "Install it: brew install ollama && brew services start ollama"
need repomix "Install it: npm install -g repomix"
"$PY" -c "import requests" 2>/dev/null || "$PY" -m pip install --user -q requests

if ! ollama show "$BASE" >/dev/null 2>&1; then
  need hf "Install the Hugging Face CLI: brew install hf (needed once, for the 5.8 GB model download)"
  mkdir -p "$STATE/models"
  hf download "$GGUF_REPO" "$GGUF_FILE" --local-dir "$STATE/models"
  echo "FROM $STATE/models/$GGUF_FILE" > "$STATE/models/Modelfile"
  ollama create "$BASE" -f "$STATE/models/Modelfile"
fi
ollama create hawksight -f "$DIR/Modelfile"

if [ ! -f "$STATE/app.json" ] || [ ! -f "$STATE/app.pem" ]; then
  echo "No GitHub App yet. Run: $PY $DIR/create_app.py <app-name>, install the app, then rerun ./install.sh"
  exit 1
fi

# launchd starts with a bare PATH, so bake in where git, node/repomix and ollama live.
TOOLS_PATH="$(dirname "$(command -v repomix)"):$(dirname "$(command -v ollama)"):$(dirname "$(command -v git)"):/usr/bin:/bin"
mkdir -p "$HOME/Library/LaunchAgents" "$HOME/Library/Logs"
cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key><string>$LABEL</string>
    <key>ProgramArguments</key>
    <array><string>$PY</string><string>$DIR/listener.py</string></array>
    <key>EnvironmentVariables</key>
    <dict><key>PATH</key><string>$TOOLS_PATH</string></dict>
    <key>RunAtLoad</key><true/>
    <key>KeepAlive</key><true/>
    <key>StandardOutPath</key><string>$HOME/Library/Logs/hawksight.log</string>
    <key>StandardErrorPath</key><string>$HOME/Library/Logs/hawksight.err</string>
</dict>
</plist>
EOF
launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
echo "hawksight is running. Logs: tail -f ~/Library/Logs/hawksight.log"
