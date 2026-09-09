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

Causa raiz #3 (confirmada 2026-09-09): nem todo link é uma playlist .m3u8 —
alguns apontam direto pra um transport stream .ts bruto e contínuo, sem
manifesto por cima. Isso é um formato válido de IPTV, mas antes essa função
exigia `#EXTM3U` sempre e rejeitava esses links como se estivessem quebrados.
Agora, quando o corpo não é um m3u8, checa se parece MPEG-TS de verdade
(Content-Type e/ou os sync bytes do próprio conteúdo) antes de rejeitar.

Causa raiz #4 (confirmada 2026-09-09): o catálogo VOD (filmes/séries) usa
bastante link .mp4 direto — outro formato sem `#EXTM3U`. Reconhecido pela
"ftyp box" no início do arquivo (assinatura padrão de qualquer MP4/MOV
válido: 4 bytes de tamanho + "ftyp") e/ou Content-Type video/mp4.
"""

from urllib.parse import urljoin

import requests

_MAX_MANIFEST_BYTES = 64 * 1024

# cada pacote MPEG-TS começa com o "sync byte" 0x47 a cada 188 bytes — checar
# se ele se repete é o jeito padrão de reconhecer um transport stream bruto
# sem depender só do Content-Type (que varia muito entre servidores de IPTV:
# video/mp2t, application/octet-stream, ou às vezes nenhum)
_TS_PACKET_SIZE = 188
_TS_SYNC_BYTE = 0x47
_TS_PACKETS_TO_CHECK = 8


def _read_bounded(resp: requests.Response) -> bytes:
    chunks = []
    total = 0
    for chunk in resp.iter_content(chunk_size=4096):
        if not chunk:
            break
        chunks.append(chunk)
        total += len(chunk)
        if total >= _MAX_MANIFEST_BYTES:
            break
    return b"".join(chunks)


def _first_variant_uri(manifest_text: str) -> str | None:
    lines = manifest_text.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("#EXT-X-STREAM-INF"):
            for candidate in lines[i + 1 :]:
                candidate = candidate.strip()
                if candidate and not candidate.startswith("#"):
                    return candidate
    return None


def _looks_like_raw_mpeg_ts(data: bytes) -> bool:
    """Confirma pacotes MPEG-TS pelo sync byte 0x47 repetindo a cada 188 bytes.
    Exige pelo menos 2 pacotes pra não confundir um arquivo qualquer cujo 1º
    byte por acaso seja 0x47 com um transport stream de verdade."""
    packet_count = len(data) // _TS_PACKET_SIZE
    if packet_count < 2:
        return False
    checked = min(packet_count, _TS_PACKETS_TO_CHECK)
    return all(data[i * _TS_PACKET_SIZE] == _TS_SYNC_BYTE for i in range(checked))


def _looks_like_mp4(data: bytes) -> bool:
    """Todo MP4/MOV válido tem uma "ftyp box" logo no início: 4 bytes de
    tamanho + o literal 'ftyp'. Suficiente pra distinguir de HTML de erro,
    JSON, texto etc. sem precisar de um parser de MP4 de verdade."""
    return len(data) >= 8 and data[4:8] == b"ftyp"


def _get_body(url: str, timeout: float, headers: dict | None) -> tuple[str | None, bytes] | None:
    """GET com corpo limitado. None se a request falhar ou o status for erro;
    senão (Content-Type, corpo bruto)."""
    try:
        with requests.get(url, headers=headers, timeout=timeout, stream=True) as resp:
            if resp.status_code >= 400:
                return None
            return resp.headers.get("Content-Type"), _read_bounded(resp)
    except requests.RequestException:
        return None


def _get_manifest_text(url: str, timeout: float, headers: dict | None) -> str | None:
    """Igual a _get_body, mas já decodificado — usado só pra buscar a
    sub-playlist de uma variante, que é sempre texto m3u8."""
    result = _get_body(url, timeout, headers)
    if result is None:
        return None
    _, data = result
    return data.decode("utf-8", errors="replace")


def stream_is_really_playable(url: str, timeout: float, headers: dict | None = None) -> bool:
    """True se a URL responder como playlist HLS válida (seguindo a cadeia até
    o nível final) OU como um transport stream .ts bruto de verdade."""
    result = _get_body(url, timeout, headers)
    if result is None:
        return False
    content_type, data = result
    text = data.decode("utf-8", errors="replace")

    if text.lstrip().startswith("#EXTM3U"):
        variant = _first_variant_uri(text)
        if variant is None:
            # já é a media playlist final (tem os segmentos), não master
            return True

        sub_url = urljoin(url, variant)
        sub_text = _get_manifest_text(sub_url, timeout, headers)
        return sub_text is not None and sub_text.lstrip().startswith("#EXTM3U")

    # não é m3u8 — pode ser um .ts bruto ou um .mp4 direto, sem manifesto por
    # cima. Aceita se o Content-Type confirma (video/mp2t ou video/mp4) OU se
    # o próprio conteúdo já parece um desses formatos de verdade.
    content_type_lower = (content_type or "").lower()
    if "mp2t" in content_type_lower or "mp4" in content_type_lower:
        return True
    return _looks_like_raw_mpeg_ts(data) or _looks_like_mp4(data)
