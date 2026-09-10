import { useState, useRef } from "preact/hooks";

// botão que dispara um job (start -> {job_id}) e faz polling do status até
// done/error, mostrando barra de progresso. `format(job)` -> texto final.
export function JobButton({ label, start, poll, format }) {
  const [running, setRunning] = useState(false);
  const [msg, setMsg] = useState("");
  const [pct, setPct] = useState(null);
  const alive = useRef(true);

  async function go() {
    if (running) return;
    setRunning(true);
    setMsg("Iniciando…");
    setPct(0);
    alive.current = true;
    try {
      const { job_id } = await start();
      while (alive.current) {
        const job = await poll(job_id);
        const total = job.total || 1;
        setPct(Math.min(100, Math.round(((job.processed || 0) / total) * 100)));
        if (job.phase) setMsg(job.phase);
        if (job.status === "done") {
          setPct(null);
          setMsg(format ? format(job) : "Concluído.");
          break;
        }
        if (job.status === "error") {
          setPct(null);
          setMsg("Erro: " + (job.error || "desconhecido"));
          break;
        }
        await new Promise((r) => setTimeout(r, 800));
      }
    } catch (e) {
      setPct(null);
      setMsg(e.message || "Falha.");
    } finally {
      setRunning(false);
    }
  }

  return (
    <div>
      <div class="flex items-center gap-3 flex-wrap">
        <button class="btn" disabled={running} onClick={go}>
          {label}
        </button>
        {msg && <span class="text-xs text-muted">{msg}</span>}
      </div>
      {pct != null && (
        <div class="mt-2 h-2 bg-white/10 rounded overflow-hidden max-w-md">
          <div class="h-full bg-gradient-to-r from-accent2 to-accent transition-[width]" style={`width:${pct}%`} />
        </div>
      )}
    </div>
  );
}
