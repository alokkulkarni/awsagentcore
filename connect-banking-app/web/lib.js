// Shared by every page. The page link's secret lives only here, in memory and in this device's storage, and
// goes only in the body of this app's own API calls (never in an address, so never in a log or a Referer).
// Every value is written as text, never as HTML.
export const $ = (id) => document.getElementById(id);
export const text = (id, value) => { const node = $(id); if (node) node.textContent = value; };
export const gbp = (n) => `${Number(n) < 0 ? '−' : ''}£${Math.abs(Number(n)).toLocaleString('en-GB', { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
export const pounds = (n) => `£${Math.round(Number(n)).toLocaleString('en-GB')}`;
export const day = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('en-GB', { day: 'numeric', month: 'short' });
export const longDay = (iso) => new Date(`${iso}T12:00:00`).toLocaleDateString('en-GB', { weekday: 'long', day: 'numeric', month: 'long' });
export const monthName = (key) => new Date(`${key}-15T12:00:00`).toLocaleDateString('en-GB', { month: 'long', year: 'numeric' });

export function el(tag, className, content) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (content !== undefined) node.textContent = content;
  return node;
}

// Stores that may refuse (private browsing, blocked storage): the app works without them.
export const store = {
  get(area, key) { try { return JSON.parse(area.getItem(key)); } catch { return null; } },
  set(area, key, value) { try { area.setItem(key, JSON.stringify(value)); } catch { /* not kept */ } },
  remove(area, key) { try { area.removeItem(key); } catch { /* nothing kept */ } },
};

const LINK_KEY = 'bankingAppLink';
let token = '';
let onExpired = () => {};

// Opened from a link whose secret is after "#": read once, wiped from the address bar, kept on this device.
export function readLink() {
  token = new URLSearchParams(location.hash.slice(1)).get('k') || store.get(localStorage, LINK_KEY) || '';
  if (location.hash) history.replaceState(null, '', location.pathname);
  if (token) store.set(localStorage, LINK_KEY, token);
  return token;
}

export function forgetLink() {
  token = '';
  store.remove(localStorage, LINK_KEY);
  try { sessionStorage.clear(); } catch { /* nothing kept */ }
}

export function whenExpired(handler) { onExpired = handler; }

export async function api(path, body = {}) {
  const response = await fetch(`/api${path}`, {
    method: 'POST', headers: { 'content-type': 'application/json' }, body: JSON.stringify({ ...body, token }),
  });
  const json = await response.json().catch(() => ({}));
  if (json.error === 'link_expired') onExpired();
  if (!response.ok) throw new Error(json.message || `Something went wrong (${response.status}).`);
  return json;
}

// A merchant's tile: its initials on a colour of its own (the same merchant always gets the same colour).
export function initialsTile(name) {
  const tile = el('span', 'tx-logo');
  tile.setAttribute('aria-hidden', 'true');
  // A web address's ending isn't a word: "AMAZON.CO.UK" is "A", not "AC".
  const words = String(name || '?').replace(/\.(com|co\.uk|uk|net)\b.*$/i, '').replace(/[^A-Za-z0-9 ]/g, ' ').split(/\s+/).filter(Boolean);
  let hash = 0;
  for (const ch of String(name || '')) hash = (hash * 31 + ch.charCodeAt(0)) >>> 0;
  tile.dataset.tone = String(hash % 8);
  tile.textContent = (words.length > 1 ? words[0][0] + words[1][0] : (words[0] || '?')[0]).toUpperCase();
  return tile;
}

// "Netflix.com" from "NETFLIX.COM", "Tesco Stores 2041" from "TESCO STORES 2041": each word's first letter only.
export const tidyMerchant = (name) => String(name || '').toLowerCase().replace(/(^|[\s/-])([a-z])/g, (_, gap, c) => gap + c.toUpperCase());
