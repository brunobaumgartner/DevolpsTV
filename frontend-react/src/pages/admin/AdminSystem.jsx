import { useState, useEffect } from "preact/hooks";
import { adminApi } from "../../lib/api.js";

function Panel({ title, right, children }) {
  return (
    <section class="rounded-md border border-border bg-card p-4 mb-4">
      <div class="flex items-center gap-2 mb-3">
        <h2 class="text-[12px] uppercase tracking-wide text-muted">{title}</h2>
        <div class="ml-auto">{right}</div>
      </div>
      {children}
    </section>
  );
}

function fmtBytes(n) {
  if (n == null) return "—";
  const u = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  while (n >= 1024 && i < u.length - 1) {
    n /= 1024;
    i++;
  }
  return `${n.toFixed(i ? 1 : 0)} ${u[i]}`;
}

function fmtDur(s) {
  if (s == null) return "—";
  s = s | 0;
  const d = (s / 86400) | 0,
    h = ((s % 86400) / 3600) | 0,
    m = ((s % 3600) / 60) | 0;
  if (d) return `${d}d ${h}h`;
  if (h) return `${h}h ${m}min`;
  if (m) return `${m}min`;
  return `${s}s`;
}

function fmtAge(s) {
  if (s == null) return "nunca";
  if (s < 60) return `há ${s | 0}s`;
  if (s < 3600) return `há ${(s / 60) | 0}min`;
  if (s < 86400) return `há ${(s / 3600) | 0}h`;
  return `há ${(s / 86400) | 0}d`;
}

function Meter({ label, pct, detail }) {
  const p = Math.max(0, Math.min(100, pct || 0));
  const color = p > 90 ? "bg-danger" : p > 70 ? "bg-warn" : "bg-gradient-to-r from-accent2 to-accent";
  return (
    <div>
      <div class="flex text-xs mb-1">
        <span class="text-muted">{label}</span>
        <span class="ml-auto text-text">{detail}</span>
      </div>
      <div class="h-2.5 bg-white/10 rounded overflow-hidden">
        <div class={"h-full " + color} style={`width:${p}%`} />
      </div>
    </div>
  );
}

export function AdminSystem() {
  const [res, setRes] = useState(null);
  const [jobs, setJobs] = useState(null);
  const [busy, setBusy] = useState(null);

  const load = () => {
    adminApi.systemResources().then(setRes).catch(() => {});
    adminApi.systemJobs().then(setJobs).catch(() => {});
  };
  useEffect(() => {
    load();
    const t = setInterval(load, 5000);
    return () => clearInterval(t);
  }, []);

  async function cancel(id) {
    if (!confirm("Pedir cancelamento desse processo?")) return;
    setBusy(id);
    try {
      await adminApi.cancelJob(id);
      load();
    } catch (e) {
      alert(e.message);
    } finally {
      setBusy(null);
    }
  }

  const r = res || {};
  const ip = jobs?.in_process || [];
  const wr = jobs?.worker_runs || [];

  return (
    <div class="p-4 md:p-8 max-w-5xl">
      <h1 class="text-lg text-accent font-display mb-4">Sistema</h1>

      <Panel title="Consumo do servidor" right={<span class="text-[11px] text-muted">atualiza a cada 5s</span>}>
        {!res ? (
          <div class="text-muted text-sm">Carregando…</div>
        ) : (
          <div class="grid md:grid-cols-3 gap-4">
            <Meter
              label={`CPU · ${r.cpu_count} núcleo(s)`}
              pct={r.cpu_percent}
              detail={r.cpu_percent == null ? "—" : `${r.cpu_percent}%`}
            />
            <Meter
              label="Memória"
              pct={r.mem_percent}
              detail={`${fmtBytes(r.mem_used)} / ${fmtBytes(r.mem_total)}`}
            />
            <Meter
              label="Disco (/srv/iptv/data)"
              pct={r.disk_percent}
              detail={`${fmtBytes(r.disk_used)} / ${fmtBytes(r.disk_total)}`}
            />
            <div class="text-xs text-muted">
              Load: <span class="text-text">{(r.load_avg || []).map((x) => x.toFixed(2)).join("  ") || "—"}</span>
            </div>
            <div class="text-xs text-muted">
              Swap: <span class="text-text">{fmtBytes(r.swap_used)} / {fmtBytes(r.swap_total)}</span>
            </div>
            <div class="text-xs text-muted">
              Uptime: <span class="text-text">{fmtDur(r.uptime_seconds)}</span>
            </div>
          </div>
        )}
      </Panel>

      <Panel title="Processos rodando agora (na API)">
        {ip.length === 0 ? (
          <div class="text-muted text-sm">Nenhum processo em andamento.</div>
        ) : (
          <div class="space-y-2">
            {ip.map((j) => {
              const pct = j.total ? Math.round((100 * (j.processed || 0)) / j.total) : null;
              const running = j.status === "running";
              return (
                <div class="rounded border border-border p-3 text-sm">
                  <div class="flex items-center gap-2 flex-wrap">
                    <span class="text-text font-medium">{j.kind}</span>
                    <span
                      class={
                        "text-[11px] px-1.5 py-0.5 rounded " +
                        (running
                          ? "bg-accent2/20 text-accent"
                          : j.status === "done"
                          ? "bg-ok/20 text-ok"
                          : j.status === "cancelled"
                          ? "bg-warn/20 text-warn"
                          : "bg-danger/20 text-danger")
                      }
                    >
                      {j.cancel_requested && running ? "cancelando…" : j.status || "?"}
                    </span>
                    <span class="text-[11px] text-muted">{fmtAge((Date.now() / 1000 - j.started_at) | 0)} · início</span>
                    {running && (
                      <button
                        class="ml-auto text-xs text-muted hover:text-danger border border-border rounded px-2 py-0.5 disabled:opacity-40"
                        disabled={busy === j.job_id || j.cancel_requested}
                        onClick={() => cancel(j.job_id)}
                      >
                        finalizar
                      </button>
                    )}
                  </div>
                  <div class="text-[11px] text-muted mt-1">
                    {j.phase}
                    {j.total ? ` · ${j.processed || 0}/${j.total} (${pct}%)` : ""}
                    {j.matched != null ? ` · ${j.matched} ok` : ""}
                    {j.classified != null ? ` · ${j.classified} classificados` : ""}
                    {j.healthy != null ? ` · ${j.healthy} saudáveis` : ""}
                    {j.error ? ` · erro: ${j.error}` : ""}
                  </div>
                  {pct != null && running && (
                    <div class="mt-2 h-1.5 bg-white/10 rounded overflow-hidden">
                      <div class="h-full bg-gradient-to-r from-accent2 to-accent" style={`width:${pct}%`} />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </Panel>

      <Panel title="Última execução dos jobs do worker">
        <table class="w-full text-xs">
          <tbody>
            {wr.length === 0 && (
              <tr>
                <td class="text-muted py-2">Sem registros.</td>
              </tr>
            )}
            {wr.map((w) => (
              <tr class="border-t border-border/60">
                <td class="py-1.5 pr-3 text-text">{w.job_name}</td>
                <td class="py-1.5 pr-3">
                  <span class={w.status === "ok" ? "text-ok" : "text-danger"}>{w.status}</span>
                </td>
                <td class="py-1.5 pr-3 text-muted">{fmtAge(w.age_seconds)}</td>
                <td class="py-1.5 pr-3 text-muted">{fmtDur(w.duration_seconds)}</td>
                <td class="py-1.5 text-muted">{w.summary}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </Panel>
    </div>
  );
}
