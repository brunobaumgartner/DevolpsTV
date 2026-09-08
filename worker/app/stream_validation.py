"""Validação de stream HLS que segue a cadeia até o nível real, não só o
manifesto raiz.

Causa raiz #1 (confirmada 2026-09-08, canal ESPN.br): o manifesto raiz de muitos
desses servidores é um "master playlist" (#EXT-X-STREAM-INF apontando pra uma
sub-playlist com o vídeo de verdade). Esse manifesto raiz costuma ficar
servindo 200 mesmo com o stream real fora do ar. Validar só o nível raiz aprova
canais que não tocam de verdade — por isso seguimos a cadeia até o fim.

Causa raiz #2 (confirmada 2026-09-08, primeira versão desta função): usar
`resp.text` baixa o corpo INTEIRO da resposta antes de retornar. Um manifesto
de playlist é sempre pequeno (poucos KB), mas se alguma URL "de playlist" na
prática devolver dados contínuos (um stream de vídeo bruto, um servidor mal
configurado, etc.), `resp.text` trava ou demora minutos por request — e com
centenas de streams testados em paralelo isso já foi o suficiente pra travar
o health-check inteiro por 6+ minutos num teste real. Por isso lemos só um
prefixo limitado (`_MAX_MANIFEST_BYTES`) via streaming em vez do corpo todo.
"""

from urllib.parse import urljoin

import requests

# manifestos de playlist reais têm no máximo algumas dezenas de KB; qualquer
# coisa maior que isso não é o que estamos procurando, então paramos de ler
_MAX_MANIFEST_BYTES = 64 * 1024


def _read_bounded_text(resp: requests.Response) -> str:
    """Lê no máximo _MAX_MANIFEST_BYTES do corpo da resposta, sem nunca tentar
    baixar tudo (proteção contra URLs que na prática são streams contínuos)."""
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
    """Se for um master playlist, devolve a URI (relativa ou absoluta) da 1ª
    variante — a linha não-comentário logo após um #EXT-X-STREAM-INF."""
    lines = manifest_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            for candidate in lines[i + 1 :]:
                candidate = candidate.strip()
                if candidate and not candidate.startswith("#"):
                    return candidate
    return None


def _get_manifest(url: str, timeout: float, headers: dict | None) -> str | None:
    """GET com corpo limitado. None se a request falhar ou o status for erro."""
    try:
        with requests.get(url, headers=headers, timeout=timeout, stream=True) as resp:
            if resp.status_code >= 400:
                return None
            return _read_bounded_text(resp)
    except requests.RequestException:
        return None


def stream_is_really_playable(url: str, timeout: float, headers: dict | None = None) -> bool:
    """True só se a cadeia de manifestos até o nível final (sem mais variantes)
    responder com um M3U8 válido. Segue no máximo 1 nível de master->variante
    (suficiente pro padrão HLS comum: raiz = master, variante = media playlist).
    O token da sub-playlist pode ser de curta duração/uso único em alguns
    servidores — por isso os dois GETs acontecem em sequência imediata, sem
    nenhuma pausa entre eles."""
    text = _get_manifest(url, timeout, headers)
    if text is None or not text.lstrip().startswith("#EXTM3U"):
        return False

    variant = _first_variant_uri(text)
    if variant is None:
        # já é a media playlist final (tem os segmentos), não master
        return True

    sub_url = urljoin(url, variant)
    sub_text = _get_manifest(sub_url, timeout, headers)
    return sub_text is not None and sub_text.lstrip().startswith("#EXTM3U")
