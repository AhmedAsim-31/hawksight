# hawksight

Local PR reviewer: polls GitHub every minute for open PRs in `AhmedAsim-31` repos and reviews them with Ollama (`hawksight`, MiMo-V2.6 Distill 9B), Greptile style.
It comments as the `hawksight` GitHub App, so its comments show as `hawksight-bot[bot]`.
Code never leaves the machine except to GitHub itself, nothing is exposed to the internet, and new repos are covered automatically.

## How a review looks

- **One summary comment per PR**, edited in place on every review: score, two-sentence summary, and a table of findings linking to their threads.
- **Every finding is verified before it posts**: a second model call checks it against the code and drops it if it misreads removed lines, claims something is missing that exists, objects to a deliberate change, or is about wording or style. The call shares the review prompt prefix, so Ollama reuses its cache and each check takes about 5 s.
- **One inline comment per finding** on its diff line (or on the file when the line is outside the diff), with severity, explanation, and fix.
- **Score out of 5**, computed from open findings, not guessed by the model: 5 = nothing open, 4 = only P2, 3 = a P1, 2 = one P0, 1 = two or more P0.
  5/5 needs every finding resolved and no new ones.
- Progress shows as the `hawksight` commit status: pending, then the score with a link to the summary.

## Re-reviews

- **New commit:** re-reviews on the next poll. Findings the new code fixes get a reply and their thread is resolved.
- **Reply in a finding's thread:** the model answers in that thread. A reply that convincingly rebuts the finding resolves it, and a resolved finding is not raised again on the same lines.
- **`/hawksight` comment:** re-reviews the current commit.
- Only comments by `AhmedAsim-31` count, so outsiders cannot trigger reviews or steer the model.

## Files

- `listener.py`: poll loop, PR checkout, repo context (repomix), and applying a review to the PR.
- `review.py`: numbered diff, prompt, model call, output parser, score, and comment bodies. `python3 review.py` runs its self-check.
- `gh_api.py`: GitHub App token and GitHub REST and GraphQL calls.
- `create_app.py`: one-time creation of the GitHub App from a manifest.
- `Modelfile`: Ollama model definition.
- `launchd/com.ahmedasim.hawksight.plist`: LaunchAgent that keeps the reviewer running.

## State

- GitHub App id and private key: `~/.hawksight/app.json` and `~/.hawksight/app.pem` (mode 600). Each poll mints a one-hour installation token from them.
- PR code: shallow-fetched into `~/.hawksight/<owner>__<repo>` per review (outside `~/Desktop`, which launchd cannot read).
- Per-PR state in `~/.hawksight/reviewed.json`: last reviewed commit, last trigger and thread-reply ids, and the summary comment id.
  A failed review retries on the next two polls. On first start, PRs already open are marked as seen. Delete an entry to force a re-review.
- Findings live on GitHub. Inline comments carry a hidden `<!-- hawksight:finding ... -->` marker and every reviewer comment carries `<!-- hawksight -->`.

## Setup

```sh
# Base model (Ollama's hf.co pulls were unreliable; hf resumes downloads)
hf download bartowski/MiMo-V2.6-Distill-Qwen-9B-GGUF MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf --local-dir ~/mimo
echo "FROM $HOME/mimo/MiMo-V2.6-Distill-Qwen-9B-Q4_K_M.gguf" > ~/mimo/Modelfile
ollama create mimo-v2.6-distill-9b -f ~/mimo/Modelfile

ollama create hawksight -f Modelfile

# GitHub App: creates it in the browser, saves the key to ~/.hawksight, then install it on all repos
python3 create_app.py

cp launchd/com.ahmedasim.hawksight.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.ahmedasim.hawksight.plist
```

Logs: `/tmp/hawksight.log` and `/tmp/hawksight.err`.
Why MiMo: benchmarked against qwen2.5-coder 7B and 14B, Qwen3.5 9B (Ollama and mlx-lm) and Mellum2.1 12B on planted bugs; results in AhmedAsim-31/greptile-bench#1.
