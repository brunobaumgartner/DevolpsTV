import { useState, useEffect } from "preact/hooks";
import { useFetch } from "../lib/useFetch.js";
import { api } from "../lib/api.js";
import { navigate } from "../lib/router.jsx";
import { Row } from "../components/Row.jsx";
import { Card } from "../components/Card.jsx";

const goChannel = (c) => navigate(`/assistir/canal/${encodeURIComponent(c.tvg_id)}`);
const goVod = (t) => navigate(`/assistir/${t.type === "series" ? "serie" : "filme"}/${t.id}`);

export function Home() {
  const channelsHome = useFetch("channels-home", () => api.channelsHome(20)); // 1 request pras fileiras de canais
  const home = useFetch("vod-home", () => api.vodHome(15)); // 1 request pras fileiras de VOD

  // "Continuar assistindo" — sempre revalida ao voltar pra Home (some quando acaba)
  const [contItems, setContItems] = useState([]);
  useEffect(() => {
    api
      .continueWatching()
      .then((r) => setContItems(r.items || []))
      .catch(() => {});
  }, []);

  const liveNow = channelsHome.data?.live_now || [];
  const channelRows = channelsHome.data?.rows || [];
  const liveRow = liveNow.length ? liveNow : (channelRows[0]?.channels || []);

  const channelCard = (c) => (
    <Card kind="channel" title={c.name} image={c.logo_url} subtitle={c.now_playing?.title} onClick={() => goChannel(c)} />
  );
  const vodCard = (t) => (
    <Card
      kind={t.type}
      title={t.title}
      image={t.poster_url}
      badge={t.type === "series" ? "série" : "filme"}
      onClick={() => goVod(t)}
    />
  );

  return (
    <div class="pb-16">
      {contItems.length > 0 && (
        <Row
          title="Continuar assistindo"
          load={async () => contItems}
          renderItem={(w) => (
            <Card
              kind={w.type}
              title={w.episode_label ? `${w.title} · ${w.episode_label}` : w.title}
              image={w.poster_url}
              progress={w.pct}
              badge={w.type === "series" ? "série" : "filme"}
              onClick={() => navigate(`/assistir/${w.type === "series" ? "serie" : "filme"}/${w.title_id}`)}
            />
          )}
        />
      )}

      {liveRow.length > 0 && (
        <Row title="Agora na TV" onSeeAll={() => navigate("/tv")} load={async () => liveRow} renderItem={channelCard} />
      )}

      {channelRows.map((r) => (
        <Row title={r.label} onSeeAll={() => navigate("/tv")} load={async () => r.channels} renderItem={channelCard} />
      ))}

      {(home.data?.rows || []).map((r) => (
        <Row
          title={r.genre}
          onSeeAll={() => navigate(`/genero/${encodeURIComponent(r.genre)}`)}
          load={async () => r.titles}
          renderItem={vodCard}
        />
      ))}
    </div>
  );
}
