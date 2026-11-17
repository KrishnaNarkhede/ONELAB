"""
Pure-stdlib HTTP server — no external dependencies.
Run: python app.py  ->  http://localhost:5000
"""

import json, os, csv as _csv, subprocess, sys, re
from http.server import BaseHTTPRequestHandler, HTTPServer
from collections import defaultdict


def build_ledger(txn_file="transactions.csv", settle_file="settlements.csv"):
    txns, settles = [], defaultdict(list)
    if os.path.exists(txn_file):
        with open(txn_file, newline="") as f:
            txns = list(_csv.DictReader(f))
    if os.path.exists(settle_file):
        with open(settle_file, newline="") as f:
            for s in _csv.DictReader(f):
                settles[s["txn_id"]].append(s)
    rows = []
    for t in txns:
        tid, amt = t["txn_id"], float(t["amount"])
        slist = settles.get(tid, [])
        if slist:
            for s in slist:
                sa = float(s["amount"])
                diff = round(sa - amt, 6)
                status = "DUPLICATE" if len(slist) > 1 else ("MATCHED" if diff == 0 else "MISMATCH")
                rows.append({"txn_id": tid, "txn_amount": amt, "created_at": t["created_at"],
                             "ref_id": s["ref_id"], "settle_amount": sa,
                             "settled_at": s["settled_at"], "diff": diff, "status": status})
        else:
            rows.append({"txn_id": tid, "txn_amount": amt, "created_at": t["created_at"],
                         "ref_id": None, "settle_amount": None, "settled_at": None,
                         "diff": None, "status": "ORPHAN_REFUND" if amt < 0 else "UNSETTLED"})
    return rows


def load_html():
    path = os.path.join(os.path.dirname(__file__), "dashboard.html")
    with open(path, "rb") as f:
        return f.read()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args): pass

    def respond(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/":
            self.respond(200, "text/html; charset=utf-8", load_html())
        elif self.path == "/api/gaps":
            if not os.path.exists("transactions.csv"):
                subprocess.run([sys.executable, "generate_data.py"], check=True)
            from reconcile import reconcile
            self.respond(200, "application/json", json.dumps(reconcile()).encode())
        elif self.path == "/api/ledger":
            self.respond(200, "application/json", json.dumps(build_ledger()).encode())
        elif self.path == "/api/stats":
            count = 0
            if os.path.exists("transactions.csv"):
                with open("transactions.csv") as f:
                    count = sum(1 for _ in _csv.DictReader(f))
            self.respond(200, "application/json", json.dumps({"txn_count": count}).encode())
        else:
            self.respond(404, "text/plain", b"Not found")

    def do_POST(self):
        if self.path == "/api/upload":
            try:
                length  = int(self.headers.get("Content-Length", 0))
                body    = self.rfile.read(length)
                ctype   = self.headers.get("Content-Type", "")
                # extract boundary
                m = re.search(r'boundary=([^;\s]+)', ctype)
                if not m:
                    raise ValueError("No boundary in Content-Type")
                boundary = ("--" + m.group(1)).encode()
                parts = body.split(boundary)
                files = {}
                for part in parts[1:-1]:          # skip preamble and epilogue
                    if b'\r\n\r\n' not in part:
                        continue
                    headers_raw, content = part.split(b'\r\n\r\n', 1)
                    content = content.rstrip(b'\r\n')
                    hdr = headers_raw.decode(errors='replace')
                    nm  = re.search(r'name="([^"]+)"', hdr)
                    if nm:
                        files[nm.group(1)] = content.decode(errors='replace')
                with open("_upload_txn.csv", "w", newline="") as f:
                    f.write(files["transactions"])
                with open("_upload_set.csv", "w", newline="") as f:
                    f.write(files["settlements"])
                from reconcile import reconcile
                self.respond(200, "application/json",
                             json.dumps(reconcile("_upload_txn.csv", "_upload_set.csv")).encode())
            except Exception as e:
                self.respond(400, "text/plain", str(e).encode())
        else:
            self.respond(404, "text/plain", b"Not found")


if __name__ == "__main__":
    if not os.path.exists("transactions.csv"):
        subprocess.run([sys.executable, "generate_data.py"], check=True)
    port = int(os.environ.get("PORT", 5000))
    server = HTTPServer(("0.0.0.0", port), Handler)
    print(f"Dashboard -> http://0.0.0.0:{port}")
    server.serve_forever()
