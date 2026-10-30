# local-greptile

Local PR reviewer: polls GitHub every minute for open PRs in `AhmedAsim-31` repos and reviews them with Ollama (`local-greptile-pro`, MiMo-V2.6 Distill 9B) the way Greptile does.
Code never leaves the machine except to GitHub itself, nothing is exposed to the internet, and new repos are covered automatically.

## How a review looks

- **One summary comment per PR**, edited in place on every review: score, two-sentence summary, and a table of findings linking to their threads.
- **One inline comment per finding** on its diff line (or on the file when the line is outside the diff), with severity, explanation, and fix.
- **Score out of 5**, computed from open findings, not guessed by the model: 5 = nothing open, 4 = only P2, 3 = a P1, 2 = one P0, 1 = two or more P0.
  5/5 needs every finding resolved and no new ones.
- Progress shows as the `local-greptile` commit status: pending, then the score with a link to the summary.

## Re-reviews

- **New commit:** re-reviews on the next poll. Findings the new code fixes get a reply and their thread is resolved.
- **Reply in a finding's thread:** the model answers in that thread. A reply that convincingly rebuts the finding resolves it, and a resolved finding is not raised again on the same lines.
- **`@local-greptile` comment:** re-reviews the current commit.
- Only comments by `AhmedAsim-31` count, so outsiders cannot trigger reviews or steer the model.

## Files

- `listener.py`: poll loop, PR checkout, repo context (repomix), and applying a review to the PR.
- `review.py`: numbered diff, prompt, model call, output parser, score, and comment bodies. `python3 review.py` runs its self-check.
- `gh_api.py`: GitHub REST and GraphQL calls.
- `Modelfile`: Ollama model definition.
- `launchd/com.ahmedasim.greptile.plist`: LaunchAgent that keeps the reviewer running.

## State

- GitHub token: read each poll from `gh auth token --user AhmedAsim-31`.
- PR code: shallow-fetched into `~/.greptile-cache/<owner>__<repo>` per review (outside `~/Desktop`, which launchd cannot read).
- Per-PR state in `~/.greptile-cache/reviewed.json`: last reviewed commit, last trigger and thread-reply ids, and the summary comment id.
  A failed review retries on the next two polls. On first start, PRs already open are marked as seen. Delete an entry to force a re-review.
- Findings live on GitHub. Inline comments carry a hidden `<!-- local-greptile:finding ... -->` marker and every reviewer comment carries `<!-- local-greptile -->`, which is how they are told apart from your own comments on the same account.

## Setup

```sh
# Base model (Ollama's hf.co pulls were unreliable; hf resumes downloads)
hf download bartowski/MiMo-V2.6-Distill-Qwen-9B-GGUF MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf --local-dir ~/mimo
echo "FROM $HOME/mimo/MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf" > ~/mimo/Modelfile
ollama create mimo-v2.6-distill-9b -f ~/mimo/Modelfile

ollama create local-greptile-pro -f Modelfile
cp launchd/com.ahmedasim.greptile.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ahmedasim.greptile.plist
```

Logs: `/tmp/greptile_listener.log` and `/tmp/greptile_listener.err`.
Why MiMo: benchmarked against qwen2.5-coder 7B and 14B, Qwen3.5 9B (Ollama and mlx-lm) and Mellum2.1 12B on planted bugs; results in AhmedAsim-31/greptile-bench#1.
