"""Lista única de idiomas do catálogo (canal ao vivo e VOD).

Fonte de verdade pro dropdown do admin, pro filtro do site e pra validação da
coluna `language` — que é um código curto (ISO-639-1 quando existe). Ter a
lista num lugar só é o que impede "pt", "PT-BR" e "Português" virarem três
idiomas diferentes no filtro.

`aceita()` normaliza a entrada (texto livre do CSV, maiúscula/minúscula, nome
por extenso em português ou inglês) pro código canônico, ou devolve None
quando não reconhece — nesse caso o valor é recusado em vez de gravado torto.
"""

# código -> rótulo mostrado pro usuário (pt-BR)
LANGUAGES: dict[str, str] = {
    "pt": "Português",
    "en": "Inglês",
    "es": "Espanhol",
    "fr": "Francês",
    "de": "Alemão",
    "it": "Italiano",
    "tr": "Turco",
    "ru": "Russo",
    "ar": "Árabe",
    "zh": "Chinês",
    "vi": "Vietnamita",
    "ko": "Coreano",
    "ja": "Japonês",
    "el": "Grego",
    "pl": "Polonês",
    "ro": "Romeno",
    "bg": "Búlgaro",
    "hu": "Húngaro",
    "nl": "Holandês",
    "sv": "Sueco",
    "da": "Dinamarquês",
    "no": "Norueguês",
    "fi": "Finlandês",
    "cs": "Tcheco",
    "sk": "Eslovaco",
    "sl": "Esloveno",
    "hr": "Croata",
    "sr": "Sérvio",
    "sq": "Albanês",
    "he": "Hebraico",
    "fa": "Persa",
    "ur": "Urdu",
    "hi": "Hindi",
    "th": "Tailandês",
    "id": "Indonésio",
    "ms": "Malaio",
    "uk": "Ucraniano",
    "ku": "Curdo",
    "az": "Azeri",
    "hy": "Armênio",
    "kk": "Cazaque",
    "bn": "Bengali",
    "mk": "Macedônio",
    "tl": "Tagalo",
}

# rótulo do que é "não identificado" — usado como valor especial no filtro
# (mesma convenção de CATEGORY_NONE/GENRE_NONE), porque um <select> não
# consegue mandar NULL pela query string
NONE_LABEL = "Sem idioma identificado"

# nomes alternativos aceitos na entrada (CSV/admin), além do próprio código e
# do rótulo em português acima
_ALIASES: dict[str, str] = {
    "portugues": "pt", "português": "pt", "portuguese": "pt", "pt-br": "pt", "ptbr": "pt", "br": "pt",
    "ingles": "en", "inglês": "en", "english": "en", "en-us": "en", "us": "en", "uk": "en",
    "espanhol": "es", "español": "es", "espanol": "es", "spanish": "es",
    "frances": "fr", "francês": "fr", "french": "fr",
    "alemao": "de", "alemão": "de", "german": "de",
    "italiano": "it", "italian": "it",
    "turco": "tr", "turkish": "tr",
    "russo": "ru", "russian": "ru",
    "arabe": "ar", "árabe": "ar", "arabic": "ar",
    "chines": "zh", "chinês": "zh", "chinese": "zh", "mandarim": "zh",
    "vietnamita": "vi", "vietnamese": "vi",
    "coreano": "ko", "korean": "ko",
    "japones": "ja", "japonês": "ja", "japanese": "ja",
    "grego": "el", "greek": "el",
    "polones": "pl", "polonês": "pl", "polish": "pl",
    "romeno": "ro", "romanian": "ro",
    "bulgaro": "bg", "búlgaro": "bg", "bulgarian": "bg",
    "hungaro": "hu", "húngaro": "hu", "hungarian": "hu",
    "holandes": "nl", "holandês": "nl", "dutch": "nl",
    "sueco": "sv", "swedish": "sv",
    "dinamarques": "da", "dinamarquês": "da", "danish": "da",
    "norueges": "no", "norueguês": "no", "norwegian": "no",
    "finlandes": "fi", "finlandês": "fi", "finnish": "fi",
    "tcheco": "cs", "czech": "cs",
    "eslovaco": "sk", "slovak": "sk",
    "esloveno": "sl", "slovenian": "sl",
    "croata": "hr", "croatian": "hr",
    "servio": "sr", "sérvio": "sr", "serbian": "sr",
    "albanes": "sq", "albanês": "sq", "albanian": "sq",
    "hebraico": "he", "hebrew": "he",
    "persa": "fa", "persian": "fa", "farsi": "fa",
    "hindi": "hi",
    "tailandes": "th", "tailandês": "th", "thai": "th",
    "indonesio": "id", "indonésio": "id", "indonesian": "id",
    "malaio": "ms", "malay": "ms",
    "ucraniano": "uk", "ukrainian": "uk",
    "curdo": "ku", "kurdish": "ku",
    "azeri": "az",
    "armenio": "hy", "armênio": "hy", "armenian": "hy",
    "cazaque": "kk", "kazakh": "kk",
    "bengali": "bn",
    "macedonio": "mk", "macedônio": "mk", "macedonian": "mk",
    "tagalo": "tl", "tagalog": "tl",
}


def label(code: str | None) -> str:
    if code is None:
        return NONE_LABEL
    return LANGUAGES.get(code, code)


def aceita(value: str | None) -> str | None:
    """Normaliza pro código canônico. Devolve None pra vazio; levanta
    ValueError quando o valor não bate com nenhum idioma conhecido (melhor
    recusar do que gravar um idioma que o filtro nunca vai encontrar)."""
    if value is None:
        return None
    v = value.strip()
    if not v:
        return None
    low = v.lower()
    if low in LANGUAGES:
        return low
    if low in _ALIASES:
        return _ALIASES[low]
    for code, lbl in LANGUAGES.items():
        if lbl.lower() == low:
            return code
    raise ValueError(f"idioma desconhecido: {value!r}")


def options() -> list[dict]:
    """Pro dropdown do admin, em ordem alfabética de rótulo."""
    return [
        {"code": code, "label": lbl}
        for code, lbl in sorted(LANGUAGES.items(), key=lambda kv: kv[1])
    ]
