"""Validação de stream HLS que segue a cadeia até o nível real, não só o
manifesto raiz. Cópia da lógica de worker/app/stream_validation.py — duplicada
de propósito porque API e worker são serviços/imagens Docker separados (ver
ARQUITETURA.md seção 6). Qualquer correção aqui precisa ser espelhada lá.

Causa raiz #1 (confirmada 2026-09-08, canal ESPN.br): o manifesto raiz de muitos
desses servidores é um "master playlist" (#EXT-X-STREAM-INF apontando pra uma
sub-playlist com o vídeo de verdade). Esse manifesto raiz costuma ficar
servindo 200 mesmo com o stream real fora do ar. Validar só o nível raiz aprova
canais que não tocam de verdade — por isso seguimos a cadeia até o fim.

Causa raiz #2 (confirmada 2026-09-08, primeira versão desta função): usar
`resp.text` baixa o corpo INTEIRO da resposta antes de retornar. Um manifesto
de playlist é sempre pequeno (poucos KB), mas se alguma URL "de playlist" na
prática devolver dados contínuos, `resp.text` pode travar/demorar minutos por
request. Lemos só um prefixo limitado via streaming em vez do corpo todo.
"""

from urllib.parse import urljoin

import requests

_MAX_MANIFEST_BYTES = 64 * 1024


def _read_bounded_text(resp: requests.Response) -> str:
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=4096):
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= _MAX_MANIFEST_BYTES:
            break
    raw = b"".join(chunks)
    return raw.decode("utf-8", errors="replace")


def _first_variant_uri(manifest_text: str) -> str | None:
    lines = manifest_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            for candidate in lines[i + 1 :]:
                candidate = candidate.strip()
                if candidate and not candidate.startswith("#"):
                    return candidate
    return None


def _get_manifest(url: str, timeout: float, headers: dict | None) -> str | None:
    try:
        with requests.get(url, headers=headers, timeout=timeout, stream=True) as resp:
            if resp.status_code >= 400:
                return None
            return _read_bounded_text(resp)
    except requests.RequestException:
        return None


def stream_is_really_playable(url: str, timeout: float, headers: dict | None = None) -> bool:
    text = _get_manifest(url, timeout, headers)
    if text is None or not text.lstrip().startswith("#EXTM3U"):
        return False

    variant = _first_variant_uri(text)
    if variant is None:
        return True

    sub_url = urljoin(url, variant)
    sub_text = _get_manifest(sub_url, timeout, headers)
    return sub_text is not None and sub_text.lstrip().startswith("#EXTM3U")
