"""Single-file MCX data downloader.

Run from the project folder with:

    python "backend/MCX Data Downloader.py"

The program uses the current official MCX commodity-wise API, processes
downloads in memory, and writes the normalized option and major-SILVER
futures CSV files to the configured local data folders. No browser window is required.
"""

from __future__ import annotations

from html import unescape
import math
import json
import logging
import os
import re
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = PROJECT_ROOT / "config" / "instruments.json"
OUTPUT_DIR = PROJECT_ROOT / "data" / "outputs"
OUTPUT_CSV = OUTPUT_DIR / "silverm_options.csv"
FUTURES_OUTPUT_CSV = PROJECT_ROOT / "data" / "inputs" / "silver_futures.csv"
FUTURES_INSTRUMENT = "FUTCOM"
FUTURES_COMMODITY = "SILVER"

NUMERIC_COLUMNS = {
    "strike_price",
    "open",
    "high",
    "low",
    "close",
    "previous_close",
    "volume_lots",
    "volume_in_thousands",
    "value_lakhs",
    "open_interest_lots",
}

KEY_COLUMNS = ["trade_date", "commodity", "expiry_date", "option_type", "strike_price"]

OUTPUT_COLUMNS = [
    "trade_date",
    "symbol",
    "expiry_date",
    "option_type",
    "strike_price",
    "open",
    "high",
    "low",
    "close",
    "volume_lots",
]

OUTPUT_HEADERS = {
    "trade_date": "Date",
    "symbol": "Symbol",
    "expiry_date": "Expiry",
    "option_type": "Option Type",
    "strike_price": "Strike Price",
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume_lots": "Volume",
}

FUTURES_COLUMNS = ["trade_date", "open", "high", "low", "close", "volume_lots"]

FUTURES_HEADERS = {
    "trade_date": "Date",
    "open": "Open",
    "high": "High",
    "low": "Low",
    "close": "Close",
    "volume_lots": "Volume",
}

FUTURES_KEY_COLUMNS = ["trade_date", "expiry_date"]


@dataclass(frozen=True)
class Settings:
    instrument: str
    commodity: str
    option_instruments: tuple[str, ...]
    mcx_url: str
    max_days_before_expiry: int
    request_delay_seconds: float
    max_retries: int
    page_timeout_seconds: int
    api_timeout_seconds: int


def load_settings() -> tuple[Settings, dict[str, Any]]:
    config = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    settings = Settings(
        instrument=str(config.get("default_instrument", "OPTFUT")).upper(),
        commodity=str(config.get("default_commodity", "SILVERM")).upper(),
        option_instruments=tuple(str(x).upper() for x in config.get("option_instruments", ["OPTFUT"])),
        mcx_url=str(config.get("mcx_url", "https://www.mcxindia.com/market-data/bhavcopy")),
        max_days_before_expiry=int(config.get("max_days_before_expiry", 90)),
        request_delay_seconds=float(config.get("request_delay_seconds", 1.0)),
        max_retries=int(config.get("max_retries", 5)),
        page_timeout_seconds=int(config.get("page_timeout_seconds", 60)),
        api_timeout_seconds=int(config.get("api_timeout_seconds", 30)),
    )
    return settings, config


def configure_logging() -> logging.Logger:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    logger = logging.getLogger("mcx_data_downloader")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    console_handler.setLevel(logging.WARNING)
    logger.addHandler(console_handler)
    return logger


def parse_date(value: str) -> date:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            pass
    raise ValueError("Use YYYY-MM-DD, for example 2025-01-01")


def ask_date(prompt: str, default: date | None = None) -> date:
    suffix = f" [{default.isoformat()}]" if default else ""
    while True:
        raw = input(f"{prompt}{suffix}: ").strip()
        if not raw and default:
            return default
        try:
            return parse_date(raw)
        except ValueError as exc:
            print(f"Invalid date. {exc}")


def choose_instrument(config: dict[str, Any], default: str) -> str:
    instruments = [str(x).upper() for x in config.get("option_instruments", [])]
    print("\nAvailable MCX option instruments:")
    for index, instrument in enumerate(instruments, 1):
        marker = " (default)" if instrument == default else ""
        print(f"  {index}. {instrument}{marker}")
    while True:
        raw = input(f"Select Instrument [{default}]: ").strip().upper()
        if not raw:
            return default
        if raw.isdigit() and 1 <= int(raw) <= len(instruments):
            return instruments[int(raw) - 1]
        if raw in instruments:
            return raw
        print("Please enter an instrument number or name from the list.")


def ask_yes_no(prompt: str, default: bool = True) -> bool:
    suffix = "Y/n" if default else "y/N"
    while True:
        raw = input(f"{prompt} [{suffix}]: ").strip().lower()
        if not raw:
            return default
        if raw in {"y", "yes"}:
            return True
        if raw in {"n", "no"}:
            return False
        print("Please answer y or n.")


def clean_for_output(frame: pd.DataFrame) -> pd.DataFrame:
    """Apply the final CSV cleaning and schema requested by the user."""
    if frame.empty:
        return pd.DataFrame(columns=list(OUTPUT_HEADERS.values()))
    output = frame.copy()
    for field in ("open", "high", "low", "close", "strike_price", "volume_lots"):
        output[field] = pd.to_numeric(output[field], errors="coerce")
    output = output[output["volume_lots"].fillna(0).gt(0)]
    output = output[output[["open", "high", "low"]].notna().all(axis=1)]
    output = output[OUTPUT_COLUMNS].copy()
    output["trade_date"] = pd.to_datetime(output["trade_date"], errors="coerce").dt.strftime("%d-%b-%y")
    output["expiry_date"] = pd.to_datetime(output["expiry_date"], errors="coerce").dt.strftime("%d-%b-%y")
    output = output.rename(columns=OUTPUT_HEADERS)
    return output.reset_index(drop=True)


def atomic_write_csv(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = clean_for_output(frame)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", mode="w", encoding="utf-8", newline="", delete=False) as handle:
        output.to_csv(handle, index=False)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)
    return output


def clean_futures_for_output(frame: pd.DataFrame) -> pd.DataFrame:
    """Keep one major-SILVER candle per date using the earliest expiry."""
    if frame.empty:
        return pd.DataFrame(columns=list(FUTURES_HEADERS.values()))
    output = frame.copy()
    for field in ("open", "high", "low", "close", "volume_lots", "open_interest_lots"):
        if field in output.columns:
            output[field] = pd.to_numeric(output[field], errors="coerce")
    output = output[output["volume_lots"].fillna(0).gt(0)]
    output = output[output[["open", "high", "low", "close"]].notna().all(axis=1)]
    output["trade_date"] = pd.to_datetime(output["trade_date"], errors="coerce")
    output["expiry_date"] = pd.to_datetime(output["expiry_date"], errors="coerce")
    output = output.dropna(subset=["trade_date", "expiry_date"])
    output = output.sort_values(["trade_date", "expiry_date"], kind="stable")
    output = output.drop_duplicates("trade_date", keep="first")
    output = output[FUTURES_COLUMNS].copy()
    output["trade_date"] = pd.to_datetime(output["trade_date"], errors="coerce").dt.strftime("%d-%b-%y")
    output = output.rename(columns=FUTURES_HEADERS)
    return output.reset_index(drop=True)


def atomic_write_futures_csv(frame: pd.DataFrame, path: Path) -> pd.DataFrame:
    path.parent.mkdir(parents=True, exist_ok=True)
    output = clean_futures_for_output(frame)
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", mode="w", encoding="utf-8", newline="", delete=False) as handle:
        output.to_csv(handle, index=False)
        temp_path = Path(handle.name)
    os.replace(temp_path, path)
    return output


def parse_numeric(value: Any, logger: logging.Logger, field: str) -> float | None:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return None
    text = str(value).strip().replace(",", "")
    if not text:
        return None
    if not re.fullmatch(r"[-+]?\d+(?:\.\d+)?(?:\s+[A-Za-z]+.*)?", text):
        logger.warning("Malformed numeric value in %s: %s", field, text)
        return None
    match = re.match(r"[-+]?\d+(?:\.\d+)?", text)
    return float(match.group(0)) if match else None


def normalize_date(value: Any) -> str | None:
    text = str(value or "").strip()
    for fmt in ("%d %b %Y", "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def normalize_expiry(value: Any) -> str | None:
    text = str(value or "").strip().upper()
    for fmt in ("%d%b%Y", "%d-%b-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date().isoformat()
        except ValueError:
            pass
    return None


def parse_api_rows(payload: dict[str, Any], logger: logging.Logger) -> pd.DataFrame:
    if not payload.get("IsSuccess", False):
        raise ValueError(str(payload.get("Message") or "MCX API request failed"))
    rows: list[dict[str, Any]] = []
    for item in payload.get("Data", []):
        row: dict[str, Any] = {
            "trade_date": normalize_date(item.get("DateDisplay") or item.get("Date")),
            "instrument": str(item.get("InstrumentName", "")).strip().upper(),
            "symbol": str(item.get("Symbol", "")).strip().upper(),
            "expiry_date": normalize_expiry(item.get("ExpiryDate")),
            "option_type": str(item.get("OptionType", "")).strip().upper(),
            "strike_price": item.get("StrikePrice"),
            "open": item.get("Open"),
            "high": item.get("High"),
            "low": item.get("Low"),
            "close": item.get("Close"),
            "previous_close": item.get("PreviousClose"),
            "volume_lots": item.get("Volume"),
            "volume_in_thousands": item.get("VolumeInThousands"),
            "value_lakhs": item.get("Value"),
            "open_interest_lots": item.get("OpenInterest"),
            "settlement_price": None,
        }
        row["commodity"] = row["symbol"]
        for field in NUMERIC_COLUMNS:
            row[field] = parse_numeric(row.get(field), logger, field)
        rows.append(row)
    return pd.DataFrame(rows)


def read_existing_output() -> pd.DataFrame:
    if not OUTPUT_CSV.exists() or OUTPUT_CSV.stat().st_size == 0:
        return pd.DataFrame()
    try:
        output = pd.read_csv(OUTPUT_CSV)
        cleaned_headers = {value: key for key, value in OUTPUT_HEADERS.items()}
        if "Date" in output.columns:
            output = output.rename(columns=cleaned_headers)
            output["instrument"] = "OPTFUT"
            output["commodity"] = output["symbol"].astype(str).str.strip().str.upper()
            output["settlement_price"] = None
        for field in ("trade_date", "expiry_date"):
            if field in output.columns:
                output[field] = pd.to_datetime(output[field], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
        return output
    except Exception:
        return pd.DataFrame()


def read_existing_futures_output() -> pd.DataFrame:
    if not FUTURES_OUTPUT_CSV.exists() or FUTURES_OUTPUT_CSV.stat().st_size == 0:
        return pd.DataFrame()
    try:
        output = pd.read_csv(FUTURES_OUTPUT_CSV)
        cleaned_headers = {
            **{value: key for key, value in FUTURES_HEADERS.items()},
            "Symbol": "symbol",
            "Expiry": "expiry_date",
            "Open Interest": "open_interest_lots",
        }
        if "Date" in output.columns:
            output = output.rename(columns=cleaned_headers)
            output["instrument"] = FUTURES_INSTRUMENT
            output["commodity"] = FUTURES_COMMODITY
            output["option_type"] = "-"
            output["strike_price"] = 0.0
            output["settlement_price"] = None
        if "expiry_date" not in output.columns:
            # New six-column output has already selected its earliest expiry.
            # A same-day placeholder keeps the existing-data path compatible
            # with the internal downloader schema during the next run.
            output["expiry_date"] = output["trade_date"]
        for field in ("trade_date", "expiry_date"):
            if field in output.columns:
                output[field] = pd.to_datetime(output[field], errors="coerce", format="mixed").dt.strftime("%Y-%m-%d")
        return output
    except Exception:
        return pd.DataFrame()


def apply_filters(
    frame: pd.DataFrame,
    instrument: str,
    commodity: str,
    start_date: date,
    end_date: date,
    max_days: int | None,
    option_instrument: bool,
    key_columns: list[str] | None = None,
) -> pd.DataFrame:
    if frame.empty:
        return frame.copy()
    output = frame.copy()
    output["trade_date"] = pd.to_datetime(output["trade_date"], errors="coerce").dt.date
    output["expiry_date"] = pd.to_datetime(output["expiry_date"], errors="coerce").dt.date
    output = output[output["trade_date"].notna() & output["expiry_date"].notna()]
    output = output[(output["trade_date"] >= start_date) & (output["trade_date"] <= end_date)]
    output = output[(output["instrument"] == instrument) & (output["commodity"] == commodity)]
    if option_instrument:
        output = output[output["option_type"].isin(["CE", "PE"])]
    output["days_before_expiry"] = (output["expiry_date"] - output["trade_date"]).map(lambda value: value.days)
    output = output[output["days_before_expiry"] >= 0]
    if max_days is not None:
        output = output[output["days_before_expiry"] <= max_days]
    output = output.sort_values(["trade_date", "expiry_date", "option_type", "strike_price"], kind="stable")
    output = output.drop_duplicates(key_columns or KEY_COLUMNS, keep="last").reset_index(drop=True)
    return output


def validation_report(frame: pd.DataFrame, max_days: int, instrument: str, commodity: str) -> dict[str, Any]:
    if frame.empty:
        return {"rows": 0, "unique_expiries": 0, "unique_trade_dates": 0, "ce_rows": 0, "pe_rows": 0, "duplicate_rows": 0, "90_day_violations": 0, "wrong_instrument": 0, "wrong_commodity": 0}
    trade = pd.to_datetime(frame["trade_date"], errors="coerce")
    expiry = pd.to_datetime(frame["expiry_date"], errors="coerce")
    days = (expiry - trade).dt.days
    return {
        "rows": int(len(frame)),
        "unique_expiries": int(frame["expiry_date"].nunique()),
        "unique_trade_dates": int(frame["trade_date"].nunique()),
        "unique_strikes": int(frame["strike_price"].nunique()),
        "ce_rows": int((frame["option_type"] == "CE").sum()),
        "pe_rows": int((frame["option_type"] == "PE").sum()),
        "earliest_trade_date": str(frame["trade_date"].min()),
        "latest_trade_date": str(frame["trade_date"].max()),
        "earliest_expiry": str(frame["expiry_date"].min()),
        "latest_expiry": str(frame["expiry_date"].max()),
        "duplicate_rows": int(frame.duplicated(KEY_COLUMNS, keep=False).sum()),
        "90_day_violations": int(((days < 0) | (days > max_days)).sum()),
        "wrong_instrument": int((frame["instrument"] != instrument).sum()),
        "wrong_commodity": int((frame["commodity"] != commodity).sum()),
    }


class MCXClient:
    def __init__(self, settings: Settings, logger: logging.Logger):
        self.settings = settings
        self.logger = logger
        self.session = requests.Session()
        self.token: str | None = None
        self.page_html: str | None = None
        self.api_url = f"{settings.mcx_url.rstrip('/')}/GetCommoditywiseBhavCopy"
        self.page_headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
            "Upgrade-Insecure-Requests": "1",
            "sec-ch-ua-platform": '"Windows"',
            "sec-ch-ua": '"Not=A?Brand";v="99", "Google Chrome";v="151", "Chromium";v="151"',
            "sec-ch-ua-mobile": "?0",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
            "Sec-Fetch-User": "?1",
        }

    def __enter__(self) -> "MCXClient":
        response = None
        for attempt in range(1, self.settings.max_retries + 1):
            try:
                response = self.session.get(
                    self.settings.mcx_url,
                    headers=self.page_headers,
                    timeout=self.settings.page_timeout_seconds,
                )
                response.raise_for_status()
                break
            except requests.RequestException as exc:
                if attempt >= self.settings.max_retries:
                    raise
                wait_seconds = min(8, 2 ** (attempt - 1))
                print(
                    f"MCX connection slow ({attempt}/{self.settings.max_retries}). "
                    f"Retrying in {wait_seconds}s...",
                    flush=True,
                )
                self.logger.warning("MCX page request failed: %s", exc)
                time.sleep(wait_seconds)
        if response is None:
            raise RuntimeError("MCX page request did not return a response")
        page = unescape(response.text)
        self.page_html = page
        token_match = re.search(r'name="__RequestVerificationToken"[^>]*value="([^"]+)', page, re.IGNORECASE)
        if not token_match:
            raise RuntimeError("MCX did not provide an API request-verification token")
        self.token = token_match.group(1)
        return self

    def __exit__(self, *_: object) -> None:
        self.session.close()

    def discover_expiries(self, instrument: str, commodity: str) -> list[date]:
        page = self.page_html
        if page is None:
            raise RuntimeError("MCX API session is not ready")
        data_match = re.search(r'<[^>]*id="symbol-data"[^>]*>(.*?)</[^>]+>', page, re.IGNORECASE | re.DOTALL)
        if not data_match:
            raise RuntimeError("MCX page did not contain instrument and expiry metadata")
        try:
            symbol_data = json.loads(data_match.group(1).strip())
        except json.JSONDecodeError as exc:
            raise RuntimeError("MCX instrument and expiry metadata was invalid") from exc
        expiries: list[date] = []
        for item in symbol_data:
            if str(item.get("InstrumentName", "")).upper() != instrument.upper():
                continue
            if str(item.get("SymbolValue", "")).upper() != commodity.upper():
                continue
            try:
                expiries.append(datetime.strptime(str(item.get("ExpiryDate", "")).strip(), "%d%b%Y").date())
            except ValueError:
                continue
        return sorted(set(expiries))

    def download_expiry_window(self, expiry: date, from_date: date, to_date: date) -> pd.DataFrame:
        if not self.token:
            raise RuntimeError("MCX API session is not ready")
        headers = {
            **self.page_headers,
            "Referer": self.settings.mcx_url,
            "X-Requested-With": "XMLHttpRequest",
            "Accept": "application/json, text/javascript, */*; q=0.01",
            "Content-Type": "application/json",
            "__RequestVerificationToken": self.token,
        }
        params = {
            "InstrumentName": self.settings.instrument,
            "Symbol": self.settings.commodity,
            "Expiry": expiry.strftime("%d%b%Y").upper(),
            "fromDate": from_date.strftime("%d/%m/%Y"),
            "toDate": to_date.strftime("%d/%m/%Y"),
        }
        response = self.session.get(
            self.api_url,
            params=params,
            headers=headers,
            timeout=self.settings.api_timeout_seconds,
        )
        response.raise_for_status()
        try:
            payload = response.json()
        except ValueError as exc:
            raise ValueError("MCX API returned an invalid response") from exc
        frame = parse_api_rows(payload, self.logger)
        if frame.empty:
            raise ValueError(f"MCX returned no data for expiry {expiry.isoformat()}")
        return frame


def download_pending(
    settings: Settings,
    start_date: date,
    end_date: date,
    logger: logging.Logger,
    expiry_window_days: int | None,
) -> list[pd.DataFrame]:
    if start_date > end_date:
        print(f"No pending dates. Existing data already reaches {start_date - timedelta(days=1)}.")
        return []
    latest_allowed_expiry = (
        end_date + timedelta(days=expiry_window_days)
        if expiry_window_days is not None
        else None
    )
    downloaded_frames: list[pd.DataFrame] = []
    batch_started = time.perf_counter()
    print("Connecting to MCX API...", flush=True)
    with MCXClient(settings, logger) as client:
        expiries = client.discover_expiries(settings.instrument, settings.commodity)
        expiries = [
            value
            for value in expiries
            if value >= start_date
            and (latest_allowed_expiry is None or value <= latest_allowed_expiry)
        ]
        if not expiries:
            print("No matching expiry windows found.", flush=True)
            return downloaded_frames
        windows = []
        for index, expiry in enumerate(expiries, 1):
            window_start = (
                max(start_date, expiry - timedelta(days=expiry_window_days))
                if expiry_window_days is not None
                else start_date
            )
            window_end = min(end_date, expiry)
            if window_start <= window_end:
                windows.append((index, expiry, window_start, window_end))
        if not windows:
            print("No usable expiry windows found.", flush=True)
            return downloaded_frames
        worker_count = 1 if len(windows) <= 16 else min(8, math.ceil(len(windows) / 16))
        print(
            f"Found {len(windows)} expiry windows. Using {worker_count} API worker"
            f"{'s' if worker_count != 1 else ''}...",
            flush=True,
        )
        logger.info("Discovered %d expiry windows for %s/%s", len(expiries), settings.instrument, settings.commodity)
        progress_lock = threading.Lock()

        def show_progress(message: str) -> None:
            with progress_lock:
                print(message, flush=True)

        def download_chunk(worker_id: int, chunk: list[tuple[int, date, date, date]]) -> list[tuple[int, pd.DataFrame]]:
            results: list[tuple[int, pd.DataFrame]] = []
            worker_client = MCXClient(settings, logger)
            worker_client.token = client.token
            worker_client.page_html = client.page_html
            try:
                for index, expiry, window_start, window_end in chunk:
                    last_error = "unknown error"
                    request_started = time.perf_counter()
                    show_progress(
                        f"Worker {worker_id} | [{index}/{len(windows)}] {expiry:%d-%b-%Y} | "
                        f"{window_start} to {window_end} | requesting..."
                    )
                    for attempt in range(1, settings.max_retries + 1):
                        try:
                            if attempt > 1:
                                show_progress(f"Worker {worker_id} | [{index}/{len(windows)}] retry {attempt}/{settings.max_retries}...")
                            logger.info("Downloading expiry %s, window %s to %s (attempt %d)", expiry, window_start, window_end, attempt)
                            frame = worker_client.download_expiry_window(expiry, window_start, window_end)
                            results.append((index, frame))
                            elapsed = time.perf_counter() - request_started
                            logger.info("Completed expiry %s in %.2f seconds", expiry, elapsed)
                            total_elapsed = time.perf_counter() - batch_started
                            show_progress(
                                f"Worker {worker_id} | [{index}/{len(windows)}] completed | "
                                f"{len(frame):,} rows | {elapsed:.1f}s | total {total_elapsed:.1f}s"
                            )
                            break
                        except Exception as exc:
                            last_error = str(exc)
                            logger.warning("Download failed for expiry %s: %s", expiry, last_error)
                            show_progress(f"Worker {worker_id} | [{index}/{len(windows)}] failed: {last_error.replace(chr(10), ' ')[:140]}")
                            if attempt < settings.max_retries:
                                time.sleep(min(60, 2 ** (attempt - 1)))
                    else:
                        logger.error("Giving up on expiry %s", expiry)
                        show_progress(f"Worker {worker_id} | [{index}/{len(windows)}] stopped after {settings.max_retries} attempts.")
                    time.sleep(settings.request_delay_seconds)
            except Exception as exc:
                show_progress(f"Worker {worker_id} could not start: {str(exc).replace(chr(10), ' ')[:140]}")
            finally:
                worker_client.session.close()
            return results

        chunks = [windows[offset::worker_count] for offset in range(worker_count)]
        results: list[tuple[int, pd.DataFrame]] = []
        with ThreadPoolExecutor(max_workers=worker_count, thread_name_prefix="mcx-api") as executor:
            futures = [executor.submit(download_chunk, worker_id, chunk) for worker_id, chunk in enumerate(chunks, 1)]
            for future in futures:
                results.extend(future.result())
        results.sort(key=lambda item: item[0])
        downloaded_frames.extend(frame for _, frame in results)
        print(f"Completed {len(results)}/{len(windows)} expiry windows.", flush=True)
    logger.info("Download phase completed in %.2f seconds", time.perf_counter() - batch_started)
    return downloaded_frames


def rebuild_output(
    settings: Settings,
    start_date: date,
    end_date: date,
    logger: logging.Logger,
    downloaded_frames: list[pd.DataFrame] | None = None,
) -> dict[str, Any]:
    rebuild_started = time.perf_counter()
    frames = list(downloaded_frames or [])
    existing = read_existing_output()
    if not existing.empty:
        frames.append(existing)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    filtered = apply_filters(combined, settings.instrument, settings.commodity, start_date, end_date, settings.max_days_before_expiry, settings.instrument in settings.option_instruments)
    if not filtered.empty:
        filtered = filtered.sort_values(["trade_date", "expiry_date", "option_type", "strike_price"], kind="stable").reset_index(drop=True)
    cleaned = atomic_write_csv(filtered, OUTPUT_CSV)
    report = validation_report(filtered, settings.max_days_before_expiry, settings.instrument, settings.commodity)
    report["downloaded_frames"] = len(downloaded_frames or [])
    report["rows_read"] = int(len(combined))
    report["rows_before_save_cleaning"] = int(len(filtered))
    report["rows_removed_by_save_cleaning"] = int(len(filtered) - len(cleaned))
    report["rows_retained"] = int(len(cleaned))
    report["save_elapsed_seconds"] = round(time.perf_counter() - rebuild_started, 3)
    logger.info("Wrote %s with %d cleaned rows", OUTPUT_CSV, len(cleaned))
    logger.info("CSV rebuild completed in %.2f seconds", report["save_elapsed_seconds"])
    return report


def rebuild_futures_output(
    settings: Settings,
    start_date: date,
    end_date: date,
    logger: logging.Logger,
    downloaded_frames: list[pd.DataFrame] | None = None,
) -> dict[str, Any]:
    rebuild_started = time.perf_counter()
    frames = list(downloaded_frames or [])
    existing = read_existing_futures_output()
    if not existing.empty:
        frames.append(existing)
    combined = pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()
    filtered = apply_filters(
        combined,
        FUTURES_INSTRUMENT,
        FUTURES_COMMODITY,
        start_date,
        end_date,
        None,
        False,
        FUTURES_KEY_COLUMNS,
    )
    if not filtered.empty:
        filtered = filtered.sort_values(["trade_date", "expiry_date"], kind="stable").reset_index(drop=True)
    cleaned = atomic_write_futures_csv(filtered, FUTURES_OUTPUT_CSV)
    report = {
        "rows_read": int(len(combined)),
        "rows_before_save_cleaning": int(len(filtered)),
        "rows_removed_by_save_cleaning": int(len(filtered) - len(cleaned)),
        "rows_retained": int(len(cleaned)),
        "unique_expiries": int(filtered["expiry_date"].nunique()) if not filtered.empty else 0,
        "unique_trade_dates": int(filtered["trade_date"].nunique()) if not filtered.empty else 0,
        "downloaded_frames": len(downloaded_frames or []),
        "save_elapsed_seconds": round(time.perf_counter() - rebuild_started, 3),
    }
    logger.info("Wrote %s with %d cleaned rows", FUTURES_OUTPUT_CSV, len(cleaned))
    logger.info("Futures CSV rebuild completed in %.2f seconds", report["save_elapsed_seconds"])
    return report


def choose_date_range(existing: pd.DataFrame) -> tuple[date, date]:
    today = date.today()
    if not existing.empty and "trade_date" in existing.columns:
        last_date = pd.to_datetime(existing["trade_date"], errors="coerce").dt.date.max()
        if pd.notna(last_date):
            print(f"\nExisting output found: {OUTPUT_CSV}")
            print(f"Latest date already in the CSV: {last_date}")
            if ask_yes_no("Download pending dates from the next date through the latest date", True):
                latest = ask_date("Latest date to download", today)
                return last_date + timedelta(days=1), latest
    print("\nEnter the date range to download.")
    start = ask_date("Start date", date(2021, 1, 1))
    end = ask_date("End date", today)
    return start, end


def main() -> None:
    total_started = time.perf_counter()
    settings, config = load_settings()
    logger = configure_logging()
    print("\nMCX Data Downloader")
    instrument = choose_instrument(config, settings.instrument)
    commodity_default = settings.commodity
    commodity_input = input(f"Commodity/symbol [{commodity_default}]: ").strip().upper()
    commodity = commodity_input or commodity_default
    selected_settings = Settings(
        instrument=instrument,
        commodity=commodity,
        option_instruments=settings.option_instruments,
        mcx_url=settings.mcx_url,
        max_days_before_expiry=settings.max_days_before_expiry,
        request_delay_seconds=settings.request_delay_seconds,
        max_retries=settings.max_retries,
        page_timeout_seconds=settings.page_timeout_seconds,
        api_timeout_seconds=settings.api_timeout_seconds,
    )
    futures_settings = Settings(
        instrument=FUTURES_INSTRUMENT,
        commodity=FUTURES_COMMODITY,
        option_instruments=settings.option_instruments,
        mcx_url=settings.mcx_url,
        max_days_before_expiry=settings.max_days_before_expiry,
        request_delay_seconds=settings.request_delay_seconds,
        max_retries=settings.max_retries,
        page_timeout_seconds=settings.page_timeout_seconds,
        api_timeout_seconds=settings.api_timeout_seconds,
    )
    existing = read_existing_output()
    start_date, end_date = choose_date_range(existing)
    if start_date > end_date:
        print("Nothing to download: the start date is after the end date.")
        return
    existing_futures = read_existing_futures_output()
    futures_start_date = start_date
    if existing_futures.empty:
        futures_start_date = date(2021, 1, 1)
    print(f"\nOptions : {instrument} | {commodity}")
    print("Futures : FUTCOM | SILVER (major contract only)")
    print(f"Date range: {start_date} to {end_date}")
    if existing_futures.empty:
        print(f"Futures range: {futures_start_date} to {end_date} (initial backfill)")
    if not ask_yes_no("Start download", True):
        print("Cancelled.")
        return
    print("\nDownloading MCX option data through the API...", flush=True)
    option_frames = download_pending(selected_settings, start_date, end_date, logger, settings.max_days_before_expiry)
    option_report = rebuild_output(selected_settings, min(start_date, date(2021, 1, 1)), end_date, logger, option_frames)

    print("\nDownloading major SILVER futures through the API...", flush=True)
    futures_frames = download_pending(futures_settings, futures_start_date, end_date, logger, None)
    futures_report = rebuild_futures_output(
        futures_settings,
        min(futures_start_date, date(2021, 1, 1)),
        end_date,
        logger,
        futures_frames,
    )

    option_downloaded = len(option_frames)
    futures_downloaded = len(futures_frames)
    total_elapsed = time.perf_counter() - total_started
    print("\nCompleted")
    print(f"Option rows saved : {option_report['rows_retained']:,}")
    print(f"Futures rows saved: {futures_report['rows_retained']:,}")
    print(f"Option windows    : {option_downloaded}")
    print(f"Futures windows   : {futures_downloaded}")
    print(f"Time taken: {total_elapsed:.2f} seconds")
    print(f"Options output : {OUTPUT_CSV}")
    print(f"Futures output: {FUTURES_OUTPUT_CSV}")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped safely. Rerun the program to continue from the pending range.")
    except Exception as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)
