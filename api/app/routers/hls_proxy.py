"""Proxy leve de MANIFESTO HLS. Alguns provedores (Pluto TV) servem o .m3u8
com CORS restrito (`access-control-allow-origin: http://pluto.tv`), então o
hls.js no navegador não consegue buscar. Os segmentos (.ts) e chaves (.key)
desses mesmos provedores liberam `*` — então só o manifesto precisa passar
por aqui (poucos KB por sessão); o vídeo pesado vai direto do CDN.

Reescreve as URIs de sub-playlist (.m3u8) pra voltarem por este proxy e
deixa .ts/.key absolutos e diretos.
"""

import re
from urllib.parse import quote, urljoin

import requests
from fastapi import APIRouter, Depends, HTTPException, Query, Response

from ..db import get_db
from ..models import AccessToken
from ..security import require_valid_token

router = APIRouter()

_TIMEOUT = 12
_MAX_BYTES = 2 * 1024 * 1024  # manifesto é pequeno; corta qualquer coisa gigante
_UA = "Mozilla/5.0 (SmartTV) AppleWebKit/537.36"


@router.get("/p/{token}/hls")
def hls_proxy(
    token: str,
    url: str = Query(..., description="URL do manifesto (encoded)"),
    _access: AccessToken = Depends(require_valid_token),
    db=Depends(get_db),
):
    if not url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="url inválida")

    try:
        r = requests.get(
            url,
            headers={"User-Agent": _UA, "Referer": "http://pluto.tv/", "Origin": "http://pluto.tv"},
            timeout=_TIMEOUT,
            stream=True,
        )
    except requests.RequestException:
        raise HTTPException(status_code=502, detail="falha ao buscar o manifesto")
    if r.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"origem respondeu {r.status_code}")

    final_url = str(r.url)
    body = r.raw.read(_MAX_BYTES, decode_content=True) or b""
    text = body.decode("utf-8", errors="replace")

    if not text.lstrip().startswith("#EXTM3U"):
        # não é m3u8 (ex: já é um .ts direto) — devolve como veio, com CORS
        return Response(
            content=body,
            media_type=r.headers.get("Content-Type", "application/octet-stream"),
            headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
        )

    prefix = f"/iptv/p/{quote(token, safe='')}/hls?url="

    def fix_line(line: str) -> str:
        s = line.strip()
        if not s or s.startswith("#"):
            # reescreve URI="..." dentro de #EXT-X-MEDIA (sub-playlists de áudio/legenda)
            def repl(m):
                abs_u = urljoin(final_url, m.group(1))
                if ".m3u8" in abs_u:
                    return f'URI="{prefix}{quote(abs_u, safe="")}"'
                return m.group(0)
            return re.sub(r'URI="([^"]+)"', repl, line)
        abs_u = urljoin(final_url, s)
        if ".m3u8" in abs_u:  # variante -> volta pelo proxy
            return prefix + quote(abs_u, safe="")
        return abs_u  # .ts / .key / outro -> absoluto e direto

    rewritten = "\n".join(fix_line(ln) for ln in text.splitlines()) + "\n"
    return Response(
        content=rewritten,
        media_type="application/vnd.apple.mpegurl",
        headers={"Access-Control-Allow-Origin": "*", "Cache-Control": "no-store"},
    )
