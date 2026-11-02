import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time

import review
from gh_api import BOT, SUMMARY, GitHub, app_config, app_token

HOME = os.path.expanduser("~")
CACHE = f"{HOME}/.hawksight"
STATE_FILE = f"{CACHE}/reviewed.json"
# ponytail: 1-minute polling; switch to webhooks behind a fixed tunnel if review latency matters
POLL_SECONDS = 60
CONTEXT_LIMIT = 60000
# ~3.3 chars/token measured: keeps the prompt near 24k tokens so num_predict 6000 fits the 32k window.
PROMPT_CHARS = 75000
INCLUDE = "**/*.js,**/*.jsx,**/*.ts,**/*.tsx,**/*.astro,**/*.vue,**/*.svelte,**/*.py,**/*.go,**/*.rs,**/*.json,**/*.md,**/*.mdx,**/*.css,**/*.yml,**/*.yaml"
IGNORE = "node_modules,build,dist,.git,**/package-lock.json,**/pnpm-lock.yaml,**/yarn.lock"
OWNER = None  # the account the app reviews for; read from the app config in main()
MENTION = None  # "@<app-slug>", the comment that asks for a re-review
MENTION_RE = None


def is_owner(comment):
    # Only the owner's comments count, so outsiders can't trigger reviews or steer the model.
    return (comment["author"] or {}).get("login") == OWNER


def pr_view(node):
    """The reviewer's finding threads on a PR, plus the comment ids that should start a review."""
    threads = []
    for t in node["reviewThreads"]["nodes"]:
        cs = t["comments"]["nodes"]
        meta = review.parse_finding(cs[0]["body"]) if cs else None
        if not meta:
            continue
        last_bot = max(i for i, c in enumerate(cs) if BOT in c["body"])
        human = [c for c in cs if is_owner(c) and BOT not in c["body"]]
        threads.append({
            "id": t["id"], "root": cs[0]["databaseId"], "url": cs[0]["url"], "path": t["path"], "line": t["line"],
            "resolved": t["isResolved"], "severity": meta["severity"], "title": meta["title"],
            "body": cs[0]["body"].split("\n\n<!--")[0],
            "replies": [c["body"] for c in cs[last_bot + 1:] if c in human],
            "last_reply": max((c["databaseId"] for c in human), default=None),
        })
    comments = [c for c in node["comments"]["nodes"] if is_owner(c)]
    return {
        "sha": node["headRefOid"],
        "threads": threads,
        "trigger": max((c["databaseId"] for c in comments if MENTION_RE.search(c["body"]) and BOT not in c["body"]),
                       default=None),
        "reply": max((t["last_reply"] for t in threads if t["last_reply"]), default=None),
        "summary": next((c["databaseId"] for c in comments if SUMMARY in c["body"]), None),
    }


def checkout_pr(full_name, ref, token):
    path = f"{CACHE}/{full_name.replace('/', '__')}"
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    # Auth header via env so the token stays out of argv and .git/config.
    env = {**os.environ, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader",
           "GIT_CONFIG_VALUE_0": f"Authorization: Basic {auth}"}
    git = ["git", "-C", path]
    if not os.path.isdir(f"{path}/.git"):
        subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(git + ["fetch", "-q", "--depth", "1", f"https://github.com/{full_name}.git", ref], check=True, env=env,
                   timeout=300)
    subprocess.run(git + ["checkout", "-q", "-f", "FETCH_HEAD"], check=True)
    subprocess.run(git + ["clean", "-qfdx"], check=True)
    return path


def repomix(path, out, args, stdin=None):
    # Full path, because Windows cannot launch the repomix.cmd shim by bare name.
    # No repomix summary or tree: they list only the packed subset, and the model read that as the whole repo.
    subprocess.run([shutil.which("repomix") or "repomix", "--output", out, "--no-file-summary",
                    "--no-directory-structure", *args], cwd=path, input=stdin, text=True,
                   check=True, stdout=subprocess.DEVNULL)
    with open(out) as f:
        return f.read()


def build_context(path, git_diff, tmp):
    changed = [p for p in re.findall(r"^\+\+\+ b/(.+)$", git_diff, re.M) if os.path.isfile(f"{path}/{p}")]
    # Every tracked path first, so the model doesn't claim a referenced doc or config file is missing.
    files = subprocess.run(["git", "-C", path, "ls-files"], check=True, capture_output=True, text=True).stdout
    context = "ALL FILES IN THE REPOSITORY (complete list):\n" + files[:8000]
    if changed:
        context += "\n\nCHANGED FILES (full contents):\n" + repomix(path, f"{tmp}/changed.txt", ["--stdin"],
                                                                     "\n".join(changed))
    rest = repomix(path, f"{tmp}/rest.txt", ["--compress", "--include", INCLUDE, "--ignore", IGNORE])
    return (context + "\n\nOTHER FILES (signatures only):\n" + rest)[:CONTEXT_LIMIT]


def run_review(gh, repo, pr, view, summary_id, token):
    sha, threads = view["sha"], view["threads"]
    gh.status(repo, sha, "pending", "Reviewing...")
    print(f"🚀 Reviewing {repo} PR #{pr} at {sha[:7]}...", flush=True)
    diff = gh.diff(repo, pr)
    numbered, valid = review.number_diff(diff)
    context = "No system-wide context mapped."
    try:
        with tempfile.TemporaryDirectory() as tmp:
            context = build_context(checkout_pr(repo, f"pull/{pr}/head", token), diff, tmp)
    except Exception as e:
        print(f"⚠️ Repomix context extraction skipped: {e}", flush=True)

    # ponytail: a diff over PROMPT_CHARS alone still overflows; chunk the diff per file if that happens.
    context = context[:max(0, PROMPT_CHARS - len(numbered))]
    open_threads = {f"F{i + 1}": t for i, t in enumerate(t for t in threads if not t["resolved"])}
    existing = [{**t, "id": k} for k, t in open_threads.items()]
    print(f"🧠 Model call ({len(existing)} open findings)...", flush=True)
    out = review.run_model(review.build_prompt(context, numbered, existing))

    for item in out["existing"]:
        t = open_threads.get(item["id"])
        if not t:
            continue
        if item["status"] in ("fixed", "rebutted"):
            gh.reply(repo, pr, t["root"], review.bot(f"✅ Resolved ({item['status']}): {item['reply']}".strip()))
            gh.resolve(t["id"])
            t["resolved"] = True
        elif t["replies"] and item["reply"]:
            gh.reply(repo, pr, t["root"], review.bot(item["reply"]))

    for f in out["new"]:
        if f["path"] not in valid or f["severity"] not in review.SEVERITIES:
            continue
        line = f["line"] if f["line"] in valid[f["path"]] else None
        # ponytail: same file within 2 lines counts as a repeat (resolved ones included, so rebuttals stick);
        # compare titles too if distinct bugs on adjacent lines get swallowed.
        if any(t["path"] == f["path"] and line and t["line"] and abs(t["line"] - line) <= 2 for t in threads):
            continue
        real, reason = review.verify(context, numbered, f)
        print(f"{'✔️ kept' if real else '🗑️ dropped'} {f['severity']} {f['path']}:{f['line']} {f['title']}: {reason}",
              flush=True)
        if not real:
            continue
        c = gh.inline(repo, pr, sha, f["path"], line, review.finding_body(f))
        threads.append({"url": c["html_url"], "path": f["path"], "resolved": False,
                        "severity": f["severity"], "title": f["title"], "line": line})

    value = review.score([t["severity"] for t in threads if not t["resolved"]])
    summary_id, url = gh.upsert_summary(repo, pr, summary_id, review.summary_body(out["summary"], value, threads, sha, MENTION))
    n_open = sum(not t["resolved"] for t in threads)
    gh.status(repo, sha, "success", f"Score {value}/5 · {n_open} open findings", url)
    print(f"✅ {repo} PR #{pr}: score {value}/5, {n_open} open", flush=True)
    return summary_id


def save(reviewed):
    with open(STATE_FILE, "w") as f:
        json.dump(reviewed, f, indent=1)


def due(seen, view):
    """A PR is due when it has a commit, mention of the app or thread reply not yet reviewed."""
    return not (seen.get("sha") == view["sha"] and view["trigger"] in (None, seen.get("trigger"))
                and view["reply"] in (None, seen.get("reply")))


def update_queue(queue, due_keys):
    """First in, first out: waiting PRs keep their place and newly due ones join the back."""
    return [k for k in queue if k in due_keys] + [k for k in due_keys if k not in queue]


def queued_label(ahead):
    return "Queued: next up" if not ahead else f"Queued: {ahead} review{'s' if ahead > 1 else ''} ahead"


def main():
    global OWNER, MENTION, MENTION_RE
    app = app_config()
    OWNER, MENTION = app["owner"], f"@{app['slug']}"
    # Either "@hawksight-bot" or "@hawksightbot" works for a slug like "hawksight-bot".
    MENTION_RE = re.compile(rf"@({re.escape(app['slug'])}|{re.escape(app['slug'].replace('-', ''))})\b", re.I)
    os.makedirs(CACHE, exist_ok=True)
    seeded = os.path.exists(STATE_FILE)
    reviewed = json.load(open(STATE_FILE)) if seeded else {}
    # One review at a time; waiting PRs show their place as a pending commit status.
    queue, shown, not_before = [], {}, {}
    while True:
        try:
            token = app_token()
            gh = GitHub(token)
            views = {f"{n['repository']['nameWithOwner']}#{n['number']}": pr_view(n) for n in gh.open_prs(OWNER)}
            if not seeded:
                # First start: PRs already open are marked seen so old PRs don't all get comments at once.
                reviewed = {k: {"sha": v["sha"], "trigger": v["trigger"], "reply": v["reply"]} for k, v in views.items()}
                seeded = True
                save(reviewed)
                print(f"👀 Watching {OWNER}; {len(views)} open PRs marked as already seen.", flush=True)
            queue = update_queue(queue, [k for k, v in views.items() if due(reviewed.get(k) or {}, v)])
            for ahead, key in enumerate(queue):
                label = (views[key]["sha"], queued_label(ahead))
                if shown.get(key) != label:
                    gh.status(key.split("#")[0], label[0], "pending", label[1])
                    shown[key] = label
            ready = [k for k in queue if not_before.get(k, 0) <= time.time()]
            if not ready:
                time.sleep(POLL_SECONDS)
                continue
            key, view = ready[0], views[ready[0]]
            seen = reviewed.get(key) or {}
            repo, num = key.split("#")
            entry = {"sha": view["sha"], "trigger": view["trigger"], "reply": view["reply"],
                     "summary": seen.get("summary") or view["summary"]}
            queue.remove(key)
            shown.pop(key, None)
            try:
                entry["summary"] = run_review(gh, repo, int(num), view, entry["summary"], token)
            except Exception as e:
                # Reruns are safe (resolved threads are skipped, repeats deduped), so retry from the back of the
                # queue a few times, then give up until a new commit or trigger so a deterministic failure can't loop.
                fails = seen.get("fails", 0) + 1
                print(f"❌ Review of {key} failed ({fails}/3): {e}", flush=True)
                # A reviewer crash is not a code failure, so the status never turns the PR red.
                state, text = (("pending", f"Review failed ({fails}/3), retrying") if fails < 3 else
                               ("success", f"Not reviewed after 3 attempts; comment {MENTION} to retry"))
                try:
                    gh.status(repo, view["sha"], state, f"{text}: {e}")
                except Exception:
                    pass
                if fails < 3:
                    reviewed[key] = {**seen, "fails": fails}
                    not_before[key] = time.time() + POLL_SECONDS
                    save(reviewed)
                    continue
            reviewed[key] = entry
            save(reviewed)
        except Exception as e:
            print(f"❌ Poll failed: {e}", flush=True)
            time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    if len(sys.argv) > 1:
        # Log file for runners without a console, such as pythonw on Windows.
        sys.stdout = sys.stderr = open(sys.argv[1], "a", buffering=1)
    main()
