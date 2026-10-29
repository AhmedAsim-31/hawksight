#!/bin/sh
# Usage: ./add-webhook.sh <repo> [https://your-domain.ngrok-free.app]
# URL defaults to the running ngrok tunnel.
set -e
# Each ngrok agent serves its own local API (4040, 4041, ...); pick the tunnel forwarding to the listener.
URL="${2:-$(for p in 4040 4041 4042 4043; do curl -s "localhost:$p/api/tunnels"; done | jq -rs '[.[].tunnels[] | select(.config.addr | endswith(":5001")) | .public_url][0] // empty')}"
[ -n "$URL" ] || { echo "ngrok tunnel not running; start com.ahmedasim.greptile-ngrok" >&2; exit 1; }
gh api "repos/AhmedAsim-31/$1/hooks" \
  -f name=web -F active=true -f 'events[]=pull_request' \
  -f config[url]="$URL/webhook" -f config[content_type]=json \
  -f config[secret]="$(cat ~/.greptile_webhook_secret)"
