import { useEffect, useMemo, useState } from 'react'
import { MapContainer, TileLayer, CircleMarker, Marker, Tooltip, useMap } from 'react-leaflet'
import L from 'leaflet'
import { BarChart, Bar, XAxis, YAxis, Tooltip as RTip, ResponsiveContainer, Cell, Legend } from 'recharts'
import { Droplets, LayoutDashboard, Map as MapIcon, Wallet, GitCompare, FileText, Bot, Cloud, CloudOff, AlertTriangle } from 'lucide-react'
import { TYPES, TIER_COLOR, FACTORS, setMeta, recommend, suitability, reasons, breakdown, adjScore, benefit, optimize, compare, SCENARIOS, ruleAgent } from './lib.js'
import { API, api } from './api.js'

const f1 = (x) => Number(x).toFixed(1)
const gmaps = (lat, lon) => `https://www.google.com/maps?q=${lat},${lon}`
const Loc = ({ lat, lon }) => <a href={gmaps(lat, lon)} target="_blank" rel="noreferrer" onClick={(e) => e.stopPropagation()} className="text-cyan-700 underline">{lat}, {lon} ↗</a>
const pin = (n, c) => L.divIcon({ className: '', iconSize: [26, 26], iconAnchor: [13, 13], html: `<div style="width:26px;height:26px;border-radius:50%;background:${c};border:2px solid #fff;color:#fff;font:700 12px system-ui;display:flex;align-items:center;justify-content:center;box-shadow:0 1px 4px #0006">${n}</div>` })
const FlyTo = ({ z }) => { const m = useMap(); useEffect(() => { if (z) m.flyTo([z.lat, z.lon], Math.max(m.getZoom(), 11), { duration: 0.6 }) }, [z]); return null }
const Card = ({ title, children, className = '' }) => <section className={`bg-white rounded-xl border border-slate-200 p-4 ${className}`}>{title && <h2 className="font-semibold mb-2 text-slate-800">{title}</h2>}{children}</section>
const Stat = ({ a, b, tone }) => <div className="bg-slate-50 rounded-lg p-2"><div className="text-xs text-slate-500">{a}</div><div className={`text-lg font-bold ${tone || ''}`}>{b}</div></div>
const Note = ({ children }) => <p className="text-xs text-slate-500 mt-2">{children}</p>
const TABS = [['dash', 'Dashboard', LayoutDashboard], ['map', 'Map & zone', MapIcon], ['plan', 'Budget & what-if', Wallet], ['scen', 'Scenarios', GitCompare], ['impact', 'Impact summary', FileText], ['ai', 'AI assistant', Bot]]

export default function App() {
  const [data, setData] = useState(null), [err, setErr] = useState(null)
  const [tab, setTab] = useState('dash'), [sel, setSel] = useState(null)
  const [budget, setBudget] = useState(20), [rain, setRain] = useState(0), [ex, setEx] = useState(0)
  const [cloud, setCloud] = useState(API ? 'checking' : 'offline')
  const load = () => { setErr(null); Promise.all(['zones', 'wells', 'meta'].map((n) => fetch(`/data/${n}.json`).then((r) => { if (!r.ok) throw new Error(`${n}.json: HTTP ${r.status}`); return r.json() })))
    .then(([zones, wells, meta]) => { setMeta(meta, zones); setData({ zones, wells, meta }); setSel(zones[0]) }).catch((e) => setErr(e.message)) }
  useEffect(load, [])
  useEffect(() => { if (API) api.health().then(() => setCloud('online')).catch(() => setCloud('offline')) }, [])
  const zones = data?.zones || []
  const base = useMemo(() => data && optimize(zones, budget, 0, 0), [data, budget])
  const plan = useMemo(() => data && optimize(zones, budget, rain, ex), [data, budget, rain, ex])
  if (err) return <div className="p-10 max-w-xl mx-auto"><div className="flex gap-2 text-red-700 font-semibold"><AlertTriangle />Could not load the data files</div><p className="text-sm my-2 text-slate-600">{err}. Check that <code>public/data/zones.json</code> exists (run <code>analysis/score_pune.py</code> and copy the JSON, see docs/FEATURES.md).</p><button className="bg-cyan-700 text-white px-4 py-2 rounded-lg" onClick={load}>Retry</button></div>
  if (!data || !sel) return <div className="p-10 text-slate-600">Loading Pune region groundwater data…</div>
  const ctx = { ...data, zones, sel, setSel, budget, setBudget, rain, setRain, ex, setEx, plan, base, setTab }
  return (
    <div className="max-w-[1300px] mx-auto p-4 space-y-4">
      <header className="flex flex-wrap items-center gap-3">
        <h1 className="text-2xl font-bold flex items-center gap-2"><Droplets className="text-cyan-700" />Aqua<span className="text-cyan-700">Prior</span></h1>
        <span className="text-slate-600 text-sm hidden md:inline">Where Should We Recharge? · explainable decision-support prototype</span>
        <span className={`ml-auto text-xs flex items-center gap-1 px-2 py-1 rounded-full ${cloud === 'online' ? 'bg-emerald-100 text-emerald-800' : 'bg-slate-200 text-slate-700'}`}>{cloud === 'online' ? <Cloud size={14} /> : <CloudOff size={14} />}{cloud === 'online' ? 'AWS API connected' : 'Offline demo mode'}</span>
      </header>
      <nav className="flex flex-wrap gap-2 print:hidden">{TABS.map(([k, n, I]) => <button key={k} onClick={() => setTab(k)} className={`flex items-center gap-1 px-3 py-1.5 rounded-lg text-sm font-semibold border ${tab === k ? 'bg-cyan-700 text-white border-cyan-700' : 'bg-white border-slate-200 text-slate-700'}`}><I size={15} />{n}</button>)}</nav>
      {tab === 'dash' && <Dashboard {...ctx} />}{tab === 'map' && <MapView {...ctx} />}{tab === 'plan' && <PlanView {...ctx} cloud={cloud} />}
      {tab === 'scen' && <Scenarios {...ctx} />}{tab === 'impact' && <Impact {...ctx} />}{tab === 'ai' && <Assistant {...ctx} cloud={cloud} />}
      <footer className="text-xs text-slate-500 pb-6">Data: India-WRIS manual groundwater levels. Costs/benefits are illustrative assumptions; scores rank relative priority and do not predict groundwater levels. Final decisions need hydrologist and field validation.</footer>
    </div>)
}

function Dashboard({ zones, wells, meta, plan, setSel, setTab }) {
  const counts = { High: 0, Medium: 0, Low: 0 }; zones.forEach((z) => counts[z.tier]++)
  const imp = Object.entries(meta.importance).map(([k, v]) => ({ k, v: +(v * 100).toFixed(1) })).sort((a, b) => b.v - a.v).slice(0, 6)
  return <div className="space-y-4">
    <Card><div className="flex flex-wrap items-center gap-3"><label className="text-sm font-semibold">Study area
      <select className="ml-2 border border-slate-300 rounded-lg px-2 py-1 font-normal"><option>{meta.area}</option><option disabled>＋ Add area (re-run analysis/score_pune.py with a new bbox)</option></select></label>
      <span className="text-sm text-slate-600">Quick start: open <b>Map &amp; zone</b>, click a red pin, then set a budget in <b>Budget &amp; what-if</b>.</span></div></Card>
    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">{[['Zones scored', zones.length], ['High priority', counts.High], ['Wells used', wells.length], ['Plan projects', plan.n], ['Plan benefit', f1(plan.benefit)]].map(([a, b]) => <Stat key={a} a={a} b={b} tone="text-cyan-700" />)}</div>
    <div className="grid md:grid-cols-2 gap-4">
      <Card title="Score factors (blueprint weights)"><div className="space-y-1 text-sm">{Object.entries(meta.weights).map(([k, w]) => <div key={k} className="flex items-center gap-2"><span className={`w-2 h-2 rounded-full ${meta.factorsAvailable[k] ? 'bg-emerald-500' : 'bg-slate-300'}`} /><span className="flex-1">{FACTORS[k]}</span><span className="text-slate-500">{w * 100}%</span><span className={`text-xs ${meta.factorsAvailable[k] ? 'text-emerald-700' : 'text-slate-400'}`}>{meta.factorsAvailable[k] ? 'in score' : 'data not loaded'}</span></div>)}</div>
        <Note>Factors without data are skipped and the remaining weights renormalised; nothing is invented. To add missing layers run analysis/colab_extras.py in Colab (docs/FEATURES.md step 3). Water demand is a cropland + built-up proxy.</Note></Card>
      <Card title="Model validation (unseen wells)"><div className="grid grid-cols-3 gap-2 text-center mb-2">{[['XGBoost R²', meta.metrics.xgb_r2], ['IDW R²', meta.metrics.idw_r2], ['Final R²', meta.metrics.final_r2]].map(([a, b]) => <Stat key={a} a={a} b={b} />)}</div>
        <div className="h-28"><ResponsiveContainer><BarChart data={imp}><XAxis dataKey="k" fontSize={11} /><YAxis hide /><RTip /><Bar dataKey="v" fill="#0b6e8a" /></BarChart></ResponsiveContainer></div>
        <p className="text-xs text-amber-700">R² is modest: groundwater varies strongly over short distances, so use scores to shortlist areas for field survey.</p></Card></div>
    <Card title="Top 10 zones"><div className="overflow-x-auto"><table className="w-full text-sm"><thead className="text-left text-slate-500"><tr><th>Rank</th><th>Zone</th><th>Score</th><th>Tier</th><th>Build</th></tr></thead><tbody>
      {zones.slice(0, 10).map((z) => <tr key={z.id} className="border-t border-slate-100 cursor-pointer hover:bg-slate-50" onClick={() => { setSel(z); setTab('map') }}><td>#{z.rank}</td><td>{z.id}</td><td>{z.score}</td><td>{z.tier}</td><td>{recommend(z)}</td></tr>)}</tbody></table></div></Card></div>
}

function ZoneCard({ z, rain, ex, plan }) {
  const t = recommend(z), bd = breakdown(z), idx = plan.projects.findIndex((p) => p.zone === z.id)
  return <Card title={`Zone ${z.id}`}>
    <div className="flex items-baseline gap-3"><span className="text-4xl font-bold text-cyan-700">{f1(adjScore(z, rain, ex))}</span><span className="text-sm text-slate-500">/100 priority · rank #{z.rank}</span><span className="ml-auto text-white text-xs px-2 py-0.5 rounded-full" style={{ background: TIER_COLOR[z.tier] }}>{z.tier}</span></div>
    <div className="my-3 space-y-1">{bd.map((o) => <div key={o.factor} className="text-xs"><div className="flex justify-between"><span className={o.available ? '' : 'text-slate-400'}>{FACTORS[o.factor]} · {o.weight * 100}%</span><span className="text-slate-500">{o.available ? `${o.value}/100 → ${o.contribution} pts` : 'data not loaded'}</span></div>
      <div className="h-2 rounded bg-slate-100 overflow-hidden"><div className="h-full bg-cyan-600" style={{ width: `${o.available ? o.value : 0}%` }} /></div></div>)}</div>
    <div className="grid grid-cols-2 gap-2 text-sm mb-3">{[['Water level (pre-monsoon)', `${z.depth} m bgl`], ['Trend', `${z.decline > 0 ? '+' : ''}${z.decline} m/yr`], ['Post-monsoon recovery', `${z.rise} m`], ['Nearest well', `${z.nearKm} km · ${Math.round(z.conf * 100)}% conf.`]].map(([a, b]) => <Stat key={a} a={a} b={<span className="text-sm">{b}</span>} />)}{[['Monsoon rainfall', z.rain != null && `${Math.round(z.rain)} mm`], ['Soil infiltration', z.soil != null && `${Math.round(z.soil * 100)}/100`], ['Mean slope', z.slope != null && `${z.slope.toFixed(1)}°`], ['Mapped water structures (2.5 km)', z.struct != null && z.struct], ['Cropland + built-up share', z.stage != null && `${Math.round(z.stage * 100)}%`]].filter(([, v]) => v !== false && v != null).map(([a, b]) => <Stat key={a} a={a} b={<span className="text-sm">{b}</span>} />)}<div className="col-span-2"><Stat a="Location (cell centre, lat, lon)" b={<span className="text-sm"><Loc lat={z.lat} lon={z.lon} /> <span className="text-slate-500">· open in Google Maps</span></span>} /></div></div>
    <div className="rounded-lg border border-slate-200 p-3 bg-slate-50"><div className="font-semibold" style={{ color: TYPES[t].color }}>Recommended: {t}</div>
      <div className="text-sm text-slate-600">Cost ₹{TYPES[t].cost}L · est. benefit {f1(benefit(z, t, rain, ex))} units · suitability {Math.round(suitability(z, t) * 100)}%</div>
      <div className="text-sm mt-1">Why: {reasons(z).join(' + ')}</div>{idx >= 0 && <div className="text-sm text-emerald-700 mt-1">✔ Project #{idx + 1} in the current plan</div>}</div>
    <Note>Intervention is rule-based on measured well data{z.soil == null ? '; soil, slope and land-use layers are not loaded yet' : ''}.</Note></Card>
}

function MapView({ zones, wells, sel, setSel, rain, ex, plan }) {
  const [show, setShow] = useState({ High: true, Medium: true, Low: false, wells: true, plan: true })
  const tg = (k) => setShow({ ...show, [k]: !show[k] }), counts = { High: 0, Medium: 0, Low: 0 }; zones.forEach((z) => counts[z.tier]++)
  return <div className="grid lg:grid-cols-[1.6fr_1fr] gap-4">
    <Card className="h-[680px] flex flex-col"><div className="flex flex-wrap gap-3 text-sm mb-2">
      {['High', 'Medium', 'Low'].map((k) => <label key={k} className="flex items-center gap-1"><input type="checkbox" checked={show[k]} onChange={() => tg(k)} /><span className="w-3 h-3 rounded-full" style={{ background: TIER_COLOR[k] }} />{k} ({counts[k]})</label>)}
      <label className="flex items-center gap-1"><input type="checkbox" checked={show.wells} onChange={() => tg('wells')} />◆ Wells</label><label className="flex items-center gap-1"><input type="checkbox" checked={show.plan} onChange={() => tg('plan')} />Plan projects</label></div>
      <div className="flex-1 min-h-0"><MapContainer center={[18.58, 74.0]} zoom={9} preferCanvas scrollWheelZoom>
        <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" /><FlyTo z={sel} />
        {zones.filter((z) => show[z.tier]).map((z) => <CircleMarker key={z.id} center={[z.lat, z.lon]} radius={z.tier === 'High' ? 6 : 4} eventHandlers={{ click: () => setSel(z) }}
          pathOptions={{ color: z.id === sel.id ? '#000' : TIER_COLOR[z.tier], weight: z.id === sel.id ? 3 : 1, fillColor: TIER_COLOR[z.tier], fillOpacity: 0.35 + 0.5 * z.conf }}><Tooltip>{z.id} · {z.score} · #{z.rank} · {z.lat}, {z.lon}</Tooltip></CircleMarker>)}
        {show.wells && wells.map((w) => <CircleMarker key={w.id} center={[w.lat, w.lon]} radius={3} pathOptions={{ color: '#111', weight: 1, fillColor: '#fff', fillOpacity: 1 }}><Tooltip>{w.name}: {w.depth} m, {w.decline > 0 ? '+' : ''}{w.decline} m/yr</Tooltip></CircleMarker>)}
        {show.plan && plan.projects.map((p, i) => <Marker key={p.zone} position={[p.lat, p.lon]} icon={pin(i + 1, TYPES[p.intervention].color)} eventHandlers={{ click: () => setSel(p.z) }}><Tooltip>#{i + 1} {p.intervention} · ₹{p.cost}L</Tooltip></Marker>)}
      </MapContainer></div><Note>Opacity = data confidence (distance to measured wells). Numbered pins = optimized projects.</Note></Card>
    <ZoneCard z={sel} rain={rain} ex={ex} plan={plan} /></div>
}

function Sliders({ budget, setBudget, rain, setRain, ex, setEx }) {
  return <div className="grid md:grid-cols-3 gap-4 mb-3 text-sm">{[['Budget (₹ lakh)', budget, setBudget, 5, 150, 5], ['Rainfall change (%)', rain, setRain, -40, 20, 5], ['Extraction change (%)', ex, setEx, -30, 30, 5]].map(([l, v, s, mn, mx, st]) =>
    <label key={l} className="font-semibold">{l}: {v}<input type="range" className="w-full" min={mn} max={mx} step={st} value={v} onChange={(e) => s(+e.target.value)} /></label>)}</div>
}

function PlanView(c) {
  const { plan, base, zones, setSel, setTab, cloud } = c, [msg, setMsg] = useState('')
  const d = plan.benefit - base.benefit, changed = plan.projects.filter((p) => !base.projects.some((b) => b.zone === p.zone)).length
  const shift = zones.slice(0, 8).map((z) => ({ id: z.id, before: z.score, after: +adjScore(z, c.rain, c.ex).toFixed(1) }))
  const save = () => api.savePlan(plan).then((r) => setMsg(r.saved ? `Saved to DynamoDB (id ${r.id.slice(0, 8)})` : 'Computed, but no table configured')).catch((e) => setMsg('Save failed: ' + e.message))
  return <div className="space-y-4"><Card title="Budget optimization & what-if"><Sliders {...c} />
    <div className="grid grid-cols-2 md:grid-cols-5 gap-2 mb-3">{[['Projects', plan.n], ['Spend', `₹${f1(plan.cost)}L of ${c.budget} (${Math.round(100 * plan.cost / c.budget)}%)`], ['Est. benefit', f1(plan.benefit)], ['vs baseline', `${d >= 0 ? '+' : ''}${f1(d)}`], ['Projects changed', changed]].map(([a, b]) => <Stat key={a} a={a} b={b} tone={a === 'vs baseline' ? (d >= 0 ? 'text-emerald-700' : 'text-orange-600') : ''} />)}</div>
    <div className="overflow-x-auto max-h-80"><table className="w-full text-sm"><thead className="text-left text-slate-500"><tr><th>#</th><th>Zone</th><th>Intervention</th><th>Score</th><th>Cost ₹L</th><th>Benefit</th><th>Location</th><th>Why</th></tr></thead><tbody>
      {plan.projects.map((p, i) => <tr key={p.zone} className="border-t border-slate-100 cursor-pointer hover:bg-slate-50" onClick={() => { setSel(p.z); setTab('map') }}><td>{i + 1}</td><td>{p.zone}</td><td style={{ color: TYPES[p.intervention].color }}>{p.intervention}</td><td>{f1(p.score)}</td><td>{p.cost}</td><td>{f1(p.benefit)}</td><td className="text-xs"><Loc lat={p.lat} lon={p.lon} /></td><td className="text-xs text-slate-500">{p.reasons[0]}</td></tr>)}</tbody></table></div>
    <div className="flex items-center gap-3 mt-3">{cloud === 'online' && <button onClick={save} className="bg-cyan-700 text-white px-3 py-1.5 rounded-lg text-sm font-semibold">Save plan to AWS</button>}<span className="text-sm text-slate-600">{msg}</span></div>
    <Note>Greedy by benefit per rupee, one project per zone, ≥3 km apart, no type over 45% of budget in the first pass. Rainfall scales recharge potential and benefit; extraction scales stress (elasticity 0.5). Model-based scenario estimates, not forecasts.</Note></Card>
    <Card title="Changed priority scores (top 8 zones, baseline → scenario)"><div className="overflow-x-auto"><table className="w-full text-sm"><thead className="text-left text-slate-500"><tr><th>Zone</th><th>Before</th><th>After</th><th>Δ</th></tr></thead><tbody>{shift.map((s) => <tr key={s.id} className="border-t border-slate-100"><td>{s.id}</td><td>{s.before}</td><td>{s.after}</td><td className={s.after - s.before < 0 ? 'text-orange-600' : 'text-emerald-700'}>{f1(s.after - s.before)}</td></tr>)}</tbody></table></div></Card></div>
}

function Scenarios({ zones, budget, setBudget }) {
  const res = useMemo(() => compare(zones, SCENARIOS(budget)), [zones, budget])
  return <Card title="Scenario comparison (blueprint section 11)"><label className="text-sm font-semibold">Baseline budget: ₹{budget} lakh<input type="range" className="w-full max-w-sm block" min={10} max={100} step={5} value={budget} onChange={(e) => setBudget(+e.target.value)} /></label>
    <div className="overflow-x-auto my-3"><table className="w-full text-sm"><thead className="text-left text-slate-500"><tr><th>Scenario</th><th>Budget</th><th>Rain</th><th>Extraction</th><th>Projects</th><th>Spend ₹L</th><th>Benefit</th><th>Δ vs baseline</th><th>Mix</th></tr></thead><tbody>
      {res.map((r) => <tr key={r.name} className="border-t border-slate-100"><td className="font-semibold">{r.name}</td><td>{r.budget}</td><td>{r.rain}%</td><td>{r.extraction}%</td><td>{r.n}</td><td>{f1(r.cost)}</td><td>{f1(r.benefit)}</td><td className={r.delta < 0 ? 'text-orange-600' : 'text-emerald-700'}>{r.delta >= 0 ? '+' : ''}{r.delta}</td><td className="text-xs">{Object.entries(r.mix).map(([k, v]) => `${v}× ${k}`).join(', ')}</td></tr>)}</tbody></table></div>
    <div className="h-56"><ResponsiveContainer><BarChart data={res}><XAxis dataKey="name" fontSize={11} /><YAxis /><RTip /><Bar dataKey="benefit" name="Est. benefit (units)" fill="#0b6e8a" /></BarChart></ResponsiveContainer></div>
    <Note>Every scenario is a model-based estimate under stated assumptions, not a guaranteed outcome.</Note></Card>
}

function Impact({ plan, budget, rain, ex, setSel, setTab }) {
  const chart = Object.entries(plan.mix).map(([k, v]) => ({ k, n: v, c: TYPES[k].color })), high = plan.projects.filter((p) => p.z.tier === 'High').length
  return <Card title="Impact summary — final plan"><div className="grid grid-cols-2 md:grid-cols-6 gap-2 mb-3">{[['Budget', `₹${budget}L`], ['Spent', `₹${f1(plan.cost)}L`], ['Utilization', `${Math.round(100 * plan.cost / budget)}%`], ['Projects', plan.n], ['In High-priority zones', `${high} / ${plan.n}`], ['Est. benefit', f1(plan.benefit)]].map(([a, b]) => <Stat key={a} a={a} b={b} tone="text-cyan-700" />)}</div>
    <p className="text-sm text-slate-600 mb-2">Scenario: rainfall {rain >= 0 ? '+' : ''}{rain}%, extraction {ex >= 0 ? '+' : ''}{ex}%. Click a project to see its zone.</p>
    <div className="grid md:grid-cols-2 gap-4"><div className="h-52"><ResponsiveContainer><BarChart data={chart}><XAxis dataKey="k" fontSize={11} /><YAxis allowDecimals={false} /><RTip /><Bar dataKey="n" name="Projects">{chart.map((d) => <Cell key={d.k} fill={d.c} />)}</Bar></BarChart></ResponsiveContainer></div>
      <ol className="text-sm list-decimal pl-5 max-h-52 overflow-auto">{plan.projects.map((p) => <li key={p.zone}><button className="text-cyan-700 underline" onClick={() => { setSel(p.z); setTab('map') }}>{p.zone}</button> — {p.intervention}, ₹{p.cost}L ({p.reasons[0]}) · <Loc lat={p.lat} lon={p.lon} /></li>)}</ol></div>
    <button className="mt-3 bg-cyan-700 text-white px-3 py-1.5 rounded-lg text-sm font-semibold print:hidden" onClick={() => window.print()}>Print / save as PDF</button>
    <Note>Assumptions: costs and benefits are illustrative; benefit = base × score × rainfall factor × suitability × data confidence. Not a prediction of groundwater levels.</Note></Card>
}

function Assistant({ zones, cloud, sel, budget, rain, ex, meta, wells }) {
  const [log, setLog] = useState([]), [q, setQ] = useState(''), [busy, setBusy] = useState(false)
  const ask = async () => { const v = q.trim(); if (!v) return; setQ(''); setBusy(true); let a, eng = 'local rules'
    try { if (cloud === 'online') { const r = await api.agent(v); if (r.engine === 'strands') { a = r.answer; eng = 'AWS Strands agent' } else { a = ruleAgent(v, zones, { sel, budget, rain, ex, meta, wells }); eng = 'local rules (agent unavailable' + (r.note ? ': ' + r.note : '') + ')' } } else a = ruleAgent(v, zones, { sel, budget, rain, ex, meta, wells }) } catch (e) { a = ruleAgent(v, zones, { sel, budget, rain, ex, meta, wells }) + `\n(API error: ${e.message}; answered locally)` }
    setLog((l) => [...l, [v, a, eng]]); setBusy(false) }
  return <Card title="AI explanation assistant"><div className="flex flex-wrap gap-2 mb-2">{['Which three locations should we prioritize?', 'Why is G047049 ranked #1?', 'Why a check dam in this zone?', 'I have 10 lakh and rainfall drops 20%', 'Top 5 zones with deepest water levels', 'Where should I build percolation tanks?', 'Compare G047049 and G066061', 'How is the score calculated?', 'How accurate is this?', 'What is a recharge pit?', 'What should we do next?', 'What data is missing?', 'Compare scenarios'].map((s) => <button key={s} onClick={() => setQ(s)} className="text-xs border border-slate-300 rounded-full px-2 py-1 hover:bg-slate-50">{s}</button>)}</div>
    <div className="max-h-80 overflow-auto text-sm space-y-3 mb-2">{log.map(([a, b, e], i) => <div key={i}><div className="font-semibold text-cyan-700">You: {a}</div><div className="whitespace-pre-wrap">{b}</div><div className="text-xs text-slate-400">via {e}</div></div>)}</div>
    <div className="flex gap-2"><input value={q} onChange={(e) => setQ(e.target.value)} onKeyDown={(e) => e.key === 'Enter' && ask()} className="flex-1 border border-slate-300 rounded-lg px-3 py-2 text-sm" placeholder="Ask about a zone, a budget or a scenario" /><button disabled={busy} onClick={ask} className="bg-cyan-700 text-white px-4 rounded-lg text-sm font-semibold">{busy ? '…' : 'Ask'}</button></div>
    <Note>Guardrail: answers use only values returned by the analysis engine and state assumptions. {cloud === 'online' ? 'Connected to the deployed Strands agent.' : 'Offline mode uses the built-in assistant (rules + knowledge base); deploying the backend adds the Strands agent.'}</Note></Card>
}
