// Visitor search history persisted in localStorage (works logged-in or not). Max 10 entries.
const KEY = 'joboolo_search_history';
const MAX = 10;

export function getHistory() {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '[]');
  } catch {
    return [];
  }
}

export function addSearch({ job, location }) {
  const j = (job || '').trim();
  const l = (location || '').trim();
  if (!j && !l) return getHistory();
  let list = getHistory().filter((s) => !(s.job === j && s.location === l));
  list.unshift({ job: j, location: l, ts: Date.now() });
  list = list.slice(0, MAX);
  localStorage.setItem(KEY, JSON.stringify(list));
  window.dispatchEvent(new Event('joboolo-history-changed'));
  return list;
}

export function removeSearch(index) {
  const list = getHistory();
  list.splice(index, 1);
  localStorage.setItem(KEY, JSON.stringify(list));
  window.dispatchEvent(new Event('joboolo-history-changed'));
  return list;
}

export function clearHistory() {
  localStorage.removeItem(KEY);
  window.dispatchEvent(new Event('joboolo-history-changed'));
  return [];
}

// Country preference (simplified geo — stored in cookie-like localStorage)
const COUNTRY_KEY = 'joboolo_country';
export function getCountry() {
  return localStorage.getItem(COUNTRY_KEY) || 'FR';
}
export function setCountry(code) {
  localStorage.setItem(COUNTRY_KEY, code);
}
