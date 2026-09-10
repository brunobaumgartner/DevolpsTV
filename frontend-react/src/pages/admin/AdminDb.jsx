import { useState, useEffect, useRef } from "preact/hooks";
import { adminApi } from "../../lib/api.js";

const DEFAULT_W = 180;
const MIN_W = 48;

function ResultTable({ data }) {
  const [widths, setWidths] = useState([]);
  const [wrap, setWrap] = useState(false);
  const drag = useRef(null);

  const columns = data?.columns || [];

  // (re)inicializa larguras quando muda o conjunto de colunas
  useEffect(() => {
    setWidths(columns.map(() => DEFAULT_W));
  }, [columns.join("")]);

  useEffect(() => {
    function onMove(e) {
      if (!drag.current) return;
      const { idx, startX, startW } = drag.current;
      const w = Math.max(MIN_W, startW + (e.clientX - startX));
      setWidths((ws) => ws.map((x, i) => (i === idx ? w : x)));
    }
    function onUp() {
      drag.current = null;
      document.body.style.cursor = "";
      document.body.style.userSelect = "";
    }
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, []);

  if (!data) return null;
  if (data.error) return <div class="text-danger text-sm">{data.error}</div>;
  const { rows = [], truncated } = data;

  function startDrag(idx, e) {
    e.preventDefault();
    drag.current = { idx, startX: e.clientX, startW: widths[idx] || DEFAULT_W };
    document.body.style.cursor = "col-resize";
    document.body.style.userSelect = "none";
  }

  return (
    <div>
      <div class="flex items-center gap-3 text-[11px] text-muted mb-1">
        <span>
          {rows.length} linha(s){truncated ? " (limitado a 500)" : ""}
        </span>
        <label class="flex items-center gap-1 cursor-pointer select-none">
          <input type="checkbox" checked={wrap} onChange={(e) => setWrap(e.currentTarget.checked)} />
          quebrar texto
        </label>
        <button class="hover:text-accent" onClick={() => setWidths(columns.map(() => DEFAULT_W))}>
          resetar larguras
        </button>
      </div>
      <div class="overflow-auto border border-border rounded max-h-[60vh]">
        <table class="text-xs" style="table-layout:fixed;border-collapse:collapse">
          <colgroup>
            {columns.map((_, i) => (
              <col style={`width:${widths[i] || DEFAULT_W}px`} />
            ))}
          </colgroup>
          <thead class="sticky top-0 bg-card z-10">
            <tr>
              {columns.map((c, i) => (
                <th class="relative text-left font-medium text-accent px-2 py-1.5 border-b border-r border-border select-none">
                  <span class="block truncate">{c}</span>
                  <span
                    onMouseDown={(e) => startDrag(i, e)}
                    class="absolute top-0 right-0 h-full w-1.5 cursor-col-resize hover:bg-accent/60"
                    title="arraste pra redimensionar"
                  />
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {rows.map((r) => (
              <tr class="border-b border-border/40 hover:bg-white/5 align-top">
                {r.map((v) => (
                  <td
                    class={
                      "px-2 py-1 text-text border-r border-border/30 " +
                      (wrap ? "whitespace-pre-wrap break-words" : "whitespace-nowrap overflow-hidden text-ellipsis")
                    }
                    title={v === null ? "" : String(v)}
                  >
                    {v === null ? <span class="text-muted italic">null</span> : String(v)}
                  </td>
                ))}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

export function AdminDb() {
  const [tables, setTables] = useState([]);
  const [sql, setSql] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    adminApi.dbTables().then((d) => setTables(d.tables || [])).catch(() => {});
  }, []);

  async function runSql(q) {
    const query = q ?? sql;
    if (!query.trim()) return;
    setLoading(true);
    setData(null);
    try {
      setData(await adminApi.dbQuery(query));
    } catch (e) {
      setData({ error: e.message });
    } finally {
      setLoading(false);
    }
  }

  function openTable(name) {
    const q = `SELECT * FROM ${name}`;
    setSql(q);
    runSql(q);
  }

  return (
    <div class="p-4 md:p-8">
      <h1 class="text-lg text-accent font-display mb-4">Banco</h1>

      <div class="grid md:grid-cols-[220px_1fr] gap-6">
        <div>
          <div class="text-[12px] uppercase tracking-wide text-muted mb-2">Tabelas</div>
          <div class="space-y-1">
            {tables.map((t) => (
              <button
                class="w-full text-left text-xs rounded px-2 py-1.5 border border-border hover:border-accent hover:text-accent text-muted"
                onClick={() => openTable(t.name)}
              >
                <div class="text-text">{t.name}</div>
                <div class="text-[10px] text-muted">
                  ~{t.approx_rows ?? "?"} linhas · {t.size_mb ?? 0} MB
                </div>
              </button>
            ))}
          </div>
        </div>

        <div>
          <textarea
            value={sql}
            onInput={(e) => setSql(e.currentTarget.value)}
            onKeyDown={(e) => {
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter") runSql();
            }}
            rows={4}
            placeholder="SELECT * FROM vod_titles WHERE genre IS NULL LIMIT 50   —   (Ctrl+Enter roda · só leitura)"
            class="w-full bg-[#081019] border border-border rounded px-3 py-2 text-xs font-mono text-text"
          />
          <div class="flex items-center gap-3 mt-2 mb-4">
            <button class="btn" disabled={loading} onClick={() => runSql()}>
              {loading ? "Rodando…" : "Rodar (Ctrl+Enter)"}
            </button>
            <span class="text-[11px] text-muted">
              somente SELECT / SHOW / DESCRIBE / EXPLAIN · máx. 500 linhas · timeout 8s
            </span>
          </div>
          <ResultTable data={data} />
        </div>
      </div>
    </div>
  );
}
