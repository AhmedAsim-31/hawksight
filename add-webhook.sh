#!/bin/sh
# Usage: ./add-webhook.sh <repo> <https://your-domain.ngrok-free.app>
set -e
gh api "repos/AhmedAsim-31/$1/hooks" \
  -f name=web -F active=true -f 'events[]=pull_request' \
  -f config[url]="$2/webhook" -f config[content_type]=json \
  -f config[secret]="$(cat ~/.greptile_webhook_secret)"
