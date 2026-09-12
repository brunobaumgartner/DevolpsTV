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
//
// Aceita múltiplos arquivos de uma vez: eles entram numa fila e são
// processados um de cada vez (a lib.api já espera o job de cada CSV
// terminar antes de liberar o próximo endpoint pra outra coisa, e do lado
// do servidor cada import roda numa thread própria — rodar vários ao mesmo
// tempo geraria corrida em cima da mesma tabela). Só dispara o próximo
// upload depois que o job do anterior chega em "done" ou "error".
export function CsvImport({ title, accept, upload, status, formatDone, onDone }) {
  const fileRef = useRef(null);
  const [queue, setQueue] = useState([]); // [{name, state: "aguardando"|"enviando"|"done"|"error", msg, pct}]
  const [running, setRunning] = useState(false);

  async function runFile(file, index) {
    setQueue((q) => q.map((it, i) => (i === index ? { ...it, state: "enviando", pct: 0 } : it)));
    try {
      const { job_id } = await upload(file);
      while (true) {
        const j = await status(job_id);
        const pct = j.total ? Math.round((j.processed / j.total) * 100) : 0;
        setQueue((q) => q.map((it, i) => (i === index ? { ...it, pct } : it)));
        if (j.status === "done") {
          setQueue((q) => q.map((it, i) => (i === index ? { ...it, state: "done", pct: null, msg: formatDone(j.stats || {}) } : it)));
          onDone?.();
          return;
        }
        if (j.status === "error") {
          setQueue((q) => q.map((it, i) => (i === index ? { ...it, state: "error", pct: null, msg: "Erro: " + (j.error || "?") } : it)));
          return;
        }
        await new Promise((r) => setTimeout(r, 800));
      }
    } catch (err) {
      setQueue((q) => q.map((it, i) => (i === index ? { ...it, state: "error", pct: null, msg: err.message } : it)));
    }
  }

  async function submit(e) {
    e.preventDefault();
    if (running) return;
    const files = Array.from(fileRef.current.files || []);
    if (!files.length) return;
    setQueue(files.map((f) => ({ name: f.name, state: "aguardando", msg: "", pct: null })));
    setRunning(true);
    for (let i = 0; i < files.length; i++) {
      await runFile(files[i], i);
    }
    setRunning(false);
    fileRef.current.value = "";
  }

  const stateLabel = { aguardando: "Na fila…", enviando: "Enviando…", done: "Concluído", error: "Erro" };

  return (
    <Panel title={title}>
      <form onSubmit={submit} class="flex items-center gap-2 flex-wrap">
        <input ref={fileRef} type="file" accept={accept} multiple disabled={running} class="text-xs" />
        <button class="btn" disabled={running}>{running ? "Importando…" : "Importar"}</button>
      </form>
      {queue.length > 0 && (
        <ul class="mt-3 space-y-2">
          {queue.map((it, i) => (
            <li key={i} class="text-xs">
              <div class="flex items-center justify-between gap-2">
                <span class="text-text truncate">{it.name}</span>
                <span class="text-muted shrink-0">{stateLabel[it.state]}</span>
              </div>
              {it.pct != null && (
                <div class="mt-1 h-1.5 bg-white/10 rounded overflow-hidden max-w-md">
                  <div class="h-full bg-gradient-to-r from-accent2 to-accent" style={`width:${it.pct}%`} />
                </div>
              )}
              {it.msg && <p class="text-muted mt-0.5">{it.msg}</p>}
            </li>
          ))}
        </ul>
      )}
    </Panel>
  );
}
