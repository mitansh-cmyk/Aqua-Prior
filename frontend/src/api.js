// Optional AWS backend. If VITE_API_URL is empty the app runs fully offline with the same engine in lib.js.
export const API = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
const call = async (path, body) => {
  const r = await fetch(API + path, body ? { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) } : undefined)
  if (!r.ok) throw new Error(`${path} → HTTP ${r.status}`); return r.json()
}
export const api = {
  health: () => call('/health'),
  agent: (question) => call('/agent', { question }),
  savePlan: (p) => call('/optimize', { budget: p.budget, rain: p.rain, extraction: p.extraction, save: true }),
}
