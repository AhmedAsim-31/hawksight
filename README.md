# hawksight

A free, self-hosted AI reviewer for GitHub pull requests that runs entirely on your Mac.
It reviews like Greptile: one summary comment with a score, one inline thread per finding, and threads that resolve themselves when you fix or rebut them.
Your code goes to GitHub and nowhere else: the model runs locally through Ollama, and nothing listens on the internet.

## What a review looks like

- **One summary comment per PR**, edited in place on every review: a score, a two-sentence summary, and a table of findings that link to their threads.
- **One inline comment per finding** on its diff line, with a severity (P0 critical, P1 important, P2 minor), what goes wrong, and the fix.
- **Every finding is verified before it posts.**
  A second model call checks it against the code and drops it if it misreads removed lines, claims something is missing that exists, objects to a deliberate change, or is about wording or style.
- **A score out of 5, computed from open findings**, not guessed by the model: 5 means nothing is open, 4 only P2, 3 a P1, 2 one P0, and 1 two or more P0.
  A 5/5 needs every finding resolved and no new ones.
- **A commit status** (`hawksight`) shows progress, then the score with a link to the summary.
- **Comments come from your own GitHub App**, so they show as `<your-app>[bot]`, not as you.

## Re-reviews

- **Push a commit:** hawksight re-reviews on its next poll. Findings the new code fixes get a reply, and their threads are resolved.
- **Reply in a finding's thread:** the model answers in that thread. A reply that convincingly rebuts the finding resolves it, and a resolved finding is not raised again on the same lines.
- **Comment `/hawksight`** on the PR to re-review the current commit.
- Only comments from the account the app is installed on count, so outsiders cannot trigger reviews or steer the model.

## Requirements

- macOS on Apple silicon with 16 GB of memory or more.
  The default model uses about 6 GB while it reviews.
- [Ollama](https://ollama.com) running as a service: `brew install ollama && brew services start ollama`.
- [repomix](https://github.com/yamadashy/repomix), which packs the repository context: `npm install -g repomix`.
- The [Hugging Face CLI](https://huggingface.co/docs/huggingface_hub/en/guides/cli), once, to download the model: `brew install hf`.
- About 6 GB of free disk space for the model.

## Install

1. Clone the repository somewhere outside `~/Desktop`, `~/Documents` and `~/Downloads`, which macOS blocks background agents from reading:

   ```sh
   git clone https://github.com/AhmedAsim-31/hawksight.git ~/hawksight
   cd ~/hawksight
   ```

2. Create your GitHub App.
   App names are unique across GitHub, so include your handle:

   ```sh
   /usr/bin/python3 create_app.py hawksight-<your-handle>
   ```

   A browser tab opens with the app form already filled in.
   Click **Create GitHub App**, then follow the **install it** link and choose **All repositories** (or pick some).
   The app's private key is saved to `~/.hawksight/app.pem`, readable only by you.

3. Run the installer:

   ```sh
   ./install.sh
   ```

   It installs `requests` for the system Python if needed, downloads the model (5.8 GB, once), builds the `hawksight` Ollama model, and starts a LaunchAgent that keeps the reviewer running across reboots.

4. Open a pull request in any repository the app is installed on.
   The first review appears within a few minutes.
   Pull requests that were already open when hawksight first started are skipped until their next commit or a `/hawksight` comment.

## Day-to-day

- Logs: `tail -f ~/Library/Logs/hawksight.log`.
- Restart after changing the code: `launchctl kickstart -k gui/$(id -u)/com.hawksight.listener`.
- Force a re-review: comment `/hawksight`, or delete the PR's entry from `~/.hawksight/reviewed.json`.
- Uninstall: `launchctl bootout gui/$(id -u)/com.hawksight.listener && rm ~/Library/LaunchAgents/com.hawksight.listener.plist`, then delete `~/.hawksight` and the app in your GitHub settings.

## How it works

- `listener.py` polls GitHub every 60 seconds for open pull requests on the app owner's repositories.
  A new commit, a `/hawksight` comment, or your reply in a finding's thread starts a review.
- It shallow-fetches the PR into `~/.hawksight/<owner>__<repo>` and builds the context with repomix: the full contents of the changed files, a list of every tracked file, and signatures for the rest of the repository.
  The prompt is capped at about 24k tokens so the answer fits the model's 32k window.
- `review.py` numbers the diff lines, asks the model for findings and for a verdict on each earlier finding, and then verifies every new finding with a second call.
  The verification prompt shares the review prompt's prefix, so Ollama reuses its cache and each check takes about 5 seconds.
- `gh_api.py` mints a one-hour installation token from the app key on every poll, then posts inline comments, replies, resolves threads, edits the summary and sets the commit status.
- A failed review (network error, or a model answer that loops or ignores the format) retries on the next two polls, then waits for a new commit or a `/hawksight` comment.
  A broken answer is never posted as a clean review.
- Findings live on GitHub.
  Inline comments carry a hidden `<!-- hawksight:finding ... -->` marker, and every reviewer comment carries `<!-- hawksight -->`.

## Files

| File | Purpose |
|---|---|
| `listener.py` | Poll loop, PR checkout, repository context, and applying a review to the PR |
| `review.py` | Numbered diff, prompts, model calls, output parser, verification, score, and comment bodies |
| `gh_api.py` | GitHub App token and the GitHub REST and GraphQL calls |
| `create_app.py` | One-time creation of your GitHub App from a manifest |
| `install.sh` | Dependency checks, model build, and the LaunchAgent |
| `Modelfile` | The `hawksight` Ollama model: base model, context size, temperature, system prompt |

## Choosing the model

The default is MiMo-V2.6 Distill 9B, which caught 4 of 5 planted bugs on an M3 Pro with 18 GB, with no visible stutter.
See [docs/benchmark.md](docs/benchmark.md) for the comparison against Mellum2.1 12B, Qwen3.5 9B and qwen2.5-coder.
To try another model, change `FROM` in `Modelfile` and rerun `ollama create hawksight -f Modelfile`.
With more memory, a larger model such as Qwen3.6-35B-A3B should review noticeably better.

## Limits

- A 9B model still produces some false positives and misses some bugs, especially on large diffs.
  The verification pass removes most of the noise, but it cannot add bugs the review missed.
- Diffs larger than about 75,000 characters leave no room for repository context and can overflow the model's window.
- Reviews take 1 to 3 minutes each, one at a time.
- macOS only, because of the LaunchAgent.
  `listener.py` itself runs anywhere Python and Ollama do.
- Tested on personal accounts.
  Organization installs should work but are untested.

## Development

`python3 review.py` runs the self-check: diff numbering, score, finding markers, and the output and verdict parsers.

## License

[MIT](LICENSE)
