"""Popula `Channel.language` a partir dos dados ORIGINAIS de importação.

Por que via CSV e não via `name`/`category` do banco: os scripts anteriores
desta sessão (`clean_channel_name_prefix.py`, `normalize_channel_categories.py`)
já removeram o prefixo de país do nome e trocaram a categoria original (país/
fonte) por um slug de gênero de conteúdo ("news", "sports"...) -- a informação
de idioma foi destruída do banco antes de existir essa coluna. Os CSVs fonte
em `data/bulk_import/m3u8_results_v2_part*.csv` (colunas
`tvg_id,name,category,logo_url,is_broadcast_tv,stream_url`) continuam
intactos e `tvg_id` é a chave estável pra recuperar o nome/categoria
ORIGINAIS de cada canal e daí inferir o idioma.

Estratégia de detecção (nessa ordem, primeira que bater vence):
1. Prefixo de país no NOME original -- "[PT] GLOBO HD", "TR: NBA TV" (mesma
   lista de códigos de `clean_channel_name_prefix._KNOWN_PREFIXES`, mapeada
   pra idioma).
2. Palavra-chave de país/idioma na CATEGORIA original -- "RU: Russia",
   "PORTUGUESE", "TR | beIN SPORTS", "United States" etc.
3. Heurística de alfabeto: categoria com caractere han (chinês) -> zh;
   categoria com diacrítico vietnamita -> vi. Cobre categorias que são só
   nome de app/jogo em chinês/vietnamita e não citam país por extenso.

Canal sem nenhum sinal fica com `language = NULL` -- melhor não adivinhar do
que unificar errado (mesmo princípio usado na consolidação de duplicados)."""

import csv
import glob
import re
import sys
import unicodedata

from .clean_channel_name_prefix import _PREFIX_RE
from .db import SessionLocal
from .models import Channel

_CSV_GLOB = "/app/data/bulk_import/m3u8_results_v2_part*.csv"
_COMMIT_EVERY = 2000

# código de prefixo -> idioma (ISO-639-1 curto, o que o front vai mostrar num
# <select>). Alguns códigos da lista de prefixos são ambíguos/regionais sem
# idioma único (ex: "YES"/"PPV"/"VIP"/"DS"/"ULTHD" são marca/qualidade, não
# país) -- ficam de fora de propósito.
_PREFIX_LANG = {
    "TR": "tr", "AR": "ar", "ALB": "sq", "DE": "de", "AF": "fa", "AL": "sq",
    "RUS": "ru", "FR": "fr", "RO": "ro", "IT": "it", "BR": "pt", "UK": "en",
    "GR": "el", "NL": "nl", "PL": "pl", "ES": "es", "USA": "en", "HU": "hu",
    "UA": "uk", "IN": "hi", "BG": "bg", "CZ": "cs", "RU": "ru", "KURD": "ku",
    "CZE": "cs", "DK": "da", "SLO": "sl", "CA": "en", "ARG": "es", "FI": "fi",
    "AT": "de", "MKD": "mk", "KRD": "ku", "BE": "nl", "NO": "no", "KR": "ko",
    "PT": "pt", "MK": "mk", "AFG": "fa", "TN": "ar", "ALG": "ar", "SP": "es",
    "MA": "ar", "AZ": "az", "PK": "ur", "MEX": "es", "NZ": "en", "DOM": "es",
    "IR": "fa", "MX": "es", "IL": "he", "CN": "zh", "COL": "es", "JP": "ja",
    "EC": "es", "VN": "vi", "KOR": "ko", "CL": "es", "TH": "th", "AU": "en",
    "PH": "tl", "PY": "es", "PE": "es", "CR": "es", "PR": "es", "CU": "es",
    "CUR": "es", "HND": "es", "US": "en", "VE": "es", "UY": "es",
    "LATINO": "es", "SC": "en", "SWISS": "de", "BD": "bn",
}

# substring (já em maiúsculas, sem acento) da CATEGORIA original -> idioma.
# Checado como substring, então "RUSSIAN", "RUSSIA" e "RU: RUSSIA" batem
# todos numa entrada só. Ordem não importa (usa a primeira substring que
# aparecer no texto).
_KEYWORD_LANG = {
    "BRAZIL": "pt", "PORTUGUESE": "pt", "PORTUGAL": "pt",
    "SPANISH": "es", "ESPANOL": "es", "ESPANA": "es", "SPAIN": "es",
    "MEXICO": "es", "ARGENTINA": "es", "COLOMBIA": "es", "PERU": "es",
    "CHILE": "es", "VENEZUELA": "es", "ECUADOR": "es", "BOLIVIA": "es",
    "HONDURAS": "es", "COSTA RICA": "es", "EL SALVADOR": "es",
    "DOMINICAN REPUBLIC": "es", "URUGUAY": "es", "LATINO": "es",
    "GUATEMALA": "es", "PARAGUAY": "es", "NICARAGUA": "es", "PANAMA": "es",
    "ITALIAN": "it", "ITALY": "it", "ITALIA": "it",
    "FRANCE": "fr", "FRENCH": "fr", "FRANCAISE": "fr",
    "GERMANY": "de", "GERMAN": "de", "DE-": "de", "AUSTRIA": "de",
    "TURKEY": "tr", "TURKCE": "tr", "TURK": "tr",
    "GREECE": "el", "GREEK": "el",
    "POLAND": "pl", "POLSKA": "pl",
    "ROMANIA": "ro", "ROMANYA": "ro", "ROMANIAN": "ro",
    "BULGARIA": "bg",
    "HUNGARY": "hu",
    "NETHERLANDS": "nl", "HOLLANDA": "nl", "DUTCH": "nl",
    "DENMARK": "da", "DANIMARKA": "da", "DENEMARK": "da",
    "NORWAY": "no", "NORVEC": "no",
    "SWEDEN": "sv", "ISVEC": "sv", "ISVICRE": "de",
    "FINLAND": "fi",
    "CZECH": "cs", "CZECHIA": "cs",
    "SLOVAKIA": "sk", "SLOVOKYA": "sk",
    "SLOVENIA": "sl",
    "CROATIA": "hr", "KROATIEN": "hr",
    "SERBIA": "sr",
    "ALBANIA": "sq", "ARNAVUTLUK": "sq",
    "ARABIC": "ar", "ARAB": "ar", "EGYPT": "ar", "IRAQ": "ar",
    "SAUDI ARABIA": "ar", "UAE": "ar", "JORDAN": "ar", "KUWAIT": "ar",
    "QATAR": "ar", "LEBANON": "ar", "SYRIA": "ar", "PALESTINE": "ar",
    "YEMEN": "ar", "LIBYA": "ar", "SUDAN": "ar", "TUNISIA": "ar",
    "ALGERIA": "ar", "MORROCO": "ar", "MOROCCO": "ar", "KSA": "ar",
    "ISRAEL": "he",
    "IRAN": "fa",
    "PAKISTAN": "ur",
    "INDIA": "hi", "INDIAN": "hi",
    "BANGLADESH": "bn",
    "CHINA": "zh", "TAIWAN": "zh", "HONG KONG": "zh",
    "KOREA": "ko",
    "JAPAN": "ja",
    "VIETNAM": "vi",
    "THAILAND": "th", "THAI": "th",
    "MALAYSIA": "ms",
    "INDONESIA": "id",
    "RUSSIA": "ru", "RUSSIAN": "ru",
    "UKRAINE": "uk",
    "KURDI": "ku", "KURDISTAN": "ku",
    "AZERBAIJAN": "az",
    "ARMENIA": "hy",
    "KAZAKHSTAN": "kk",
    "USA": "en", "UNITED STATES": "en", "UNITED KINGDOM": "en",
    "CANADIAN": "en", "CANADA": "en", "AUSTRALIA": "en",
}
# ordena por tamanho decrescente pra "SAUDI ARABIA" bater antes de nada
# menor que possa colidir por acidente
_KEYWORD_ITEMS = sorted(_KEYWORD_LANG.items(), key=lambda kv: -len(kv[0]))

_VIETNAMESE_CHARS = re.compile(r"[Ạ-ỹÐĐ]")
_HAN_CHARS = re.compile(r"[一-鿿]")


def _strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def detect_language(original_name: str, original_category: str | None) -> str | None:
    if original_name:
        m = _PREFIX_RE.match(original_name.strip())
        if m:
            code = re.sub(r"[\[\]:\|\s]", "", m.group(0)).upper()
            if code in _PREFIX_LANG:
                return _PREFIX_LANG[code]

    if original_category:
        upper = _strip_accents(original_category).upper()
        for keyword, lang in _KEYWORD_ITEMS:
            if keyword in upper:
                return lang

    if original_category:
        if _HAN_CHARS.search(original_category):
            return "zh"
        if _VIETNAMESE_CHARS.search(original_category):
            return "vi"

    return None


def load_csv_originals(csv_glob: str = _CSV_GLOB) -> dict[str, tuple[str, str]]:
    """tvg_id -> (nome original, categoria original), lendo todos os CSVs."""
    originals: dict[str, tuple[str, str]] = {}
    files = sorted(glob.glob(csv_glob))
    for path in files:
        with open(path, newline="", encoding="utf-8", errors="replace") as f:
            for row in csv.DictReader(f):
                tvg_id = row.get("tvg_id")
                if tvg_id and tvg_id not in originals:
                    originals[tvg_id] = (row.get("name") or "", row.get("category") or "")
    return originals


def run(db=None, originals: dict[str, tuple[str, str]] | None = None) -> dict:
    owns_session = db is None
    db = db or SessionLocal()
    stats = {"canais_atualizados": 0, "sem_correspondencia_no_csv": 0, "idioma_nao_identificado": 0}
    try:
        if originals is None:
            print("lendo CSVs originais...", file=sys.stderr)
            originals = load_csv_originals()
            print(f"{len(originals)} tvg_id únicos carregados dos CSVs", file=sys.stderr)

        rows = db.query(Channel.id, Channel.tvg_id).all()
        total = len(rows)
        updates: dict[str, list[int]] = {}
        for i, (cid, tvg_id) in enumerate(rows, start=1):
            original = originals.get(tvg_id)
            if original is None:
                stats["sem_correspondencia_no_csv"] += 1
                continue
            lang = detect_language(original[0], original[1])
            if lang is None:
                stats["idioma_nao_identificado"] += 1
                continue
            updates.setdefault(lang, []).append(cid)

            if i % 5000 == 0:
                print(f"  ... {i}/{total} canais avaliados", file=sys.stderr)

        for lang, ids in updates.items():
            for start in range(0, len(ids), _COMMIT_EVERY):
                chunk = ids[start:start + _COMMIT_EVERY]
                db.query(Channel).filter(Channel.id.in_(chunk)).update(
                    {Channel.language: lang}, synchronize_session=False
                )
                db.commit()
                stats["canais_atualizados"] += len(chunk)

        return stats
    finally:
        if owns_session:
            db.close()


if __name__ == "__main__":
    result = run()
    print("Recuperação de idioma dos canais concluída:")
    for k, v in result.items():
        print(f"  {k}: {v}")
