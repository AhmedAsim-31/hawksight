import base64
import json
import os
import re
import subprocess
import tempfile
import time

import review
from gh_api import BOT, SUMMARY, GitHub, app_token

GITHUB_USER = "AhmedAsim-31"
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
TRIGGER = "/hawksight"


def is_owner(comment):
    # Only the owner's comments count, so outsiders can't trigger reviews or steer the model.
    return (comment["author"] or {}).get("login") == GITHUB_USER


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
        "trigger": max((c["databaseId"] for c in comments if TRIGGER in c["body"] and BOT not in c["body"]),
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
    subprocess.run(["repomix", "--output", out, *args], cwd=path, input=stdin, text=True,
                   check=True, stdout=subprocess.DEVNULL)
    with open(out) as f:
        return f.read()


def build_context(path, git_diff, tmp):
    changed = [p for p in re.findall(r"^\+\+\+ b/(.+)$", git_diff, re.M) if os.path.isfile(f"{path}/{p}")]
    context = ""
    if changed:
        context = "CHANGED FILES (full contents):\n" + repomix(path, f"{tmp}/changed.txt", ["--stdin"], "\n".join(changed))
    rest = repomix(path, f"{tmp}/rest.txt", ["--compress", "--include", INCLUDE, "--ignore", IGNORE])
    # Every tracked path, so the model doesn't claim a referenced doc or config file is missing.
    files = subprocess.run(["git", "-C", path, "ls-files"], check=True, capture_output=True, text=True).stdout
    return (context + "\n\nALL FILES IN THE REPOSITORY:\n" + files[:8000]
            + "\n\nREST OF REPOSITORY (signatures only):\n" + rest)[:CONTEXT_LIMIT]


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
    summary_id, url = gh.upsert_summary(repo, pr, summary_id, review.summary_body(out["summary"], value, threads, sha))
    n_open = sum(not t["resolved"] for t in threads)
    gh.status(repo, sha, "success", f"Score {value}/5 · {n_open} open findings", url)
    print(f"✅ {repo} PR #{pr}: score {value}/5, {n_open} open", flush=True)
    return summary_id


def save(reviewed):
    with open(STATE_FILE, "w") as f:
        json.dump(reviewed, f, indent=1)


def main():
    os.makedirs(CACHE, exist_ok=True)
    seeded = os.path.exists(STATE_FILE)
    reviewed = json.load(open(STATE_FILE)) if seeded else {}
    while True:
        try:
            token = app_token(GITHUB_USER)
            gh = GitHub(token)
            views = {f"{n['repository']['nameWithOwner']}#{n['number']}": pr_view(n) for n in gh.open_prs(GITHUB_USER)}
            if not seeded:
                # First start: PRs already open are marked seen so old PRs don't all get comments at once.
                reviewed = {k: {"sha": v["sha"], "trigger": v["trigger"], "reply": v["reply"]} for k, v in views.items()}
                seeded = True
                save(reviewed)
                print(f"👀 Watching {GITHUB_USER}; {len(views)} open PRs marked as already seen.", flush=True)
            for key, view in views.items():
                seen = reviewed.get(key) or {}
                if isinstance(seen, str):
                    seen = {"sha": seen}
                if (seen.get("sha") == view["sha"] and view["trigger"] in (None, seen.get("trigger"))
                        and view["reply"] in (None, seen.get("reply"))):
                    continue
                repo, num = key.split("#")
                entry = {"sha": view["sha"], "trigger": view["trigger"], "reply": view["reply"],
                         "summary": seen.get("summary") or view["summary"]}
                try:
                    entry["summary"] = run_review(gh, repo, int(num), view, entry["summary"], token)
                except Exception as e:
                    # Reruns are safe (resolved threads are skipped, repeats deduped), so retry a few polls,
                    # then give up until a new commit or trigger so a deterministic failure can't loop forever.
                    fails = seen.get("fails", 0) + 1
                    print(f"❌ Review of {key} failed ({fails}/3): {e}", flush=True)
                    try:
                        gh.status(repo, view["sha"], "error", f"Review failed, comment {TRIGGER} to retry: {e}")
                    except Exception:
                        pass
                    if fails < 3:
                        reviewed[key] = {**seen, "fails": fails}
                        save(reviewed)
                        continue
                reviewed[key] = entry
                save(reviewed)
        except Exception as e:
            print(f"❌ Poll failed: {e}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
