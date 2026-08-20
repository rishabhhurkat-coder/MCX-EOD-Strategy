"""Local API bridge for the MCX EOD Strategy React interface."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config" / "strategy_settings.json"


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def csv_summary(path: Path) -> dict:
    if not path.exists():
        return {"exists": False, "rows": 0, "latest_date": None}

    rows = 0
    latest_date = None
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            rows += 1
            value = row.get("Date") or row.get("MTM Date")
            if value:
                latest_date = value
    return {"exists": True, "rows": rows, "latest_date": latest_date}


def status_payload() -> dict:
    settings = load_json(CONFIG_FILE)
    paths = settings.get("paths", {})
    resolved = {
        name: (PROJECT_ROOT / value).resolve()
        if not Path(value).is_absolute()
        else Path(value)
        for name, value in paths.items()
    }
    return {
        "app": "MCX EOD Strategy",
        "bridge": "ready",
        "market_data": {
            "options": csv_summary(resolved["options_csv"]),
            "futures": csv_summary(resolved["silver_futures_csv"]),
        },
        "reports": {
            "trades": csv_summary(resolved["trades_csv"]),
            "mtm": csv_summary(resolved["mtm_csv"]),
            "mtm_database": {
                "exists": resolved["mtm_database"].exists(),
                "path": str(resolved["mtm_database"]),
            },
        },
    }


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "MCXEODBridge/1.0"

    def log_message(self, format, *args):
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "http://127.0.0.1")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        route = urlparse(self.path).path.rstrip("/") or "/"
        try:
            if route == "/api/health":
                self.send_json({
                    "status": "ok",
                    "app": "MCX EOD Strategy",
                    "time_utc": datetime.now(timezone.utc).isoformat(),
                })
            elif route == "/api/status":
                self.send_json(status_payload())
            elif route == "/api/settings":
                self.send_json(load_json(CONFIG_FILE))
            else:
                self.send_json({"error": "Not found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, required=True)
    args = parser.parse_args()
    server = ThreadingHTTPServer((args.host, args.port), BridgeHandler)
    print(f"MCX UI bridge listening on http://{args.host}:{args.port}", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"UI bridge error: {exc}", file=sys.stderr)
        sys.exit(1)
