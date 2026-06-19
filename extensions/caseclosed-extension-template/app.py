from __future__ import annotations

import base64
import csv
import io
import json
import os
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler
from http.server import ThreadingHTTPServer
from urllib.error import HTTPError
from urllib.parse import parse_qs
from urllib.parse import urlencode
from urllib.parse import urlparse
from urllib.request import Request
from urllib.request import urlopen


API_BASE_URL = os.environ.get("CASECLOSED_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
TOKEN = os.environ.get("CASECLOSED_EXTENSION_TOKEN", "")
PORT = int(os.environ.get("CASECLOSED_EXTENSION_PORT", "8765"))


def caseclosed_request(path: str, *, method: str = "GET", payload: dict[str, object] | None = None) -> object:
    data = None
    headers = {"X-CaseClosed-Extension-Token": TOKEN}
    if payload is not None:
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        headers["Content-Type"] = "application/json"
    request = Request(f"{API_BASE_URL}{path}", data=data, headers=headers, method=method)
    with urlopen(request, timeout=30) as response:
        body = response.read().decode("utf-8")
    decoded = json.loads(body)
    if not decoded.get("ok"):
        raise RuntimeError(decoded)
    return decoded["data"]


def build_mail_summary_csv(mails: list[dict[str, object]]) -> bytes:
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["received_at", "from_address", "subject", "importance", "snippet"])
    for mail in mails:
        writer.writerow(
            [
                mail.get("received_at", ""),
                mail.get("from_address", ""),
                mail.get("subject", ""),
                mail.get("effective_importance", ""),
                mail.get("snippet", ""),
            ]
        )
    return output.getvalue().encode("utf-8-sig")


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path == "/":
            self.respond_html()
            return
        if parsed.path == "/api/context":
            self.respond_json(lambda: caseclosed_request("/api/v1/extension-api/context"))
            return
        if parsed.path == "/api/case":
            self.respond_json(lambda: caseclosed_request("/api/v1/extension-api/case"))
            return
        if parsed.path == "/api/files":
            self.respond_json(lambda: caseclosed_request("/api/v1/extension-api/case/files"))
            return
        if parsed.path == "/api/mails":
            self.respond_json(lambda: self.search_mails(parsed.query))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        if self.path == "/api/export-mails-csv":
            self.respond_json(self.export_mails_csv)
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def search_mails(self, query_string: str) -> object:
        params = parse_qs(query_string)
        query = {
            "q": params.get("q", [""])[0],
            "from_address": params.get("from_address", [""])[0],
            "subject": params.get("subject", [""])[0],
            "received_from": params.get("received_from", [""])[0],
            "received_to": params.get("received_to", [""])[0],
            "include_body": params.get("include_body", ["false"])[0],
            "limit": params.get("limit", ["20"])[0],
        }
        return caseclosed_request(f"/api/v1/extension-api/mails?{urlencode(query)}")

    def export_mails_csv(self) -> object:
        mails = caseclosed_request("/api/v1/extension-api/mails?limit=100")["items"]
        csv_bytes = build_mail_summary_csv(mails)
        return caseclosed_request(
            "/api/v1/extension-api/case/files",
            method="POST",
            payload={
                "filename": "caseclosed-extension-template-mails.csv",
                "content_type": "text/csv",
                "data_base64": base64.b64encode(csv_bytes).decode("ascii"),
            },
        )

    def respond_json(self, producer) -> None:
        try:
            payload = {"ok": True, "data": producer()}
            status = HTTPStatus.OK
        except HTTPError as error:
            payload = {"ok": False, "error": error.read().decode("utf-8")}
            status = HTTPStatus.BAD_GATEWAY
        except Exception as error:
            payload = {"ok": False, "error": str(error)}
            status = HTTPStatus.INTERNAL_SERVER_ERROR
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def respond_html(self) -> None:
        html = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>CaseClosed Extension Template</title>
  <style>
    body { font-family: system-ui, sans-serif; margin: 32px; color: #4d241b; background: #fff7ea; }
    main { max-width: 980px; margin: 0 auto; display: grid; gap: 18px; }
    section { border: 1px solid #e2c7a9; border-radius: 8px; padding: 16px; background: #fffaf2; }
    label { display: grid; gap: 4px; font-weight: 700; }
    input { min-height: 34px; border: 1px solid #d9b894; border-radius: 8px; padding: 6px 10px; }
    button { min-height: 36px; padding: 8px 14px; border-radius: 8px; border: 1px solid #d9b894; background: #fffdf8; font-weight: 700; }
    .grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr)); gap: 10px; }
    .actions { display: flex; flex-wrap: wrap; gap: 8px; }
    pre { padding: 16px; border: 1px solid #e2c7a9; border-radius: 8px; background: #fffdf8; overflow: auto; min-height: 220px; }
  </style>
</head>
<body>
  <main>
    <header>
      <h1>CaseClosed Extension Template</h1>
      <p>This template demonstrates CaseClosed Extension APIs without external dependencies.</p>
    </header>
    <section>
      <h2>Basic APIs</h2>
      <div class="actions">
        <button id="context">Load context</button>
        <button id="case">Load Case</button>
        <button id="files">Load Case files</button>
      </div>
    </section>
    <section>
      <h2>Mail query API</h2>
      <div class="grid">
        <label>Keyword <input id="q" /></label>
        <label>From <input id="from_address" /></label>
        <label>Subject <input id="subject" /></label>
        <label>Received from <input id="received_from" placeholder="2026-06-01T00:00:00+09:00" /></label>
        <label>Received to <input id="received_to" placeholder="2026-06-30T23:59:59+09:00" /></label>
        <label>Limit <input id="limit" type="number" min="1" max="200" value="20" /></label>
      </div>
      <div class="actions" style="margin-top: 12px;">
        <button id="mails">Search mails</button>
        <button id="export">Export current Case mails CSV</button>
      </div>
    </section>
    <pre id="output">Ready.</pre>
  </main>
  <script>
    const output = document.getElementById('output');
    async function show(url, options) {
      output.textContent = 'Working...';
      const response = await fetch(url, options);
      output.textContent = JSON.stringify(await response.json(), null, 2);
    }
    function mailQuery() {
      const params = new URLSearchParams({
        q: document.getElementById('q').value,
        from_address: document.getElementById('from_address').value,
        subject: document.getElementById('subject').value,
        received_from: document.getElementById('received_from').value,
        received_to: document.getElementById('received_to').value,
        limit: document.getElementById('limit').value || '20',
      });
      return `/api/mails?${params.toString()}`;
    }
    document.getElementById('context').addEventListener('click', () => show('/api/context'));
    document.getElementById('case').addEventListener('click', () => show('/api/case'));
    document.getElementById('files').addEventListener('click', () => show('/api/files'));
    document.getElementById('mails').addEventListener('click', () => show(mailQuery()));
    document.getElementById('export').addEventListener('click', () => show('/api/export-mails-csv', { method: 'POST' }));
  </script>
</body>
</html>
"""
        data = html.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)


if __name__ == "__main__":
    server = ThreadingHTTPServer(("127.0.0.1", PORT), Handler)
    server.serve_forever()
