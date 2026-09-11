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

  // "Continuar assistindo"
  continueWatching: () => req(`p/${encodeURIComponent(_token)}/continue-watching`),
  saveProgress: (body) =>
    fetch(BASE + `p/${encodeURIComponent(_token)}/progress`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      keepalive: true, // sobrevive ao fechar a aba
      body: JSON.stringify(body),
    }).catch(() => {}),
  removeProgress: (titleId) =>
    fetch(BASE + `p/${encodeURIComponent(_token)}/progress/${titleId}`, {
      method: "DELETE",
    }).catch(() => {}),

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
const jpost = (path, body) =>
  req(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const jpatch = (path, body) =>
  req(path, { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
const jdel = (path) => req(path, { method: "DELETE" });

export const adminApi = {
  me: () => req("admin/me"),
  tokens: () => req("admin/tokens"),
  login: (username, password) => jpost("admin/login", { username, password }),
  logout: () => fetch(BASE + "admin/logout", { method: "POST", credentials: "include" }).catch(() => {}),

  dashboard: () => req("admin/dashboard"),
  streams: (healthy) => req(`admin/streams${healthy == null ? "" : "?healthy=" + healthy}`),

  // jobs (todos: POST inicia -> {job_id}; GET status)
  startClassifyImdb: () => jpost("admin/vod/classify-genres-imdb"),
  classifyImdbStatus: (id) => req(`admin/vod/classify-genres-imdb/${id}/status`),
  startFetchMetadata: () => jpost("admin/vod/fetch-metadata"),
  fetchMetadataStatus: (id) => req(`admin/vod/fetch-metadata/${id}/status`),
  startHealthcheck: () => jpost("admin/healthcheck"),
  healthcheckStatus: (id) => req(`admin/healthcheck/${id}/status`),
  startClassifyChannels: () => jpost("admin/channels/classify-categories"),
  classifyChannelsStatus: (id) => req(`admin/channels/classify-categories/${id}/status`),

  // sistema (processos + consumo)
  systemJobs: () => req("admin/system/jobs"),
  cancelJob: (id) => jpost(`admin/system/jobs/${id}/cancel`),
  systemResources: () => req("admin/system/resources"),

  // banco (consulta somente-leitura)
  dbTables: () => req("admin/db/tables"),
  dbTable: (name) => req(`admin/db/tables/${encodeURIComponent(name)}`),
  dbQuery: (sql) => jpost("admin/db/query", { sql }),

  // usuários do site (login admin/usuário)
  users: () => req("admin/users"),
  createUser: (b) => jpost("admin/users", b),
  deleteUser: (id) => jdel(`admin/users/${id}`),

  // gêneros manuais
  titlesWithoutGenre: (type, limit, offset) =>
    req(`admin/vod/titles-without-genre?type=${type}&limit=${limit}&offset=${offset}`),
  setTitleGenre: (id, genre) => jpatch(`admin/vod/titles/${id}/genre`, { genre }),

  // genre-keywords
  genreKeywords: () => req("admin/genre-keywords"),
  addGenreKeyword: (genre, keyword) => jpost("admin/genre-keywords", { genre, keyword }),
  delGenreKeyword: (id) => jdel(`admin/genre-keywords/${id}`),
  delGenre: (genre) => jdel(`admin/genre-keywords/genre/${encodeURIComponent(genre)}`),

  // catálogo / cadastro
  vodList: (params = {}) => req(`admin/vod?${new URLSearchParams(params)}`),
  vodAdminDetail: (id) => req(`admin/vod/${id}`),
  addMovie: (b) => jpost("admin/vod/movie", b),
  addSeries: (b) => jpost("admin/vod/series", b),
  addEpisode: (titleId, b) => jpost(`admin/vod/${titleId}/episodes`, b),
  updateItem: (id, b) => jpatch(`admin/vod/items/${id}`, b),
  delTitle: (id) => jdel(`admin/vod/titles/${id}`),
  delItem: (id) => jdel(`admin/vod/items/${id}`),
  addChannel: (b) => jpost("admin/channels", b),

  // catálogo de canais
  channelCategories: () => req("admin/channels/categories"),
  channelList: (params = {}) => req(`admin/channels?${new URLSearchParams(params)}`),
  channelDetail: (id) => req(`admin/channels/${id}`),
  updateChannel: (id, b) => jpatch(`admin/channels/${id}`, b),
  delChannel: (id) => jdel(`admin/channels/${id}`),
  updateStream: (id, b) => jpatch(`admin/streams/${id}`, b),
  delStream: (id) => jdel(`admin/streams/${id}`),

  importCsvStatus: (id) => req(`admin/vod/import-csv/${id}/status`),
  importCsv: (file) => {
    const fd = new FormData();
    fd.append("file", file);
    return fetch(BASE + "admin/vod/import-csv", { method: "POST", credentials: "include", body: fd }).then(async (r) => {
      const j = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(j.detail || `HTTP ${r.status}`);
      return j;
    });
  },
};
