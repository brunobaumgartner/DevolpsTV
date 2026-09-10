import { useState, useEffect } from "preact/hooks";
import { api } from "../lib/api.js";
import { useFetch } from "../lib/useFetch.js";
import { navigate, useLocation } from "../lib/router.jsx";
import { Card } from "../components/Card.jsx";
import { ChipBar } from "../components/ChipBar.jsx";

const PAGE = 24;

// /filmes (type=movie) · /series (type=series) · /animes (genre=Anime)
// · /genero/:nome (genre=nome)
export function VodList({ mode, params }) {
  const { query } = useLocation();
  const fixedGenre = mode === "anime" ? "Anime" : mode === "genre" ? decodeURIComponent(params.nome) : null;
  const type = mode === "movie" || mode === "series" ? mode : null;

  const [q, setQ] = useState(query.q || "");
  const [genre, setGenre] = useState("");
  const [page, setPage] = useState(0);
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(true);

  const genres = useFetch("vod-genres", () => api.vodGenres());
  const showGenreSelect = !fixedGenre;

  // debounce da busca -> reflete em ?q= e reseta a página
  useEffect(() => {
    const id = setTimeout(() => {
      setPage(0);
      const base = "#" + location.hash.replace(/^#/, "").split("?")[0];
      history.replaceState(null, "", base + (q ? `?q=${encodeURIComponent(q)}` : ""));
      fetchPage(0, q, genre);
    }, 250);
    return () => clearTimeout(id);
  }, [q, genre, mode, params?.nome]);

  function fetchPage(p, qq = q, gg = genre) {
    setLoading(true);
    const p2 = {};
    if (type) p2.type = type;
    if (fixedGenre) p2.genre = fixedGenre;
    else if (gg) p2.genre = gg;
    if (qq) p2.q = qq;
    p2.limit = PAGE;
    p2.offset = p * PAGE;
    api
      .vod(p2)
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
  const titleTxt =
    mode === "movie" ? "Filmes" : mode === "series" ? "Séries" : mode === "anime" ? "Animes" : fixedGenre;

  return (
    <div class="pb-16">
      <div class="flex flex-wrap items-center gap-3 px-4 md:px-8 pt-4">
        <h1 class="text-lg text-accent font-display mr-2">{titleTxt}</h1>
        <input
          value={q}
          onInput={(e) => setQ(e.currentTarget.value)}
          placeholder="Buscar título…"
          class="flex-1 min-w-[160px] bg-[#081019] border border-border rounded px-3 py-1.5 text-sm"
        />
      </div>

      {showGenreSelect && (
        <ChipBar
          items={(genres.data?.genres || []).map((g) => ({ value: g.genre, label: `${g.genre} (${g.count})` }))}
          active={genre || null}
          onSelect={(v) => setGenre(v || "")}
        />
      )}

      {loading && !data && <div class="text-muted text-sm px-8 py-10">Carregando…</div>}

      {data && (
        <>
          <div class="text-[11px] text-muted px-4 md:px-8 mb-2">{total} título(s)</div>
          {data.titles.length === 0 ? (
            <div class="text-muted text-sm px-8 py-10">Nada encontrado.</div>
          ) : (
            <div class="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-6 gap-3 md:gap-4 px-4 md:px-8">
              {data.titles.map((t) => (
                <Card
                  fill
                  kind={t.type}
                  title={t.title}
                  image={t.poster_url}
                  badge={t.type === "series" ? "série" : "filme"}
                  onClick={() => navigate(`/assistir/${t.type === "series" ? "serie" : "filme"}/${t.id}`)}
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
