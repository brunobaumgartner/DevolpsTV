"""Ingestão de EPG (grade de programação) do BrazilTVEPG (limaalef/BrazilTVEPG),
atualizado 5x/dia. Cada arquivo XMLTV usa como `channel id` o NOME DE EXIBIÇÃO
do canal na operadora de origem (ex: "ESPN", "BAND HD"), não o tvg-id no padrão
iptv-org — então o cruzamento com nossa tabela `channels` é feito por
correspondência EXATA de nome normalizado (sem fuzzy match, pra não arriscar
mesclar programação no canal errado). Canais cujo nome não bate ficam de fora
— melhor não trazer EPG de um canal do que trazer errado.
"""

import logging
import re
import unicodedata
from datetime import datetime, timezone
from xml.etree import ElementTree as ET

import requests

logger = logging.getLogger("iptv-worker.epg_sources")

REQUEST_TIMEOUT = 60

# arquivos do BrazilTVEPG que fazem sentido pro nosso catálogo (canais BR).
# fora: globo-internacional.xml (público dos EUA, fora do nosso escopo) e
# maissbt.xml (serviço "ainda não lançou" segundo o próprio README da fonte,
# em 2026-09-08 — sem dado real pra trazer).
EPG_SOURCE_URLS = {
    "epg": "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/epg.xml",
    "globo": "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/globo.xml",
    "claro": "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/claro.xml",
    "vivoplay": "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/vivoplay.xml",
    "xsports": "https://raw.githubusercontent.com/limaalef/BrazilTVEPG/main/xsports.xml",
}

# sufixos técnicos comuns em nomes de operadora que não existem no nosso
# catálogo (que vem do iptv-org, sem qualificador de qualidade no nome).
# Curada pequena de propósito — só o que é claramente qualidade de sinal, não
# tentamos remover nada que possa fazer parte do nome de marca do canal.
_QUALITY_SUFFIXES = {"hd", "fhd", "uhd", "4k", "8k", "sd"}

# formato de data usado pelo XMLTV: "20260904211144 -0300"
_XMLTV_DATE_FORMAT = "%Y%m%d%H%M%S %z"


def normalize_channel_name(name: str) -> str:
    """Normalização usada NOS DOIS LADOS do cruzamento (nome do XMLTV e
    channels.name do nosso banco) — minúsculo, sem acento, sem sufixo de
    qualidade, espaços colapsados."""
    ascii_name = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    ascii_name = ascii_name.lower()
    ascii_name = re.sub(r"[^a-z0-9]+", " ", ascii_name).strip()
    tokens = [t for t in ascii_name.split(" ") if t and t not in _QUALITY_SUFFIXES]
    return " ".join(tokens)


def parse_xmltv_datetime(value: str) -> datetime | None:
    """Parseia e converte pra UTC. O XMLTV vem com offset local (ex: "-0300" pra
    Brasília) — se gravássemos os campos numéricos como vieram, sem converter,
    o banco ficaria com o horário local guardado como se fosse UTC (defasagem
    de até 3h em todo o cálculo de "o que está passando agora"). Todo o resto
    do sistema assume horários gravados em UTC (ver client_failed_at na API),
    então o EPG precisa seguir a mesma convenção."""
    try:
        dt = datetime.strptime(value, _XMLTV_DATE_FORMAT)
    except ValueError:
        return None
    return dt.astimezone(timezone.utc)


class ParsedProgramme:
    __slots__ = ("channel_name_raw", "title", "subtitle", "description", "category", "start", "end")

    def __init__(self, channel_name_raw, title, subtitle, description, category, start, end):
        self.channel_name_raw = channel_name_raw
        self.title = title
        self.subtitle = subtitle
        self.description = description
        self.category = category
        self.start = start
        self.end = end


def fetch_and_parse(source_name: str, url: str):
    """Baixa e faz streaming-parse (iterparse) do XMLTV — os arquivos passam de
    6MB cada, carregar a árvore inteira na memória de um container pequeno não
    é necessário nem desejável. Devolve (channel_names_vistos, lista_de_programas)."""
    try:
        resp = requests.get(url, timeout=REQUEST_TIMEOUT, stream=True)
        resp.raise_for_status()
        resp.raw.decode_content = True
    except requests.RequestException:
        logger.warning("[%s] falha ao baixar EPG, pulando fonte", source_name, exc_info=True)
        return set(), []

    channel_names = set()
    programmes = []

    try:
        for event, elem in ET.iterparse(resp.raw, events=("end",)):
            if elem.tag == "channel":
                display_name = elem.findtext("display-name")
                if display_name:
                    channel_names.add(display_name.strip())
                elem.clear()
            elif elem.tag == "programme":
                channel_attr = elem.get("channel")
                start = parse_xmltv_datetime(elem.get("start", ""))
                end = parse_xmltv_datetime(elem.get("stop", ""))
                title = elem.findtext("title")
                if channel_attr and start and end and title:
                    programmes.append(
                        ParsedProgramme(
                            channel_name_raw=channel_attr.strip(),
                            title=title.strip(),
                            subtitle=(elem.findtext("sub-title") or "").strip() or None,
                            description=(elem.findtext("desc") or "").strip() or None,
                            category=(elem.findtext("category") or "").strip() or None,
                            start=start,
                            end=end,
                        )
                    )
                elem.clear()
    except ET.ParseError:
        logger.warning("[%s] XML malformado/incompleto, aproveitando o que foi parseado até aqui", source_name)

    logger.info("[%s] %d canais no EPG, %d programas parseados", source_name, len(channel_names), len(programmes))
    return channel_names, programmes
