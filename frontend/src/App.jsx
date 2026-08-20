import { useEffect, useMemo, useState } from 'react'

const NAV_ITEMS = [
  { path: '/data-download', label: 'Data Download', icon: '↓' },
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
  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark">MCX</div><div><strong>EOD Strategy</strong><span>Operations Console</span></div></div>
      <div className="sidebar-label">WORKSPACE</div>
      <nav className="nav-list">{NAV_ITEMS.map((item) => <button key={item.path} className={`nav-item ${path === item.path ? 'active' : ''}`} onClick={() => navigate(item.path)}><span className="nav-icon">{item.icon}</span>{item.label}</button>)}</nav>
      <div className="sidebar-footer"><span className={`connection-dot ${health ? 'online' : ''}`} /><div><strong>{health ? 'API Connected' : 'Connecting'}</strong><span>Local strategy bridge</span></div></div>
    </aside>
    <main className="main-content"><header className="topbar"><span>MCX / Strategy workspace</span><span className={`status-pill ${health ? 'success' : 'warning'}`}>{health ? '● ONLINE' : '○ OFFLINE'}</span></header><div className="page-wrap">{children}</div></main>
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
  const navigate = (next) => { window.history.pushState({}, '', next); setPath(next) }; const page = useMemo(() => path === '/trade-entry' ? <TradeEntryPage /> : path === '/settings' ? <SettingsPage /> : <DataDownloadPage />, [path])
  return <AppShell path={path} navigate={navigate} health={health}>{page}</AppShell>
}
