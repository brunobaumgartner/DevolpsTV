import { useState, useEffect } from "preact/hooks";
import { adminApi } from "../../lib/api.js";

export function AdminGenres() {
  const [genres, setGenres] = useState(null);
  const [ngGenre, setNgGenre] = useState("");
  const [ngKw, setNgKw] = useState("");
  const [msg, setMsg] = useState("");

  const load = () => adminApi.genreKeywords().then((d) => setGenres(d.genres || [])).catch(() => setGenres([]));
  useEffect(load, []);

  async function addNew(e) {
    e.preventDefault();
    if (!ngGenre.trim() || !ngKw.trim()) return setMsg("Preencha os dois campos.");
    await adminApi.addGenreKeyword(ngGenre.trim(), ngKw.trim());
    setNgGenre("");
    setNgKw("");
    setMsg(`Gênero "${ngGenre}" criado.`);
    load();
  }

  if (!genres) return <div class="p-8 text-muted text-sm">Carregando…</div>;

  return (
    <div class="p-4 md:p-8 max-w-3xl">
      <section class="rounded-md border border-border bg-card p-4 mb-4">
        <h2 class="text-[12px] uppercase tracking-wide text-muted mb-3">Novo gênero</h2>
        <form onSubmit={addNew} class="flex gap-2 flex-wrap">
          <input value={ngGenre} onInput={(e) => setNgGenre(e.currentTarget.value)} placeholder="Nome do gênero" class="flex-1 min-w-[140px] bg-[#081019] border border-border rounded px-3 py-1.5 text-sm" />
          <input value={ngKw} onInput={(e) => setNgKw(e.currentTarget.value)} placeholder="1ª palavra-chave" class="flex-1 min-w-[140px] bg-[#081019] border border-border rounded px-3 py-1.5 text-sm" />
          <button class="btn">Criar</button>
        </form>
        {msg && <p class="text-xs text-ok mt-2">{msg}</p>}
      </section>

      {genres.map((g) => (
        <section class="rounded-md border border-border bg-card p-4 mb-3">
          <div class="flex items-center gap-2 mb-2">
            <h3 class="text-accent text-sm flex-1">{g.genre}</h3>
            <span class="text-[11px] text-muted">{g.keywords.length}</span>
            <button
              class="text-[11px] text-danger border border-danger rounded px-2 py-0.5"
              onClick={async () => {
                if (!confirm(`Excluir o gênero "${g.genre}"?`)) return;
                await adminApi.delGenre(g.genre);
                load();
              }}
            >
              excluir
            </button>
          </div>
          <div class="flex flex-wrap gap-1.5 mb-2">
            {g.keywords.map((k) => (
              <span class="chip">
                {k.keyword}
                <button class="text-muted hover:text-danger ml-1" onClick={async () => { await adminApi.delGenreKeyword(k.id); load(); }}>×</button>
              </span>
            ))}
          </div>
          <form
            class="flex gap-2"
            onSubmit={async (e) => {
              e.preventDefault();
              const inp = e.currentTarget.querySelector("input");
              if (!inp.value.trim()) return;
              await adminApi.addGenreKeyword(g.genre, inp.value.trim());
              inp.value = "";
              load();
            }}
          >
            <input placeholder="nova palavra-chave" class="flex-1 bg-[#081019] border border-border rounded px-3 py-1.5 text-sm" />
            <button class="btn-ghost rounded px-3 py-1.5 border border-border text-xs">+ add</button>
          </form>
        </section>
      ))}
    </div>
  );
}
