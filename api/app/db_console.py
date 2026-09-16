"""Console de banco da tela "Banco" do admin.

Duas portas separadas de propósito:

- `run_query`: SOMENTE LEITURA (SELECT / SHOW / DESCRIBE / EXPLAIN /
  WITH...SELECT). Aplica LIMIT e MAX_EXECUTION_TIME pra não travar o banco.
- `start_write_job`: UPDATE e DELETE, nada além disso (DDL continua barrado —
  DROP/TRUNCATE/ALTER não têm volta e nunca são necessários aqui). Roda como
  job em background porque write em tabela grande leva minutos (medido em
  2026-09-13: `DELETE FROM vod_streams` com 1,38 milhão de linhas levou mais
  de 2 min) e a requisição HTTP morreria antes no timeout do Cloudflare.

Uma só instrução por vez nos dois casos.
"""

import re
import threading
import time
import uuid

from sqlalchemy import text

from . import job_registry
from .db import engine

_MAX_ROWS = 500
_STMT_TIMEOUT_MS = 8000

_READ_START = re.compile(r"^\s*(select|show|describe|desc|explain|with)\b", re.IGNORECASE)
_WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|rename|grant|revoke|"
    r"replace|call|lock|unlock|set|use|load|handler|into\s+outfile|into\s+dumpfile)\b",
    re.IGNORECASE,
)

_WRITE_START = re.compile(r"^\s*(update|delete)\b", re.IGNORECASE)
# DDL fica de fora mesmo no console de escrita: apagar/alterar ESTRUTURA é de
# outra natureza (não dá pra desfazer com um backup de linhas) e nada do uso
# real do admin precisa disso.
_DDL_WORDS = re.compile(
    r"\b(drop|truncate|alter|create|rename|grant|revoke|lock|unlock|use|load|"
    r"handler|into\s+outfile|into\s+dumpfile)\b",
    re.IGNORECASE,
)
_HAS_WHERE = re.compile(r"\bwhere\b", re.IGNORECASE)


class QueryError(ValueError):
    pass


def _guard(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise QueryError("consulta vazia")
    if ";" in s:
        raise QueryError("uma instrução por vez (sem ';' no meio)")
    if not _READ_START.match(s):
        raise QueryError("só SELECT / SHOW / DESCRIBE / EXPLAIN são permitidos")
    if _WRITE_WORDS.search(s):
        raise QueryError("a consulta contém uma palavra de escrita/DDL — bloqueada")
    return s


def _wrap_limit(s: str) -> str:
    # só aplica LIMIT em SELECT/WITH; SHOW/DESCRIBE/EXPLAIN não aceitam
    head = s.lstrip()[:6].lower()
    if head.startswith(("select", "with")):
        if not re.search(r"\blimit\s+\d", s, re.IGNORECASE):
            return f"{s}\nLIMIT {_MAX_ROWS}"
    return s


def run_query(sql: str) -> dict:
    s = _wrap_limit(_guard(sql))
    with engine.connect() as conn:
        try:
            conn.exec_driver_sql(f"SET SESSION MAX_EXECUTION_TIME={_STMT_TIMEOUT_MS}")
        except Exception:
            pass
        result = conn.execute(text(s))
        cols = list(result.keys())
        rows = [_row_to_list(r) for r in result.fetchmany(_MAX_ROWS + 1)]
    truncated = len(rows) > _MAX_ROWS
    return {"columns": cols, "rows": rows[:_MAX_ROWS], "truncated": truncated, "sql": s}


def _row_to_list(row) -> list:
    out = []
    for v in row:
        if isinstance(v, (bytes, bytearray)):
            out.append(v.decode("utf-8", "replace"))
        elif v is None or isinstance(v, (str, int, float, bool)):
            out.append(v)
        else:
            out.append(str(v))
    return out


def list_tables() -> list[dict]:
    q = text(
        "SELECT table_name AS name, table_rows AS approx_rows, "
        "ROUND((data_length + index_length) / 1048576, 1) AS size_mb "
        "FROM information_schema.tables WHERE table_schema = DATABASE() "
        "ORDER BY table_name"
    )
    with engine.connect() as conn:
        return [dict(r._mapping) for r in conn.execute(q)]


def _guard_write(sql: str) -> str:
    s = sql.strip().rstrip(";").strip()
    if not s:
        raise QueryError("consulta vazia")
    if ";" in s:
        raise QueryError("uma instrução por vez (sem ';' no meio)")
    if not _WRITE_START.match(s):
        raise QueryError("aqui só rodam UPDATE e DELETE (pra ler, use a aba de consulta)")
    if _DDL_WORDS.search(s):
        raise QueryError("DROP / TRUNCATE / ALTER / CREATE continuam bloqueados")
    return s


def check_write(sql: str, confirm_full_table: bool = False) -> str:
    """Valida a instrução e devolve ela limpa. Sem WHERE, exige confirmação
    explícita: é a diferença entre corrigir uma linha e zerar a tabela, e um
    typo não pode decidir isso sozinho."""
    s = _guard_write(sql)
    if not _HAS_WHERE.search(s) and not confirm_full_table:
        raise QueryError(
            "essa instrução não tem WHERE — ela afeta a TABELA INTEIRA. "
            "Marque a confirmação se for isso mesmo."
        )
    return s


# --- execução em background (ver docstring do módulo) ---

_jobs: dict[str, dict] = {}
_jobs_lock = threading.Lock()


def get_write_job(job_id: str) -> dict | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return dict(job) if job is not None else None


def start_write_job(sql: str, confirm_full_table: bool = False) -> str:
    """Valida na hora (erro de sintaxe/regra volta na mesma requisição) e roda
    o write numa thread, devolvendo um job_id pra acompanhar."""
    s = check_write(sql, confirm_full_table)

    job_id = uuid.uuid4().hex
    with _jobs_lock:
        _jobs[job_id] = {
            "status": "running",
            "sql": s,
            "rowcount": None,
            "error": None,
            "started_at": time.time(),
            "finished_at": None,
        }

    def _worker():
        try:
            with engine.begin() as conn:
                result = conn.execute(text(s))
                rowcount = result.rowcount
            with _jobs_lock:
                _jobs[job_id].update(status="done", rowcount=rowcount, finished_at=time.time())
        except Exception as e:
            with _jobs_lock:
                _jobs[job_id].update(
                    status="error", error=f"{type(e).__name__}: {e}"[:400], finished_at=time.time()
                )

    job_registry.register("db_write", job_id, get_write_job)
    threading.Thread(target=_worker, daemon=True, name=f"db-write-{job_id[:8]}").start()
    return job_id


def describe_table(name: str) -> dict:
    if not re.match(r"^[A-Za-z0-9_]+$", name or ""):
        raise QueryError("nome de tabela inválido")
    with engine.connect() as conn:
        cols = [dict(r._mapping) for r in conn.execute(text(f"SHOW COLUMNS FROM `{name}`"))]
        sample = run_query(f"SELECT * FROM `{name}`")
    return {"columns_schema": cols, **sample}
