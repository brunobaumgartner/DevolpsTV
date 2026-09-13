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

    # via relacionamento (não db.add com item.id direto): funciona mesmo se o
    # item ainda nem foi flushado (id ainda None) — o SQLAlchemy resolve a FK
    # sozinho no flush final, economizando uma ida ao banco por item novo.
    item.streams.append(VodStream(url=url))
    if item.stream_url is None:
        item.stream_url = url
    return True


def item_is_available(item: VodItem) -> bool:
    """Disponível = tem pelo menos 1 link cadastrado.

    Antes exigia "passou no health-check do servidor" — revertido em
    2026-09-13: o health-check roda do IP da VPS, e provedores que bloqueiam
    IP de datacenter (comum em fontes de IPTV pirata) fazem o teste do
    servidor dar falso-negativo sistemático, mesmo quando o link funciona
    perfeitamente pro navegador do usuário real (confirmado comparando a
    mesma URL da VPS vs de uma rede residencial). A validação de verdade
    agora acontece no navegador, na hora de tocar — ver rank_mirrors()."""
    return bool(item.streams) or item.stream_url is not None


def ranked_mirror_urls(item: VodItem, max_mirrors: int = 5) -> list[str]:
    """URLs dos mirrors do item, do melhor pro pior (ranking, não filtro —
    ver rank_mirrors()). Cai de volta pro `stream_url` legado só quando o item
    não tem NENHUMA linha em `vod_streams` ainda (dado importado antes dessa
    tabela existir) — se tem linhas mas todas saíram do ranking (suprimidas
    por falha reportada pelo navegador), o resultado certo é lista vazia, não
    o link legado por baixo do pano (senão a supressão do cliente não valeria
    nada)."""
    if not item.streams:
        return [item.stream_url] if item.stream_url else []
    return [s.url for s in rank_mirrors(item.streams)[:max_mirrors]]
