import { useState, useEffect } from "preact/hooks";
import { adminApi } from "../../lib/api.js";
import { CsvImport, Panel, inp } from "./CsvImport.jsx";

function num(v) {
  return v ? Number(v) : null;
}

export function AdminCadastroVod() {
  const [genres, setGenres] = useState([]);

  useEffect(() => {
    adminApi.genreKeywords().then((d) => setGenres((d.genres || []).map((g) => g.genre)));
  }, []);

  return (
    <div class="p-4 md:p-8 max-w-3xl">
      <h1 class="text-lg text-accent font-display mb-4">Cadastrar VOD</h1>
      <MovieForm genres={genres} />
      <SeriesForm genres={genres} />
      <CsvImport
        title="Importar CSV (filmes/séries)"
        accept=".csv,text/csv"
        upload={adminApi.importCsv}
        status={adminApi.importCsvStatus}
        formatDone={(st) => `Importado: ${st.titulos_novos ?? 0} novo(s), ${st.titulos_atualizados ?? 0} atualizado(s), ${st.itens_novos ?? 0} item(ns).`}
      />
      <p class="text-xs text-muted">
        Pra ver, editar ou apagar o que já foi cadastrado, use a aba{" "}
        <a href="#/admin/catalogo" class="text-accent hover:underline">
          Catálogo
        </a>
        .
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

function MovieForm({ genres }) {
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

function SeriesForm({ genres }) {
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
