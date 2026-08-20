# MCX EOD Strategy

MCX Silver end-of-day option strategy project with a direct MCX API downloader,
editable strategy settings, interactive trade monitoring, and DuckDB-backed MTM reporting.

## Start the strategy

```powershell
python "backend\StategyRules.py"
```

## Start the UI

Double-click the Desktop shortcut:

```text
MCX EOD Strategy.lnk
```

The shortcut runs `launch_mcx_eod_strategy.vbs` invisibly. It starts the local
Python API bridge and Vite frontend, finds the next available ports, waits for
both services to respond, and opens the UI in the browser. The UI currently
includes a data-status and download-window page, a trade-entry preview page,
and an editable settings page.

The bridge endpoints currently include:

- `/api/health`
- `/api/status`
- `/api/settings`
- `/api/strategy/preview?date=YYYY-MM-DD`

The UI is a basic control surface for the existing workflow. The downloader
itself remains available from the console so its interactive progress and
worker messages stay visible during a long MCX API run.

The strategy uses major SILVER futures only to identify the daily Silver price
and ATM strike. The actual trade, target, stop-loss, averaging, MTM, and exit
calculations use the selected SILVERM option contract.

The current rules include:

- Automatic `SELL CE` or `SELL PE` selection from the Silver entry candle.
- ATM rounding below 200,000 by 1,000 and at/above 200,000 by 5,000.
- Target distance below premium 4,000: 500 points; 4,000–8,000: 1,000 points; above 8,000: 1,500 points.
- Initial option stop-loss at the entry-date option High.
- Maximum one averaging position.
- Quantity 10 when Silver is at or below 200,000; quantity 5 above 200,000.
- Day-wise open-position and MTM recording in DuckDB and CSV.

Trade settings are stored in `config/strategy_settings.json`.

Generated strategy files are kept locally in `data/outputs` and are excluded from Git.

## Update market data

```powershell
python "backend\MCX Data Downloader.py"
```

The console will:

1. Ask you to select an MCX instrument from `config/instruments.json`.
2. Ask for the commodity or symbol, defaulting to `SILVERM`.
3. Detect the existing output CSV and offer to download pending dates from the last stored date through a latest date you provide.
4. Otherwise ask for a start date and end date.
5. Download official MCX option data through the direct HTTP API.
6. Download major `FUTCOM / SILVER` futures for the same date range into a separate CSV. Mini contracts such as `SILVERM` futures are excluded.
7. Apply the 90-calendar-day rule only to options. Futures are downloaded expiry-to-expiry and deduplicated by Date + Symbol + Expiry.

Before saving, the CSV is cleaned by removing rows with zero volume or blank Open/High/Low values. The saved columns are exactly:

```text
Date, Symbol, Expiry, Option Type, Strike Price, Open, High, Low, Close, Volume
```

`Date` and `Expiry` are written as `dd-mmm-yy`, for example `02-Jan-25`.

The futures file contains one valid major-SILVER contract row per trade date and expiry, with these columns:

```text
Date, Symbol, Expiry, Open, High, Low, Close, Volume, Open Interest
```

The console stays compact, shows each expiry-window request as it runs, and shows the total time taken when the run finishes. Downloads are processed in memory; no raw download, state, or log files are created. The downloader calls MCX directly over HTTP and does not open Chrome or any browser window.

The MCX page exposes a JSON commodity-wise endpoint. The downloader obtains the page request token over HTTP and uses that endpoint directly, so Chrome and Playwright are not required.

When more than 16 expiry windows are required, the downloader automatically uses parallel API workers, with no more than eight workers at once.

## Folders:

- `backend` — the single downloader Python file.
- `frontend` — Vite + React UI.
- `data/inputs` — local downloaded option and major-SILVER futures CSV files.
- `data/outputs` — local strategy CSV, MTM CSV, and DuckDB files.
- `config` — available MCX instruments and defaults.
