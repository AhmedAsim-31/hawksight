# local-greptile

Local PR reviewer: GitHub webhook -> Flask listener -> Ollama (`local-greptile-pro`) -> PR comment.

## Files

- `listener.py`: webhook server on port 5001. Symlinked from `~/greptile_listener.py`.
- `Modelfile`: Ollama model definition. Symlinked from `~/greptile_modelfile`.
- `launchd/`: LaunchAgents for the listener and the ngrok tunnel. Copy into `~/Library/LaunchAgents/`.

## Secrets

- Webhook secret: `~/.greptile_webhook_secret` (never committed).
- GitHub token: read at request time from `gh auth token --user AhmedAsim-31`.

## Setup

```sh
ollama create local-greptile-pro -f Modelfile
cp launchd/*.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ahmedasim.greptile.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ahmedasim.greptile-ngrok.plist
```

Then add a webhook per repo (see `add-webhook.sh`).
