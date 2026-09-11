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

  useEffect(() => {
    adminApi.genreKeywords().then((d) => setGenres((d.genres || []).map((g) => g.genre)));
  }, []);

  return (
    <div class="p-4 md:p-8 max-w-3xl">
      <MovieForm genres={genres} />
      <SeriesForm genres={genres} />
      <ChannelForm />
      <CsvImport />
      <p class="text-xs text-muted">
        Pra ver, editar ou apagar o que já foi cadastrado, use as abas{" "}
        <a href="#/admin/catalogo" class="text-accent hover:underline">
          Catálogo
        </a>{" "}
        (filmes/séries) e{" "}
        <a href="#/admin/canais" class="text-accent hover:underline">
          Canais
        </a>{" "}
        (TV ao vivo).
      </p>
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
      onDone?.();
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
      onDone?.();
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
          onDone?.();
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

