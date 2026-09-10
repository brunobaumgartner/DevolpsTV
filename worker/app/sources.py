"""Fontes de canais/streams em português. Cada `load_*` devolve ChannelEntry
normalizados, já sem os que nosso health-check HTTP não consegue validar de
verdade (YouTube, protocolos não-HTTP etc). ALL_SOURCES define a ordem de
prioridade: a primeira fonte que trouxer um dado (nome/logo/categoria) pra um
tvg_id "ganha"; as seguintes só completam o que faltar e somam mirrors novos.

Escopo (2026-09-09): não é só Brasil — é qualquer canal de língua portuguesa.
O iptv-org/api não tem campo de idioma no canal (só em `feeds.json`, por feed,
o que exigiria filtrar streams por feed em vez de por canal — mais complexo e
arriscado de fazer errado). Por ora o critério é país de língua oficial
portuguesa (`LUSOPHONE_COUNTRY_CODES`), que já cobre a esmagadora maioria com
segurança. Canais de língua portuguesa hospedados em outros países (feeds
dublados de redes internacionais, por exemplo) ficam de fora por ora — ver
ARQUITETURA.md seção 2.1."""

import logging
import re
import unicodedata
from dataclasses import dataclass
from typing import Iterable, Optional

import requests

from .config import BROADCAST_TV_NAME_HINTS

logger = logging.getLogger("iptv-worker.sources")

REQUEST_TIMEOUT = 30

# países cuja língua oficial é o português (medido em 2026-09-09 contra o
# iptv-org/api: 1.062 canais no total — BR 796, PT 144, AO 52, MZ 51, CV 11,
# GW 2, ST 1, TL 5)
LUSOPHONE_COUNTRY_CODES = {"BR", "PT", "AO", "MZ", "CV", "GW", "ST", "TL"}

IPTV_ORG_CHANNELS_URL = "https://iptv-org.github.io/api/channels.json"
IPTV_ORG_STREAMS_URL = "https://iptv-org.github.io/api/streams.json"
IPTV_ORG_LOGOS_URL = "https://iptv-org.github.io/api/logos.json"
# feeds.json tem o idioma POR FEED (channels.json não tem idioma nenhum). É o
# que pega Pluto TV / Samsung TV Plus / Plex etc: o canal é registrado como
# país "US" no iptv-org, mas o feed dublado/legendado pro Brasil tem
# languages=["por"]. Sem isso, esses canais (Pluto TV Anime, Naruto 24/7,
# Tokusato, Pluto TV Cine *, ...) ficavam todos de fora.
IPTV_ORG_FEEDS_URL = "https://iptv-org.github.io/api/feeds.json"
PORTUGUESE_LANG_CODE = "por"
IPTVCOM_M3U_URL = "https://raw.githubusercontent.com/iptv-com/iptv/main/lists/brazil.m3u"
FREETV_M3U_URL = "https://raw.githubusercontent.com/Free-TV/IPTV/master/playlists/playlist_brazil.m3u8"
FTA_BRASIL_M3U_URL = "https://raw.githubusercontent.com/joaoguidugli/FTA-IPTV-Brasil/master/playlist.m3u8"

# grupos em português -> categoria do iptv-org. Só mapeados os que têm correspondência
# direta e defensável (confirmado contra a lista oficial de categories.json). "Agro" e
# "Saúde" não têm categoria equivalente no iptv-org — ficam sem categoria (None) em vez
# de forçar um mapeamento impreciso.
_FTA_CATEGORY_MAP = {
    "educativo": "education",
    "educação": "education",
    "esportes": "sports",
    "geral": "general",
    "governamental": "public",
    "legislativo": "legislative",
    "notícias": "news",
    "religioso": "religious",
}

# categorias válidas (iptv-org/api categories.json) — qualquer group-title fora
# disso é ignorado como categoria, pra não poluir o filtro do frontend com lixo
KNOWN_CATEGORIES = {
    "auto", "animation", "business", "classic", "comedy", "cooking", "culture",
    "documentary", "education", "entertainment", "family", "general", "interactive",
    "kids", "legislative", "lifestyle", "movies", "music", "news", "outdoor",
    "public", "relax", "religious", "series", "science", "shop", "sports",
    "travel", "weather",
}  # "xxx" fica de fora de propósito — ver _is_playable_url / load_iptv_org


@dataclass
class ChannelEntry:
    tvg_id: str
    name: str
    logo_url: Optional[str]
    category: Optional[str]
    url: str
    source: str
    feed_id: Optional[str] = None
    lang_label: Optional[str] = None


def _fetch_json(url: str):
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.json()


def _fetch_text(url: str) -> str:
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.text


def _fetch_text_latin1(url: str) -> str:
    """Alguns M3U por aí não são UTF-8 mesmo sem declarar isso — decodificar errado
    corrompe nomes acentuados (silenciosamente, sem erro). Confirmado por inspeção
    de bytes que esta fonte específica (FTA-IPTV-Brasil) é Latin-1/ISO-8859-1: 'í'
    e 'ú' aparecem como os bytes únicos 0xED/0xFA, não os pares UTF-8 0xC3 0xAD /
    0xC3 0xBA. O próprio GitHub confirma isso servindo o arquivo como
    application/octet-stream em vez de text/plain;charset=utf-8 (que é o que ele
    devolve pras outras fontes, essas sim UTF-8 de verdade)."""
    resp = requests.get(url, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return resp.content.decode("latin-1")


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    slug = re.sub(r"[^a-zA-Z0-9]+", "", normalized)
    return slug or "canal"


def _is_playable_url(url: Optional[str]) -> bool:
    """Filtra links que o nosso health-check (HTTP puro) não consegue validar de
    verdade: YouTube (não é um endpoint de stream), e qualquer coisa que não seja
    http(s) (rtmp/rtsp puro etc)."""
    if not url:
        return False
    if "youtube.com" in url or "youtu.be" in url:
        return False
    return url.startswith("http://") or url.startswith("https://")


def _normalize_category(raw: Optional[str]) -> Optional[str]:
    if not raw:
        return None
    value = raw.strip().lower()
    return value if value in KNOWN_CATEGORIES else None


def _parse_m3u(text: str):
    """Parser simples de M3U: casa cada #EXTINF com a 1ª linha não-comentário
    seguinte (a URL)."""
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            attrs = dict(re.findall(r'([\w-]+)="([^"]*)"', line))
            name = line.rsplit(",", 1)[-1].strip()
            j = i + 1
            while j < len(lines) and lines[j].startswith("#"):
                j += 1
            if j < len(lines):
                yield attrs, name, lines[j]
                i = j
        i += 1


def _build_logo_map(channel_ids: set) -> dict:
    try:
        logos = _fetch_json(IPTV_ORG_LOGOS_URL)
    except requests.RequestException:
        logger.warning("[iptv-org] falha ao buscar logos.json, seguindo sem logos", exc_info=True)
        return {}
    logo_map = {}
    for logo in logos:
        cid = logo.get("channel")
        if cid not in channel_ids or cid in logo_map:
            continue
        if logo.get("in_use") and logo.get("url"):
            logo_map[cid] = logo["url"]
    return logo_map


_LUSOPHONE_BROADCAST_AREAS = {f"c/{code}" for code in LUSOPHONE_COUNTRY_CODES}

# iso 639-3 -> nome curto pra rótulo de idioma no player. Só os que aparecem
# de verdade nos feeds que a gente puxa; o resto cai no fallback.
_LANG_NAMES = {
    "por": "Português", "eng": "Inglês", "spa": "Espanhol", "jpn": "Japonês",
    "jap": "Japonês", "fra": "Francês", "fre": "Francês", "deu": "Alemão",
    "ger": "Alemão", "ita": "Italiano", "kor": "Coreano", "zho": "Chinês",
    "cmn": "Chinês", "rus": "Russo",
}


def _feed_label(feed: dict) -> str:
    """Rótulo de idioma pro player, a partir de 1 feed do iptv-org."""
    langs = feed.get("languages") or []
    areas = feed.get("broadcast_area") or []
    if PORTUGUESE_LANG_CODE in langs:
        return "Português"
    if any(a in _LUSOPHONE_BROADCAST_AREAS for a in areas):
        # transmitido pra país lusófono mas áudio não é português — é o feed
        # legendado (ex: feed "BR" do One Piece, áudio japonês + legenda PT)
        return "Legendado"
    if langs:
        return _LANG_NAMES.get(langs[0], langs[0].upper())
    return "Outro idioma"


def _iptv_org_feeds():
    """feeds.json inteiro, ou [] se falhar (aí cai só no filtro por país)."""
    try:
        return _fetch_json(IPTV_ORG_FEEDS_URL)
    except requests.RequestException:
        logger.warning("[iptv-org] falha ao buscar feeds.json, seguindo só com filtro por país", exc_info=True)
        return []


def load_iptv_org() -> Iterable[ChannelEntry]:
    channels_data = _fetch_json(IPTV_ORG_CHANNELS_URL)
    by_id = {c["id"]: c for c in channels_data}

    def _usable(info) -> bool:
        return bool(info) and not info.get("closed") and not info.get("is_nsfw")

    feeds = _iptv_org_feeds()
    feeds_by_channel: dict[str, list[dict]] = {}
    for f in feeds:
        if f.get("channel") and f.get("id"):
            feeds_by_channel.setdefault(f["channel"], []).append(f)

    def _has_lusophone_feed(cid: str) -> bool:
        for f in feeds_by_channel.get(cid, []):
            langs = f.get("languages") or []
            areas = f.get("broadcast_area") or []
            if PORTUGUESE_LANG_CODE in langs or any(a in _LUSOPHONE_BROADCAST_AREAS for a in areas):
                return True
        return False

    # canal entra se: país de língua oficial portuguesa OU tem ao menos 1 feed
    # lusófono (áudio PT ou transmitido pra país lusófono/legendado)
    lusophone_country_ids = {
        cid for cid, info in by_id.items()
        if _usable(info) and info.get("country") in LUSOPHONE_COUNTRY_CODES
    }
    wanted_ids = set(lusophone_country_ids) | {
        cid for cid, info in by_id.items() if _usable(info) and _has_lusophone_feed(cid)
    }

    # rótulo de idioma por (channel, feed) — pra TODO feed de um canal que
    # entrou, não só o lusófono: assim o player lista "Português / Japonês /
    # ..." e o usuário escolhe. Feed sem entrada em feeds.json (feed_id None
    # nos streams) → rótulo fica None e o frontend assume "Português".
    feed_label: dict[tuple, str] = {}
    for cid in wanted_ids:
        for f in feeds_by_channel.get(cid, []):
            feed_label[(cid, f["id"])] = _feed_label(f)

    logger.info(
        "[iptv-org] canais em português: %d (%d por país lusófono + %d por feed)",
        len(wanted_ids), len(lusophone_country_ids), len(wanted_ids) - len(lusophone_country_ids),
    )

    logo_map = _build_logo_map(wanted_ids)
    channel_meta = {}
    for cid in wanted_ids:
        info = by_id[cid]
        categories = info.get("categories") or []
        channel_meta[cid] = {
            "name": info.get("name") or cid,
            "logo_url": logo_map.get(cid),
            "category": _normalize_category(categories[0]) if categories else None,
        }

    streams_data = _fetch_json(IPTV_ORG_STREAMS_URL)
    kept = 0
    for s in streams_data:
        cid = s.get("channel")
        if cid not in wanted_ids or not _is_playable_url(s.get("url")):
            continue
        fid = s.get("feed")
        label = feed_label.get((cid, fid))
        # canal de país lusófono sem info de feed → assume português
        if label is None and cid in lusophone_country_ids:
            label = "Português"
        # canal que entrou só por feed lusófono: descarta stream de feed que
        # não sabemos o idioma (evita servir um feed aleatório sem rótulo)
        if label is None:
            continue

        kept += 1
        meta = channel_meta.get(cid, {})
        yield ChannelEntry(
            tvg_id=cid,
            name=meta.get("name", cid),
            logo_url=meta.get("logo_url"),
            category=meta.get("category"),
            url=s["url"],
            source="iptv-org",
            feed_id=fid,
            lang_label=label,
        )
    logger.info("[iptv-org] streams em português: %d", kept)


def load_iptvcom() -> Iterable[ChannelEntry]:
    try:
        text = _fetch_text(IPTVCOM_M3U_URL)
    except requests.RequestException:
        logger.warning("[iptv-com] falha ao buscar brazil.m3u, pulando fonte", exc_info=True)
        return

    count = 0
    for attrs, name, url in _parse_m3u(text):
        if not _is_playable_url(url):
            continue
        # iptv-com usa "Xxx.br@SD" — normaliza cortando o "@..." pra casar com o
        # mesmo id do iptv-org (o projeto deles é baseado no iptv-org)
        tvg_id = attrs.get("tvg-id", "").split("@")[0]
        if not tvg_id:
            continue
        yield ChannelEntry(
            tvg_id=tvg_id,
            name=name,
            logo_url=attrs.get("tvg-logo"),
            category=_normalize_category(attrs.get("group-title")),
            url=url,
            source="iptv-com",
        )
        count += 1
    logger.info("[iptv-com] entradas processadas: %d", count)


def load_freetv() -> Iterable[ChannelEntry]:
    try:
        text = _fetch_text(FREETV_M3U_URL)
    except requests.RequestException:
        logger.warning("[free-tv] falha ao buscar playlist_brazil.m3u8, pulando fonte", exc_info=True)
        return

    count = 0
    for attrs, name, url in _parse_m3u(text):
        if not _is_playable_url(url):
            continue
        tvg_id = attrs.get("tvg-id", "")
        if not tvg_id:
            continue
        yield ChannelEntry(
            tvg_id=tvg_id,
            name=attrs.get("tvg-name") or name,
            logo_url=attrs.get("tvg-logo"),
            category=None,  # group-title do Free-TV é só "Brazil", sem valor de categoria
            url=url,
            source="free-tv",
        )
        count += 1
    logger.info("[free-tv] entradas processadas: %d", count)


def load_fta_brasil() -> Iterable[ChannelEntry]:
    try:
        text = _fetch_text_latin1(FTA_BRASIL_M3U_URL)
    except requests.RequestException:
        logger.warning("[fta-brasil] falha ao buscar playlist.m3u8, pulando fonte", exc_info=True)
        return

    count = 0
    for attrs, name, url in _parse_m3u(text):
        if not _is_playable_url(url):
            continue
        # tvg-id dessa fonte não é confiável (49/101 entradas vazias no momento da
        # verificação, e o restante usa convenção própria incompatível com o
        # iptv-org, ex: "CNTBahia.br(m3u4u)") — não tenta cruzar por id, gera um id
        # sintético com namespace próprio pra nunca mesclar errado com outra fonte
        channel_name = attrs.get("tvg-name") or name
        synthetic_id = f"fta:{_slugify(channel_name)}"
        yield ChannelEntry(
            tvg_id=synthetic_id,
            name=channel_name,
            logo_url=attrs.get("tvg-logo") or None,
            category=_FTA_CATEGORY_MAP.get((attrs.get("group-title") or "").strip().lower()),
            url=url,
            source="fta-brasil",
        )
        count += 1
    logger.info("[fta-brasil] entradas processadas: %d", count)


def is_broadcast_tv(name: str) -> bool:
    name_lower = name.lower()
    return any(pattern.search(name_lower) for pattern in _BROADCAST_TV_PATTERNS)


_BROADCAST_TV_PATTERNS = [re.compile(r"\b" + re.escape(hint) + r"\b") for hint in BROADCAST_TV_NAME_HINTS]

# ordem = prioridade: iptv-org primeiro (metadados mais completos e confiáveis),
# depois as fontes complementares só pra somar mirrors/canais novos. fta-brasil vai
# por último e nunca mescla com as outras (id sintético namespaced, ver load_fta_brasil)
ALL_SOURCES = [load_iptv_org, load_iptvcom, load_freetv, load_fta_brasil]
