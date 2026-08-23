// Capture de la provenance à la première visite (source / referrer / utm / landing).
const KEY = 'joboolo_attribution';

const computeSource = (referrer, utmSource) => {
  if (utmSource) return utmSource;
  if (!referrer) return 'direct';
  try {
    const host = new URL(referrer).hostname;
    if (host.includes('google')) return 'google';
    if (host.includes(window.location.hostname)) return 'direct';
    return `referrer:${host}`;
  } catch {
    return 'referrer';
  }
};

export const captureAttribution = () => {
  try {
    const existing = localStorage.getItem(KEY);
    if (existing) return JSON.parse(existing);
    const params = new URLSearchParams(window.location.search);
    const referrer = document.referrer || '';
    const data = {
      signup_source: computeSource(referrer, params.get('utm_source')),
      signup_referrer: referrer || null,
      signup_landing: window.location.pathname + window.location.search,
      utm_source: params.get('utm_source') || null,
      utm_medium: params.get('utm_medium') || null,
      utm_campaign: params.get('utm_campaign') || null,
    };
    localStorage.setItem(KEY, JSON.stringify(data));
    return data;
  } catch {
    return {};
  }
};

export const getAttribution = () => {
  try {
    return JSON.parse(localStorage.getItem(KEY) || '{}');
  } catch {
    return {};
  }
};
