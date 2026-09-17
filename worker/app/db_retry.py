"""Retry de transação pra deadlock/lock-timeout do MySQL.

Mesma ideia (e mesmos códigos de erro) do `_run_with_deadlock_retry` do
api/app/import_vod.py: 1213 (deadlock) e 1205 (lock wait timeout) não são bug,
são o MySQL escolhendo uma vítima quando duas transações brigam pelas mesmas
linhas — a prática padrão é tentar a transação inteira de novo.

Os jobs do worker rodam serializados entre si (ver scheduler.py), mas ainda
disputam as mesmas tabelas com o container da API (importação de CSV, edição
no admin, health-check manual). Foi assim que o fetch_fast_meta morreu com
deadlock em 2026-09-14.
"""

import logging
import time

from sqlalchemy.exc import OperationalError

logger = logging.getLogger("iptv-worker.db_retry")

_RETRYABLE_ERRNOS = {1213, 1205}
_MAX_RETRIES = 4


def with_deadlock_retry(fn, *, what: str):
    """Roda `fn()` de novo do zero quando o MySQL abortar por deadlock/lock
    timeout. Qualquer outro erro sobe na hora."""
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            return fn()
        except OperationalError as e:
            errno = e.orig.args[0] if e.orig and e.orig.args else None
            if errno not in _RETRYABLE_ERRNOS or attempt == _MAX_RETRIES:
                raise
            wait = attempt * 2  # 2s, 4s, 6s...
            logger.warning(
                "%s: deadlock/lock timeout (errno=%s), tentativa %d/%d — repetindo em %ds",
                what, errno, attempt, _MAX_RETRIES, wait,
            )
            time.sleep(wait)
