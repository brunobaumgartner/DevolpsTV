import { useState, useEffect } from "preact/hooks";
import { adminApi, api } from "../../lib/api.js";
import { ChipBar } from "../../components/ChipBar.jsx";

const PAGE = 30;

function num(v) {
  return v ? Number(v) : null;
}

// tela própria (era um Panel dentro de "Cadastro" que carregava os 26k+
// títulos com todos os 273k itens de uma vez — pesadíssimo). Paginado e
// filtrado igual à listagem pública; os episódios de cada título só carregam
// quando expande o card (GET /admin/vod/{id}), não na listagem.
export function AdminVodCatalog() {
  const [q, setQ] = useState("");
  const [type, setType] = useState("");
  const [genre, setGenre] = useState(null);
  const [page, setPage] = useState(0);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);
  const [genres, setGenres] = useState([]);
  const [openId, setOpenId] = useState(null);

  useEffect(() => {
    api.vodGenres().then((d) => setGenres(d.genres || [])).catch(() => {});
  }, []);

  function load(p = page) {
    setLoading(true);
    const params = { limit: PAGE, offset: p * PAGE };
    if (type) params.type = type;
    if (genre) params.genre = genre;
    if (q) params.q = q;
    adminApi
      .vodList(params)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }

  useEffect(() => {
    setPage(0);
    load(0);
  }, [q, type, genre]);

  const total = data?.count || 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));

  const go = (p) => {
    setPage(p);
    load(p);
    window.scrollTo({ top: 0 });
  };

  const reload = () => load(page);

  return (
    <div class="p-4 md:p-8">
      <h1 class="text-lg text-accent font-display mb-4">Catálogo</h1>

      <div class="flex flex-wrap items-center gap-3 mb-2">
        <input
          value={q}
          onInput={(e) => setQ(e.currentTarget.value)}
          placeholder="Buscar título…"
          class="flex-1 min-w-[160px] bg-[#081019] border border-border rounded px-3 py-1.5 text-sm"
        />
        <div class="flex gap-1.5">
          {[
            ["", "Todos"],
            ["movie", "Filmes"],
            ["series", "Séries"],
          ].map(([v, l]) => (
            <button class={"chip " + (type === v ? "active" : "")} onClick={() => setType(v)}>
              {l}
            </button>
          ))}
        </div>
      </div>

      <ChipBar
        items={genres.map((g) => ({ value: g.genre, label: `${g.genre} (${g.count})` }))}
        active={genre}
        onSelect={setGenre}
      />

      <div class="text-[11px] text-muted mb-2">{total} título(s)</div>

      {loading && !data && <div class="text-muted text-sm py-10">Carregando…</div>}
      {data && data.titles.length === 0 && <div class="text-muted text-sm py-10">Nada encontrado.</div>}

      <div class="space-y-2">
        {data?.titles.map((t) => (
          <TitleRow t={t} open={openId === t.id} onToggle={() => setOpenId(openId === t.id ? null : t.id)} onChange={reload} />
        ))}
      </div>

      {pages > 1 && (
        <div class="flex items-center justify-center gap-4 mt-6 text-sm">
          <button class="btn-ghost rounded px-3 py-1.5 border border-border disabled:opacity-40" disabled={page <= 0} onClick={() => go(page - 1)}>
            ← Anterior
          </button>
          <span class="text-muted">
            {page + 1} / {pages}
          </span>
          <button class="btn-ghost rounded px-3 py-1.5 border border-border disabled:opacity-40" disabled={page + 1 >= pages} onClick={() => go(page + 1)}>
            Próxima →
          </button>
        </div>
      )}
    </div>
  );
}

function TitleRow({ t, open, onToggle, onChange }) {
  const [detail, setDetail] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    if (open && !detail) {
      setLoading(true);
      adminApi.vodAdminDetail(t.id).then((d) => {
        setDetail(d);
        setLoading(false);
      });
    }
  }, [open]);

  return (
    <div class="border border-border rounded-md bg-card">
      <button class="w-full flex items-center gap-2 p-3 text-left" onClick={onToggle}>
        <span class="text-muted text-xs w-4">{open ? "▾" : "▸"}</span>
        {t.poster_url ? (
          <img src={t.poster_url} class="w-8 h-11 object-cover rounded shrink-0" />
        ) : (
          <div class="w-8 h-11 rounded bg-card-hover shrink-0" />
        )}
        <strong class="text-sm flex-1 truncate">{t.title}</strong>
        <span class="text-[11px] text-muted shrink-0">
          {t.type === "movie" ? "filme" : "série"}
          {t.genre ? " · " + t.genre : ""}
          {t.year ? " · " + t.year : ""}
        </span>
        <span
          class="text-[11px] text-danger border border-danger rounded px-2 py-0.5 shrink-0"
          onClick={async (e) => {
            e.stopPropagation();
            if (!confirm(`Excluir "${t.title}"?`)) return;
            await adminApi.delTitle(t.id);
            onChange();
          }}
        >
          excluir
        </span>
      </button>

      {open && (
        <div class="px-3 pb-3 border-t border-border">
          {loading && <div class="text-muted text-xs py-2">Carregando episódios…</div>}
          {detail?.items.map((it) => (
            <ItemRow t={detail} it={it} onChange={() => adminApi.vodAdminDetail(t.id).then(setDetail)} />
          ))}
          {detail?.type === "series" && (
            <AddEpisode titleId={t.id} onChange={() => adminApi.vodAdminDetail(t.id).then(setDetail)} />
          )}
        </div>
      )}
    </div>
  );
}

function ItemRow({ t, it, onChange }) {
  const [url, setUrl] = useState(it.stream_url || "");
  const [saved, setSaved] = useState(false);
  const label = t.type === "series" ? `T${it.season_number ?? "?"}E${it.episode_number ?? "?"} ${it.episode_title || ""}` : "Link do filme";
  return (
    <div class="flex items-center gap-2 py-1.5 border-t border-border/60 text-xs">
      <span class="w-32 shrink-0 text-muted truncate">{label}</span>
      <input
        class="flex-1 bg-[#081019] border border-border rounded px-2 py-1"
        placeholder="sem link"
        value={url}
        onInput={(e) => setUrl(e.currentTarget.value)}
      />
      <button
        class="btn-ghost rounded px-2 py-1 border border-border"
        onClick={async () => {
          await adminApi.updateItem(it.id, { stream_url: url.trim() || null });
          setSaved(true);
          setTimeout(() => setSaved(false), 1500);
        }}
      >
        {saved ? "✓" : "salvar"}
      </button>
      {t.type === "series" && (
        <button
          class="text-danger"
          onClick={async () => {
            await adminApi.delItem(it.id);
            onChange();
          }}
        >
          ×
        </button>
      )}
    </div>
  );
}

function AddEpisode({ titleId, onChange }) {
  return (
    <form
      class="flex gap-1.5 mt-2"
      onSubmit={async (e) => {
        e.preventDefault();
        const els = e.currentTarget.elements;
        await adminApi.addEpisode(titleId, {
          season_number: num(els.s.value),
          episode_number: num(els.ep.value),
          episode_title: els.t.value.trim() || null,
          stream_url: els.u.value.trim() || null,
        });
        e.currentTarget.reset();
        onChange();
      }}
    >
      <input name="s" type="number" placeholder="T" class="w-12 bg-[#081019] border border-border rounded px-2 py-1 text-xs" />
      <input name="ep" type="number" placeholder="E" class="w-12 bg-[#081019] border border-border rounded px-2 py-1 text-xs" />
      <input name="t" placeholder="Nome" class="flex-1 bg-[#081019] border border-border rounded px-2 py-1 text-xs" />
      <input name="u" placeholder="Link" class="flex-1 bg-[#081019] border border-border rounded px-2 py-1 text-xs" />
      <button class="btn-ghost rounded px-2 py-1 border border-border text-xs">+ ep</button>
    </form>
  );
}
