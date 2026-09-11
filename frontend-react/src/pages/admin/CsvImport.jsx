import { useState, useRef } from "preact/hooks";

export const inp = "w-full bg-[#081019] border border-border rounded px-3 py-1.5 text-sm";

export function Panel({ title, children }) {
  return (
    <section class="rounded-md border border-border bg-card p-4 mb-4">
      <h2 class="text-[12px] uppercase tracking-wide text-muted mb-3">{title}</h2>
      {children}
    </section>
  );
}

// upload de CSV com progresso — genérico (VOD e canais usam o mesmo fluxo de
// job em background, só muda o endpoint e a mensagem final).
export function CsvImport({ title, accept, upload, status, formatDone, onDone }) {
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
      const { job_id } = await upload(file);
      while (true) {
        const j = await status(job_id);
        setPct(j.total ? Math.round((j.processed / j.total) * 100) : 0);
        if (j.status === "done") {
          setPct(null);
          setMsg(formatDone(j.stats || {}));
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
    <Panel title={title}>
      <form onSubmit={submit} class="flex items-center gap-2 flex-wrap">
        <input ref={fileRef} type="file" accept={accept} class="text-xs" />
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
