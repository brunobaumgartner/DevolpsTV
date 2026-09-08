"""Verificação AO VIVO de um stream, feita na hora que o usuário pede pra assistir —
diferente do health-check do worker (que roda em background e pode ficar
desatualizado em poucos minutos com fontes tão instáveis quanto essas)."""

from concurrent.futures import ThreadPoolExecutor, as_completed

from .stream_validation import stream_is_really_playable

LIVE_CHECK_TIMEOUT_SEC = 5  # 1s a mais que antes: agora pode precisar de 2 requests em cadeia


def _is_reachable(url: str) -> bool:
    return stream_is_really_playable(url, LIVE_CHECK_TIMEOUT_SEC)


def resolve_live_url(candidate_urls: list[str]) -> str | None:
    """Testa os mirrors candidatos em paralelo e devolve o primeiro que responder
    de verdade agora. None se nenhum responder."""
    if not candidate_urls:
        return None
    if len(candidate_urls) == 1:
        return candidate_urls[0] if _is_reachable(candidate_urls[0]) else None

    with ThreadPoolExecutor(max_workers=len(candidate_urls)) as pool:
        futures = {pool.submit(_is_reachable, url): url for url in candidate_urls}
        for future in as_completed(futures):
            if future.result():
                url = futures[future]
                for f in futures:
                    f.cancel()
                return url
    return None
