import { useState, useEffect } from "preact/hooks";
import { adminApi } from "../../lib/api.js";
import { JobButton } from "../../components/admin/JobButton.jsx";
import { Bars } from "../../components/admin/Bars.jsx";

function Card({ label, value, sub }) {
  return (
    <div class="rounded-md border border-border bg-card p-4">
      <div class="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div class="text-2xl font-bold text-accent mt-1">{value}</div>
      {sub && <div class="text-[11px] text-muted mt-1">{sub}</div>}
    </div>
  );
}

function Panel({ title, children }) {
  return (
    <section class="rounded-md border border-border bg-card p-4 mb-4">
      <h2 class="text-[12px] uppercase tracking-wide text-muted mb-3">{title}</h2>
      {children}
    </section>
  );
}

function fmtAge(s) {
  if (s == null) return "nunca";
  if (s < 60) return `há ${s | 0}s`;
  if (s < 3600) return `há ${(s / 60) | 0}min`;
  if (s < 86400) return `há ${(s / 3600) | 0}h`;
  return `há ${(s / 86400) | 0}d`;
}

const JOB_LABELS = {
  fetch_channels: "Buscar canais",
  healthcheck: "Health-check",
  fetch_epg: "Buscar EPG",
  fetch_fast_meta: "Metadado FAST",
};

export function AdminDashboard() {
  const [s, setS] = useState(null);
  const [modal, setModal] = useState(null); // 'streams' | {genreType}

  const load = () => adminApi.dashboard().then(setS).catch(() => {});
  useEffect(() => {
    load();
    const t = setInterval(load, 30000);
    return () => clearInterval(t);
  }, []);

  if (!s) return <div class="p-8 text-muted text-sm">Carregando…</div>;

  const langRows = (s.streams.by_language || []).map((r) => ({ label: r.language, v: r.count }));
  const catRows = (s.channels.by_category || []).slice(0, 14).map((r) => ({ label: r.category, v: r.count }));
  const movieG = (s.vod.movies_by_genre || []).slice(0, 15).map((r) => ({ label: r.genre, v: r.count, _clickable: r.genre === "sem gênero", _type: "movie" }));
  const seriesG = (s.vod.series_by_genre || []).slice(0, 15).map((r) => ({ label: r.genre, v: r.count, _clickable: r.genre === "sem gênero", _type: "series" }));

  return (
    <div class="p-4 md:p-8">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-3 mb-4">
        <Card label="Canais ativos" value={s.channels.total_active} sub={`${s.channels.with_healthy_stream} no ar`} />
        <div class="cursor-pointer" onClick={() => setModal("streams")}>
          <Card label="Streams saudáveis" value={s.streams.healthy} sub={`de ${s.streams.total} (clique)`} />
        </div>
        <Card label="TV aberta" value={s.channels.broadcast_tv} />
        <Card label="EPG" value={s.epg.channels_with_epg} sub={`${s.epg.total_programs} programas`} />
        <Card label="Catálogo VOD" value={s.vod.total_titles} sub={`${s.vod.movies} filmes · ${s.vod.series} séries`} />
        <Card label="Itens com link" value={s.vod.items_with_link} sub={`de ${s.vod.total_items}`} />
        <Card label="Tokens ativos" value={s.access_tokens} />
      </div>

      <Panel title="Ações">
        <div class="space-y-4">
          <JobButton
            label="Classificar gêneros"
            start={adminApi.startClassifyImdb}
            poll={adminApi.classifyImdbStatus}
            format={(j) => `IMDb: ${j.newly_classified} novo(s), ${j.corrected} corrigido(s); palavra-chave: ${j.keyword_classified}.`}
          />
          <JobButton
            label="Health-check agora"
            start={adminApi.startHealthcheck}
            poll={adminApi.healthcheckStatus}
            format={(j) => `${j.healthy} de ${j.total} respondendo.`}
          />
          <JobButton
            label="Classificar canais sem categoria"
            start={adminApi.startClassifyChannels}
            poll={adminApi.classifyChannelsStatus}
            format={(j) => `${j.classified} de ${j.total} classificados.`}
          />
        </div>
      </Panel>

      <Panel title="Jobs do worker">
        <table class="w-full text-xs">
          <tbody>
            {Object.keys(JOB_LABELS).map((k) => {
              const j = s.worker_jobs.find((x) => x.job_name === k);
              return (
                <tr class="border-t border-border first:border-0">
                  <td class="py-1.5">{JOB_LABELS[k]}</td>
                  <td class={"py-1.5 " + (j?.status === "error" ? "text-danger" : "text-ok")}>{j?.status || "—"}</td>
                  <td class="py-1.5 text-muted">{fmtAge(j?.age_seconds)}</td>
                  <td class="py-1.5 text-muted truncate max-w-[280px]">{j?.summary || ""}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </Panel>

      <Panel title="Streams por idioma"><Bars rows={langRows} labelKey="label" valueKey="v" /></Panel>
      <Panel title="Canais por categoria"><Bars rows={catRows} labelKey="label" valueKey="v" /></Panel>
      <Panel title="Filmes por gênero">
        <Bars rows={movieG} labelKey="label" valueKey="v" onRowClick={() => setModal({ genreType: "movie" })} />
      </Panel>
      <Panel title="Séries por gênero">
        <Bars rows={seriesG} labelKey="label" valueKey="v" onRowClick={() => setModal({ genreType: "series" })} />
      </Panel>

      {modal === "streams" && <StreamsModal onClose={() => setModal(null)} />}
      {modal?.genreType && <GenreAssignModal type={modal.genreType} onClose={() => setModal(null)} />}
    </div>
  );
}

function Backdrop({ children, onClose }) {
  return (
    <div class="fixed inset-0 bg-black/70 grid place-items-center p-4 z-50" onClick={(e) => e.target === e.currentTarget && onClose()}>
      <div class="bg-card border border-border rounded-lg w-full max-w-2xl max-h-[85vh] flex flex-col overflow-hidden">
        {children}
      </div>
    </div>
  );
}

function StreamsModal({ onClose }) {
  const [tab, setTab] = useState(true); // true = saudáveis
  const [rows, setRows] = useState(null);
  useEffect(() => {
    setRows(null);
    adminApi.streams(tab).then((d) => setRows(d.streams)).catch(() => setRows([]));
  }, [tab]);
  return (
    <Backdrop onClose={onClose}>
      <div class="flex items-center justify-between px-4 py-3 border-b border-border">
        <h3 class="text-accent text-sm">Streams testados</h3>
        <button class="text-muted hover:text-danger" onClick={onClose}>×</button>
      </div>
      <div class="flex gap-1 px-4 pt-2 border-b border-border">
        {[["Saudáveis", true], ["Não saudáveis", false]].map(([l, v]) => (
          <button class={"px-3 py-2 text-xs uppercase tracking-wide border-b-2 " + (tab === v ? "text-accent border-accent" : "text-muted border-transparent")} onClick={() => setTab(v)}>
            {l}
          </button>
        ))}
      </div>
      <div class="overflow-y-auto p-4 text-xs">
        {!rows && <div class="text-muted">Carregando…</div>}
        {rows && rows.length === 0 && <div class="text-muted">Nenhum.</div>}
        {rows &&
          rows.map((r) => (
            <div class="py-2 border-t border-border first:border-0">
              <div class="font-semibold">{r.channel_name || "(?)"}</div>
              <div class="text-muted break-all">{r.url}</div>
              <div class="text-muted text-[11px]">
                {r.checked_age_seconds != null ? "checado " + fmtAge(r.checked_age_seconds) : "nunca"}
                {r.consecutive_failures ? ` · ${r.consecutive_failures} falha(s)` : ""}
              </div>
            </div>
          ))}
      </div>
    </Backdrop>
  );
}

function GenreAssignModal({ type, onClose }) {
  const PAGE = 20;
  const [offset, setOffset] = useState(0);
  const [data, setData] = useState(null);
  const [genres, setGenres] = useState([]);

  useEffect(() => {
    adminApi.genreKeywords().then((d) => setGenres((d.genres || []).map((g) => g.genre)));
  }, []);
  const load = () => {
    setData(null);
    adminApi.titlesWithoutGenre(type, PAGE, offset).then(setData).catch(() => setData({ titles: [], total: 0 }));
  };
  useEffect(load, [offset, type]);

  return (
    <Backdrop onClose={onClose}>
      <div class="flex items-center justify-between px-4 py-3 border-b border-border">
        <h3 class="text-accent text-sm">Classificar {type === "movie" ? "filmes" : "séries"} sem gênero</h3>
        <button class="text-muted hover:text-danger" onClick={onClose}>×</button>
      </div>
      <div class="overflow-y-auto p-4">
        {!data && <div class="text-muted text-sm">Carregando…</div>}
        {data?.titles.map((t) => (
          <div class="py-2 border-t border-border first:border-0" data-id={t.id}>
            <div class="text-sm">{t.title}{t.year ? ` (${t.year})` : ""}</div>
            <div class="flex gap-2 mt-1.5 items-center">
              <select class="bg-[#081019] border border-border rounded px-2 py-1 text-xs flex-1" id={`g-${t.id}`}>
                <option value="">Selecione…</option>
                {genres.map((g) => <option value={g}>{g}</option>)}
              </select>
              <button
                class="btn-ghost text-[11px] rounded px-2 py-1 border border-border"
                onClick={async (e) => {
                  const sel = document.getElementById(`g-${t.id}`);
                  if (!sel.value) return;
                  e.currentTarget.disabled = true;
                  await adminApi.setTitleGenre(t.id, sel.value);
                  e.currentTarget.textContent = "salvo ✓";
                  e.currentTarget.closest("[data-id]").style.opacity = ".4";
                }}
              >
                salvar
              </button>
            </div>
          </div>
        ))}
      </div>
      <div class="flex items-center justify-between px-4 py-2 border-t border-border text-xs">
        <span class="text-muted">{data ? `${offset + 1}–${offset + (data.titles?.length || 0)} de ${data.total}` : ""}</span>
        <div class="flex gap-2">
          <button class="btn-ghost rounded px-2 py-1 border border-border" disabled={offset <= 0} onClick={() => setOffset(Math.max(0, offset - PAGE))}>←</button>
          <button class="btn-ghost rounded px-2 py-1 border border-border" disabled={data && offset + PAGE >= data.total} onClick={() => setOffset(offset + PAGE)}>→</button>
        </div>
      </div>
    </Backdrop>
  );
}
