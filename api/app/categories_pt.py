"""Rótulo em português pras categorias de canal (os slugs vêm do iptv-org em
inglês: animation, movies, news...). O slug continua sendo a chave interna
(filtro, agrupamento); isto é só pra tela."""

CATEGORY_LABELS = {
    "animation": "Animação",
    "auto": "Automóveis",
    "business": "Negócios",
    "classic": "Clássicos",
    "comedy": "Comédia",
    "cooking": "Culinária",
    "culture": "Cultura",
    "documentary": "Documentário",
    "education": "Educação",
    "entertainment": "Entretenimento",
    "family": "Família",
    "general": "Geral",
    "kids": "Infantil",
    "legislative": "Legislativo",
    "lifestyle": "Estilo de vida",
    "movies": "Filmes",
    "music": "Música",
    "news": "Notícias",
    "outdoor": "Ar livre",
    "public": "Público",
    "relax": "Relax",
    "religious": "Religioso",
    "science": "Ciência",
    "series": "Séries",
    "shop": "Compras",
    "sports": "Esportes",
    "travel": "Viagem",
    "weather": "Clima",
    "xxx": "Adulto",
    "outros": "Outros",
}


def category_label(slug):
    if not slug:
        return "Sem categoria"
    return CATEGORY_LABELS.get(slug, slug.capitalize())
