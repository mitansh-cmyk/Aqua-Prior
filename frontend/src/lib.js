// JS mirror of backend/engine.py (same rules, same numbers) so sliders work instantly and the app also runs offline.
export const TYPES = {
  'Check Dam': { cost: 8.5, base: 18.5, color: '#0b6e8a' }, 'Percolation Tank': { cost: 12, base: 24.8, color: '#6d4aa8' },
  'Recharge Well': { cost: 3.2, base: 12.2, color: '#d9480f' }, 'Farm Pond': { cost: 4.5, base: 14.1, color: '#2b8a3e' },
  'Recharge Pit': { cost: 1.5, base: 4.5, color: '#c2255c' },
}
export const TIER_COLOR = { High: '#c92a2a', Medium: '#f08c00', Low: '#2f9e44' }
export const FACTORS = { stress: 'Groundwater stress', recharge: 'Recharge potential', rain: 'Rainfall / runoff', soil: 'Soil suitability', demand: 'Water demand (proxy)', gap: 'Infrastructure gap' }
const clamp = (v, a = 0, b = 1) => Math.min(b, Math.max(a, v))
const KX = 111 * Math.cos(18.6 * Math.PI / 180)
let META = null, RNG = {}
export const setMeta = (m, zones) => { META = m; RNG = {}; ZONES = zones }
let ZONES = []
const norm = (k, v) => {
  if (v == null) return null
  if (!RNG[k]) { const xs = ZONES.map((z) => z[k]).filter((x) => x != null).sort((a, b) => a - b)
    RNG[k] = xs.length ? [xs[Math.floor(0.05 * (xs.length - 1))], xs[Math.floor(0.95 * (xs.length - 1))]] : [0, 1] }
  const [lo, hi] = RNG[k]; return hi > lo ? clamp((v - lo) / (hi - lo)) : 0.5
}
const rel = (k, v) => { const r = norm(k, v); return r == null ? 0.5 : r }   // position inside this study area's 5th-95th percentile range
export function suitability(z, t) {
  const deep = clamp((z.depth - 3) / 15), dec = clamp(z.decline / 0.8), rise = clamp(z.rise / 6)
  const soil = rel('soil', z.soil), rain = rel('rain', z.rain), steep = z.slope == null ? 0.5 : clamp(z.slope / 6)
  if (t === 'Recharge Well') return 0.3 + 0.7 * deep
  if (t === 'Percolation Tank') return 0.35 + 0.65 * (0.3 * rise + 0.2 * dec + 0.25 * soil + 0.25 * rain)
  if (t === 'Check Dam') return 0.35 + 0.65 * (0.35 * dec + 0.25 * rain + 0.25 * steep + 0.15 * (1 - deep))
  if (t === 'Recharge Pit') return 0.3 + 0.7 * (0.35 * (1 - deep) + 0.65 * soil) * 0.9
  return 0.45 + 0.2 * rise
}
export const recommend = (z) => Object.keys(TYPES).reduce((a, t) => (suitability(z, t) > suitability(z, a) ? t : a))
export function reasons(z) {
  const r = []
  if (z.decline > 0.3) r.push(`water table falling ${z.decline.toFixed(2)} m/yr`)
  if (z.depth > 10) r.push(`deep pre-monsoon water level (${z.depth} m)`)
  if (z.rise > 3) r.push(`strong post-monsoon recovery (${z.rise} m)`)
  if (z.soil != null && z.soil > 0.6) r.push('permeable soil')
  if (z.struct === 0) r.push('no mapped recharge structures nearby')
  if (z.conf < 0.4) r.push('low data confidence (far from wells)')
  return r.length ? r : ['moderate signals on all measured factors']
}
export function breakdown(z) {
  const W = META.weights
  const raw = { stress: z.stress, recharge: z.recharge, rain: norm('rain', z.rain), soil: norm('soil', z.soil), demand: norm('stage', z.stage), gap: z.struct == null ? null : 1 - norm('struct', z.struct) }
  const out = Object.keys(W).map((k) => ({ factor: k, weight: W[k], value: raw[k] == null ? null : Math.round(raw[k] * 100), available: raw[k] != null }))
  const tot = out.reduce((s, o) => s + (o.available ? o.weight * o.value : 0), 0) || 1
  out.forEach((o) => { o.contribution = o.available ? +(z.score * o.weight * o.value / tot).toFixed(1) : null }); return out
}
// What-if: extraction scales stress, rainfall scales recharge potential (elasticity 0.5 each). Assumptions, shown in the UI.
export function adjScore(z, rain = 0, ex = 0) {
  const { stress: ws, recharge: wr } = META.weights
  const ds = (z.stress || 0) * 0.5 * ex / 100, dr = (z.recharge || 0) * 0.5 * rain / 100
  return clamp(z.score + 100 * (ws * ds + wr * dr) / (ws + wr), 0, 100)
}
export const benefit = (z, t, rain = 0, ex = 0) => TYPES[t].base * adjScore(z, rain, ex) / 100 * (1 + rain / 100) * (0.5 + suitability(z, t)) * (0.6 + 0.4 * z.conf)
export function optimize(zones, budget, rain = 0, ex = 0, spacing = 3, maxCand = 600, cap = 0.45) {
  const c = zones.slice(0, maxCand).map((z) => { const t = recommend(z); return { z, t, r: benefit(z, t, rain, ex) / TYPES[t].cost } }).sort((a, b) => b.r - a.r)
  let rem = budget; const out = [], spent = {}
  for (const lim of [cap, 1]) for (const { z, t } of c) {
    const cost = TYPES[t].cost
    if (cost > rem || (spent[t] || 0) + cost > lim * budget || out.some((o) => o.zone === z.id)) continue
    if (out.some((o) => Math.hypot((o.lon - z.lon) * KX, (o.lat - z.lat) * 111) < spacing)) continue
    out.push({ zone: z.id, lat: z.lat, lon: z.lon, intervention: t, cost, benefit: +benefit(z, t, rain, ex).toFixed(2), score: +adjScore(z, rain, ex).toFixed(1), reasons: reasons(z), z })
    rem -= cost; spent[t] = (spent[t] || 0) + cost
  }
  const mix = {}; out.forEach((p) => (mix[p.intervention] = (mix[p.intervention] || 0) + 1))
  return { budget, rain, extraction: ex, projects: out, n: out.length, cost: +(budget - rem).toFixed(2), benefit: +out.reduce((s, p) => s + p.benefit, 0).toFixed(1), mix }
}
export const SCENARIOS = (b) => [{ name: 'Baseline', budget: b }, { name: 'Budget constrained', budget: b / 2 }, { name: 'Rainfall shock −20%', budget: b, rain: -20 }, { name: 'Demand reduction −15%', budget: b, extraction: -15 }]
export const compare = (zones, sc) => { let base; return sc.map((s) => { const r = optimize(zones, s.budget, s.rain || 0, s.extraction || 0); r.name = s.name; base = base || r; r.delta = +(r.benefit - base.benefit).toFixed(1); return r }) }

// Offline assistant: many intents, answers ONLY from computed values. (Deployed Strands agent handles open-ended questions.)
const TYPE_KEYS = [['check dam', 'Check Dam'], ['percolation', 'Percolation Tank'], ['tank', 'Percolation Tank'], ['recharge well', 'Recharge Well'], ['farm pond', 'Farm Pond'], ['pond', 'Farm Pond'], ['pit', 'Recharge Pit']]
const NEG = /decreas|drop|fall|reduc|less|lower|cut|decline|down/
export function ruleAgent(q, zones, c = {}) {
  const x = q.toLowerCase(), ids = [...new Set((x.match(/g\d{6}/gi) || []).map((s) => s.toUpperCase()))]
  const zl = ids.map((i) => zones.find((z) => z.id === i)).filter(Boolean)
  if (!zl.length && /\b(this|selected|here)\b/.test(x) && /zone|why|suitab|cost|benefit|breakdown|factor|location|site|intervention|structure|dam|tank|well|pond|pit|rank|score of/.test(x) && c.sel) zl.push(c.sel)
  const signed = (re) => { const m = x.match(re); if (!m) return null; const v = Math.abs(+m[1]); return NEG.test(x.slice(Math.max(0, m.index - 25), m.index + m[0].length)) || +m[1] < 0 ? -v : v }
  const L = (x.match(/(\d+(?:\.\d+)?)\s*(?:lakhs?|l\b)/) || [])[1], R = signed(/rain\w*[^\d+-]{0,25}([+-]?\d+)/), E = signed(/(?:extraction|demand|pumping)\w*[^\d+-]{0,25}([+-]?\d+)/)
  const type = (TYPE_KEYS.find(([k]) => x.includes(k)) || [])[1], N = Math.min(15, +((x.match(/top\s*(\d+)|(\d+)\s*(?:zones|locations|places|sites)/) || []).slice(1).find(Boolean) || 3))
  const sc = (z) => `${z.id} (score ${z.score}, ${z.tier}, ${recommend(z)})`
  if (zl.length >= 2) { const [a, b] = zl; return [a, b].map((z) => `${z.id}: rank #${z.rank}, score ${z.score}, depth ${z.depth} m, trend ${z.decline > 0 ? '+' : ''}${z.decline} m/yr, recovery ${z.rise} m → ${recommend(z)}`).join('\n') + `\n${a.score >= b.score ? a.id : b.id} has the higher priority by ${Math.abs(a.score - b.score).toFixed(1)} points.` }
  if (zl.length === 1) { const z = zl[0], t = recommend(z)
    if (/suitab|why.*(dam|tank|well|pond|pit)|which (intervention|structure)|instead/.test(x)) return (type && type !== t ? `${type} scores ${Math.round(suitability(z, type) * 100)}% here versus ${Math.round(suitability(z, t) * 100)}% for ${t}. ` : '') + `Suitability at ${z.id} (rule-based): ` + Object.keys(TYPES).map((k) => `${k} ${Math.round(suitability(z, k) * 100)}%`).join(', ') + `. Best fit: ${t}, because ${reasons(z).join(' + ')}.`
    if (/breakdown|factor|contribut/.test(x)) return `Factor inputs for ${z.id}: ` + breakdown(z).map((o) => `${FACTORS[o.factor]} ${o.available ? `${o.value}/100 → ${o.contribution} pts` : 'not loaded'}`).join('; ') + '.'
    if (/cost|benefit|afford/.test(x)) return `${t} at ${z.id}: cost ₹${TYPES[t].cost}L, est. benefit ${f2(benefit(z, t, c.rain || 0, c.ex || 0))} units (illustrative).`
    return `${z.id} is ranked #${z.rank} of ${zones.length} (score ${z.score}, ${z.tier}). Pre-monsoon water level ${z.depth} m, trend ${z.decline > 0 ? '+' : ''}${z.decline} m/yr, post-monsoon recovery ${z.rise} m; nearest well ${z.nearKm} km. Location ${z.lat}°N, ${z.lon}°E (https://www.google.com/maps?q=${z.lat},${z.lon}). Drivers: ${reasons(z).join(', ')}. Suggested ${t} (₹${TYPES[t].cost}L, suitability ${Math.round(suitability(z, t) * 100)}%, rule-based).` }
  if (/scenario|compare|versus|\bvs\b/.test(x)) return compare(zones, SCENARIOS(L ? +L : c.budget || 20)).map((r) => `${r.name}: ${r.n} projects, spend ₹${r.cost}L, benefit ${r.benefit} (${r.delta >= 0 ? '+' : ''}${r.delta} vs baseline)`).join('\n')
  if (/how.*(score|calculat)|formula|weight/.test(x) && c.meta) return 'Priority = weighted factors: ' + Object.entries(c.meta.weights).map(([k, w]) => `${FACTORS[k]} ${w * 100}%${c.meta.factorsAvailable[k] ? '' : ' (data not loaded)'}`).join(', ') + '. Groundwater factors come from 145 real wells (depth, decline, post-monsoon recovery), spatially predicted with XGBoost + inverse-distance interpolation. Missing factors are skipped and weights renormalised.'
  if (/accura|valid|r2|r²|reliab|trust/.test(x) && c.meta) return `Validation on unseen wells: R² ${c.meta.metrics.final_r2} (XGBoost ${c.meta.metrics.xgb_r2}, interpolation ${c.meta.metrics.idw_r2}). That is modest: groundwater varies over short distances, so scores shortlist areas for field survey. Costs/benefits are illustrative, interventions are rule-based, and scenarios are estimates, not forecasts.`
  if (/cost|price|expensive|cheap/.test(x) || /which (interventions?|types?|structures?)|what interventions/.test(x)) return (type ? [type] : Object.keys(TYPES)).map((k) => `${k}: ₹${TYPES[k].cost}L, base benefit ${TYPES[k].base} units`).join('\n') + '\n(illustrative assumptions)'
  if (L || R != null || E != null || /budget|plan|spend|action|summar|what should (i|we) build/.test(x)) { const b = L ? +L : c.budget || 20, r = R ?? c.rain ?? 0, e = E ?? c.ex ?? 0, p = optimize(zones, b, r, e), bs = optimize(zones, b, 0, 0)
    return `₹${b}L, rainfall ${r >= 0 ? '+' : ''}${r}%, extraction ${e >= 0 ? '+' : ''}${e}%: ${p.n} projects, spend ₹${p.cost}L (${Math.round(100 * p.cost / b)}%), est. benefit ${p.benefit} (${p.benefit - bs.benefit >= 0 ? '+' : ''}${(p.benefit - bs.benefit).toFixed(1)} vs no-change baseline). Mix: ${Object.entries(p.mix).map(([k, v]) => `${v}× ${k}`).join(', ')}. First: ${p.projects.slice(0, 3).map((q2) => `${q2.intervention} at ${q2.zone}`).join('; ')}. Illustrative, model-based.` }
  const tier = ['high', 'medium', 'low'].find((t) => x.includes(t)), wantList = /where|which|list|show|find|best|top|most|highest|deepest|fastest|worst/.test(x)
  if (wantList && (type || tier || /deep|declin|fall|shallow|confiden|recover/.test(x))) {
    let a = zones.filter((z) => (!type || recommend(z) === type) && (!tier || z.tier.toLowerCase() === tier)), by = 'priority'
    if (/deep/.test(x)) { a = [...a].sort((p, q2) => q2.depth - p.depth); by = 'water-level depth' } else if (/declin|falling|fastest/.test(x)) { a = [...a].sort((p, q2) => q2.decline - p.decline); by = 'decline rate' }
    else if (/recover/.test(x)) { a = [...a].sort((p, q2) => q2.rise - p.rise); by = 'post-monsoon recovery' } else if (/confiden/.test(x)) { a = [...a].sort((p, q2) => q2.conf - p.conf); by = 'data confidence' }
    return a.length ? `Top ${Math.min(N, a.length)} of ${a.length} matching zones by ${by}: ` + a.slice(0, N).map((z) => `${z.id} (${z.score}, depth ${z.depth} m, ${z.decline > 0 ? '+' : ''}${z.decline} m/yr, ${recommend(z)})`).join('; ') : 'No zones match that filter.' }
  if (/how many|count|number of|average|overview|statistic/.test(x)) { const n = (t) => zones.filter((z) => z.tier === t).length, av = (k) => (zones.reduce((s, z) => s + z[k], 0) / zones.length).toFixed(2)
    return `${zones.length} zones scored over ${c.meta?.area || 'the study area'}: ${n('High')} High, ${n('Medium')} Medium, ${n('Low')} Low. Based on ${c.wells?.length || 145} real wells. Average pre-monsoon depth ${av('depth')} m, average trend ${av('decline')} m/yr; ${zones.filter((z) => z.decline > 0).length} zones show a deepening water table.` }
  if (/top|prioriti|rank|highest|best|first|which|where/.test(x)) return `Top ${N} zones: ` + zones.slice(0, N).map(sc).join('; ')
  return openEnded(q, zones, c)
}

// ---- open-ended questions: small knowledge base + fuzzy keyword retrieval (no LLM, no network) ----
const STOP = new Set('a an the is are was be to of in on for and or it this that what how why can do does did i we you me my our your with about tell explain please should would could there which who when where any some more much very mean means meaning'.split(' '))
const stem = (w) => w.replace(/(ing|ed|es|s)$/, '')
const toks = (t) => t.toLowerCase().replace(/[^a-z0-9 ]/g, ' ').split(/\s+/).filter((w) => w && !STOP.has(w)).map(stem)
const lev = (a, b) => { if (Math.abs(a.length - b.length) > 1) return 2; const d = Array.from({ length: a.length + 1 }, (_, i) => [i, ...Array(b.length).fill(0)]); for (let j = 1; j <= b.length; j++) d[0][j] = j
  for (let i = 1; i <= a.length; i++) for (let j = 1; j <= b.length; j++) d[i][j] = Math.min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)); return d[a.length][b.length] }
const hit = (qt, kw) => qt.some((w) => w === kw || (w.length >= 5 && kw.length >= 5 && lev(w, kw) <= 1))
const nType = (zones, t) => zones.filter((z) => recommend(z) === t).length
const DEF = { 'Check Dam': 'a small barrier across a stream or drainage line that slows runoff so water infiltrates; suits places with real runoff and valley/slope conditions', 'Percolation Tank': 'a larger storage basin where captured runoff percolates into the aquifer; needs land, runoff and good infiltration', 'Recharge Well': 'a well that sends water directly to the aquifer; suits areas where the water table is deep', 'Farm Pond': 'a pond on agricultural land that captures seasonal runoff; a flexible low-priority fallback', 'Recharge Pit': 'a small localized infiltration pit; suits shallow water tables and permeable soil where space is limited' }
const KB = (zones, c) => { const m = c.meta || {}, n = (t) => zones.filter((z) => z.tier === t).length, tdef = (t) => `${t}: ${DEF[t]}. Illustrative cost ₹${TYPES[t].cost}L; recommended in ${nType(zones, t)} of ${zones.length} zones.`
  const miss = Object.keys(m.factorsAvailable || {}).filter((k) => !m.factorsAvailable[k]).map((k) => FACTORS[k])
  return [
  { k: ['recharge', 'groundwater', 'aquifer', 'what', 'purpose', 'project', 'about', 'aquaprior'], w: 1, a: () => 'AquaPrior ranks where groundwater recharge structures are most worth investigating, recommends what to build, and picks a project mix for a budget. Groundwater recharge means getting more water back into the aquifer (e.g. by capturing monsoon runoff). The score is a relative priority for decisions, not a prediction of future water levels.', ph: ['what is aquaprior', 'what is recharge', 'what does this do'] },
  { k: ['tier', 'high', 'medium', 'low', 'category', 'colour', 'color', 'red', 'amber', 'green'], a: () => `Tiers are relative: High = top 20% of zones (score ≥ ${m.q80}), Medium = next 30% (≥ ${m.q50}), Low = the rest. Currently ${n('High')} High, ${n('Medium')} Medium, ${n('Low')} Low. Pin colours: red High, amber Medium, green Low.`, ph: ['what does high priority mean'] },
  { k: ['legend', 'map', 'pin', 'fade', 'opacity', 'faded', 'marker', 'diamond', 'numbered'], a: () => 'Map legend: coloured dots are scored zones (red/amber/green by tier); fainter dots have lower data confidence (far from measured wells); ◆ outlined dots are the real observation wells; numbered coloured pins are the projects in the current plan. Click any dot for its decision card.', ph: ['how to read the map'] },
  { k: ['confidence', 'nearest', 'distance', 'uncertain', 'reliable'], a: () => 'Data confidence combines distance to the nearest measured well (closer = better) and how many wells are within 15 km. Zones far from any well are interpolated estimates and should be checked first in the field.', ph: ['data confidence'] },
  { k: ['depth', 'bgl', 'level', 'trend', 'decline', 'recovery', 'monsoon', 'premonsoon', 'metre', 'meter'], a: () => 'Water level is depth below ground (bgl) before the monsoon (Mar–May average, recent 5 years): bigger = deeper. Trend is the yearly slope of that depth (+ means the water table is falling). Recovery is the pre-monsoon minus post-monsoon depth, i.e. how much the aquifer recovers after the rains.', ph: ['what is trend'] },
  { k: ['source', 'dataset', 'india', 'wris', 'cgwb', 'real', 'measured', 'year'], a: () => `Data: India-WRIS manual groundwater levels (depth below ground). ${c.wells?.length || 145} Pune-region wells with at least 6 pre-monsoon years between ${m.years?.[0]} and ${m.years?.[1]}. Zones (${m.cellKm} km cells) are predicted from nearby wells.`, ph: ['where does the data come from', 'is this real data'] },
  { k: ['missing', 'rainfall', 'soil', 'slope', 'structure', 'demand', 'improve', 'add', 'layer', 'factor'], a: () => miss.length ? `Not yet in the score: ${miss.join(', ')}. Run analysis/colab_extras.py in Colab, save the output as data/extra_features.csv, then re-run analysis/score_pune.py. Missing factors are skipped and weights renormalised, never invented.` : 'All six blueprint factors are loaded. Caveats: water demand is a proxy (cropland + built-up share, not CGWB extraction data); structure counts come from OpenStreetMap, which is incomplete in rural India; rainfall is CHIRPS 2014-2023 and soil is SoilGrids sand/clay. To improve further: add CGWB block extraction stage, field-verified structures and local cost estimates.', ph: ['what data is missing', 'how can we improve'] },
  { k: ['optimizer', 'optimise', 'optimize', 'algorithm', 'greedy', 'select', 'choose', 'knapsack'], a: () => 'The optimizer ranks candidate projects by estimated benefit per rupee, then adds them while budget remains, with one project per zone, at least 3 km spacing and no intervention type above 45% of budget in the first pass (then a fill pass uses leftovers). It is a transparent heuristic, not a proven optimum.', ph: ['how does the optimizer work'] },
  { k: ['whatif', 'scenario', 'assumption', 'elasticity', 'simulate', 'simulation'], a: () => 'What-if assumptions: rainfall change scales recharge potential (×0.5) and the benefit estimate; extraction change scales groundwater stress (×0.5). These are labelled model-based assumptions, not hydrological forecasts.', ph: ['how does what-if work'] },
  { k: ['benefit', 'unit', 'impact', 'estimate'], a: () => 'Benefit is an illustrative index: base benefit of the structure × score × rainfall factor × suitability × data confidence. It is for comparing options, not litres of water recharged.', ph: ['what is benefit'] },
  { k: ['aws', 'backend', 'deploy', 'lambda', 'strands', 'bedrock', 'agent', 'cloud', 'dynamodb', 'api'], a: () => 'The AWS backend (API Gateway, Lambda, S3, DynamoDB, Strands agent) is optional. It exists in backend/ and is not deployed in this offline session; this assistant already answers from the same engine locally. See docs/FEATURES.md step 10 to deploy it.', ph: ['do we need aws', 'is it deployed'] },
  { k: ['start', 'use', 'guide', 'tutorial', 'demo', 'step', 'begin', 'work'], a: () => 'Quick path: 1) Dashboard shows coverage and top zones. 2) Map & zone: click a red pin. 3) Budget & what-if: set ₹ budget, rainfall and extraction. 4) Scenarios: compare four cases. 5) Impact summary: print the final plan. Ask me anything along the way.', ph: ['how do i use this'] },
  { k: ['next', 'recommend', 'advice', 'suggest', 'action', 'priority', 'first', 'begin', 'survey', 'field'], a: () => { const p = optimize(zones, c.budget || 20, c.rain || 0, c.ex || 0); return `Suggested next steps: (1) field-verify the top zones, starting with ${zones.slice(0, 3).map((z) => z.id).join(', ')}; (2) check the weakest-data zones in the plan first; (3) for ₹${c.budget || 20}L the current plan has ${p.n} projects (${Object.entries(p.mix).map(([k, v]) => `${v}× ${k}`).join(', ')}); (4) validate costs with local estimates and have a hydrologist review sites.` }, ph: ['what should we do next', 'what do you recommend'] },
  { k: ['risk', 'limitation', 'caveat', 'wrong', 'error', 'problem', 'weakness', 'honest'], a: () => `Honest limits: modest model accuracy (R² ${m.metrics?.final_r2} on unseen wells), ${miss.length ? miss.length + ' of 6 factors not loaded' : 'water demand is only a proxy and OSM structure counts are incomplete'}, rule-based interventions, illustrative costs/benefits, and relative (not absolute) tiers. Use results to shortlist where to investigate, not to certify sites.`, ph: ['what are the limitations'] },
  { k: ['hello', 'hi', 'hey', 'thanks', 'thank', 'help'], a: () => 'Hi! Try: "why is G047049 ranked #1?", "I have 10 lakh and rainfall drops 20%", "top 5 deepest zones", "where should I build percolation tanks?", "how accurate is this?", or "what should we do next?".', ph: [] },
  ...Object.keys(TYPES).map((t) => ({ k: TYPE_KEYS.filter(([, v]) => v === t).map(([k]) => k.split(' ').pop()).concat(t.toLowerCase().split(' ')), a: () => tdef(t), ph: [t.toLowerCase()] })),
] }
function openEnded(q, zones, c) {
  const qt = toks(q), x = q.toLowerCase(), types = [...new Set(TYPE_KEYS.filter(([k]) => x.includes(k)).map(([, v]) => v))]
  if (types.length >= 2) return types.map((t) => `${t}: ${DEF[t]}. ₹${TYPES[t].cost}L (illustrative); recommended in ${nType(zones, t)} zones.`).join('\n')
  const kb = KB(zones, c), scored = kb.map((e) => ({ e, s: e.k.reduce((a, kw) => a + (hit(qt, stem(kw)) ? 1 : 0), 0) + (e.ph || []).reduce((a, p) => a + (x.includes(p) ? 3 : 0), 0) })).sort((a, b) => b.s - a.s)
  if (scored[0].s > 0) { const top = scored[0], extra = scored[1].s > 0 && scored[1].s >= top.s - 0 && scored[1].e !== top.e ? '\n\nAlso relevant: ' + scored[1].e.a() : ''; return top.e.a() + extra }
  const p = optimize(zones, c.budget || 20, c.rain || 0, c.ex || 0)
  return `I don't have a specific answer for that, but here is the current picture: ${zones.filter((z) => z.tier === 'High').length} High-priority zones; top zones ${zones.slice(0, 3).map((z) => `${z.id} (${z.score})`).join(', ')}; the ₹${c.budget || 20}L plan funds ${p.n} projects with estimated benefit ${p.benefit}. Ask about a zone ID, a budget, a scenario, an intervention type, the data, the score method, accuracy or next steps.`
}

const f2 = (v) => (+v).toFixed(1)
