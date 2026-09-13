import { useState, useEffect } from "preact/hooks";
import { api } from "../lib/api.js";
import { useFetch } from "../lib/useFetch.js";
import { navigate } from "../lib/router.jsx";
import { Card } from "../components/Card.jsx";
import { ChipBar } from "../components/ChipBar.jsx";

const PAGE = 60;

export function LiveTV() {
  const [q, setQ] = useState("");
  const [cat, setCat] = useState(null);
  const [page, setPage] = useState(0);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  // contagem por categoria vem do servidor (achado em 2026-09-13: montar o
  // chip bar a partir da lista de canais já carregada no navegador não dava
  // pra paginar — e sem contagem real, a lista de ~1200 categorias virava
  // uma bagunça sem hierarquia nenhuma)
  const categories = useFetch("channel-categories", () => api.channelCategories());

  useEffect(() => {
    const id = setTimeout(() => {
      setPage(0);
      fetchPage(0, q, cat);
    }, 250);
    return () => clearTimeout(id);
  }, [q, cat]);

  function fetchPage(p, qq = q, cc = cat) {
    setLoading(true);
    const params = { limit: PAGE, offset: p * PAGE };
    if (cc) params.category = cc;
    if (qq) params.q = qq;
    api
      .channels(params)
      .then((d) => {
        setData(d);
        setLoading(false);
      })
      .catch(() => setLoading(false));
  }

  const go = (p) => {
    setPage(p);
    fetchPage(p);
    window.scrollTo({ top: 0 });
  };

  const total = data?.count || 0;
  const pages = Math.max(1, Math.ceil(total / PAGE));
  const list = data?.channels || [];

  return (
    <div class="pb-16">
      <div class="flex flex-wrap items-center gap-3 px-4 md:px-8 py-4">
        <h1 class="text-lg text-accent font-display mr-2">TV ao vivo</h1>
        <input
          value={q}
          onInput={(e) => setQ(e.currentTarget.value)}
          placeholder="Buscar canal…"
          class="flex-1 min-w-[160px] bg-[#081019] border border-border rounded px-3 py-1.5 text-sm"
        />
      </div>

      <ChipBar
        items={(categories.data?.categories || []).map((c) => ({
          value: c.category,
          label: `${c.label} (${c.count})`,
        }))}
        active={cat}
        onSelect={setCat}
      />

      {loading && !data && <div class="text-muted text-sm px-8 py-10">Carregando…</div>}

      {data && (
        <>
          <div class="text-[11px] text-muted px-4 md:px-8 mb-2">{total} canal(is)</div>
          {list.length === 0 ? (
            <div class="text-muted text-sm px-8 py-10">Nenhum canal.</div>
          ) : (
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 md:gap-4 px-4 md:px-8">
              {list.map((c) => (
                <Card
                  fill
                  kind="channel"
                  title={c.name}
                  image={c.logo_url}
                  subtitle={c.now_playing?.title}
                  onClick={() => navigate(`/assistir/canal/${encodeURIComponent(c.tvg_id)}`)}
                />
              ))}
            </div>
          )}

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
        </>
      )}
    </div>
  );
}
