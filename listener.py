import base64
import json
import os
import re
import subprocess
import tempfile
import time
import requests

GITHUB_USER = "AhmedAsim-31"
OLLAMA_URL = "http://localhost:11434/api/generate"
HOME = os.path.expanduser("~")
CACHE = f"{HOME}/.greptile-cache"
STATE_FILE = f"{CACHE}/reviewed.json"
# ponytail: 1-minute polling; switch to webhooks behind a fixed tunnel if review latency matters
POLL_SECONDS = 60
CONTEXT_LIMIT = 60000
INCLUDE = "**/*.js,**/*.ts,**/*.py,**/*.json"
IGNORE = "node_modules,build,dist,.git"
SEARCH = """query($q: String!) { search(query: $q, type: ISSUE, first: 100) {
  nodes { ... on PullRequest { number headRefOid repository { nameWithOwner } } } } }"""


def github_token():
    return subprocess.run(
        ["/opt/homebrew/bin/gh", "auth", "token", "--user", GITHUB_USER],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def open_prs(headers):
    r = requests.post("https://api.github.com/graphql", headers=headers, timeout=30, json={
        "query": SEARCH, "variables": {"q": f"is:pr is:open archived:false user:{GITHUB_USER}"}})
    r.raise_for_status()
    nodes = r.json()["data"]["search"]["nodes"]
    return {f"{n['repository']['nameWithOwner']}#{n['number']}": n["headRefOid"] for n in nodes}


def checkout_pr(full_name, ref, token):
    path = f"{CACHE}/{full_name.replace('/', '__')}"
    auth = base64.b64encode(f"x-access-token:{token}".encode()).decode()
    # Auth header via env so the token stays out of argv and .git/config.
    env = {**os.environ, "GIT_CONFIG_COUNT": "1", "GIT_CONFIG_KEY_0": "http.extraHeader",
           "GIT_CONFIG_VALUE_0": f"Authorization: Basic {auth}"}
    git = ["git", "-C", path]
    if not os.path.isdir(f"{path}/.git"):
        subprocess.run(["git", "init", "-q", path], check=True)
    subprocess.run(git + ["fetch", "-q", "--depth", "1", f"https://github.com/{full_name}.git", ref], check=True, env=env)
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
    return (context + "\n\nREST OF REPOSITORY (signatures only):\n" + rest)[:CONTEXT_LIMIT]


def set_status(full_name, sha, headers, state, description, target_url=None):
    requests.post(f"https://api.github.com/repos/{full_name}/statuses/{sha}", headers=headers, timeout=30, json={
        "state": state, "context": "local-greptile", "description": description[:140], "target_url": target_url,
    }).raise_for_status()


def review(full_name, pr_num, sha, headers, token):
    api = f"https://api.github.com/repos/{full_name}"
    set_status(full_name, sha, headers, "pending", "Reviewing with local-greptile-pro...")
    print(f"🚀 Fetching live diff for {full_name} PR #{pr_num}...", flush=True)
    diff = requests.get(f"{api}/pulls/{pr_num}", timeout=30,
                        headers={**headers, "Accept": "application/vnd.github.v3.diff"})
    diff.raise_for_status()
    git_diff = diff.text

    print(f"📁 Packing system-wide repository context for {full_name}...", flush=True)
    repo_context = "No system-wide context mapped."
    try:
        with tempfile.TemporaryDirectory() as tmp:
            path = checkout_pr(full_name, f"pull/{pr_num}/head", token)
            repo_context = build_context(path, git_diff, tmp)
    except Exception as e:
        print(f"⚠️ Repomix context extraction skipped: {e}", flush=True)

    print("🧠 Processing diff with Local Greptile-Pro Engine...", flush=True)
    combined_prompt = f"""
    SYSTEM ARCHITECTURE AND REPOSITORY CONTEXT:
    {repo_context}

    =========================================
    LIVE CHANGES (PULL REQUEST DIFF):
    {git_diff}
    """
    ollama = requests.post(OLLAMA_URL, json={"model": "local-greptile-pro", "prompt": combined_prompt, "stream": False})
    ollama.raise_for_status()
    review_markdown = ollama.json()["response"]

    print("📤 Posting findings directly onto the GitHub PR...", flush=True)
    gh = requests.post(f"{api}/issues/{pr_num}/comments", headers=headers, timeout=30,
                       json={"body": f"### 🤖 Local Greptile Review (System Aware)\n\n{review_markdown}"})
    gh.raise_for_status()
    set_status(full_name, sha, headers, "success", "Review posted", gh.json()["html_url"])
    print(f"✅ Review posted successfully to {full_name} PR #{pr_num}!", flush=True)


def save(reviewed):
    with open(STATE_FILE, "w") as f:
        json.dump(reviewed, f, indent=1)


def main():
    os.makedirs(CACHE, exist_ok=True)
    seeded = os.path.exists(STATE_FILE)
    reviewed = json.load(open(STATE_FILE)) if seeded else {}
    while True:
        try:
            token = github_token()
            headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}
            prs = open_prs(headers)
            if not seeded:
                # First start: PRs already open are marked seen so old PRs don't all get comments at once.
                reviewed, seeded = dict(prs), True
                save(reviewed)
                print(f"👀 Watching {GITHUB_USER}; {len(prs)} open PRs marked as already seen.", flush=True)
            for key, sha in prs.items():
                if reviewed.get(key) == sha:
                    continue
                full_name, num = key.split("#")
                try:
                    review(full_name, int(num), sha, headers, token)
                    reviewed[key] = sha
                    save(reviewed)
                except Exception as e:
                    print(f"❌ Review of {key} failed, retrying next poll: {e}", flush=True)
                    try:
                        set_status(full_name, sha, headers, "error", f"Review failed, retrying: {e}")
                    except Exception:
                        pass
        except Exception as e:
            print(f"❌ Poll failed: {e}", flush=True)
        time.sleep(POLL_SECONDS)


if __name__ == "__main__":
    main()
