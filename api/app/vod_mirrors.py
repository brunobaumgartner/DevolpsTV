"""Gerencia os mirrors (`VodStream`) de um `VodItem` — mesmo papel que
`streams` tem pra canais ao vivo: mais de um link por filme/episódio, com
fallback automático se um deles parar de responder.

`VodItem.stream_url` continua existindo como cache do "melhor link atual"
(usado por quem ainda lê esse campo direto, ex: listagem admin, contagem de
disponibilidade) — mas a fonte de verdade pra ranking/fallback é sempre
`VodItem.streams`.
"""

from sqlalchemy.orm import Session

from .models import VodItem, VodStream
from .playlist_builder import rank_mirrors


def upsert_mirror(db: Session, item: VodItem, url: str | None) -> bool:
    """Garante que `url` existe como mirror do item (cria se for novo), sem
    nunca apagar mirrors antigos — o mesmo link trocado de fonte vira só mais
    uma opção de fallback, não substitui a anterior. Mantém
    `item.stream_url` preenchido com algum link disponível (nunca sobrescreve
    um valor já setado só porque veio um mirror adicional).

    Devolve True se um mirror NOVO foi criado (pra estatística de import)."""
    if not url:
        return False

    existing = next((s for s in item.streams if s.url == url), None)
    if existing is not None:
        return False

    db.add(VodStream(item_id=item.id, url=url))
    if item.stream_url is None:
        item.stream_url = url
    return True


def ranked_mirror_urls(item: VodItem, max_mirrors: int = 5) -> list[str]:
    """URLs dos mirrors saudáveis do item, do melhor pro pior. Cai de volta pro
    `stream_url` legado se o item ainda não tem nenhuma linha em `vod_streams`
    (dado importado antes dessa tabela existir e que o health-check ainda não
    migrou)."""
    ranked = rank_mirrors(item.streams)
    if ranked:
        return [s.url for s in ranked[:max_mirrors]]
    return [item.stream_url] if item.stream_url else []
