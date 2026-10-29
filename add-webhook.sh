#!/bin/sh
# Usage: ./add-webhook.sh <repo> [https://your-domain.ngrok-free.app]
# URL defaults to the running ngrok tunnel.
set -e
URL="${2:-$(curl -s localhost:4040/api/tunnels | jq -r '.tunnels[0].public_url // empty')}"
[ -n "$URL" ] || { echo "ngrok tunnel not running; start com.ahmedasim.greptile-ngrok" >&2; exit 1; }
gh api "repos/AhmedAsim-31/$1/hooks" \
  -f name=web -F active=true -f 'events[]=pull_request' \
  -f config[url]="$URL/webhook" -f config[content_type]=json \
  -f config[secret]="$(cat ~/.greptile_webhook_secret)"
