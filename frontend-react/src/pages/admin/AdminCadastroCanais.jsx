import { useState } from "preact/hooks";
import { adminApi } from "../../lib/api.js";
import { CsvImport, Panel, inp } from "./CsvImport.jsx";

export function AdminCadastroCanais() {
  return (
    <div class="p-4 md:p-8 max-w-3xl">
      <h1 class="text-lg text-accent font-display mb-4">Cadastrar Canais</h1>
      <ChannelForm />
      <CsvImport
        title="Importar CSV (canais ao vivo)"
        accept=".csv,text/csv"
        upload={adminApi.importChannelsCsv}
        status={adminApi.importChannelsCsvStatus}
        formatDone={(st) => `Importado: ${st.canais_novos ?? 0} canal(is) novo(s), ${st.canais_atualizados ?? 0} atualizado(s), ${st.links_novos ?? 0} link(s) novo(s).`}
      />
      <p class="text-xs text-muted">
        Pra ver, editar ou apagar o que já foi cadastrado, use a aba{" "}
        <a href="#/admin/canais" class="text-accent hover:underline">
          Canais
        </a>
        .
      </p>
    </div>
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
