import { useFetch } from "../lib/useFetch.js";
import { api } from "../lib/api.js";
import { navigate } from "../lib/router.jsx";
import { Row } from "../components/Row.jsx";
import { Card } from "../components/Card.jsx";
import { usePlayer } from "../components/Player.jsx";

export function Home() {
  const { playChannel } = usePlayer();
  const channels = useFetch("channels", () => api.channels());
  const genres = useFetch("vod-genres", () => api.vodGenres());

  const chList = channels.data?.channels || [];
  const liveNow = chList.filter((c) => c.now_playing).slice(0, 20);
  const liveRow = (liveNow.length ? liveNow : chList.slice(0, 20));

  // categorias de canal com pelo menos alguns itens
  const cats = [...new Set(chList.map((c) => c.category_label || "Outros"))].slice(0, 6);

  return (
    <div class="pb-16">
      {liveRow.length > 0 && (
        <Row
          title="Agora na TV"
          load={async () => liveRow}
          onSeeAll={() => navigate("/tv")}
          renderItem={(c) => (
            <Card
              kind="channel"
              title={c.name}
              image={c.logo_url}
              subtitle={c.now_playing?.title}
              onClick={() => playChannel(c)}
            />
          )}
        />
      )}

      {cats.map((cat) => (
        <Row
          title={cat}
          load={async () => chList.filter((c) => (c.category_label || "Outros") === cat).slice(0, 20)}
          renderItem={(c) => (
            <Card
              kind="channel"
              title={c.name}
              image={c.logo_url}
              subtitle={c.now_playing?.title}
              onClick={() => playChannel(c)}
            />
          )}
        />
      ))}

      {(genres.data?.genres || []).map((g) => {
        const name = typeof g === "string" ? g : g.genre;
        return (
          <Row
            title={name}
            onSeeAll={() => navigate(`/genero/${encodeURIComponent(name)}`)}
            load={async () => (await api.vod({ genre: name, limit: 20 })).titles}
            renderItem={(t) => (
              <Card
                kind={t.type}
                title={t.title}
                image={t.poster_url}
                badge={t.type === "series" ? "série" : "filme"}
                onClick={() => navigate(`/titulo/${t.id}`)}
              />
            )}
          />
        );
      })}
    </div>
  );
}
