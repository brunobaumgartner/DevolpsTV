"""Canais FAST via dataset mjh.nz (github.com/matthuisman/i.mjh.nz):
  - ENRIQUECE canais que já temos (do iptv-org) com descrição, capa (art),
    logo melhor e EPG "está passando agora" (a lista `programs`)
  - CRIA os canais que o dataset tem e o iptv-org não — stream montado via
    o encurtador do próprio matthuisman (jmp2.uk/<slug>), que faz o
    hand-shake de geo/token do lado dele

Cobertura Brasil hoje: só Pluto TV tem região `br` no dataset. Samsung/Plex/
Roku não têm `br` em nenhuma fonte comunitária — precisariam da API oficial
de cada um (frágil, geo-gated, esforço à parte). A estrutura abaixo já aceita
esses provedores automaticamente se/quando o dataset ganhar região BR.

Casamento com o catálogo é por NOME normalizado (mesma função do fetch_epg).
"""

import gzip
import io
import json
import logging
import re
import unicodedata
from datetime import datetime, timedelta, timezone

import requests

from ..db import SessionLocal
from ..epg_sources import normalize_channel_name
from ..job_tracking import track_job
from ..models import Channel, Program, Stream

logger = logging.getLogger("iptv-worker.fetch_fast_meta")

REQUEST_TIMEOUT = 60
_BASE = "https://github.com/matthuisman/i.mjh.nz/raw/master"

# provedor -> (arquivo, códigos de região a usar, template de slug jmp2.uk).
# O template é usado quando o JSON não traz `slug` próprio (caso da Pluto).
MJH_PROVIDERS = {
    "PlutoTV": (f"{_BASE}/PlutoTV/.channels.json.gz", ("br",), "plu-{id}"),
    "SamsungTVPlus": (f"{_BASE}/SamsungTVPlus/.channels.json.gz", ("br", "BR"), None),
    "Plex": (f"{_BASE}/Plex/.channels.json.gz", ("br", "BR"), "plex-{id}"),
}

# grupo do dataset (PT-BR) -> categoria nossa (slug iptv-org)
_GROUP_TO_CATEGORY = {
    "filmes": "movies", "cine": "movies", "cinema": "movies",
    "series": "series", "séries": "series",
    "noticias": "news", "notícias": "news", "jornalismo": "news",
    "esportes": "sports", "esporte": "sports",
    "infantil": "kids", "kids": "kids", "criancas": "kids", "crianças": "kids",
    "animacao": "animation", "animação": "animation", "anime": "animation",
    "documentario": "documentary", "documentário": "documentary",
    "documentarios": "documentary", "documentários": "documentary",
    "entretenimento": "entertainment", "variedades": "entertainment",
    "musica": "music", "música": "music",
    "estilo de vida": "lifestyle", "lifestyle": "lifestyle",
    "comedia": "comedy", "comédia": "comedy",
    "reality": "entertainment",
}

_DEFAULT_LAST_DURATION = timedelta(hours=2)


def _norm_group(g):
    if not g:
        return None
    key = unicodedata.normalize("NFKD", g).encode("ascii", "ignore").decode("ascii").lower().strip()
    return _GROUP_TO_CATEGORY.get(key)


def _load(url):
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return json.loads(gzip.GzipFile(fileobj=io.BytesIO(resp.content)).read())


def _iter_region(data, region_codes):
    regions = data.get("regions") or {}
    for code in region_codes:
        r = regions.get(code)
        if r and r.get("channels"):
            for cid, ch in r["channels"].items():
                yield cid, ch


def _programs_to_rows(channel_id, programs):
    rows = []
    for i, entry in enumerate(programs or []):
        if not entry or len(entry) < 2:
            continue
        try:
            start = datetime.fromtimestamp(int(entry[0]), tz=timezone.utc).replace(tzinfo=None)
        except (TypeError, ValueError, OSError):
            continue
        end = None
        if i + 1 < len(programs) and programs[i + 1]:
            try:
                end = datetime.fromtimestamp(int(programs[i + 1][0]), tz=timezone.utc).replace(tzinfo=None)
            except (TypeError, ValueError, OSError):
                end = None
        if end is None or end <= start:
            end = start + _DEFAULT_LAST_DURATION
        rows.append(Program(channel_id=channel_id, title=str(entry[1])[:500], start_time=start, end_time=end))
    return rows


@track_job("fetch_fast_meta")
def run():
    db = SessionLocal()
    try:
        channels = db.query(Channel).all()
        by_norm = {}
        for c in channels:
            k = normalize_channel_name(c.name)
            if k and k not in by_norm:
                by_norm[k] = c
        existing_tvg = {c.tvg_id for c in channels}

        enriched = created = 0
        touched_ids = set()
        epg_rows = []

        for provider, (url, regions, slug_tpl) in MJH_PROVIDERS.items():
            try:
                data = _load(url)
            except Exception:
                logger.warning("[%s] falha ao baixar dataset, pulando", provider, exc_info=True)
                continue

            slug = data.get("slug") or slug_tpl  # ex: "stvp-{id}"
            p_enriched = p_created = 0

            for cid, ch in _iter_region(data, regions):
                name = ch.get("name")
                if not name:
                    continue
                target = by_norm.get(normalize_channel_name(name))

                if target is None:
                    if not slug or "{id}" not in slug:
                        continue  # sem como montar o stream -> não cria
                    tvg = f"{provider}-{cid}"
                    if tvg in existing_tvg:
                        continue
                    target = Channel(
                        tvg_id=tvg,
                        name=name,
                        logo_url=(ch.get("logo") or "")[:500] or None,
                        backdrop_url=(ch.get("art") or "")[:600] or None,
                        description=ch.get("description"),
                        category=_norm_group(ch.get("group")),
                        is_active=True,
                    )
                    db.add(target)
                    db.flush()
                    db.add(
                        Stream(
                            channel_id=target.id,
                            url="https://jmp2.uk/" + slug.replace("{id}", cid) + ".m3u8",
                            lang_label="Português",
                        )
                    )
                    by_norm[normalize_channel_name(name)] = target
                    existing_tvg.add(tvg)
                    created += 1
                    p_created += 1
                else:
                    if ch.get("description"):
                        target.description = ch["description"]
                    if ch.get("art"):
                        target.backdrop_url = ch["art"][:600]
                    if ch.get("logo") and not target.logo_url:
                        target.logo_url = ch["logo"][:500]
                    enriched += 1
                    p_enriched += 1

                touched_ids.add(target.id)
                epg_rows.extend(_programs_to_rows(target.id, ch.get("programs")))

            logger.info("[%s] %d enriquecido(s), %d criado(s)", provider, p_enriched, p_created)

        # troca a programação só dos canais tocados aqui (FAST não está no
        # BrazilTVEPG, sem conflito com o fetch_epg)
        db.flush()
        if touched_ids:
            db.query(Program).filter(Program.channel_id.in_(touched_ids)).delete(synchronize_session=False)
        for row in epg_rows:
            db.add(row)
        db.commit()

        logger.info(
            "fetch_fast_meta: %d enriquecido(s), %d criado(s), %d programa(s) de EPG.",
            enriched, created, len(epg_rows),
        )
        return {"enriquecidos": enriched, "criados": created, "programas_epg": len(epg_rows)}
    except Exception:
        db.rollback()
        logger.exception("Erro no fetch_fast_meta")
        raise
    finally:
        db.close()
