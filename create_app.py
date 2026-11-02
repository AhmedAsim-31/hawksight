"""One-time setup: creates your hawksight GitHub App from a manifest and saves its key to ~/.hawksight.

Usage: python3 create_app.py <app-name>   (GitHub App names are global, e.g. hawksight-<your-handle>)
"""
import html
import json
import os
import sys
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

PORT = 8765
DIR = os.path.expanduser("~/.hawksight")


def manifest(name):
    return {
        "name": name,
        "url": "https://github.com/AhmedAsim-31/hawksight",
        "description": "Local AI PR reviewer. Runs on its owner's machine; code never leaves it.",
        "redirect_url": f"http://localhost:{PORT}/callback",
        "public": False,
        "default_permissions": {"contents": "read", "pull_requests": "write", "issues": "write",
                                "statuses": "write", "metadata": "read"},
        "default_events": [],
    }


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        url = urlparse(self.path)
        if url.path == "/callback":
            code = parse_qs(url.query)["code"][0]
            req = Request(f"https://api.github.com/app-manifests/{code}/conversions", method="POST")
            with urlopen(req, timeout=30) as r:
                app = json.load(r)
            os.makedirs(DIR, mode=0o700, exist_ok=True)
            with open(os.open(f"{DIR}/app.pem", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                f.write(app["pem"])
            with open(f"{DIR}/app.json", "w") as f:
                json.dump({"id": app["id"], "slug": app["slug"], "owner": app["owner"]["login"]}, f)
            install = f'{app["html_url"]}/installations/new'
            body = f'Created {app["slug"]}. Now <a href="{install}">install it</a> on your repositories.'
            print(f"Created {app['slug']} (id {app['id']}). Install it: {install}", flush=True)
            self.server.done = True
        else:
            body = ('<form id="f" method="post" action="https://github.com/settings/apps/new">'
                    f'<input type="hidden" name="manifest" value="{html.escape(json.dumps(self.server.manifest))}">'
                    '</form><script>document.getElementById("f").submit()</script>')
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    server.manifest, server.done = manifest(sys.argv[1]), False
    print(f"Opening http://localhost:{PORT}/ ; click Create GitHub App on the page that loads.", flush=True)
    webbrowser.open(f"http://localhost:{PORT}/")
    while not server.done:
        server.handle_request()
