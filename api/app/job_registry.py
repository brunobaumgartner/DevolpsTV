"""Registro central dos jobs em processo (rodam como thread daemon dentro do
container da API). Cada `start_*_job` chama `register()`; a tela "Sistema" do
admin lista tudo e pode pedir cancelamento. O cancelamento é cooperativo: o
loop do worker checa `is_cancelled(job_id)` e sai limpo.

Não substitui o `_jobs` dict de cada módulo (esses continuam sendo a fonte do
progresso detalhado) — aqui só guardamos o suficiente pra listar e cancelar.
"""

import threading
import time

_lock = threading.Lock()
# job_id -> {"kind": str, "started_at": float, "cancel": Event, "get": callable}
_registry: dict[str, dict] = {}


def register(kind: str, job_id: str, get_fn) -> threading.Event:
    """Registra um job. `get_fn(job_id)` devolve o dict de status do módulo
    (com status/processed/total/etc). Retorna o Event de cancelamento pra o
    worker checar."""
    ev = threading.Event()
    with _lock:
        _registry[job_id] = {
            "kind": kind,
            "started_at": time.time(),
            "cancel": ev,
            "get": get_fn,
        }
    return ev


def is_cancelled(job_id: str) -> bool:
    with _lock:
        entry = _registry.get(job_id)
    return bool(entry and entry["cancel"].is_set())


def request_cancel(job_id: str) -> bool:
    with _lock:
        entry = _registry.get(job_id)
        if not entry:
            return False
        entry["cancel"].set()
        return True


def list_jobs() -> list[dict]:
    with _lock:
        entries = list(_registry.items())
    out = []
    for job_id, e in entries:
        try:
            status = e["get"](job_id) or {}
        except Exception:
            status = {}
        out.append(
            {
                "job_id": job_id,
                "kind": e["kind"],
                "started_at": e["started_at"],
                "cancel_requested": e["cancel"].is_set(),
                "status": status.get("status"),
                "phase": status.get("phase"),
                "processed": status.get("processed"),
                "total": status.get("total"),
                "matched": status.get("matched"),
                "classified": status.get("classified"),
                "healthy": status.get("healthy"),
                "error": status.get("error"),
            }
        )
    out.sort(key=lambda j: j["started_at"], reverse=True)
    return out


def prune(max_age_seconds: int = 6 * 3600) -> None:
    """Tira do registro os jobs terminados há mais de X (só limpeza de memória)."""
    now = time.time()
    with _lock:
        for job_id in list(_registry):
            e = _registry[job_id]
            if now - e["started_at"] < max_age_seconds:
                continue
            try:
                st = (e["get"](job_id) or {}).get("status")
            except Exception:
                st = None
            if st in ("done", "error", "cancelled", None):
                _registry.pop(job_id, None)
