import { useState, useEffect, useRef } from "preact/hooks";
import { adminApi } from "../../lib/api.js";

const inp = "w-full bg-[#081019] border border-border rounded px-3 py-1.5 text-sm";

function Panel({ title, children }) {
  return (
    <section class="rounded-md border border-border bg-card p-4 mb-4">
      <h2 class="text-[12px] uppercase tracking-wide text-muted mb-3">{title}</h2>
      {children}
    </section>
  );
}

function num(v) {
  return v ? Number(v) : null;
}

export function AdminCatalog() {
  const [genres, setGenres] = useState([]);
  const [catalog, setCatalog] = useState([]);

  const loadCatalog = () => adminApi.vodList().then((d) => setCatalog(d.titles || [])).catch(() => {});
  useEffect(() => {
    adminApi.genreKeywords().then((d) => setGenres((d.genres || []).map((g) => g.genre)));
    loadCatalog();
  }, []);

  return (
    <div class="p-4 md:p-8 max-w-3xl">
      <MovieForm genres={genres} onDone={loadCatalog} />
      <SeriesForm genres={genres} onDone={loadCatalog} />
      <ChannelForm />
      <CsvImport onDone={loadCatalog} />
      <Panel title="Catálogo">
        {catalog.length === 0 && <div class="text-muted text-sm">Nada cadastrado.</div>}
        {catalog.map((t) => (
          <TitleCard t={t} onChange={loadCatalog} />
        ))}
      </Panel>
    </div>
  );
}

function GenreSelect({ genres, value, onChange }) {
  return (
    <select class={inp} value={value} onChange={(e) => onChange(e.currentTarget.value)}>
      <option value="">Gênero (opcional)</option>
      {genres.map((g) => <option value={g}>{g}</option>)}
    </select>
  );
}

function MovieForm({ genres, onDone }) {
  const [f, setF] = useState({});
  const [msg, setMsg] = useState("");
  const up = (k) => (e) => setF({ ...f, [k]: e.currentTarget.value });
  async function submit(e) {
    e.preventDefault();
    if (!f.title) return setMsg("Título obrigatório.");
    try {
      await adminApi.addMovie({ title: f.title, genre: f.genre || null, year: num(f.year), poster_url: f.poster || null, stream_url: f.url || null, description: f.desc || null });
      setMsg(`"${f.title}" adicionado.`);
      setF({});
      onDone();
    } catch (err) {
      setMsg(err.message);
    }
  }
  return (
    <Panel title="Adicionar filme">
      <form onSubmit={submit} class="grid grid-cols-2 gap-2">
        <input class={inp} placeholder="Título *" value={f.title || ""} onInput={up("title")} />
        <GenreSelect genres={genres} value={f.genre || ""} onChange={(v) => setF({ ...f, genre: v })} />
        <input class={inp} type="number" placeholder="Ano" value={f.year || ""} onInput={up("year")} />
        <input class={inp} placeholder="Poster URL" value={f.poster || ""} onInput={up("poster")} />
        <input class={inp + " col-span-2"} placeholder="Link do stream (opcional)" value={f.url || ""} onInput={up("url")} />
        <textarea class={inp + " col-span-2"} placeholder="Descrição" value={f.desc || ""} onInput={up("desc")} />
        <button class="btn col-span-2 justify-center">Adicionar filme</button>
      </form>
      {msg && <p class="text-xs text-ok mt-2">{msg}</p>}
    </Panel>
  );
}

function SeriesForm({ genres, onDone }) {
  const [f, setF] = useState({});
  const [msg, setMsg] = useState("");
  const up = (k) => (e) => setF({ ...f, [k]: e.currentTarget.value });
  async function submit(e) {
    e.preventDefault();
    if (!f.title) return setMsg("Título obrigatório.");
    try {
      await adminApi.addSeries({
        title: f.title, genre: f.genre || null, year: num(f.year), poster_url: f.poster || null, description: f.desc || null,
        season_number: num(f.s), episode_number: num(f.ep), episode_title: f.eptitle || null, stream_url: f.url || null,
      });
      setMsg(`"${f.title}" adicionada.`);
      setF({});
      onDone();
    } catch (err) {
      setMsg(err.message);
    }
  }
  return (
    <Panel title="Adicionar série">
      <form onSubmit={submit} class="grid grid-cols-2 gap-2">
        <input class={inp} placeholder="Título *" value={f.title || ""} onInput={up("title")} />
        <GenreSelect genres={genres} value={f.genre || ""} onChange={(v) => setF({ ...f, genre: v })} />
        <input class={inp} type="number" placeholder="Ano" value={f.year || ""} onInput={up("year")} />
        <input class={inp} placeholder="Poster URL" value={f.poster || ""} onInput={up("poster")} />
        <textarea class={inp + " col-span-2"} placeholder="Descrição" value={f.desc || ""} onInput={up("desc")} />
        <p class="text-[11px] text-muted col-span-2">1º episódio (opcional):</p>
        <input class={inp} type="number" placeholder="Temp." value={f.s || ""} onInput={up("s")} />
        <input class={inp} type="number" placeholder="Ep." value={f.ep || ""} onInput={up("ep")} />
        <input class={inp} placeholder="Nome do episódio" value={f.eptitle || ""} onInput={up("eptitle")} />
        <input class={inp} placeholder="Link do episódio" value={f.url || ""} onInput={up("url")} />
        <button class="btn col-span-2 justify-center">Adicionar série</button>
      </form>
      {msg && <p class="text-xs text-ok mt-2">{msg}</p>}
    </Panel>
  );
}

function ChannelForm() {
  const [f, setF] = useState({});
  const [msg, setMsg] = useState("");
  const up = (k) => (e) => setF({ ...f, [k]: e.currentTarget.value });
  async function submit(e) {
    e.preventDefault();
    if (!f.tvg_id || !f.name || !f.url) return setMsg("ID, nome e link são obrigatórios.");
    try {
      const r = await adminApi.addChannel({
        tvg_id: f.tvg_id, name: f.name, category: f.category || null, logo_url: f.logo || null,
        is_broadcast_tv: !!f.broadcast, stream_url: f.url,
      });
      setMsg(r.new_channel ? `Canal "${f.name}" criado.` : r.stream_added ? "Link adicionado como mirror." : "Link já existia.");
      setF({});
    } catch (err) {
      setMsg(err.message);
    }
  }
  return (
    <Panel title="Adicionar canal de TV ao vivo">
      <form onSubmit={submit} class="grid grid-cols-2 gap-2">
        <input class={inp} placeholder="tvg-id *" value={f.tvg_id || ""} onInput={up("tvg_id")} />
        <input class={inp} placeholder="Nome *" value={f.name || ""} onInput={up("name")} />
        <input class={inp} placeholder="Categoria" value={f.category || ""} onInput={up("category")} />
        <input class={inp} placeholder="Logo URL" value={f.logo || ""} onInput={up("logo")} />
        <input class={inp + " col-span-2"} placeholder="Link .m3u8 *" value={f.url || ""} onInput={up("url")} />
        <label class="text-xs text-muted flex items-center gap-2 col-span-2">
          <input type="checkbox" checked={!!f.broadcast} onChange={(e) => setF({ ...f, broadcast: e.currentTarget.checked })} /> É TV aberta
        </label>
        <button class="btn col-span-2 justify-center">Adicionar canal</button>
      </form>
      {msg && <p class="text-xs text-ok mt-2">{msg}</p>}
    </Panel>
  );
}

function CsvImport({ onDone }) {
  const fileRef = useRef(null);
  const [msg, setMsg] = useState("");
  const [pct, setPct] = useState(null);

  async function submit(e) {
    e.preventDefault();
    const file = fileRef.current.files[0];
    if (!file) return setMsg("Escolha um CSV.");
    setMsg("Enviando…");
    setPct(0);
    try {
      const { job_id } = await adminApi.importCsv(file);
      while (true) {
        const j = await adminApi.importCsvStatus(job_id);
        setPct(j.total ? Math.round((j.processed / j.total) * 100) : 0);
        if (j.status === "done") {
          setPct(null);
          const st = j.stats || {};
          setMsg(`Importado: ${st.titulos_novos ?? 0} novo(s), ${st.titulos_atualizados ?? 0} atualizado(s), ${st.itens_novos ?? 0} item(ns).`);
          onDone();
          break;
        }
        if (j.status === "error") {
          setPct(null);
          setMsg("Erro: " + (j.error || "?"));
          break;
        }
        await new Promise((r) => setTimeout(r, 800));
      }
    } catch (err) {
      setPct(null);
      setMsg(err.message);
    }
  }

  return (
    <Panel title="Importar CSV">
      <form onSubmit={submit} class="flex items-center gap-2 flex-wrap">
        <input ref={fileRef} type="file" accept=".csv,text/csv" class="text-xs" />
        <button class="btn">Importar</button>
      </form>
      {pct != null && (
        <div class="mt-2 h-2 bg-white/10 rounded overflow-hidden max-w-md">
          <div class="h-full bg-gradient-to-r from-accent2 to-accent" style={`width:${pct}%`} />
        </div>
      )}
      {msg && <p class="text-xs text-muted mt-2">{msg}</p>}
    </Panel>
  );
}

function TitleCard({ t, onChange }) {
  return (
    <div class="border border-border rounded p-3 mb-2">
      <div class="flex items-center gap-2">
        <strong class="text-sm flex-1">{t.title}</strong>
        <span class="text-[11px] text-muted">
          {t.type === "movie" ? "filme" : "série"}{t.genre ? " · " + t.genre : ""}{t.year ? " · " + t.year : ""}
        </span>
        <button
          class="text-[11px] text-danger border border-danger rounded px-2 py-0.5"
          onClick={async () => {
            if (!confirm(`Excluir "${t.title}"?`)) return;
            await adminApi.delTitle(t.id);
            onChange();
          }}
        >
          excluir
        </button>
      </div>
      {t.items.map((it) => (
        <ItemRow t={t} it={it} onChange={onChange} />
      ))}
      {t.type === "series" && <AddEpisode titleId={t.id} onChange={onChange} />}
    </div>
  );
}

function ItemRow({ t, it, onChange }) {
  const [url, setUrl] = useState(it.stream_url || "");
  const [saved, setSaved] = useState(false);
  const label = t.type === "series" ? `T${it.season_number ?? "?"}E${it.episode_number ?? "?"} ${it.episode_title || ""}` : "Link do filme";
  return (
    <div class="flex items-center gap-2 py-1.5 border-t border-border text-xs">
      <span class="w-32 shrink-0 text-muted truncate">{label}</span>
      <input class="flex-1 bg-[#081019] border border-border rounded px-2 py-1" placeholder="sem link" value={url} onInput={(e) => setUrl(e.currentTarget.value)} />
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
        <button class="text-danger" onClick={async () => { await adminApi.delItem(it.id); onChange(); }}>×</button>
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
          season_number: num(els.s.value), episode_number: num(els.ep.value),
          episode_title: els.t.value.trim() || null, stream_url: els.u.value.trim() || null,
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
