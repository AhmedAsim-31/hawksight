import base64
import json
import os
import subprocess
import time

import requests

API = "https://api.github.com"
APP_DIR = os.path.expanduser("~/.hawksight")
BOT = "<!-- hawksight"
SUMMARY = "<!-- hawksight:summary -->"
SEARCH = """query($q: String!) { search(query: $q, type: ISSUE, first: 50) {
  nodes { ... on PullRequest { number headRefOid repository { nameWithOwner }
    comments(last: 50) { nodes { databaseId body author { login } } }
    reviewThreads(first: 100) { nodes { id isResolved path line
      comments(first: 50) { nodes { databaseId body url author { login } } } } } } } } }"""


def _b64(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def app_token(owner):
    """An installation token for the hawksight app, so comments post as hawksight-bot[bot] instead of the owner."""
    with open(f"{APP_DIR}/app.json") as f:
        app_id = json.load(f)["id"]
    now = int(time.time())
    claims = json.dumps({"iat": now - 60, "exp": now + 540, "iss": app_id}).encode()
    head = _b64(b'{"alg":"RS256","typ":"JWT"}') + "." + _b64(claims)
    # openssl signs the JWT so the reviewer needs no crypto dependency.
    sig = subprocess.run(["openssl", "dgst", "-sha256", "-sign", f"{APP_DIR}/app.pem"], input=head.encode(),
                         check=True, capture_output=True).stdout
    headers = {"Authorization": f"Bearer {head}.{_b64(sig)}", "Accept": "application/vnd.github+json"}
    r = requests.get(f"{API}/users/{owner}/installation", headers=headers, timeout=30)
    r.raise_for_status()
    r = requests.post(f"{API}/app/installations/{r.json()['id']}/access_tokens", headers=headers, timeout=30)
    r.raise_for_status()
    return r.json()["token"]


class GitHub:
    def __init__(self, token):
        self.headers = {"Authorization": f"token {token}", "Accept": "application/vnd.github.v3+json"}

    def call(self, method, path, **kw):
        r = requests.request(method, f"{API}{path}", headers={**self.headers, **kw.pop("headers", {})},
                             timeout=30, **kw)
        r.raise_for_status()
        return r

    def graphql(self, query, **variables):
        data = self.call("POST", "/graphql", json={"query": query, "variables": variables}).json()
        if data.get("errors"):
            raise RuntimeError(data["errors"])
        return data["data"]

    def open_prs(self, user):
        q = f"is:pr is:open archived:false user:{user}"
        return [n for n in self.graphql(SEARCH, q=q)["search"]["nodes"] if n]

    def diff(self, repo, pr):
        return self.call("GET", f"/repos/{repo}/pulls/{pr}", headers={"Accept": "application/vnd.github.v3.diff"}).text

    def status(self, repo, sha, state, description, url=None):
        self.call("POST", f"/repos/{repo}/statuses/{sha}", json={
            "state": state, "context": "hawksight", "description": description[:140], "target_url": url})

    def inline(self, repo, pr, sha, path, line, body):
        # A line outside the diff hunks is rejected by GitHub, so those findings attach to the file instead.
        where = {"line": line, "side": "RIGHT"} if line else {"subject_type": "file"}
        return self.call("POST", f"/repos/{repo}/pulls/{pr}/comments",
                         json={"commit_id": sha, "path": path, "body": body, **where}).json()

    def reply(self, repo, pr, comment_id, body):
        self.call("POST", f"/repos/{repo}/pulls/{pr}/comments/{comment_id}/replies", json={"body": body})

    def resolve(self, thread_id):
        self.graphql("mutation($id: ID!) { resolveReviewThread(input: {threadId: $id}) { thread { id } } }",
                     id=thread_id)

    def upsert_summary(self, repo, pr, comment_id, body):
        if comment_id:
            c = self.call("PATCH", f"/repos/{repo}/issues/comments/{comment_id}", json={"body": body}).json()
        else:
            c = self.call("POST", f"/repos/{repo}/issues/{pr}/comments", json={"body": body}).json()
        return c["id"], c["html_url"]
