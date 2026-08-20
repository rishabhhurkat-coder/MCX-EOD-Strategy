"""
MCX Silver option strategy engine.

This is a separate strategy program. It does not modify Trade Setup.py or
MCX Data Downloader.py.

Run from the project folder:
    python "backend\\StategyRules.py"

All values that may need to be changed later are in:
    config/strategy_settings.json
"""

from __future__ import annotations

import json
import math
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import duckdb


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_FILE = PROJECT_ROOT / "config" / "strategy_settings.json"

TRADE_COLUMNS = [
    "Date",
    "Expiry",
    "Option Type",
    "Strike Price",
    "Entry Reason",
    "Entry Date",
    "Entry Price",
    "Target Price",
    "Stop Loss Price",
    "Exit Reason",
    "Exit Date",
    "Exit Price",
    "Max MTM",
    "Min MTM",
    "PL Points",
    "PL Amount",
    "Quantity",
]

MTM_COLUMNS = [
    "Trade ID",
    "Date",
    "MTM Date",
    "Position No",
    "Entry Reason",
    "Entry Date",
    "Expiry",
    "Option Type",
    "Strike Price",
    "Quantity",
    "Entry Price",
    "Market Close",
    "Mark Price",
    "Position Status",
    "Position Open",
    "Target Price",
    "Stop Loss Price",
    "MTM Points",
    "MTM Amount",
    "Total MTM Points",
    "Total MTM Amount",
    "Exit Reason",
    "Exit Date",
]

CONSOLE_COLORS = {
    "reset": "\033[0m",
    "red": "\033[91m",
    "green": "\033[92m",
    "yellow": "\033[93m",
    "cyan": "\033[96m",
    "blue": "\033[94m",
    "white": "\033[97m",
    "dim": "\033[90m",
}
COLORS_ENABLED = False


def load_settings() -> dict:
    if not CONFIG_FILE.exists():
        raise FileNotFoundError(f"Settings file not found: {CONFIG_FILE}")

    with CONFIG_FILE.open("r", encoding="utf-8") as handle:
        settings = json.load(handle)

    settings.setdefault("paths", {})
    settings.setdefault("market", {})
    settings.setdefault("strategy", {})
    settings.setdefault("console", {})
    return settings


def configure_console(settings: dict) -> None:
    global COLORS_ENABLED
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass
    console = settings.get("console", {})
    COLORS_ENABLED = bool(console.get("use_colors", True)) and (
        sys.stdout.isatty() or bool(console.get("force_colors", False))
    )


def paint(value: str, color: str) -> str:
    text = str(value)
    if not COLORS_ENABLED or color not in CONSOLE_COLORS:
        return text
    return f"{CONSOLE_COLORS[color]}{text}{CONSOLE_COLORS['reset']}"


def side_color(direction: str, option_type: str) -> str:
    if direction == "SELL" and option_type == "CE":
        return "red"
    if direction == "SELL" and option_type == "PE":
        return "green"
    return "yellow"


def side_text(direction: str, option_type: str) -> str:
    return paint(side_label(direction, option_type), side_color(direction, option_type))


def side_label(direction: str, option_type: str) -> str:
    if direction == "BUY" and option_type == "PE":
        return "SELL PE"
    return f"{direction} {option_type}"


def event_color(event_name: str) -> str:
    return {
        "TARGET": "green",
        "SL": "red",
        "STOPLOSS": "red",
        "AVERAGING": "yellow",
        "EOD": "cyan",
    }.get(event_name.upper(), "cyan")


def cell_value(cell) -> str:
    return str(cell[0] if isinstance(cell, tuple) else cell)


def cell_color(cell):
    return cell[1] if isinstance(cell, tuple) and len(cell) > 1 else None


def table_widths(headers, rows) -> list[int]:
    values = [[str(header) for header in headers]]
    values.extend([[cell_value(cell) for cell in row] for row in rows])
    return [max(len(row[index]) for row in values) for index in range(len(headers))]


def table_border(widths, left, middle, right) -> str:
    return left + middle.join("─" * (width + 2) for width in widths) + right


def table_row(row, widths) -> str:
    cells = []
    for cell, width in zip(row, widths):
        value = cell_value(cell)
        color = cell_color(cell)
        rendered = value.ljust(width)
        cells.append(paint(rendered, color) if color else rendered)
    return "│ " + " │ ".join(cells) + " │"


def print_table(headers, rows, header_color="cyan") -> None:
    widths = table_widths(headers, rows)
    print(table_border(widths, "┌", "┬", "┐"))
    print(table_row([(header, header_color) for header in headers], widths))
    print(table_border(widths, "├", "┼", "┤"))
    for row in rows:
        print(table_row(row, widths))
    print(table_border(widths, "└", "┴", "┘"))


DAILY_HEADERS = ["Date", "From Entry", "Side", "Entry", "Open", "High", "Low", "Close", "SL", "Target", "Status"]
DAILY_WIDTHS = [10, 11, 10, 12, 12, 12, 12, 12, 12, 12, 30]


def print_daily_header() -> None:
    print(table_border(DAILY_WIDTHS, "┌", "┬", "┐"))
    print(table_row([(header, "cyan") for header in DAILY_HEADERS], DAILY_WIDTHS))
    print(table_border(DAILY_WIDTHS, "├", "┼", "┤"))


def resolve_path(settings: dict, name: str) -> Path:
    value = settings["paths"][name]
    path = Path(value)
    return path if path.is_absolute() else PROJECT_ROOT / path


def display_date(value, settings: dict) -> str:
    if value is None or pd.isna(value):
        return ""
    return pd.Timestamp(value).strftime(settings["strategy"]["date_display_format"])


def compact_date(value) -> str:
    timestamp = pd.Timestamp(value)
    return f"{timestamp.day}-{timestamp.month}-{timestamp.year % 100:02d}"


def parse_user_date(value):
    value = str(value).strip()
    if not value:
        return None

    parsed = pd.to_datetime(value, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        parsed = pd.to_datetime(value, errors="coerce", dayfirst=False)
    if pd.isna(parsed):
        return None
    return pd.Timestamp(parsed).normalize()


def confirm(prompt: str) -> bool:
    answer = input(f"{paint(prompt, 'cyan')} [Y/N]: ").strip().upper()
    return answer in {"", "Y", "YES"}


def number(value):
    return pd.to_numeric(value, errors="coerce")


def parse_dates(values):
    return pd.to_datetime(
        values,
        format="mixed",
        errors="coerce",
        dayfirst=True,
    ).dt.normalize()


def round_atm(value: float, interval: float) -> float:
    """Round to the nearest strike interval; an exact tie uses the lower strike."""
    if interval <= 0:
        raise ValueError("market.strike_interval must be greater than zero")

    scaled = float(value) / interval
    lower = math.floor(scaled)
    upper = lower + 1
    lower_distance = scaled - lower
    upper_distance = upper - scaled
    return float(lower * interval if lower_distance <= upper_distance else upper * interval)


def atm_interval_for_price(value: float, settings: dict) -> float:
    rounding = settings["market"].get("atm_rounding", {})
    threshold = float(rounding.get("price_threshold", 200000))
    if float(value) < threshold:
        return float(rounding.get("interval_below_threshold", 1000))
    return float(rounding.get("interval_at_or_above_threshold", 5000))


def target_points_for_premium(premium: float, settings: dict) -> float:
    rules = settings["strategy"].get("target_rules", {})
    if float(premium) < float(rules.get("premium_below", 3000)):
        return float(rules.get("target_below", 500))
    if float(premium) <= float(rules.get("premium_middle_upper", 7500)):
        return float(rules.get("target_middle", 1000))
    return float(rules.get("target_above", 1500))


def quantity_for_silver_price(silver_price: float, settings: dict) -> int:
    rules = settings["market"].get("quantity_rules", {})
    threshold = float(rules.get("silver_price_threshold", 200000))
    if float(silver_price) > threshold:
        return int(rules.get("quantity_above", 5))
    return int(rules.get("quantity_below_or_equal", 10))


def load_silver(settings: dict) -> pd.DataFrame:
    path = resolve_path(settings, "silver_futures_csv")
    if not path.exists():
        raise FileNotFoundError(f"Silver futures file not found: {path}")

    df = pd.read_csv(path, low_memory=False)
    df.columns = df.columns.astype(str).str.strip()
    required = ["Date", "Open", "High", "Low", "Close"]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Silver futures file is missing: {missing}")

    futures_symbol = str(settings["market"]["futures_symbol"]).strip().upper()
    simplified_futures = "Symbol" not in df.columns or "Expiry" not in df.columns
    if "Symbol" not in df.columns:
        df["Symbol"] = futures_symbol
    df["Symbol"] = df["Symbol"].astype(str).str.strip().str.upper()
    df = df[df["Symbol"] == futures_symbol].copy()
    df["Date"] = parse_dates(df["Date"])
    if "Expiry" in df.columns:
        df["Expiry"] = parse_dates(df["Expiry"])
    else:
        df["Expiry"] = df["Date"]

    for column in ["Open", "High", "Low", "Close"]:
        df[column] = number(df[column])
    if "Volume" in df.columns:
        df["Volume"] = number(df["Volume"])
    else:
        df["Volume"] = 0.0

    df = df.dropna(subset=required).copy()
    if not simplified_futures:
        allow_expiry_day = bool(settings["strategy"].get("allow_expiry_day", False))
        if allow_expiry_day:
            df = df[df["Expiry"] >= df["Date"]]
        else:
            df = df[df["Expiry"] > df["Date"]]

    selection = str(settings["market"].get("contract_selection", "nearest_expiry")).lower()
    if selection == "highest_volume":
        sort_columns = ["Date", "Volume", "Expiry"]
        ascending = [True, False, True]
    else:
        sort_columns = ["Date", "Expiry", "Volume"]
        ascending = [True, True, False]

    daily = (
        df.sort_values(sort_columns, ascending=ascending, kind="stable")
        .drop_duplicates("Date", keep="first")
        .sort_values("Date")
        .reset_index(drop=True)
    )
    daily["ATM Strike"] = daily["Close"].map(
        lambda value: round_atm(value, atm_interval_for_price(value, settings))
    )
    return daily


def load_options(settings: dict) -> pd.DataFrame:
    path = resolve_path(settings, "options_csv")
    if not path.exists():
        raise FileNotFoundError(f"Options file not found: {path}")

    df = pd.read_csv(path, low_memory=False)
    df.columns = df.columns.astype(str).str.strip()
    df = df.rename(
        columns={
            "Expiry Date": "Expiry",
            "Volume(Lots)": "Volume",
        }
    )
    required = [
        "Date",
        "Symbol",
        "Expiry",
        "Option Type",
        "Strike Price",
        "Open",
        "High",
        "Low",
        "Close",
    ]
    missing = [column for column in required if column not in df.columns]
    if missing:
        raise ValueError(f"Options file is missing: {missing}")

    option_symbol = str(settings["market"]["option_symbol"]).strip().upper()
    df["Symbol"] = df["Symbol"].astype(str).str.strip().str.upper()
    df["Option Type"] = df["Option Type"].astype(str).str.strip().str.upper()
    df = df[df["Symbol"] == option_symbol].copy()
    df["Date"] = parse_dates(df["Date"])
    df["Expiry"] = parse_dates(df["Expiry"])

    for column in ["Strike Price", "Open", "High", "Low", "Close"]:
        df[column] = number(df[column])
    if "Volume" in df.columns:
        df["Volume"] = number(df["Volume"])

    df = df.dropna(subset=required).copy()
    df = df[df["Option Type"].isin(["CE", "PE"])]
    df = (
        df.sort_values(["Date", "Expiry", "Strike Price", "Option Type"], kind="stable")
        .drop_duplicates(["Date", "Expiry", "Strike Price", "Option Type"], keep="last")
        .reset_index(drop=True)
    )
    return df


def get_silver_candle(silver: pd.DataFrame, trade_date):
    rows = silver[silver["Date"] == trade_date]
    return None if rows.empty else rows.iloc[0]


def available_expiries(options: pd.DataFrame, trade_date, settings: dict) -> list:
    rows = options[options["Date"] == trade_date]
    if not bool(settings["strategy"].get("allow_expiry_day", False)):
        rows = rows[rows["Expiry"] > trade_date]
    else:
        rows = rows[rows["Expiry"] >= trade_date]
    return rows["Expiry"].dropna().drop_duplicates().sort_values().tolist()


def find_option_row(
    options: pd.DataFrame,
    trade_date,
    expiry,
    requested_strike: float,
    option_type: str,
    allow_nearest: bool = True,
):
    rows = options[
        (options["Date"] == trade_date)
        & (options["Expiry"] == expiry)
        & (options["Option Type"] == option_type)
    ].copy()
    if rows.empty:
        return None, None

    exact = rows[rows["Strike Price"] == requested_strike]
    if not exact.empty:
        row = exact.iloc[0]
        return row, float(row["Strike Price"])
    if not allow_nearest:
        return None, None

    rows["_distance"] = (rows["Strike Price"] - requested_strike).abs()
    rows = rows.sort_values(["_distance", "Strike Price"], kind="stable")
    row = rows.iloc[0].drop(labels="_distance")
    return row, float(row["Strike Price"])


def select_expiry(options: pd.DataFrame, trade_date, requested_strike: float, option_type: str, settings: dict):
    expiries = available_expiries(options, trade_date, settings)
    if not expiries:
        return None, None, None

    current = expiries[0]
    switch_days = int(settings["strategy"]["expiry_switch_days"])
    days_left = (current - trade_date).days
    if days_left > switch_days or len(expiries) == 1:
        row, strike = find_option_row(options, trade_date, current, requested_strike, option_type)
        return (current, strike, row) if row is not None else (None, None, None)

    next_expiry = expiries[1]
    current_row, current_strike = find_option_row(options, trade_date, current, requested_strike, option_type)
    next_row, next_strike = find_option_row(options, trade_date, next_expiry, requested_strike, option_type)

    print(f"\n{paint('EXPIRY SELECTION', 'cyan')}")
    print(f"1. Current: {paint(display_date(current, settings), 'yellow')} | {days_left} days | "
          f"{format_option(current_row, current_strike)}")
    print(f"2. Next   : {paint(display_date(next_expiry, settings), 'yellow')} | "
          f"{format_option(next_row, next_strike)}")
    while True:
        choice = input("Select expiry [1/2]: ").strip()
        if choice == "1" and current_row is not None:
            return current, current_strike, current_row
        if choice == "2" and next_row is not None:
            return next_expiry, next_strike, next_row
        print("That expiry is not available. Choose 1 or 2.")


def format_option(row, strike) -> str:
    if row is None:
        return "not available"
    return f"strike {float(strike):,.0f}, close {float(row['Close']):,.2f}"


def exact_option_row(options, position: dict, trade_date):
    row, actual_strike = find_option_row(
        options,
        trade_date,
        position["expiry"],
        position["strike"],
        position["option_type"],
        allow_nearest=False,
    )
    if row is None or actual_strike != position["strike"]:
        return None
    return row


def target_event(options, positions: list[dict], target: float, trade_date) -> bool:
    for position in positions:
        row = exact_option_row(options, position, trade_date)
        if row is not None and float(row["Low"]) <= target:
            return True
    return False


def stop_loss_event(options, positions: list[dict], stop_loss: float, trade_date) -> bool:
    for position in positions:
        row = exact_option_row(options, position, trade_date)
        if row is not None and float(row["High"]) >= stop_loss:
            return True
    return False


def first_available_option_row(options, positions: list[dict], trade_date):
    for position in positions:
        row = exact_option_row(options, position, trade_date)
        if row is not None:
            return row
    return None


def exit_prices(options, positions: list[dict], trade_date, target_price: float | None = None):
    prices = []
    for position in positions:
        row = exact_option_row(options, position, trade_date)
        if row is None:
            return None
        prices.append(float(target_price) if target_price is not None else float(row["Close"]))
    return prices


def calculate_hh_ll(options, positions: list[dict], exit_date):
    highs = []
    lows = []
    for position in positions:
        history = options[
            (options["Expiry"] == position["expiry"])
            & (options["Strike Price"] == position["strike"])
            & (options["Option Type"] == position["option_type"])
            & (options["Date"] > position["entry_date"])
            & (options["Date"] <= exit_date)
        ]
        highs.extend(history["High"].dropna().astype(float).tolist())
        lows.extend(history["Low"].dropna().astype(float).tolist())
    return (max(highs) if highs else np.nan, min(lows) if lows else np.nan)


def exit_reason_label(exit_reason: str) -> str:
    return {"TARGET": "Target", "SL": "StopLoss", "EOD": "EOD"}.get(exit_reason, exit_reason)


def stop_loss_on_date(sl_history: list[tuple], trade_date, settings: dict) -> float:
    active = sl_history[0][1]
    for change_date, stop_loss in sl_history:
        if change_date <= trade_date:
            active = stop_loss
    return float(active)


def build_mtm_rows(
    silver: pd.DataFrame,
    options: pd.DataFrame,
    trade_id: str,
    master_entry_date,
    positions: list[dict],
    exit_date,
    exit_reason: str,
    target: float,
    sl_history: list[tuple],
    exit_prices_for_positions: list[float],
    settings: dict,
) -> list[dict]:
    rows = []
    days = silver[
        (silver["Date"] >= master_entry_date)
        & (silver["Date"] <= exit_date)
    ]["Date"].drop_duplicates().sort_values().tolist()

    for mtm_date in days:
        day_rows = []
        total_points = 0.0
        total_amount = 0.0
        for position_no, (position, exit_price) in enumerate(
            zip(positions, exit_prices_for_positions), start=1
        ):
            if position["entry_date"] > mtm_date:
                continue

            option_row = exact_option_row(options, position, mtm_date)
            market_close = float(option_row["Close"]) if option_row is not None else np.nan
            is_exit_day = mtm_date == exit_date
            mark_price = float(exit_price) if is_exit_day else market_close
            entry_price = float(position["entry_price"])
            quantity = int(position["quantity"])
            mtm_points = entry_price - mark_price if not pd.isna(mark_price) else np.nan
            mtm_amount = mtm_points * quantity if not pd.isna(mtm_points) else np.nan
            if not pd.isna(mtm_points):
                total_points += mtm_points
                total_amount += mtm_amount

            day_rows.append({
                "Trade ID": trade_id,
                "Date": display_date(master_entry_date, settings),
                "MTM Date": display_date(mtm_date, settings),
                "Position No": position_no,
                "Entry Reason": position["entry_reason"],
                "Entry Date": display_date(position["entry_date"], settings),
                "Expiry": display_date(position["expiry"], settings),
                "Option Type": position["option_type"],
                "Strike Price": position["strike"],
                "Quantity": quantity,
                "Entry Price": entry_price,
                "Market Close": market_close,
                "Mark Price": mark_price,
                "Position Status": "CLOSED" if is_exit_day else "OPEN",
                "Position Open": not is_exit_day,
                "Target Price": target,
                "Stop Loss Price": stop_loss_on_date(sl_history, mtm_date, settings),
                "MTM Points": mtm_points,
                "MTM Amount": mtm_amount,
                "Total MTM Points": np.nan,
                "Total MTM Amount": np.nan,
                "Exit Reason": exit_reason_label(exit_reason) if is_exit_day else "",
                "Exit Date": display_date(exit_date, settings) if is_exit_day else "",
            })

        for day_row in day_rows:
            day_row["Total MTM Points"] = total_points
            day_row["Total MTM Amount"] = total_amount
        rows.extend(day_rows)
    return rows


def create_result(
    silver,
    options,
    trade_id: str,
    master_entry_date,
    positions: list[dict],
    exit_date,
    target: float,
    stop_loss_price: float,
    sl_history: list[tuple],
    exit_reason: str,
    settings: dict,
):
    exit_price_override = None
    if exit_reason == "TARGET":
        exit_price_override = target
    elif exit_reason == "SL":
        exit_price_override = stop_loss_price
    prices = exit_prices(options, positions, exit_date, exit_price_override)
    if not prices:
        return None

    mtm_rows = build_mtm_rows(
        silver,
        options,
        trade_id,
        master_entry_date,
        positions,
        exit_date,
        exit_reason,
        target,
        sl_history,
        prices,
        settings,
    )
    mtm_frame = pd.DataFrame(mtm_rows)
    max_mtm = mtm_frame["Total MTM Amount"].max() if not mtm_frame.empty else np.nan
    min_mtm = mtm_frame["Total MTM Amount"].min() if not mtm_frame.empty else np.nan
    output_reason = exit_reason_label(exit_reason)

    trade_rows = []
    for position, exit_price in zip(positions, prices):
        entry_price = float(position["entry_price"])
        pl_points = entry_price - float(exit_price)
        trade_rows.append({
            "Date": display_date(master_entry_date, settings),
            "Expiry": display_date(position["expiry"], settings),
            "Option Type": position["option_type"],
            "Strike Price": position["strike"],
            "Entry Reason": position["entry_reason"],
            "Entry Date": display_date(position["entry_date"], settings),
            "Entry Price": round(entry_price, 2),
            "Target Price": round(target, 2),
            "Stop Loss Price": round(stop_loss_price, 2),
            "Exit Reason": output_reason,
            "Exit Date": display_date(exit_date, settings),
            "Exit Price": round(float(exit_price), 2),
            "Max MTM": round(float(max_mtm), 2) if not pd.isna(max_mtm) else np.nan,
            "Min MTM": round(float(min_mtm), 2) if not pd.isna(min_mtm) else np.nan,
            "PL Points": round(pl_points, 2),
            "PL Amount": round(pl_points * int(position["quantity"]), 2),
            "Quantity": int(position["quantity"]),
        })

    return {
        "_trade_id": trade_id,
        "_trade_rows": trade_rows,
        "_mtm_rows": mtm_rows,
        "_exit_reason": output_reason,
        "PL Amount": sum(row["PL Amount"] for row in trade_rows),
        "PL Points": sum(row["PL Points"] for row in trade_rows),
        "Exit Date": display_date(exit_date, settings),
    }


def save_trades(trades: list[dict], settings: dict) -> None:
    if not trades:
        return

    csv_path = resolve_path(settings, "trades_csv")
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    frame = pd.DataFrame(trades)
    for column in TRADE_COLUMNS:
        if column not in frame.columns:
            frame[column] = np.nan
    frame = frame[TRADE_COLUMNS].copy()
    frame["_sort"] = pd.to_datetime(frame["Date"], errors="coerce", dayfirst=True)
    frame = frame.sort_values(["_sort", "Entry Date"], kind="stable").drop(columns="_sort").reset_index(drop=True)
    frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    print(paint(f"Saved trade history: {csv_path}", "green"))


def save_mtm_report(mtm_rows: list[dict], settings: dict) -> None:
    if not mtm_rows:
        return

    database_path = resolve_path(settings, "mtm_database")
    csv_path = resolve_path(settings, "mtm_csv")
    database_path.parent.mkdir(parents=True, exist_ok=True)
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    current = pd.DataFrame(mtm_rows)
    for column in MTM_COLUMNS:
        if column not in current.columns:
            current[column] = np.nan
    current = current[MTM_COLUMNS].copy()

    with duckdb.connect(str(database_path)) as connection:
        existing = pd.DataFrame()
        tables = connection.execute("SHOW TABLES").fetchall()
        if any(row[0] == "mtm_daily" for row in tables):
            existing = connection.execute("SELECT * FROM mtm_daily").fetchdf()
        combined = pd.concat([existing, current], ignore_index=True)
        combined = combined.drop_duplicates(
            ["Trade ID", "MTM Date", "Position No"],
            keep="last",
        )
        connection.register("mtm_frame", combined)
        connection.execute("CREATE OR REPLACE TABLE mtm_daily AS SELECT * FROM mtm_frame")
        escaped_csv_path = str(csv_path).replace("'", "''")
        connection.execute(
            f"COPY mtm_daily TO '{escaped_csv_path}' (HEADER, DELIMITER ',')"
        )

    print(paint(f"MTM database: {database_path}", "green"))
    print(paint(f"MTM report  : {csv_path}", "green"))


def load_existing_trades(settings: dict) -> list[dict]:
    path = resolve_path(settings, "trades_csv")
    if not path.exists():
        return []
    try:
        frame = pd.read_csv(path)
        if frame.empty:
            return []
        if not set(TRADE_COLUMNS).issubset(frame.columns):
            print(paint("Legacy trade CSV detected; it will be rebuilt in the new format.", "yellow"))
            return []
        return frame.to_dict(orient="records")
    except Exception as exc:
        print(f"Could not read existing trade history: {exc}")
        return []


def show_entry(trade_date, silver_row, option_row, direction, option_type, expiry, strike, price, target, sl, quantity, settings):
    print(f"\n{paint('=' * 72, 'cyan')}")
    print(paint("TRADE ENTRY SETUP", "cyan"))
    print(paint("=" * 72, "cyan"))
    print_table(
        ["ATM Lookup | Silver", "Value"],
        [
            [("Date", "cyan"), (display_date(trade_date, settings), "yellow")],
            [("Close", "cyan"), (f"{silver_row['Close']:,.2f}", "white")],
            [("ATM | Used Strike", "cyan"), (f"{silver_row['ATM Strike']:,.0f} | {strike:,.0f}", "yellow")],
        ],
    )
    print(paint("TRADED OPTION | SHORT POSITION", "cyan"))
    print_table(
        ["Field", "Value"],
        [
            [("Direction", "cyan"), (side_label(direction, option_type), side_color(direction, option_type))],
            [("Expiry", "cyan"), (display_date(expiry, settings), "yellow")],
            [("Contract", "cyan"), (option_type, side_color(direction, option_type))],
            [("Open", "cyan"), (f"{option_row['Open']:,.2f}", "white")],
            [("High", "cyan"), (f"{option_row['High']:,.2f}", "yellow")],
            [("Low", "cyan"), (f"{option_row['Low']:,.2f}", "white")],
            [("Close", "cyan"), (f"{option_row['Close']:,.2f}", "white")],
            [("Entry Price", "cyan"), (f"{price:,.2f}", "cyan")],
            [("Target Price", "cyan"), (f"{target:,.2f}", "green")],
            [("Option Stop Loss", "cyan"), (f"{sl:,.2f}", "red")],
            [("Quantity", "cyan"), (quantity, "yellow")],
        ],
    )
    print(paint("=" * 72, "cyan"))


def show_event(event_name, trade_date, candle, positions, target, sl, settings):
    color = event_color(event_name)
    print(f"\n{paint('-' * 72, color)}")
    print(paint(f"TRADE EVENT: {event_name} | {display_date(trade_date, settings)}", color))
    print(paint('-' * 72, color))
    print_table(
        ["Traded Option | Candle", "Value"],
        [
            [("Date", "cyan"), (display_date(trade_date, settings), "yellow")],
            [("Open", "cyan"), (f"{candle['Open']:,.2f}", "white")],
            [("High", "cyan"), (f"{candle['High']:,.2f}", "yellow")],
            [("Low", "cyan"), (f"{candle['Low']:,.2f}", "white")],
            [("Close", "cyan"), (f"{candle['Close']:,.2f}", "white")],
            [("Active Stop Loss", "cyan"), (f"{sl:,.2f}", "red")],
            [("Active Target", "cyan"), (f"{target:,.2f}", "green")],
        ],
    )
    position_rows = []
    for number, position in enumerate(positions, start=1):
        position_rows.append([
            number,
            display_date(position["expiry"], settings),
            f"{position['strike']:,.0f}",
            (position["option_type"], color),
            (f"{position['entry_price']:,.2f}", "cyan"),
            position["quantity"],
        ])
    print(paint("OPEN POSITIONS", "cyan"))
    print_table(["No.", "Expiry", "Strike", "Type", "Entry", "Qty"], position_rows)


def choose_event(events: list[str]) -> str:
    if len(events) == 1:
        return events[0]
    print(f"\n{paint('MULTIPLE EVENTS ON ONE DAILY CANDLE', 'yellow')}")
    print(paint("Daily OHLC cannot prove which happened first.", "yellow"))
    for number, event in enumerate(events, start=1):
        print(f"{number}. {paint(event, event_color(event))}")
    while True:
        choice = input("Which event happened first? ").strip()
        if choice.isdigit() and 1 <= int(choice) <= len(events):
            return events[int(choice) - 1]
        print("Choose one of the displayed event numbers.")


def averaging_state(
    trigger_active: bool,
    current_high: float,
    original_high: float,
    current_close: float,
    previous_day_low: float,
) -> tuple[bool, bool]:
    """Apply the two-stage averaging rule and return (state, trade_event)."""
    trigger_active = trigger_active or current_high > original_high
    trade_event = trigger_active and current_close < previous_day_low
    return trigger_active, trade_event


def show_daily_candle(
    trade_date,
    option_row,
    direction,
    option_type,
    entry_date,
    average_entry,
    target,
    stop_loss,
    events,
    averaging_triggered,
    settings,
):
    if not bool(settings.get("console", {}).get("show_daily_candles", True)):
        return

    if events:
        status = " + ".join(events)
        status_color = event_color(events[0]) if len(events) == 1 else "yellow"
    else:
        status = "MONITORING"
        status_color = "dim"
    trigger = " | AVG TRIGGER ACTIVE" if averaging_triggered else ""
    row = [
        (compact_date(trade_date), "cyan"),
        (str((pd.Timestamp(trade_date) - pd.Timestamp(entry_date)).days), "white"),
        (side_label(direction, option_type), side_color(direction, option_type)),
        (f"{average_entry:,.0f}", "cyan"),
        f"{option_row['Open']:,.0f}",
        (f"{option_row['High']:,.0f}", "yellow"),
        f"{option_row['Low']:,.0f}",
        f"{option_row['Close']:,.0f}",
        (f"{stop_loss:,.0f}", "red"),
        (f"{target:,.0f}", "green"),
        (f"{status}{trigger}", status_color),
    ]
    print(table_row(row, DAILY_WIDTHS))
    print(table_border(DAILY_WIDTHS, "├", "┼", "┤"))


def next_trade_id(trades: list[dict], trade_date) -> str:
    prefix = f"T{pd.Timestamp(trade_date):%Y%m%d}-"
    return f"{prefix}{time.time_ns() % 1_000_000:06d}"


def process_trade(
    silver: pd.DataFrame,
    options: pd.DataFrame,
    trade_date,
    trade_id: str,
    settings: dict,
):
    silver_row = get_silver_candle(silver, trade_date)
    if silver_row is None:
        print(paint("No Silver candle exists for that date.", "red"))
        return None

    open_price = float(silver_row["Open"])
    close_price = float(silver_row["Close"])
    requested_atm = float(silver_row["ATM Strike"])

    if close_price == open_price:
        print(paint("Skipped: Silver Open equals Close.", "yellow"))
        return None
    if close_price < open_price:
        direction, option_type = "SELL", "CE"
    else:
        direction, option_type = "SELL", "PE"

    print(f"\n{paint('=' * 72, 'cyan')}")
    print(paint(f"TRADE START | {display_date(trade_date, settings)}", "cyan"))
    print(f"Signal     : {side_text(direction, option_type)}")
    print(paint("=" * 72, "cyan"))

    expiry, strike, option_row = select_expiry(options, trade_date, requested_atm, option_type, settings)
    if option_row is None:
        print(paint("No matching entry option was found for this date.", "red"))
        return None

    entry_price = float(option_row["Close"])
    target_points = target_points_for_premium(entry_price, settings)
    target = entry_price - target_points
    stop_loss = float(option_row["High"])
    quantity = quantity_for_silver_price(close_price, settings)
    show_entry(
        trade_date,
        silver_row,
        option_row,
        direction,
        option_type,
        expiry,
        strike,
        entry_price,
        target,
        stop_loss,
        quantity,
        settings,
    )
    if not confirm("Confirm entry?"):
        print(paint("Entry cancelled.", "yellow"))
        return None

    print(f"\n{paint('TRADE ACTIVE - DAILY EVENT MONITORING', 'green')}")
    print(f"Position: {side_text(direction, option_type)} | "
          f"Expiry {display_date(expiry, settings)} | Strike {strike:,.0f}")
    show_daily_table = bool(settings.get("console", {}).get("show_daily_candles", True))
    if show_daily_table:
        print_daily_header()

    positions = [{
        "expiry": expiry,
        "strike": strike,
        "option_type": option_type,
        "entry_date": trade_date,
        "entry_price": entry_price,
        "entry_reason": "Original trade",
        "quantity": quantity,
    }]
    original_high = float(option_row["High"])
    previous_day_low = float(option_row["Low"])
    averaging_triggered = False
    averaging_done = False
    sl_history = [(trade_date, stop_loss)]

    future_silver = silver[silver["Date"] > trade_date].sort_values("Date")
    for _, silver_candle in future_silver.iterrows():
        current_date = silver_candle["Date"]
        option_candle = first_available_option_row(options, positions, current_date)
        if option_candle is None:
            continue
        current_high = float(option_candle["High"])
        current_close = float(option_candle["Close"])

        is_target = target_event(options, positions, target, current_date)
        is_sl = stop_loss_event(options, positions, stop_loss, current_date)

        if not averaging_done:
            old_triggered = averaging_triggered
            averaging_triggered, is_averaging = averaging_state(
                averaging_triggered,
                current_high,
                original_high,
                current_close,
                previous_day_low,
            )
            if averaging_triggered and not old_triggered:
                print(
                    f"Averaging trigger active from {display_date(current_date, settings)} "
                    f"(High crossed original High {paint(f'{original_high:,.2f}', 'yellow')})."
                )
        else:
            is_averaging = False

        events = []
        if is_target:
            events.append("TARGET")
        if is_sl:
            events.append("SL")
        if is_averaging:
            events.append("AVERAGING")

        show_daily_candle(
            current_date,
            option_candle,
            direction,
            option_type,
            trade_date,
            float(np.mean([p["entry_price"] for p in positions])),
            target,
            stop_loss,
            events,
            averaging_triggered,
            settings,
        )

        if events:
            if show_daily_table:
                print(table_border(DAILY_WIDTHS, "└", "┴", "┘"))
            selected = choose_event(events)
            if selected in {"TARGET", "SL"}:
                show_event(selected, current_date, option_candle, positions, target, stop_loss, settings)
                if confirm(f"Proceed with {selected} exit?"):
                    result = create_result(
                        silver,
                        options,
                        trade_id,
                        trade_date,
                        positions,
                        current_date,
                        target,
                        stop_loss,
                        sl_history,
                        selected,
                        settings,
                    )
                    if result is None:
                        print(paint("Exact option contract close is unavailable; trade remains open.", "yellow"))
                    else:
                        return result
                else:
                    print(paint("Exit declined; trade continues.", "yellow"))

            elif selected == "AVERAGING":
                current_atm = float(silver_candle["ATM Strike"])
                avg_expiry, avg_strike, avg_row = select_expiry(
                    options, current_date, current_atm, option_type, settings
                )
                if avg_row is None:
                    print(paint("Averaging skipped: current ATM option is unavailable.", "yellow"))
                else:
                    avg_price = float(avg_row["Close"])
                    new_sl = current_high
                    average_entry = float(np.mean([p["entry_price"] for p in positions] + [avg_price]))
                    target_points = target_points_for_premium(average_entry, settings)
                    new_target = average_entry - target_points
                    print(f"\n{paint('AVERAGING SETUP', 'yellow')} | {display_date(current_date, settings)}")
                    print(f"New contract : {display_date(avg_expiry, settings)} {paint(f'{avg_strike:,.0f} {option_type}', side_color(direction, option_type))}")
                    print(f"Entry price  : {avg_price:,.2f}")
                    print(f"New target   : {paint(f'{new_target:,.2f}', 'green')}")
                    print(f"New Option SL: {paint(f'{new_sl:,.2f}', 'red')} (averaging candle High)")
                    if confirm("Proceed with averaging?"):
                        positions.append({
                            "expiry": avg_expiry,
                            "strike": avg_strike,
                            "option_type": option_type,
                            "entry_date": current_date,
                            "entry_price": avg_price,
                            "entry_reason": "Averaging",
                            "quantity": quantity_for_silver_price(current_close, settings),
                        })
                        averaging_done = True
                        stop_loss = new_sl
                        target = new_target
                        sl_history.append((current_date, new_sl))
                        print(paint("Averaging confirmed. No further averaging is allowed.", "green"))
                    else:
                        print(paint("Averaging declined; trade continues.", "yellow"))

        previous_day_low = float(option_candle["Low"])

    if show_daily_table:
        print(table_border(DAILY_WIDTHS, "└", "┴", "┘"))
    eod_date = future_silver.iloc[-1]["Date"] if not future_silver.empty else trade_date
    eod_prices = exit_prices(options, positions, eod_date)
    if not eod_prices:
        print(paint("Trade remains open: exact option data is unavailable for EOD exit.", "yellow"))
        return None

    eod_option_candle = first_available_option_row(options, positions, eod_date)
    if eod_option_candle is None:
        print(paint("Trade remains open: exact option data is unavailable for EOD display.", "yellow"))
        return None
    show_event("EOD", eod_date, eod_option_candle, positions, target, stop_loss, settings)
    if not confirm("Close trade at EOD?"):
        print(paint("Trade left open by user.", "yellow"))
        return None
    return create_result(
        silver,
        options,
        trade_id,
        trade_date,
        positions,
        eod_date,
        target,
        stop_loss,
        sl_history,
        "EOD",
        settings,
    )


def show_final_result(result: dict) -> None:
    pl_color = "green" if float(result["PL Amount"]) >= 0 else "red"
    trade_rows = result["_trade_rows"]
    first_row = trade_rows[0]
    print(f"\n{paint('=' * 72, pl_color)}")
    print(paint("TRADE CLOSED", pl_color))
    print(paint("=" * 72, pl_color))
    print(f"Trade date  : {first_row['Date']}")
    print(f"Exit reason : {paint(result['_exit_reason'], event_color(result['_exit_reason'].upper()))}")
    for row in trade_rows:
        print(f"{row['Entry Reason']}: {row['Entry Date']} entry {row['Entry Price']:,.2f} -> "
              f"exit {row['Exit Price']:,.2f} | qty {row['Quantity']} | "
              f"PL {row['PL Points']:+,.2f} pts | {row['PL Amount']:+,.2f}")
    print(f"Max MTM    : {first_row['Max MTM']:,.2f} | Min MTM {first_row['Min MTM']:,.2f}")
    print(f"Final P/L  : {paint(f'{result['PL Points']:+,.2f} points | {result['PL Amount']:+,.2f}', pl_color)}")
    print(paint("=" * 72, pl_color))


def main() -> None:
    started = time.perf_counter()
    try:
        settings = load_settings()
        configure_console(settings)
        print(f"\n{paint('MCX SILVER OPTION STRATEGY', 'cyan')}")
        print(f"Settings: {CONFIG_FILE}")
        print(f"{paint('RED = SELL CE', 'red')} | {paint('GREEN = SELL PE', 'green')} | "
              f"{paint('CYAN = flow/data', 'cyan')} | {paint('YELLOW = decision', 'yellow')}")
        silver = load_silver(settings)
        options = load_options(settings)
    except Exception as exc:
        print(paint(f"\nERROR: {exc}", "red"))
        return

    trades = load_existing_trades(settings)
    saved_trade_dates = len({str(row.get("Date", "")) for row in trades if row.get("Date")})
    print(f"{paint('DATA READY', 'green')} | Silver days: {len(silver):,} | "
          f"Option rows: {len(options):,} | Saved trades: {saved_trade_dates:,}")

    while True:
        value = input(f"\n{paint('TRADE DATE (or EXIT)', 'cyan')}: ").strip()
        if value.upper() in {"EXIT", "QUIT", "Q"}:
            break
        trade_date = parse_user_date(value)
        if trade_date is None:
            print(paint("Enter a valid date, for example 20-08-2026.", "red"))
            continue
        trade_id = next_trade_id(trades, trade_date)
        result = process_trade(silver, options, trade_date, trade_id, settings)
        if result is not None:
            trades.extend(result["_trade_rows"])
            save_trades(trades, settings)
            save_mtm_report(result["_mtm_rows"], settings)
            show_final_result(result)
        if not confirm("Enter another trade?"):
            break

    print(paint(f"\nStrategy engine closed. Time taken: {time.perf_counter() - started:.2f} seconds", "cyan"))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nStopped by user.")
    except Exception as exc:
        print(f"\nERROR: {exc}")
        sys.exit(1)
