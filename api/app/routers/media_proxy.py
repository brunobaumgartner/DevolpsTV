"""Proxy genérico de mídia — resolve "mixed content" nos links diretos de VOD
(.mp4). O site é servido em https (o Cloudflare termina o TLS na frente), mas
o `stream_url` de muito título no catálogo é http://. O Chrome faz upgrade
automático de http-> https em qualquer elemento de página https (política de
"mixed content"), e a origem real desses provedores (depois de um redirect
pra um IP direto) não tem certificado — a conexão https cai com
ERR_CONNECTION_RESET (achado real em 2026-09-11, via log do Chrome do
usuário). Buscando pelo NOSSO servidor (sem navegador, sem mixed content) e
devolvendo pelo mesmo domínio https do site, o problema desaparece.

Suporta Range (essencial pra seek/streaming de vídeo — sem isso o navegador
teria que baixar o arquivo inteiro antes de tocar qualquer trecho).
"""

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from ..db import get_db
from ..models import AccessToken
from ..security import require_valid_token

router = APIRouter()

_TIMEOUT = 15
_CHUNK = 64 * 1024
_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
_PASSTHROUGH_HEADERS = ("Content-Type", "Content-Length", "Content-Range", "Accept-Ranges")


@router.get("/p/{token}/media")
def media_proxy(
    token: str,
    request: Request,
    url: str = Query(..., description="URL do arquivo de mídia (encoded)"),
    _access: AccessToken = Depends(require_valid_token),
    db=Depends(get_db),
):
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url inválida")

    headers = {"User-Agent": _UA}
    range_header = request.headers.get("range")
    if range_header:
        headers["Range"] = range_header

    try:
        upstream = requests.get(url, headers=headers, timeout=_TIMEOUT, stream=True, allow_redirects=True)
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="falha ao buscar o vídeo na origem")
    if upstream.status_code >= 400:
        upstream.close()
        raise HTTPException(status_code=502, detail=f"origem respondeu {upstream.status_code}")

    resp_headers = {"Cache-Control": "no-store", "Access-Control-Allow-Origin": "*"}
    for h in _PASSTHROUGH_HEADERS:
        v = upstream.headers.get(h)
        if v:
            resp_headers[h] = v

    def _iter():
        try:
            for chunk in upstream.iter_content(chunk_size=_CHUNK):
                if chunk:
                    yield chunk
        finally:
            upstream.close()

    return StreamingResponse(
        _iter(),
        status_code=upstream.status_code,
        headers=resp_headers,
        media_type=upstream.headers.get("Content-Type", "application/octet-stream"),
    )
