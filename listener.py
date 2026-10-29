import hashlib
import hmac
import os
import subprocess
import tempfile
import requests
from flask import Flask, request, jsonify

app = Flask(__name__)

GITHUB_USER = "ahmedasim-31"
OLLAMA_URL = "http://localhost:11434/api/generate"
HOME = os.path.expanduser("~")
REPO_ROOTS = [f"{HOME}/Desktop/Work", f"{HOME}/Desktop/Work/Portfolio"]
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
    headers = {
        "Authorization": f"token {github_token()}",
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
    repo_path = next((p for p in (f"{r}/{repo_name}" for r in REPO_ROOTS) if os.path.isdir(p)), None)
    repo_context = "No system-wide context mapped."
    fd, temp_context_file = tempfile.mkstemp(suffix=".txt")
    os.close(fd)

    if repo_path:
        try:
            subprocess.run([
                "repomix", "--output", temp_context_file,
                "--include", "**/*.js,**/*.ts,**/*.py,**/*.json",
                "--ignore", "node_modules,build,dist,.git"
            ], cwd=repo_path, check=True, stdout=subprocess.DEVNULL)

            with open(temp_context_file, "r") as f:
                repo_context = f.read()[:60000]
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
    finally:
        print("🧹 Cleaning up temporary repomix files to free Mac storage...", flush=True)
        if os.path.exists(temp_context_file):
            try:
                os.remove(temp_context_file)
                print("🗑️ Temp files successfully purged.", flush=True)
            except Exception as ce:
                print(f"⚠️ Failed to delete temp file: {ce}", flush=True)

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
