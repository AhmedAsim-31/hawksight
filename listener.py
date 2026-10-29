import base64
import hashlib
import hmac
import os
import re
import subprocess
import tempfile
import threading
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

GITHUB_USER = "ahmedasim-31"
OLLAMA_URL = "http://localhost:11434/api/generate"
HOME = os.path.expanduser("~")
CACHE = f"{HOME}/.greptile-cache"
CONTEXT_LIMIT = 60000
INCLUDE = "**/*.js,**/*.ts,**/*.py,**/*.json"
IGNORE = "node_modules,build,dist,.git"
# ponytail: one global lock serializes reviews; per-repo locks if reviews start queueing
cache_lock = threading.Lock()
with open(f"{HOME}/.greptile_webhook_secret", "rb") as f:
    WEBHOOK_SECRET = f.read().strip()


def github_token():
    return subprocess.run(
        ["/opt/homebrew/bin/gh", "auth", "token", "--user", "AhmedAsim-31"],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def signature_ok(req):
    expected = "sha256=" + hmac.new(WEBHOOK_SECRET, req.get_data(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, req.headers.get("X-Hub-Signature-256", ""))


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


@app.route("/webhook", methods=["POST"])
def github_webhook():
    if not signature_ok(request):
        return jsonify({"status": "bad signature"}), 401
    data = request.json
    if "pull_request" not in data:
        return jsonify({"status": "ignored, not a PR event"})
    repo_owner = data["repository"]["owner"]["login"]
    if repo_owner.lower() != GITHUB_USER:
        return jsonify({"status": f"ignored, owner is {repo_owner}"})
    action = data.get("action")
    if action not in ["opened", "synchronize", "reopened"]:
        return jsonify({"status": f"ignored PR action: {action}"})

    pr_num = data["pull_request"]["number"]
    repo_name = data["repository"]["name"]
    comments_url = data["pull_request"]["comments_url"]
    token = github_token()
    headers = {
        "Authorization": f"token {token}",
        "Accept": "application/vnd.github.v3+json"
    }

    print(f"🚀 Fetching live diff for {repo_name} PR #{pr_num}...", flush=True)
    diff_response = requests.get(
        data["pull_request"]["url"],
        headers={**headers, "Accept": "application/vnd.github.v3.diff"},
    )
    if diff_response.status_code != 200:
        return jsonify({"status": "failed to fetch PR diff"}), 400
    git_diff = diff_response.text

    print(f"📁 Packing system-wide repository context for {repo_name}...", flush=True)
    repo_context = "No system-wide context mapped."
    try:
        with cache_lock, tempfile.TemporaryDirectory() as tmp:
            path = checkout_pr(data["repository"]["full_name"], f"pull/{pr_num}/head", token)
            repo_context = build_context(path, git_diff, tmp)
    except Exception as re:
        print(f"⚠️ Repomix context extraction skipped: {re}", flush=True)

    print("🧠 Processing diff with Local Greptile-Pro Engine...", flush=True)
    combined_prompt = f"""
    SYSTEM ARCHITECTURE AND REPOSITORY CONTEXT:
    {repo_context}

    =========================================
    LIVE CHANGES (PULL REQUEST DIFF):
    {git_diff}
    """

    payload = {
        "model": "local-greptile-pro",
        "prompt": combined_prompt,
        "stream": False
    }

    review_markdown = "No response generated."
    try:
        ollama_response = requests.post(OLLAMA_URL, json=payload).json()
        review_markdown = ollama_response.get("response", "No response generated.")
    except Exception as e:
        print(f"❌ Ollama error: {e}", flush=True)

    print("📤 Posting findings directly onto the GitHub PR...", flush=True)
    github_payload = {
        "body": f"### 🤖 Local Greptile Review (System Aware)\n\n{review_markdown}"
    }
    gh_response = requests.post(comments_url, json=github_payload, headers=headers)
    if gh_response.status_code == 201:
        print(f"✅ Review posted successfully to {repo_name} PR #{pr_num}!", flush=True)
        return jsonify({"status": "review posted to github"})
    else:
        print(f"❌ Failed to post comment to GitHub. Status: {gh_response.status_code}", flush=True)
        return jsonify({"status": "failed to post comment to github"}), 500

if __name__ == "__main__":
    app.run(port=5001)
