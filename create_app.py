"""One-time setup: creates the hawksight GitHub App from a manifest and saves its key to ~/.hawksight."""
import html
import json
import os
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlparse

import requests

PORT = 8765
DIR = os.path.expanduser("~/.hawksight")
MANIFEST = {
    "name": "hawksight-bot",
    "url": "https://github.com/AhmedAsim-31/hawksight",
    "description": "Local AI PR reviewer. Runs on its owner's Mac; code never leaves it.",
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
            app = requests.post(f"https://api.github.com/app-manifests/{code}/conversions", timeout=30).json()
            os.makedirs(DIR, mode=0o700, exist_ok=True)
            with open(os.open(f"{DIR}/app.pem", os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as f:
                f.write(app["pem"])
            with open(f"{DIR}/app.json", "w") as f:
                json.dump({"id": app["id"], "slug": app["slug"]}, f)
            body = f'Created {app["slug"]}. Now <a href="{app["html_url"]}/installations/new">install it</a>.'
            print(f"CREATED {app['slug']} id={app['id']}", flush=True)
            self.server.done = True
        else:
            body = ('<form id="f" method="post" action="https://github.com/settings/apps/new">'
                    f'<input type="hidden" name="manifest" value="{html.escape(json.dumps(MANIFEST))}"></form>'
                    '<script>document.getElementById("f").submit()</script>')
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(body.encode())


if __name__ == "__main__":
    server = HTTPServer(("127.0.0.1", PORT), Handler)
    server.done = False
    webbrowser.open(f"http://localhost:{PORT}/")
    while not server.done:
        server.handle_request()
