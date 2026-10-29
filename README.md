# local-greptile

Local PR reviewer: polls GitHub every minute for open PRs in `AhmedAsim-31` repos, reviews each new head commit with Ollama (`local-greptile-pro`), and posts the review as a PR comment.
Nothing is exposed to the internet, and new repos are covered automatically.

## Files

- `listener.py`: the polling reviewer. Symlinked from `~/greptile_listener.py`.
- `Modelfile`: Ollama model definition. Symlinked from `~/greptile_modelfile`.
- `launchd/com.ahmedasim.greptile.plist`: LaunchAgent that keeps the reviewer running. Copy into `~/Library/LaunchAgents/`.

## State

- GitHub token: read each poll from `gh auth token --user AhmedAsim-31`.
- PR code: shallow-fetched into `~/.greptile-cache/<owner>__<repo>` per review (outside `~/Desktop`, which launchd cannot read).
- Reviewed head commits: `~/.greptile-cache/reviewed.json`. On first start, PRs already open are marked as seen. Delete an entry to force a re-review.

## Setup

```sh
ollama create local-greptile-pro -f Modelfile
cp launchd/com.ahmedasim.greptile.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ahmedasim.greptile.plist
```

Logs: `/tmp/greptile_listener.log` and `/tmp/greptile_listener.err`.
