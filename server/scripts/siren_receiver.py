"""A local siren controller for testing webhooks (implementation-plan-v2 §7).

    SIREN_WEBHOOK_SECRET=... python -m scripts.siren_receiver [port]

Checks X-HUDA-Signature and the timestamp, prints each event, and replies 200 (401 on a
bad signature). Expose it with a tunnel (e.g. `cloudflared tunnel --url http://localhost:8787`)
and use the https URL as a siren's endpoint.
"""

import hmac
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

from app.services.sirens import sign

SECRET = os.environ.get("SIREN_WEBHOOK_SECRET", "")
MAX_SKEW_S = 300


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        stamp = self.headers.get("X-HUDA-Timestamp", "")
        good = (SECRET and stamp.isdigit() and abs(time.time() - int(stamp)) <= MAX_SKEW_S
                and hmac.compare_digest(sign(SECRET, stamp, body), self.headers.get("X-HUDA-Signature", "")))
        if not good:
            print("REJECTED: bad signature or timestamp")
            self.send_response(401)
            self.end_headers()
            return
        event = json.loads(body)
        print(f"{event['event']:<11} {event['zone']['name']} · max_on_s={event.get('max_on_s')} "
              f"rule={event.get('rule')} reason={event.get('reason')}")
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b'{"ok":true}')

    def log_message(self, *_):
        pass


if __name__ == "__main__":
    if not SECRET:
        sys.exit("Set SIREN_WEBHOOK_SECRET to the same value as the server")
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8787
    print(f"siren receiver on http://localhost:{port}")
    HTTPServer(("", port), Handler).serve_forever()
