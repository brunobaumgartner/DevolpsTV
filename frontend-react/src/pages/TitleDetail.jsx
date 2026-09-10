import { useFetch } from "../lib/useFetch.js";
import { api } from "../lib/api.js";
import { navigate } from "../lib/router.jsx";
import { usePlayer } from "../components/Player.jsx";

export function TitleDetail({ params }) {
  const { playUrl } = usePlayer();
  const { data, loading, error } = useFetch(`vod-${params.id}`, () => api.vodDetail(params.id));

  if (loading) return <div class="p-8 text-muted text-sm">Carregando…</div>;
  if (error) return <div class="p-8 text-danger text-sm">Não foi possível carregar.</div>;

  const t = data;
  const movieItem = t.type === "movie" ? t.items[0] : null;

  return (
    <div class="max-w-3xl mx-auto p-4 md:p-8">
      <button onClick={() => history.back()} class="text-muted text-sm mb-4">← voltar</button>
      <div class="flex gap-4">
        {t.poster_url ? (
          <img src={t.poster_url} class="w-32 md:w-44 aspect-[2/3] object-cover rounded-md border border-border" />
        ) : (
          <div class="w-32 md:w-44 aspect-[2/3] grid place-items-center bg-card-hover rounded-md text-3xl">
            {t.type === "movie" ? "🎬" : "📺"}
          </div>
        )}
        <div class="flex-1 min-w-0">
          <h1 class="text-xl text-accent">{t.title}</h1>
          <div class="text-xs text-muted mt-1">
            {t.type === "movie" ? "Filme" : "Série"}
            {t.genre ? " · " + t.genre : ""}
            {t.year ? " · " + t.year : ""}
          </div>
          {t.description && <p class="text-sm text-muted mt-3 leading-relaxed">{t.description}</p>}
          {movieItem && (
            <button
              class="btn mt-4"
              disabled={!movieItem.available}
              onClick={() => movieItem.stream_url && playUrl(movieItem.stream_url, t.title)}
            >
              {movieItem.available ? "▶ Assistir" : "Sem link ainda"}
            </button>
          )}
        </div>
      </div>

      {t.type === "series" && (
        <div class="mt-6">
          <h2 class="text-[13px] uppercase tracking-wide text-muted mb-2">Episódios</h2>
          <div class="divide-y divide-border">
            {t.items.map((i) => (
              <button
                class="w-full flex items-center gap-3 py-2.5 text-left disabled:opacity-40"
                disabled={!i.available}
                onClick={() => i.stream_url && playUrl(i.stream_url, `${t.title} — T${i.season_number}E${i.episode_number}`)}
              >
                <span class="text-xs text-muted w-14 shrink-0">
                  T{i.season_number ?? "?"}E{i.episode_number ?? "?"}
                </span>
                <span class="text-sm flex-1 truncate">{i.episode_title || "—"}</span>
                <span class="text-[11px] text-accent">{i.available ? "▶" : ""}</span>
              </button>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
