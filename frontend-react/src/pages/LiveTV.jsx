import { useState } from "preact/hooks";
import { useFetch } from "../lib/useFetch.js";
import { api } from "../lib/api.js";
import { navigate } from "../lib/router.jsx";
import { Card } from "../components/Card.jsx";
import { ChipBar } from "../components/ChipBar.jsx";

const norm = (s) =>
  (s || "").normalize("NFD").replace(/[̀-ͯ]/g, "").toLowerCase();

export function LiveTV() {
  const { data, loading } = useFetch("channels", () => api.channels());
  const [q, setQ] = useState("");
  const [cat, setCat] = useState(null);

  const all = data?.channels || [];
  const cats = [...new Set(all.map((c) => c.category_label || "Outros"))].sort((a, b) =>
    a.localeCompare(b, "pt", { sensitivity: "base" })
  );

  const nq = norm(q);
  const list = all
    .filter((c) => (!cat || (c.category_label || "Outros") === cat) && (!nq || norm(c.name).includes(nq)))
    .sort((a, b) => a.name.localeCompare(b.name, "pt", { sensitivity: "base" }));

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

      <ChipBar items={cats.map((c) => ({ value: c, label: c }))} active={cat} onSelect={setCat} />

      {loading && <div class="text-muted text-sm px-8 py-10">Carregando…</div>}
      {!loading && list.length === 0 && <div class="text-muted text-sm px-8 py-10">Nenhum canal.</div>}

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
    </div>
  );
}
