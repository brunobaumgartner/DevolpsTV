from datetime import datetime, timedelta, timezone

from sqlalchemy import or_
from sqlalchemy.orm import Session, joinedload

from .models import Channel, Stream, VodItem, VodStream, VodTitle

# mesmo valor de vod.py:ADULT_GENRE / GENRE_NONE -- não importa de lá pra
# evitar acoplar este módulo (usado também pela TV ao vivo) ao router de VOD
_ADULT_GENRE = "Adulto"
_GENRE_NONE = "Outros"

# por quanto tempo um "falhou de verdade no navegador" reportado pelo cliente
# continua suprimindo o stream da lista, mesmo que o health-check do worker
# ache ele saudável. Depois desse prazo, volta a ser oferecido normalmente —
# dá chance de se recuperar sem precisar de intervenção manual.
CLIENT_FAILURE_SUPPRESS_MINUTES = 30


def _is_client_suppressed(stream) -> bool:
    """Genérico: vale tanto pra `Stream` (canal) quanto `VodStream` (filme/
    episódio) — os dois têm os mesmos campos `client_failed_at`."""
    if stream.client_failed_at is None:
        return False
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=CLIENT_FAILURE_SUPPRESS_MINUTES)
    failed_at = stream.client_failed_at
    if failed_at.tzinfo is None:
        failed_at = failed_at.replace(tzinfo=timezone.utc)
    return failed_at > cutoff


def rank_mirrors(candidates):
    """Ordena uma lista de mirrors (objetos com `is_healthy`,
    `consecutive_failures`, `last_checked_at`, `client_failed_at` — `Stream`
    ou `VodStream`) do melhor pro pior. Genérico pra ser reaproveitado pelo
    VOD (`vod_mirrors.py`) sem duplicar a regra de ranking já usada pelos
    canais ao vivo.

    IMPORTANTE (mudança de 2026-09-13): `is_healthy` NÃO é mais filtro de
    exclusão, só critério de ORDEM. Achado real: o health-check roda do IP
    da VPS, e vários provedores de IPTV bloqueiam especificamente IP de
    datacenter — redirecionam pra conteúdo de verdade só quando quem pede é
    um IP residencial (confirmado comparando a mesma URL da VPS vs de uma
    rede doméstica: a VPS recebia uma página de erro disfarçada, a rede
    doméstica pegava o vídeo real). Ou seja, o teste do servidor tem
    falso-negativo sistemático — se ele virasse filtro, esconderia conteúdo
    que funciona perfeitamente pro usuário de verdade. A única exclusão que
    resta é `client_failed_at`: reportado pelo NAVEGADOR de um usuário real
    tentando tocar, esse sim reflete o que importa."""
    usable = [s for s in candidates if not _is_client_suppressed(s)]
    if not usable:
        return []

    def health_rank(s):
        # só PREMIA o que o servidor confirmou funcionar; NÃO penaliza o que
        # ele disse que não funciona. Achado em 2026-09-13: o health-check
        # marcou 88% dos mirrors de canal e 582 mil de VOD como "ruins"
        # (contra 88 confirmados bons no VOD inteiro) -- como ele roda do IP
        # da VPS e os provedores bloqueiam datacenter, esse "ruim" é falso
        # negativo em massa. Tratar False como "pior que nunca testado"
        # empurrava justamente os links bons pro fim da fila, atrás de
        # qualquer link novo não testado (que em geral é lixo de importação).
        return 0 if s.is_healthy is True else 1

    fallback = datetime(2000, 1, 1)
    usable.sort(
        key=lambda s: (
            health_rank(s),
            # falha REAL reportada pelo navegador de um usuário vale como
            # desempate (mesmo já tendo expirado a supressão); a contagem de
            # falhas do servidor não, pelo mesmo motivo acima
            s.client_failure_count,
            -(s.last_checked_at or fallback).timestamp(),
        )
    )
    return usable


def _ranked_streams(channel: Channel):
    """Todos os mirrors saudáveis de um canal (e sem reporte recente de falha real
    do navegador de um usuário), do melhor pro pior (menos falhas seguidas,
    checado mais recentemente primeiro)."""
    return rank_mirrors(channel.streams)


def _best_stream(channel: Channel):
    ranked = _ranked_streams(channel)
    return ranked[0] if ranked else None


def _active_channels(db: Session):
    # joinedload dos streams: sem isso cada canal disparava 1 SELECT lazy dos
    # próprios streams (N+1) — ~250 queries a mais por chamada de channels.json
    #
    # Filtro simplificado (2026-09-13): exige só ter algum stream cadastrado,
    # não mais "is_healthy=True" — ver o comentão em rank_mirrors() pro
    # motivo (falso-negativo do health-check rodando de IP de datacenter).
    # Quem realmente decide se aparece "tocável" é o rank_mirrors() na hora
    # do /resolve, que só exclui suprimido por falha real do navegador.
    return (
        db.query(Channel)
        .options(joinedload(Channel.streams))
        .filter(Channel.is_active.is_(True))
        .filter(Channel.streams.any())
        .order_by(Channel.category, Channel.name)
        .all()
    )


def active_channels_with_stream(db: Session):
    """Canais ativos que têm pelo menos 1 stream saudável, já com o melhor stream escolhido."""
    result = []
    for ch in _active_channels(db):
        stream = _best_stream(ch)
        if stream is not None:
            result.append((ch, stream))
    return result


def ranked_stream_urls(channel: Channel, max_mirrors: int = 5, lang: str | None = None) -> list[str]:
    """URLs dos mirrors saudáveis de um canal, do melhor pro pior — usado pra
    verificação ao vivo na hora que o usuário pede pra assistir. Se `lang` for
    passado, só os streams daquele idioma (rótulo)."""
    streams = _ranked_streams(channel)
    if lang is not None:
        streams = [s for s in streams if _stream_lang(s) == lang]
    return [s.url for s in streams[:max_mirrors]]


def _stream_lang(stream: Stream) -> str:
    """Rótulo de idioma do stream; NULL no banco = 'Português' (canal de país
    lusófono / fonte brasileira sem info de feed)."""
    return stream.lang_label or "Português"


# "Português" primeiro, "Legendado" logo depois, o resto em ordem alfabética
_LANG_ORDER = {"Português": 0, "Legendado": 1}


def ranked_streams_by_language(channel: Channel, max_mirrors: int = 3) -> list[dict]:
    """Agrupa os mirrors saudáveis do canal por idioma, cada grupo já ordenado
    do melhor mirror pro pior. Usado pro frontend listar os idiomas disponíveis
    e o usuário escolher qual tocar."""
    groups: dict[str, list[str]] = {}
    for s in _ranked_streams(channel):
        groups.setdefault(_stream_lang(s), []).append(s.url)
    ordered = sorted(groups.items(), key=lambda kv: (_LANG_ORDER.get(kv[0], 2), kv[0]))
    return [{"label": label, "stream_urls": urls[:max_mirrors]} for label, urls in ordered]


_VOD_CHUNK = 2000  # mesmo tamanho de lote do import_channels.py/import_vod.py


def _chunks(seq, size):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]


def _preload_vod_streams(db: Session, item_ids: list[int]) -> dict[int, list]:
    """1 SELECT por lote pra TODOS os mirrors de uma vez, em vez de joinedload
    da coleção (que multiplica a linha de cada VodItem por cada mirror dele —
    com 273k itens isso vira um produto cartesiano gigante e trava a query;
    achado real gerando o m3u8 em 2026-09-16). Mesmo padrão de
    _preload_streams em import_channels.py."""
    by_item: dict[int, list] = {}
    for chunk in _chunks(item_ids, _VOD_CHUNK):
        for s in db.query(VodStream).filter(VodStream.item_id.in_(chunk)).all():
            by_item.setdefault(s.item_id, []).append(s)
    return by_item


def _best_vod_url(item: VodItem, streams: list) -> str | None:
    """Mesma lógica de vod_mirrors.ranked_mirror_urls (melhor mirror, ou o
    stream_url legado se o item ainda não tem linha em vod_streams) — não
    importamos vod_mirrors aqui porque ele importa rank_mirrors DESTE
    arquivo, e um import circular quebraria os dois módulos."""
    if not streams:
        return item.stream_url
    ranked = rank_mirrors(streams)
    return ranked[0].url if ranked else None


# tamanho máximo de página mesmo se o chamador pedir mais -- nenhuma request
# de VOD pode varrer o catálogo inteiro (achado real 2026-09-16: sem limite,
# a m3u8 de VOD ficou com 265 mil entradas, 91MB e ~2min pra gerar, o que
# estoura timeout de proxy/CDN e trava a maioria dos players externos)
VOD_M3U_MAX_TITLES = 1000


def _vod_titles_page(
    db: Session,
    type: str | None = None,  # noqa: A002 - nome claro pro chamador
    genre: str | None = None,
    hide_adult: bool = True,
    limit: int = 300,
    offset: int = 0,
) -> list[VodTitle]:
    """Mesmo filtro de disponibilidade/gênero/adulto do GET /p/{token}/vod
    (routers/vod.py:list_vod), só que devolvendo os objetos `VodTitle` em vez
    de dict -- reaproveitado aqui pra montar a playlist M3U de VOD sempre
    escopada (nunca o catálogo inteiro de uma vez)."""
    base = db.query(VodTitle).filter(VodTitle.items.any(VodItem.stream_url.isnot(None)))
    if hide_adult:
        base = base.filter(or_(VodTitle.genre != _ADULT_GENRE, VodTitle.genre.is_(None)))
    if type in ("movie", "series"):
        base = base.filter(VodTitle.type == type)
    if genre == _GENRE_NONE:
        base = base.filter(VodTitle.genre.is_(None))
    elif genre:
        base = base.filter(VodTitle.genre == genre)

    limit = max(1, min(limit, VOD_M3U_MAX_TITLES))
    return base.order_by(VodTitle.title).offset(offset).limit(limit).all()


def _vod_m3u_lines(
    db: Session,
    type: str | None = None,  # noqa: A002 - nome claro pro chamador
    genre: str | None = None,
    hide_adult: bool = True,
    limit: int = 300,
    offset: int = 0,
):
    """Filme = 1 entrada em group-title "Filmes". Série = cada TÍTULO vira o
    próprio group-title (assim os episódios ficam agrupados como "categoria"
    dentro do player externo, igual painel Xtream costuma fazer).

    Sempre PAGINADO por título (`limit`/`offset`, tetado em
    VOD_M3U_MAX_TITLES) e opcionalmente filtrado por `type`/`genre` -- nunca
    monta o catálogo inteiro de uma vez (ver VOD_M3U_MAX_TITLES)."""
    titles = _vod_titles_page(db, type, genre, hide_adult, limit, offset)
    title_ids = [t.id for t in titles]
    if not title_ids:
        return

    items = (
        db.query(VodItem)
        .filter(VodItem.title_id.in_(title_ids))
        .order_by(VodItem.season_number, VodItem.episode_number)
        .all()
    )
    items_by_title: dict[int, list[VodItem]] = {}
    for it in items:
        items_by_title.setdefault(it.title_id, []).append(it)
    streams_by_item = _preload_vod_streams(db, [it.id for it in items])

    for title in titles:
        for item in items_by_title.get(title.id, []):
            url = _best_vod_url(item, streams_by_item.get(item.id, []))
            if not url:
                continue
            logo_attr = f' tvg-logo="{stream_escape(title.poster_url)}"' if title.poster_url else ""

            if title.type == "movie":
                group = "Filmes"
                name = f"{title.title} ({title.year})" if title.year else title.title
            else:
                group = title.title
                if item.season_number and item.episode_number:
                    ep_label = f"S{item.season_number:02d}E{item.episode_number:02d}"
                else:
                    ep_label = ""
                name = " ".join(p for p in (title.title, ep_label, item.episode_title) if p)

            yield f'#EXTINF:-1{logo_attr} group-title="{stream_escape(group)}",{stream_escape(name)}'
            yield url


def build_m3u(db: Session) -> str:
    """Só TV ao vivo -- o VOD tem playlist própria e paginada, ver
    build_vod_m3u (motivo: catálogo de VOD é grande demais pra caber numa
    única lista, ver VOD_M3U_MAX_TITLES)."""
    lines = ["#EXTM3U"]
    for channel, stream in active_channels_with_stream(db):
        group = channel.category or "outros"
        logo_attr = f' tvg-logo="{stream_escape(channel.logo_url)}"' if channel.logo_url else ""
        lines.append(
            f'#EXTINF:-1 tvg-id="{stream_escape(channel.tvg_id)}"{logo_attr} '
            f'group-title="{stream_escape(group)}",{stream_escape(channel.name)}'
        )
        if stream.referrer:
            lines.append(f"#EXTVLCOPT:http-referrer={stream.referrer}")
        if stream.user_agent:
            lines.append(f"#EXTVLCOPT:http-user-agent={stream.user_agent}")
        lines.append(stream.url)

    return "\n".join(lines) + "\n"


def build_vod_m3u(
    db: Session,
    type: str | None = None,  # noqa: A002 - nome claro pro chamador
    genre: str | None = None,
    hide_adult: bool = True,
    limit: int = 300,
    offset: int = 0,
) -> str:
    """Playlist M3U só de VOD, sempre filtrada/paginada (ver _vod_m3u_lines).
    Usada por um link separado do playlist.m3u8 principal."""
    lines = ["#EXTM3U"]
    lines.extend(_vod_m3u_lines(db, type=type, genre=genre, hide_adult=hide_adult, limit=limit, offset=offset))
    return "\n".join(lines) + "\n"


def stream_escape(value: str) -> str:
    """Escape simples para não quebrar os atributos do EXTINF."""
    if value is None:
        return ""
    return value.replace('"', "'")
