// Placeholder API client for accounting endpoints
// Intentionally minimal; to be wired to /accounting/api/* endpoints later.
const csrfToken = document.querySelector('meta[name=\"csrf-token\"]')?.content || '';
export async function fetchJSON(url, opts = {}) {
  const headers = { 'Content-Type': 'application/json', ...(opts.headers || {}) };
  if (csrfToken) {
    headers['X-CSRFToken'] = csrfToken;
  }
  const res = await fetch(url, { credentials: 'same-origin', ...opts, headers });
  if (!res.ok) throw new Error(await res.text());
  return res.json();
}

export const AccountingAPI = {
  // Examples (to be used in future refactor replacing localStorage)
  listCuentas: (empresa) => fetchJSON(`/accounting/api/cuentas${empresa?`?empresa=${empresa}`:''}`),
  listAsientos: (empresa) => fetchJSON(`/accounting/api/asientos${empresa?`?empresa=${empresa}`:''}`),
  createAsiento: (payload) => fetchJSON(`/accounting/api/asientos`, { method: 'POST', body: JSON.stringify(payload) }),
  mayor: (empresa, cuenta) => fetchJSON(`/accounting/api/mayor?cuenta=${cuenta}${empresa?`&empresa=${empresa}`:''}`),
  balance: (empresa) => fetchJSON(`/accounting/api/balance${empresa?`?empresa=${empresa}`:''}`),
  estados: (empresa) => fetchJSON(`/accounting/api/estados${empresa?`?empresa=${empresa}`:''}`),
};
