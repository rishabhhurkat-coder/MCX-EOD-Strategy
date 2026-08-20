import { useEffect, useMemo, useRef, useState } from 'react'
import { CandlestickSeries, HistogramSeries, LineSeries, createChart } from 'lightweight-charts'

const NAV_ITEMS = [
  { path: '/data-download', label: 'Data Download', icon: '↓' },
  { path: '/futures-chart', label: 'FUT Chart', icon: '◒' },
  { path: '/trade-entry', label: 'Trade Entry', icon: '↗' },
  { path: '/settings', label: 'Settings', icon: '⚙' },
]

const number = (value, digits = 2) => {
  if (value === null || value === undefined || value === '') return '—'
  return Number(value).toLocaleString('en-IN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}
const dateLabel = (value) => value ? new Date(`${value}T00:00:00`).toLocaleDateString('en-GB', { day: '2-digit', month: 'short', year: 'numeric' }) : '—'

async function api(path, options = {}) {
  const response = await fetch(path, { headers: { 'Content-Type': 'application/json' }, ...options })
  const payload = await response.json()
  if (!response.ok || payload.error) throw new Error(payload.error || `Request failed (${response.status})`)
  return payload
}

function AppShell({ path, navigate, health, children }) {
  const [sidebarOpen, setSidebarOpen] = useState(false)
  return <div className="app-shell">
    <aside className={`sidebar ${sidebarOpen ? 'expanded' : 'collapsed'}`}>
      <div className="brand"><div className="brand-mark">MCX</div><div className="brand-copy"><strong>EOD Strategy</strong><span>Operations Console</span></div></div>
      <div className="sidebar-label">WORKSPACE</div>
      <nav className="nav-list">{NAV_ITEMS.map((item) => <button title={item.label} key={item.path} className={`nav-item ${path === item.path ? 'active' : ''}`} onClick={() => navigate(item.path)}><span className="nav-icon">{item.icon}</span><span className="nav-label">{item.label}</span></button>)}</nav>
      <div className="sidebar-footer"><span className={`connection-dot ${health ? 'online' : ''}`} /><div className="footer-copy"><strong>{health ? 'API Connected' : 'Connecting'}</strong><span>Local strategy bridge</span></div></div>
    </aside>
    <main className={`main-content ${path === '/futures-chart' ? 'futures-main' : ''}`}><header className="topbar"><button type="button" className="menu-toggle" aria-label={sidebarOpen ? 'Collapse navigation' : 'Expand navigation'} aria-expanded={sidebarOpen} onClick={() => setSidebarOpen((open) => !open)}>M</button><span className="workspace-label">MCX / Strategy workspace</span><span className={`status-pill ${health ? 'success' : 'warning'}`}>{health ? '● ONLINE' : '○ OFFLINE'}</span></header><div className={`page-wrap ${path === '/futures-chart' ? 'futures-page-wrap' : ''}`}>{children}</div></main>
  </div>
}

function PageHeader({ eyebrow, title, subtitle, action }) { return <div className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{subtitle}</p></div>{action}</div> }
function StatCard({ label, value, detail, tone = '' }) { return <div className={`stat-card ${tone}`}><span>{label}</span><strong>{value}</strong><small>{detail}</small></div> }

function DataDownloadPage() {
  const [status, setStatus] = useState(null); const [loading, setLoading] = useState(true); const [message, setMessage] = useState('')
  const [form, setForm] = useState({ instrument: 'OPTFUT', symbol: 'SILVERM', start: '2021-01-01', end: new Date().toISOString().slice(0, 10) })
  const refresh = () => { setLoading(true); api('/api/status').then(setStatus).catch((error) => setMessage(error.message)).finally(() => setLoading(false)) }
  useEffect(refresh, [])
  const options = status?.market_data?.options || {}; const futures = status?.market_data?.futures || {}
  return <>
    <PageHeader eyebrow="MARKET DATA" title="MCX Data Download" subtitle="Manage the official Silver option and futures data used by the strategy." action={<button className="button secondary" onClick={refresh}>{loading ? 'Checking…' : 'Refresh status'}</button>} />
    {message && <div className="notice error">{message}</div>}
    <div className="stats-grid"><StatCard label="Option rows" value={number(options.rows, 0)} detail={`Latest ${options.latest_date || 'not available'}`} tone="blue" /><StatCard label="Silver futures rows" value={number(futures.rows, 0)} detail={`Latest ${futures.latest_date || 'not available'}`} tone="green" /><StatCard label="Download mode" value="API" detail="Official MCX data source" tone="purple" /></div>
    <section className="card"><div className="card-head"><div><h2>Download window</h2><p>Choose the instrument and date range for the next data run.</p></div><span className="badge neutral">READY</span></div><div className="form-grid four">
      <label className="field"><span>Instrument</span><select value={form.instrument} onChange={(e) => setForm({ ...form, instrument: e.target.value })}><option>OPTFUT</option><option>FUTCOM</option><option>FUTIDX</option><option>OPTCOM</option><option>OPTIDX</option></select></label>
      <label className="field"><span>Commodity / symbol</span><input value={form.symbol} onChange={(e) => setForm({ ...form, symbol: e.target.value.toUpperCase() })} /></label><label className="field"><span>Start date</span><input type="date" value={form.start} onChange={(e) => setForm({ ...form, start: e.target.value })} /></label><label className="field"><span>End date</span><input type="date" value={form.end} onChange={(e) => setForm({ ...form, end: e.target.value })} /></label>
    </div><div className="download-summary"><div><strong>{form.instrument}</strong><span>{form.symbol} · {dateLabel(form.start)} to {dateLabel(form.end)}</span></div><button className="button primary" onClick={() => setMessage('Download window saved. Run the MCX Data Downloader console to start the API download.')}>Prepare download</button></div></section>
    <section className="card"><div className="card-head"><div><h2>Available datasets</h2><p>Only the processed CSV files are used by the strategy.</p></div></div><table className="data-table"><thead><tr><th>Dataset</th><th>Purpose</th><th>Rows</th><th>Latest date</th><th>Status</th></tr></thead><tbody><tr><td><strong>Silver options</strong></td><td>Entry, target, stop and MTM</td><td>{number(options.rows, 0)}</td><td>{options.latest_date || '—'}</td><td><span className="badge success">{options.exists ? 'READY' : 'MISSING'}</span></td></tr><tr><td><strong>Silver futures</strong></td><td>Signal and ATM lookup</td><td>{number(futures.rows, 0)}</td><td>{futures.latest_date || '—'}</td><td><span className="badge success">{futures.exists ? 'READY' : 'MISSING'}</span></td></tr></tbody></table></section>
  </>
}

function Metric({ label, value, tone = '' }) { return <div className={`metric ${tone}`}><span>{label}</span><strong>{value}</strong></div> }

function simpleMovingAverage(values, period) {
  return values.map((item, index) => index < period - 1 ? null : { time: item.time, value: values.slice(index - period + 1, index + 1).reduce((sum, point) => sum + point.close, 0) / period }).filter(Boolean)
}

function exponentialMovingAverage(values, period) {
  if (values.length < period) return []
  const multiplier = 2 / (period + 1); let ema = values.slice(0, period).reduce((sum, point) => sum + point.close, 0) / period
  const result = [{ time: values[period - 1].time, value: ema }]
  values.slice(period).forEach((point) => { ema = (point.close - ema) * multiplier + ema; result.push({ time: point.time, value: ema }) })
  return result
}

function relativeStrengthIndex(values, period = 14) {
  if (values.length <= period) return []
  let gains = 0; let losses = 0
  for (let index = 1; index <= period; index += 1) { const change = values[index].close - values[index - 1].close; gains += Math.max(change, 0); losses += Math.max(-change, 0) }
  const result = [{ time: values[period].time, value: losses === 0 ? 100 : 100 - (100 / (1 + (gains / period) / (losses / period))) }]
  for (let index = period + 1; index < values.length; index += 1) {
    const change = values[index].close - values[index - 1].close; gains = (gains * (period - 1) + Math.max(change, 0)) / period; losses = (losses * (period - 1) + Math.max(-change, 0)) / period
    result.push({ time: values[index].time, value: losses === 0 ? 100 : 100 - (100 / (1 + gains / losses)) })
  }
  return result
}

function bollingerBands(values, period = 20, multiplier = 2) {
  const middle = []; const upper = []; const lower = []
  values.forEach((item, index) => { if (index < period - 1) return; const window = values.slice(index - period + 1, index + 1).map((point) => point.close); const average = window.reduce((sum, value) => sum + value, 0) / period; const deviation = Math.sqrt(window.reduce((sum, value) => sum + ((value - average) ** 2), 0) / period); middle.push({ time: item.time, value: average }); upper.push({ time: item.time, value: average + multiplier * deviation }); lower.push({ time: item.time, value: average - multiplier * deviation }) })
  return { middle, upper, lower }
}

function volumeWeightedAveragePrice(values) {
  let totalVolume = 0; let totalValue = 0
  return values.map((item) => { totalVolume += item.volume; totalValue += ((item.high + item.low + item.close) / 3) * item.volume; return { time: item.time, value: totalVolume ? totalValue / totalVolume : item.close } })
}

function movingAverageLine(values, period, source = 'close') {
  const points = values.map((item) => ({ time: item.time, close: source === 'close' ? item.close : item.value }))
  return exponentialMovingAverage(points, period)
}

function FuturesChartPage() {
  const chartRef = useRef(null); const gotoInputRef = useRef(null); const [data, setData] = useState([]); const [loading, setLoading] = useState(true); const [message, setMessage] = useState(''); const [range, setRange] = useState('1Y'); const [selectedTool, setSelectedTool] = useState('crosshair'); const [indicatorMenu, setIndicatorMenu] = useState(false); const [replayMode, setReplayMode] = useState(false); const [replayIndex, setReplayIndex] = useState(0); const [replayDate, setReplayDate] = useState(''); const [playing, setPlaying] = useState(false); const [speed, setSpeed] = useState('1'); const [gotoDate, setGotoDate] = useState(''); const [indicators, setIndicators] = useState({ volume: true, sma20: false, ema50: false, bb20: false, vwap: false, rsi14: false, macd: false })
  useEffect(() => { api('/api/market/futures').then((payload) => setData(payload.candles || [])).catch((error) => setMessage(error.message)).finally(() => setLoading(false)) }, [])
  useEffect(() => { const timer = window.setInterval(() => { api('/api/market/futures').then((payload) => setData(payload.candles || [])).catch(() => {}) }, 30000); return () => window.clearInterval(timer) }, [])
  useEffect(() => { if (data.length && !replayMode) setReplayIndex(data.length - 1) }, [data.length, replayMode])
  useEffect(() => { if (data[replayIndex] && (!replayMode || replayDate)) setReplayDate(data[replayIndex].time) }, [data, replayIndex, replayMode])
  const chartData = useMemo(() => replayMode && replayDate ? data.slice(0, replayIndex + 1) : data, [data, replayIndex, replayDate, replayMode])
  useEffect(() => {
    if (!chartData.length) return undefined
    const container = document.getElementById('futures-chart')
    if (!container) return undefined
    const chart = createChart(container, { autoSize: true, layout: { background: { type: 'solid', color: 'transparent' }, textColor: '#4c6e91' }, grid: { vertLines: { color: '#d9edff' }, horzLines: { color: '#d9edff' } }, rightPriceScale: { borderColor: '#a9d5f4' }, timeScale: { borderColor: '#a9d5f4', timeVisible: false, rightOffset: 5, rightBarStaysOnScroll: true, shiftVisibleRangeOnNewBar: true }, crosshair: { mode: 0 }, handleScroll: { mouseWheel: true, pressedMouseMove: true, horzTouchDrag: true, vertTouchDrag: true }, handleScale: { axisPressedMouseMove: true, mouseWheel: true, pinch: true }, kineticScroll: { mouse: true, touch: true } })
    const series = chart.addSeries(CandlestickSeries, { upColor: '#10c98a', downColor: '#ff4774', borderVisible: false, wickUpColor: '#05a873', wickDownColor: '#e62d5c' })
    series.setData(chartData.map(({ time, open, high, low, close }) => ({ time, open, high, low, close })))
    if (indicators.volume) { const volumeSeries = chart.addSeries(HistogramSeries, { priceFormat: { type: 'volume' }, priceScaleId: '' }, 1); volumeSeries.setData(chartData.map(({ time, open, close, volume }) => ({ time, value: volume, color: close >= open ? '#5ee2b4' : '#ff9aaf' }))); chart.panes()[1]?.setHeight(105) }
    if (indicators.sma20) chart.addSeries(LineSeries, { color: '#277ff1', lineWidth: 2, title: 'SMA 20' }).setData(simpleMovingAverage(chartData, 20))
    if (indicators.ema50) chart.addSeries(LineSeries, { color: '#d48b16', lineWidth: 2, title: 'EMA 50' }).setData(exponentialMovingAverage(chartData, 50))
    if (indicators.bb20) { const bands = bollingerBands(chartData); chart.addSeries(LineSeries, { color: '#71a9e7', lineWidth: 1, title: 'BB 20' }).setData(bands.upper); chart.addSeries(LineSeries, { color: '#71a9e7', lineWidth: 1, title: 'BB 20' }).setData(bands.lower); }
    if (indicators.vwap) chart.addSeries(LineSeries, { color: '#e06c9b', lineWidth: 2, title: 'VWAP' }).setData(volumeWeightedAveragePrice(chartData))
    const oscillatorPane = indicators.volume ? 2 : 1
    if (indicators.rsi14) { const rsiSeries = chart.addSeries(LineSeries, { color: '#9b63db', lineWidth: 2, title: 'RSI 14', autoscaleInfoProvider: () => ({ priceRange: { minValue: 0, maxValue: 100 } }) }, oscillatorPane); rsiSeries.setData(relativeStrengthIndex(chartData)); chart.panes()[oscillatorPane]?.setHeight(120) }
    if (indicators.macd) { const fast = movingAverageLine(chartData, 12); const slow = movingAverageLine(chartData, 26); const macd = fast.slice(fast.length - slow.length).map((item, index) => ({ time: item.time, value: item.value - slow[index].value })); const signal = movingAverageLine(macd.map((item) => ({ ...item, close: item.value })), 9, 'value'); chart.addSeries(LineSeries, { color: '#277ff1', lineWidth: 2, title: 'MACD' }, oscillatorPane).setData(macd); chart.addSeries(LineSeries, { color: '#e06c9b', lineWidth: 2, title: 'Signal' }, oscillatorPane).setData(signal); chart.panes()[oscillatorPane]?.setHeight(130) }
    const visibleCount = range === 'ALL' ? chartData.length : range === '1M' ? 22 : range === '3M' ? 66 : 252
    chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, chartData.length - visibleCount), to: chartData.length + 2 })
    chartRef.current = chart
    chart.subscribeClick((param) => { if (!replayMode || param.time === undefined) return; const index = data.findIndex((candle) => candle.time === String(param.time)); if (index >= 0) { setReplayIndex(index); setReplayDate(data[index].time) } })
    const resize = new ResizeObserver(() => chart.applyOptions({ width: container.clientWidth }))
    resize.observe(container)
    return () => { resize.disconnect(); chart.remove(); chartRef.current = null }
  }, [chartData, range, indicators, replayMode, data])
  const setIndicator = (name) => setIndicators((current) => ({ ...current, [name]: !current[name] }))
  const goToSelectedDate = () => { const target = gotoDate || replayDate; const index = chartData.findIndex((candle) => candle.time === target); if (index < 0) { setMessage('That date is not available in the FUT CSV.'); return } setMessage(''); chartRef.current?.timeScale().setVisibleLogicalRange({ from: Math.max(0, index - 45), to: Math.min(chartData.length + 2, index + 45) }) }
  const stepReplay = (amount) => { if (!data.length || !replayDate) return; setReplayMode(true); setPlaying(false); setReplayIndex((current) => Math.max(0, Math.min(data.length - 1, current + amount))) }
  const toggleReplay = () => { if (!replayMode) { setPlaying(false); setReplayIndex(data.length - 1); setReplayDate(''); setReplayMode(true) } else { setPlaying(false); setReplayDate(''); setReplayMode(false) } }
  useEffect(() => { if (!replayMode || !playing) return undefined; const timer = window.setInterval(() => setReplayIndex((current) => { if (current >= data.length - 1) { setPlaying(false); return current } return current + 1 }), Math.max(120, 750 / Number(speed))); return () => window.clearInterval(timer) }, [data.length, playing, replayMode, speed])
  useEffect(() => {
    const onKeyDown = (event) => {
      if (['INPUT', 'SELECT', 'TEXTAREA'].includes(document.activeElement?.tagName)) return
      const key = event.key.toLowerCase()
      if (key === 'r') { event.preventDefault(); toggleReplay() }
      else if (key === 'i') { event.preventDefault(); setIndicatorMenu((open) => !open) }
      else if (key === 'g') { event.preventDefault(); gotoInputRef.current?.focus() }
      else if (event.code === 'Space' && replayMode) { event.preventDefault(); setPlaying((active) => !active) }
      else if (event.key === 'ArrowLeft' && replayMode) { event.preventDefault(); stepReplay(-1) }
      else if (event.key === 'ArrowRight' && replayMode) { event.preventDefault(); stepReplay(1) }
      else if (key === '1') setRange('1M')
      else if (key === '3') setRange('3M')
      else if (key === 'y') setRange('1Y')
      else if (key === 'a') setRange('ALL')
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  })
  return <section className="chart-hero">
    {message && <div className="notice error">{message}</div>}
    <div className="chart-toolbar"><div className="chart-symbol"><strong>SILVER</strong><span>· 1D · Futures</span></div><div className="chart-actions"><div className="indicator-control"><button type="button" className={`chart-action ${indicatorMenu ? 'selected' : ''}`} onClick={() => setIndicatorMenu((open) => !open)}>Indicators <span>⌄</span></button>{indicatorMenu && <div className="indicator-menu">{[['volume', 'Volume'], ['sma20', 'SMA 20'], ['ema50', 'EMA 50'], ['bb20', 'Bollinger Bands'], ['vwap', 'VWAP'], ['rsi14', 'RSI 14'], ['macd', 'MACD']].map(([key, label]) => <label key={key}><input type="checkbox" checked={indicators[key]} onChange={() => setIndicator(key)} />{label}</label>)}</div>}</div><label className="goto-control"><span>Go to date</span><input ref={gotoInputRef} type="date" value={gotoDate} onChange={(event) => setGotoDate(event.target.value)} /><button type="button" onClick={goToSelectedDate}>↗</button></label><button type="button" className={`chart-action ${replayMode ? 'selected replay-on' : ''}`} onClick={toggleReplay}>{replayMode ? '× Exit Replay' : '▶ Replay'}</button><div className="chart-range" role="group" aria-label="Chart range">{['1M', '3M', '1Y', 'ALL'].map((item) => <button type="button" key={item} className={range === item ? 'selected' : ''} onClick={() => setRange(item)}>{item}</button>)}</div></div></div>
    {replayMode && <div className="replay-bar"><button type="button" title="Previous bar" disabled={!replayDate} onClick={() => stepReplay(-1)}>◀</button><button type="button" className="replay-play" disabled={!replayDate} title={playing ? 'Pause replay' : 'Play replay'} onClick={() => setPlaying((active) => !active)}>{playing ? 'Ⅱ' : '▶'}</button><button type="button" title="Next bar" disabled={!replayDate} onClick={() => stepReplay(1)}>▶</button><span className="replay-label">{replayDate ? `BAR ${replayIndex + 1} / ${data.length}` : 'SELECT BAR'}</span><input className="replay-scrubber" type="range" min="0" max={Math.max(0, data.length - 1)} value={Math.min(replayIndex, Math.max(0, data.length - 1))} onChange={(event) => { setReplayIndex(Number(event.target.value)); setReplayDate(data[Number(event.target.value)]?.time || '') }} /><span className="replay-date">{replayDate || 'Click a candle'}</span><label className="replay-speed">Speed<select value={speed} onChange={(event) => setSpeed(event.target.value)}><option value="0.5">0.5×</option><option value="1">1×</option><option value="2">2×</option><option value="4">4×</option></select></label><span className="shortcut-hint">Click a candle · Space play · ← → step · R exit</span></div>}
    <div className="chart-layout"><div className="drawing-toolbar" aria-label="Drawing tools">{[['crosshair', '⌖', 'Crosshair'], ['trendline', '╱', 'Trend line'], ['horizontal', '━', 'Horizontal line'], ['vertical', '┃', 'Vertical line'], ['rectangle', '□', 'Rectangle'], ['text', 'T', 'Text note']].map(([tool, icon, label]) => <button type="button" title={`${label} · select then draw on chart`} aria-label={label} className={selectedTool === tool ? 'active' : ''} key={tool} onClick={() => setSelectedTool(tool)}>{icon}</button>)}</div><div id="futures-chart" className="futures-chart" role="img" aria-label="Interactive daily SILVER futures candlestick chart" />{loading && <div className="chart-loading">Loading futures candles…</div>}</div>
  </section>
}

function TradeEntryPage() {
  const [date, setDate] = useState('2025-01-06'); const [preview, setPreview] = useState(null); const [loading, setLoading] = useState(false); const [message, setMessage] = useState('')
  const previewTrade = () => { setLoading(true); setMessage(''); api(`/api/strategy/preview?date=${encodeURIComponent(date)}`).then(setPreview).catch((error) => { setPreview(null); setMessage(error.message) }).finally(() => setLoading(false)) }
  useEffect(previewTrade, [])
  const p = preview?.silver; const c = preview?.contract
  return <>
    <PageHeader eyebrow="TRADE WORKFLOW" title="Trade Entry" subtitle="Review the Silver signal and its traded option before confirming an entry." action={<span className="badge neutral">SELL-ONLY OPTIONS</span>} />
    <section className="card entry-selector"><div className="card-head"><div><h2>Trade date</h2><p>The option type is selected automatically from the Silver candle.</p></div></div><div className="inline-form"><label className="field"><span>Entry date</span><input type="date" value={date} onChange={(e) => setDate(e.target.value)} /></label><button className="button primary" onClick={previewTrade}>{loading ? 'Loading…' : 'Preview setup'}</button></div></section>
    {message && <div className="notice error">{message}</div>}{preview?.status === 'SKIP' && <div className="notice warning">Trade skipped: {preview.reason}</div>}
    {preview?.status === 'READY' && <><div className="signal-banner"><div><span className="eyebrow">SIGNAL READY · {preview.date}</span><h2 className={preview.option_type === 'PE' ? 'green-text' : 'red-text'}>{preview.direction} {preview.option_type}</h2></div><div className="signal-note">Silver finds the ATM.<br /><strong>The option sets the trade levels.</strong></div></div><div className="two-column">
      <section className="card"><div className="card-head"><div><h2>Silver ATM lookup</h2><p>Used only to select direction and strike.</p></div><span className="badge cyan">SOURCE</span></div><div className="metrics-grid"><Metric label="Open" value={number(p.open)} tone="cyan" /><Metric label="High" value={number(p.high)} tone="yellow" /><Metric label="Low" value={number(p.low)} /><Metric label="Close" value={number(p.close)} /></div><div className="data-line"><span>ATM strike</span><strong>{number(p.atm, 0)}</strong></div></section>
      <section className="card"><div className="card-head"><div><h2>Traded option</h2><p>Actual option OHLC drives the setup.</p></div><span className={`badge ${preview.option_type === 'PE' ? 'buy-green' : 'sell-red'}`}>{preview.option_type}</span></div><div className="data-table compact"><div className="data-line"><span>Expiry</span><strong>{c.expiry}</strong></div><div className="data-line"><span>Strike</span><strong>{number(c.strike, 0)}</strong></div><div className="data-line"><span>Entry price</span><strong className="cyan-text">{number(preview.entry_price)}</strong></div><div className="data-line"><span>Target price</span><strong className="green-text">{number(preview.target_price)}</strong></div><div className="data-line"><span>Stop loss price</span><strong className="red-text">{number(preview.stop_loss_price)}</strong></div><div className="data-line"><span>Quantity</span><strong>{preview.quantity}</strong></div></div></section>
    </div><section className="card"><div className="card-head"><div><h2>Confirm entry</h2><p>Review complete. Confirmation will continue through the existing strategy workflow.</p></div><button className="button primary" onClick={() => setMessage('Entry preview confirmed. Interactive trade execution remains available in the strategy console.')}>Confirm entry</button></div></section></>}
  </>
}

function SettingsPage() {
  const [settings, setSettings] = useState(null); const [message, setMessage] = useState(''); const [saving, setSaving] = useState(false)
  useEffect(() => { api('/api/settings').then(setSettings).catch((error) => setMessage(error.message)) }, [])
  const setNested = (section, group, key, value) => setSettings((current) => ({ ...current, [section]: { ...current[section], [group]: { ...current[section][group], [key]: Number.isNaN(Number(value)) ? value : Number(value) } } }))
  const save = () => { setSaving(true); setMessage(''); api('/api/settings', { method: 'PUT', body: JSON.stringify(settings) }).then(() => setMessage('Settings saved successfully.')).catch((error) => setMessage(error.message)).finally(() => setSaving(false)) }
  if (!settings) return <><PageHeader eyebrow="CONFIGURATION" title="Settings" subtitle="Configure the strategy rules used by the console and entry preview." /><div className="card empty">Loading settings…</div></>
  const target = settings.strategy.target_rules; const atm = settings.market.atm_rounding; const qty = settings.market.quantity_rules
  return <><PageHeader eyebrow="CONFIGURATION" title="Settings" subtitle="Configure the strategy rules used by the console and entry preview." action={<button className="button primary" onClick={save}>{saving ? 'Saving…' : 'Save settings'}</button>} />{message && <div className={`notice ${message.includes('successfully') ? 'success-box' : 'error'}`}>{message}</div>}<div className="settings-grid">
    <section className="card"><div className="card-head"><div><h2>Target rules</h2><p>Target points are selected from the option premium.</p></div></div><div className="form-grid two"><label className="field"><span>Premium below</span><input type="number" value={target.premium_below} onChange={(e) => setNested('strategy', 'target_rules', 'premium_below', e.target.value)} /></label><label className="field"><span>Middle band upper</span><input type="number" value={target.premium_middle_upper} onChange={(e) => setNested('strategy', 'target_rules', 'premium_middle_upper', e.target.value)} /></label><label className="field"><span>Target below</span><input type="number" value={target.target_below} onChange={(e) => setNested('strategy', 'target_rules', 'target_below', e.target.value)} /></label><label className="field"><span>Target middle</span><input type="number" value={target.target_middle} onChange={(e) => setNested('strategy', 'target_rules', 'target_middle', e.target.value)} /></label><label className="field"><span>Target above</span><input type="number" value={target.target_above} onChange={(e) => setNested('strategy', 'target_rules', 'target_above', e.target.value)} /></label></div></section>
    <section className="card"><div className="card-head"><div><h2>Market rules</h2><p>ATM rounding and quantity thresholds.</p></div></div><h3>ATM rounding</h3><div className="form-grid two"><label className="field"><span>Price threshold</span><input type="number" value={atm.price_threshold} onChange={(e) => setNested('market', 'atm_rounding', 'price_threshold', e.target.value)} /></label><label className="field"><span>Interval below</span><input type="number" value={atm.interval_below_threshold} onChange={(e) => setNested('market', 'atm_rounding', 'interval_below_threshold', e.target.value)} /></label><label className="field"><span>Interval at / above</span><input type="number" value={atm.interval_at_or_above_threshold} onChange={(e) => setNested('market', 'atm_rounding', 'interval_at_or_above_threshold', e.target.value)} /></label></div><h3>Quantity</h3><div className="form-grid two"><label className="field"><span>Silver threshold</span><input type="number" value={qty.silver_price_threshold} onChange={(e) => setNested('market', 'quantity_rules', 'silver_price_threshold', e.target.value)} /></label><label className="field"><span>Quantity below / equal</span><input type="number" value={qty.quantity_below_or_equal} onChange={(e) => setNested('market', 'quantity_rules', 'quantity_below_or_equal', e.target.value)} /></label><label className="field"><span>Quantity above</span><input type="number" value={qty.quantity_above} onChange={(e) => setNested('market', 'quantity_rules', 'quantity_above', e.target.value)} /></label></div></section>
  </div><section className="card"><div className="card-head"><div><h2>Data paths</h2><p>Managed by the project structure.</p></div></div>{Object.entries(settings.paths).map(([key, value]) => <div className="data-line" key={key}><span>{key.replaceAll('_', ' ')}</span><code>{value}</code></div>)}</section></>
}

export default function App() {
  const [path, setPath] = useState(window.location.pathname === '/' ? '/data-download' : window.location.pathname); const [health, setHealth] = useState(null)
  useEffect(() => { document.title = 'MCX EOD Strategy'; api('/api/health').then((value) => { setHealth(value); window.__MCX_BRIDGE__ = value }).catch((error) => { window.__MCX_BRIDGE_ERROR__ = error.message }) }, [])
  useEffect(() => { const onPop = () => setPath(window.location.pathname); window.addEventListener('popstate', onPop); return () => window.removeEventListener('popstate', onPop) }, [])
  const navigate = (next) => { window.history.pushState({}, '', next); setPath(next) }; const page = useMemo(() => path === '/futures-chart' ? <FuturesChartPage /> : path === '/trade-entry' ? <TradeEntryPage /> : path === '/settings' ? <SettingsPage /> : <DataDownloadPage />, [path])
  return <AppShell path={path} navigate={navigate} health={health}>{page}</AppShell>
}
