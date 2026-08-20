"""Local API bridge for the MCX EOD Strategy React interface."""

from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse


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


def futures_chart_payload() -> dict:
    rules = strategy_module()
    settings = load_json(CONFIG_FILE)
    daily = rules.load_silver(settings)
    candles = []
    for _, row in daily.iterrows():
        candles.append({
            "time": row["Date"].strftime("%Y-%m-%d"),
            "open": float(row["Open"]),
            "high": float(row["High"]),
            "low": float(row["Low"]),
            "close": float(row["Close"]),
            "volume": float(row["Volume"]),
            "expiry": row["Expiry"].strftime("%d-%m-%Y"),
        })
    return {
        "symbol": settings["market"].get("futures_symbol", "SILVER"),
        "contract_selection": settings["market"].get("contract_selection", "nearest_expiry"),
        "candles": candles,
    }


def strategy_module():
    path = PROJECT_ROOT / "backend" / "StategyRules.py"
    spec = importlib.util.spec_from_file_location("mcx_strategy_rules", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load strategy rules")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def entry_preview(date_value: str) -> dict:
    rules = strategy_module()
    settings = load_json(CONFIG_FILE)
    # Browser date inputs return ISO dates.  Parse that format explicitly so
    # 2025-01-06 cannot be interpreted as 1 June by a day-first parser.
    try:
        parsed_iso = datetime.strptime(str(date_value).strip(), "%Y-%m-%d")
        trade_date = rules.parse_user_date(parsed_iso.strftime("%d-%m-%Y"))
    except ValueError:
        trade_date = rules.parse_user_date(date_value)
    if trade_date is None:
        raise ValueError("Enter a valid trade date")

    silver = rules.load_silver(settings)
    options = rules.load_options(settings)
    silver_row = rules.get_silver_candle(silver, trade_date)
    if silver_row is None:
        raise ValueError("No Silver candle exists for this date")

    silver_open = float(silver_row["Open"])
    silver_close = float(silver_row["Close"])
    if silver_close == silver_open:
        return {
            "date": date_value,
            "status": "SKIP",
            "reason": "Silver Open equals Close",
        }

    option_type = "CE" if silver_close < silver_open else "PE"
    direction = "SELL"
    requested_atm = float(silver_row["ATM Strike"])
    expiries = rules.available_expiries(options, trade_date, settings)
    if not expiries:
        raise ValueError("No unexpired option expiry is available for this date")
    expiry = expiries[0]
    option_row, actual_strike = rules.find_option_row(
        options, trade_date, expiry, requested_atm, option_type
    )
    if option_row is None:
        raise ValueError("No matching option contract is available for this date")

    entry_price = float(option_row["Close"])
    target_points = rules.target_points_for_premium(entry_price, settings)
    quantity = rules.quantity_for_silver_price(silver_close, settings)
    return {
        "date": trade_date.strftime("%d-%m-%Y"),
        "status": "READY",
        "direction": direction,
        "option_type": option_type,
        "silver": {
            "open": silver_open,
            "high": float(silver_row["High"]),
            "low": float(silver_row["Low"]),
            "close": silver_close,
            "atm": requested_atm,
        },
        "contract": {
            "expiry": expiry.strftime("%d-%m-%Y"),
            "requested_strike": requested_atm,
            "strike": float(actual_strike),
            "open": float(option_row["Open"]),
            "high": float(option_row["High"]),
            "low": float(option_row["Low"]),
            "close": entry_price,
        },
        "entry_price": entry_price,
        "target_points": target_points,
        "target_price": entry_price - target_points,
        "stop_loss_price": float(option_row["High"]),
        "quantity": quantity,
    }


def save_settings(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ValueError("Settings body must be a JSON object")
    required = {"paths", "market", "strategy", "console"}
    if not required.issubset(payload):
        raise ValueError("Settings object is missing one or more configuration sections")
    temporary = CONFIG_FILE.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.replace(CONFIG_FILE)
    return payload


class BridgeHandler(BaseHTTPRequestHandler):
    server_version = "MCXEODBridge/1.0"

    def log_message(self, format, *args):
        return

    def send_json(self, payload: dict, status: int = 200) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed = urlparse(self.path)
        route = parsed.path.rstrip("/") or "/"
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
            elif route == "/api/market/futures":
                self.send_json(futures_chart_payload())
            elif route == "/api/strategy/preview":
                date_value = parse_qs(parsed.query).get("date", [""])[0]
                self.send_json(entry_preview(date_value))
            else:
                self.send_json({"error": "Not found"}, 404)
        except Exception as exc:
            self.send_json({"error": str(exc)}, 500)

    def do_PUT(self):
        route = urlparse(self.path).path.rstrip("/") or "/"
        if route != "/api/settings":
            self.send_json({"error": "Not found"}, 404)
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            self.send_json({"status": "saved", "settings": save_settings(payload)})
        except Exception as exc:
            self.send_json({"error": str(exc)}, 400)


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
