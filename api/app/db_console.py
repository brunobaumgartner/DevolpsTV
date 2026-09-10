"""Console de consulta ao banco pra tela "Banco" do admin. SOMENTE LEITURA:
aceita SELECT / SHOW / DESCRIBE / EXPLAIN / WITH...SELECT e nada mais. Uma só
instrução por vez. Aplica LIMIT e MAX_EXECUTION_TIME pra não travar o banco.
"""

import re

from sqlalchemy import text

from .db import engine

_MAX_ROWS = 500
_STMT_TIMEOUT_MS = 8000

_READ_START = re.compile(r"^\s*(select|show|describe|desc|explain|with)\b", re.IGNORECASE)
_WRITE_WORDS = re.compile(
    r"\b(insert|update|delete|drop|alter|create|truncate|rename|grant|revoke|"
    r"replace|call|lock|unlock|set|use|load|handler|into\s+outfile|into\s+dumpfile)\b",
    re.IGNORECASE,
)


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


def describe_table(name: str) -> dict:
    if not re.match(r"^[A-Za-z0-9_]+$", name or ""):
        raise QueryError("nome de tabela inválido")
    with engine.connect() as conn:
        cols = [dict(r._mapping) for r in conn.execute(text(f"SHOW COLUMNS FROM `{name}`"))]
        sample = run_query(f"SELECT * FROM `{name}`")
    return {"columns_schema": cols, **sample}
