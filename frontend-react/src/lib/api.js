// a API vive em /iptv/ ; o app pode estar em /iptv/ ou /iptv/v2/ durante a
// migração, então fixamos o prefixo da API absoluto.
const BASE = "/iptv/";

let _token = null;
export function setToken(t) {
  _token = t;
}
export function getToken() {
  return _token;
}

async function req(path, opts = {}) {
  const resp = await fetch(BASE + path, { credentials: "include", ...opts });
  if (!resp.ok) {
    const body = await resp.json().catch(() => ({}));
    const err = new Error(body.detail || `HTTP ${resp.status}`);
    err.status = resp.status;
    throw err;
  }
  return resp.json();
}

// --- público (precisa de token no path) ---
export const api = {
  channels: () => req(`p/${encodeURIComponent(_token)}/channels.json`),
  vod: (params = {}) =>
    req(`p/${encodeURIComponent(_token)}/vod?${new URLSearchParams(params)}`),
  vodHome: (perGenre = 15) =>
    req(`p/${encodeURIComponent(_token)}/vod/home?per_genre=${perGenre}`),
  vodGenres: () => req(`p/${encodeURIComponent(_token)}/vod/genres`),
  vodDetail: (id) => req(`p/${encodeURIComponent(_token)}/vod/${id}`),
  resolve: (tvgId, lang) =>
    req(
      `p/${encodeURIComponent(_token)}/channels/${encodeURIComponent(tvgId)}/resolve` +
        (lang ? `?lang=${encodeURIComponent(lang)}` : "")
    ),
  epg: (tvgId) =>
    req(`p/${encodeURIComponent(_token)}/channels/${encodeURIComponent(tvgId)}/epg`),
  reportFailure: (tvgId, url) =>
    fetch(
      BASE + `p/${encodeURIComponent(_token)}/channels/${encodeURIComponent(tvgId)}/report-failure`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url }),
      }
    ).catch(() => {}),
};

// --- admin (sessão por cookie) ---
export const adminApi = {
  me: () => req("admin/me"),
  tokens: () => req("admin/tokens"),
  login: (username, password) =>
    req("admin/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username, password }),
    }),
  logout: () => fetch(BASE + "admin/logout", { method: "POST", credentials: "include" }).catch(() => {}),
};
