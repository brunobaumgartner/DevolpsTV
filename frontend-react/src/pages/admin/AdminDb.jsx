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

const IS_WRITE = /^\s*(update|delete)\b/i;
const HAS_WHERE = /\bwhere\b/i;

export function AdminDb() {
  const [tables, setTables] = useState([]);
  const [sql, setSql] = useState("");
  const [data, setData] = useState(null);
  const [loading, setLoading] = useState(false);
  const [confirmFullTable, setConfirmFullTable] = useState(false);
  const [writeResult, setWriteResult] = useState(null);

  const isWrite = IS_WRITE.test(sql);
  // sem WHERE, o alvo é a tabela inteira — pede confirmação explícita (a
  // mesma regra vale no servidor, aqui é só pra avisar antes de mandar)
  const needsConfirm = isWrite && !HAS_WHERE.test(sql);

  useEffect(() => {
    adminApi.dbTables().then((d) => setTables(d.tables || [])).catch(() => {});
  }, []);

  // trocar a instrução zera a confirmação: marcar num DELETE e a caixa
  // continuar marcada no próximo é exatamente como um acidente acontece
  useEffect(() => {
    setConfirmFullTable(false);
  }, [sql]);

  async function runSql(q) {
    const query = q ?? sql;
    if (!query.trim()) return;
    setLoading(true);
    setData(null);
    setWriteResult(null);
    try {
      setData(await adminApi.dbQuery(query));
    } catch (e) {
      setData({ error: e.message });
    } finally {
      setLoading(false);
    }
  }

  async function runWrite() {
    if (!sql.trim()) return;
    setLoading(true);
    setData(null);
    setWriteResult({ status: "running" });
    try {
      const { job_id } = await adminApi.dbExecute(sql, confirmFullTable);
      // write em tabela grande leva minutos (o servidor roda em background
      // justamente por isso) — aqui só acompanhamos até terminar
      for (;;) {
        const job = await adminApi.dbExecuteStatus(job_id);
        setWriteResult(job);
        if (job.status !== "running") break;
        await new Promise((r) => setTimeout(r, 1000));
      }
      adminApi.dbTables().then((d) => setTables(d.tables || [])).catch(() => {});
    } catch (e) {
      setWriteResult({ status: "error", error: e.message });
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
              if (!((e.ctrlKey || e.metaKey) && e.key === "Enter")) return;
              // atalho não dispara escrita que ainda precisa de confirmação
              if (isWrite) {
                if (!needsConfirm || confirmFullTable) runWrite();
                return;
              }
              runSql();
            }}
            rows={4}
            placeholder="SELECT * FROM vod_titles WHERE genre IS NULL LIMIT 50   —   (Ctrl+Enter roda)"
            class="w-full bg-[#081019] border border-border rounded px-3 py-2 text-xs font-mono text-text"
          />
          <div class="flex items-center flex-wrap gap-3 mt-2 mb-4">
            {isWrite ? (
              <button
                class="btn bg-danger/20 border-danger text-danger hover:bg-danger/30"
                disabled={loading || (needsConfirm && !confirmFullTable)}
                onClick={runWrite}
              >
                {loading ? "Executando…" : "Executar escrita"}
              </button>
            ) : (
              <button class="btn" disabled={loading} onClick={() => runSql()}>
                {loading ? "Rodando…" : "Rodar (Ctrl+Enter)"}
              </button>
            )}

            {needsConfirm && (
              <label class="flex items-center gap-2 text-[11px] text-danger cursor-pointer select-none">
                <input
                  type="checkbox"
                  checked={confirmFullTable}
                  onChange={(e) => setConfirmFullTable(e.currentTarget.checked)}
                />
                sem WHERE — confirmo que quero afetar a TABELA INTEIRA
              </label>
            )}

            <span class="text-[11px] text-muted">
              {isWrite
                ? "UPDATE/DELETE rodam em background (pode levar minutos) · DROP/TRUNCATE/ALTER bloqueados"
                : "SELECT / SHOW / DESCRIBE / EXPLAIN · máx. 500 linhas · timeout 8s"}
            </span>
          </div>

          {writeResult && (
            <div
              class={
                "text-xs rounded border px-3 py-2 mb-4 " +
                (writeResult.status === "error"
                  ? "border-danger text-danger"
                  : writeResult.status === "done"
                    ? "border-accent text-accent"
                    : "border-border text-muted")
              }
            >
              {writeResult.status === "running" && "Executando… (pode levar minutos em tabela grande)"}
              {writeResult.status === "done" && `Concluído — ${writeResult.rowcount} linha(s) afetada(s).`}
              {writeResult.status === "error" && `Erro: ${writeResult.error}`}
            </div>
          )}

          <ResultTable data={data} />
        </div>
      </div>
    </div>
  );
}
