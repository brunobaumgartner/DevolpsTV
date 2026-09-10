import { useState, useEffect } from "preact/hooks";
import { useFetch } from "../lib/useFetch.js";
import { api } from "../lib/api.js";
import { navigate } from "../lib/router.jsx";
import { VideoBox } from "../components/VideoBox.jsx";
import { Row } from "../components/Row.jsx";
import { Card } from "../components/Card.jsx";

// /assistir/:tipo/:id   tipo = canal | filme | serie
export function Watch({ params }) {
  const { tipo, id } = params;
  return tipo === "canal" ? <WatchChannel tvgId={id} /> : <WatchVod id={id} isSeries={tipo === "serie"} />;
}

function BackBar({ children }) {
  return (
    <div class="flex items-center gap-3 px-4 md:px-8 py-3">
      <button onClick={() => history.back()} class="text-sm text-muted hover:text-accent">
        ← voltar
      </button>
      <span class="text-sm text-text truncate">{children}</span>
    </div>
  );
}

// ---------- CANAL AO VIVO ----------
function WatchChannel({ tvgId }) {
  const { data } = useFetch("channels", () => api.channels());
  const channel = (data?.channels || []).find((c) => c.tvg_id === tvgId);

  const [lang, setLang] = useState(null);
  const [url, setUrl] = useState(null);
  const [status, setStatus] = useState("Verificando…");

  const langs = channel?.languages || [];

  useEffect(() => {
    if (!channel) return;
    const chosen = lang || (langs.find((g) => g.label === "Português") || langs[0])?.label || null;
    if (lang !== chosen) setLang(chosen);
    let alive = true;
    setStatus(`Verificando "${channel.name}"${chosen && langs.length > 1 ? " (" + chosen + ")" : ""}…`);
    setUrl(null);
    api
      .resolve(channel.tvg_id, langs.length > 1 ? chosen : null)
      .then((r) => {
        if (!alive) return;
        setUrl(r.url);
        setStatus(`Reproduzindo: ${channel.name}`);
      })
      .catch((e) => alive && setStatus(e.message || `"${channel.name}" indisponível agora.`));
    return () => {
      alive = false;
    };
  }, [channel?.tvg_id, lang]);

  if (!data) return <div class="p-8 text-muted text-sm">Carregando…</div>;
  if (!channel) return <div class="p-8 text-danger text-sm">Canal não encontrado ou fora do ar.</div>;

  const sameCat = (data.channels || [])
    .filter((c) => c.tvg_id !== channel.tvg_id && c.category === channel.category)
    .slice(0, 20);

  return (
    <div class="pb-16">
      <BackBar>{channel.name}</BackBar>
      <div class="bg-black">
        {url ? (
          <VideoBox url={url} class="w-full max-w-[1100px] mx-auto aspect-video bg-black" onFatal={() => setStatus("Falha ao reproduzir.")} />
        ) : (
          <div class="w-full max-w-[1100px] mx-auto aspect-video grid place-items-center text-muted text-sm">
            {status}
          </div>
        )}
      </div>

      <div class="px-4 md:px-8 py-3">
        <h1 class="text-lg text-accent">{channel.name}</h1>
        <div class="text-xs text-muted mt-1">
          {channel.category_label || "Sem categoria"}
          {channel.now_playing ? " · ▶ " + channel.now_playing.title : ""}
        </div>
        <div class="text-xs text-muted mt-1">{status}</div>

        {langs.length > 1 && (
          <div class="flex items-center gap-1.5 flex-wrap mt-3">
            <span class="text-[11px] uppercase tracking-wide text-muted mr-1">Idioma:</span>
            {langs.map((g) => (
              <button class={"chip " + (g.label === lang ? "active" : "")} onClick={() => setLang(g.label)}>
                {g.label}
              </button>
            ))}
          </div>
        )}
      </div>

      {sameCat.length > 0 && (
        <Row
          title={"Mais de " + (channel.category_label || "TV")}
          load={async () => sameCat}
          renderItem={(c) => (
            <Card
              kind="channel"
              title={c.name}
              image={c.logo_url}
              subtitle={c.now_playing?.title}
              onClick={() => navigate(`/assistir/canal/${encodeURIComponent(c.tvg_id)}`)}
            />
          )}
        />
      )}
    </div>
  );
}

// ---------- FILME / SÉRIE ----------
function WatchVod({ id }) {
  const { data, loading, error } = useFetch(`vod-${id}`, () => api.vodDetail(id));
  const [current, setCurrent] = useState(null); // {url, label}

  useEffect(() => {
    if (data?.type === "movie" && data.items[0]?.stream_url) {
      setCurrent({ url: data.items[0].stream_url, label: data.title });
    } else {
      setCurrent(null);
    }
  }, [data?.id]);

  if (loading) return <div class="p-8 text-muted text-sm">Carregando…</div>;
  if (error) return <div class="p-8 text-danger text-sm">Não foi possível carregar.</div>;

  const t = data;

  return (
    <div class="pb-16">
      <BackBar>{t.title}</BackBar>

      <div class="bg-black">
        {current ? (
          <VideoBox url={current.url} class="w-full max-w-[1100px] mx-auto aspect-video bg-black" />
        ) : (
          <div class="w-full max-w-[1100px] mx-auto aspect-video grid place-items-center">
            {t.poster_url ? (
              <img src={t.poster_url} class="h-full object-contain opacity-60" />
            ) : (
              <span class="text-5xl opacity-40">{t.type === "movie" ? "🎬" : "📺"}</span>
            )}
          </div>
        )}
      </div>

      <div class="px-4 md:px-8 py-3">
        <h1 class="text-lg text-accent">{t.title}</h1>
        <div class="text-xs text-muted mt-1">
          {t.type === "movie" ? "Filme" : "Série"}
          {t.genre ? " · " + t.genre : ""}
          {t.year ? " · " + t.year : ""}
        </div>
        {t.description && <p class="text-sm text-muted mt-3 leading-relaxed max-w-2xl">{t.description}</p>}
        {current && <div class="text-xs text-accent mt-2">▶ {current.label}</div>}
      </div>

      {t.type === "series" && (
        <Row
          title="Episódios"
          load={async () => t.items}
          renderItem={(i) => {
            const label = `T${i.season_number ?? "?"}E${i.episode_number ?? "?"}`;
            const active = current?.url === i.stream_url;
            return (
              <button
                disabled={!i.available}
                onClick={() => setCurrent({ url: i.stream_url, label: `${t.title} — ${label}` })}
                class={
                  "shrink-0 snap-start w-[190px] rounded-md border bg-card p-3 text-left transition-transform disabled:opacity-40 " +
                  (active ? "border-accent" : "border-border hover:border-accent hover:-translate-y-0.5")
                }
              >
                <div class="text-accent font-display text-sm">{label}</div>
                <div class="text-[13px] mt-1 line-clamp-2 min-h-[2.4em]">{i.episode_title || "—"}</div>
                <div class="text-[11px] text-muted mt-1">
                  {i.available ? (active ? "▶ tocando" : "▶ assistir") : "sem link"}
                </div>
              </button>
            );
          }}
        />
      )}

      {t.genre && t.genre !== "Outros" && (
        <div class="mt-6">
          <Row
            title={"Mais de " + t.genre}
            load={async () => (await api.vod({ genre: t.genre, limit: 20 })).titles.filter((x) => x.id !== t.id)}
            renderItem={(x) => (
              <Card
                kind={x.type}
                title={x.title}
                image={x.poster_url}
                badge={x.type === "series" ? "série" : "filme"}
                onClick={() => navigate(`/assistir/${x.type === "series" ? "serie" : "filme"}/${x.id}`)}
              />
            )}
          />
        </div>
      )}
    </div>
  );
}
