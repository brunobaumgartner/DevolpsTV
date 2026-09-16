import os

DATABASE_URL = os.environ["DATABASE_URL"]

# URLs das fontes de dados e a lógica de fetch/parse ficam em sources.py

# Intervalos dos jobs (minutos)
FETCH_CHANNELS_INTERVAL_MIN = 360  # 6h
# 1h (era 15min): medido em 2026-09-14, cada rodada leva ~4min testando 1049
# streams + 10 mil mirrors VOD — a cada 15min isso era mais de 25% do tempo
# com o MySQL sob carga, e os picos de CPU do servidor eram esse job. Em 1h
# cai pra ~7%. O catálogo VOD passa a levar ~2,5 dias por passada completa
# (578 mil mirrors / 10 mil por rodada), o que é aceitável: o teste de VOD
# feito daqui é majoritariamente INCONCLUSIVO mesmo (ver stream_validation),
# então o valor dele é achar link morto de verdade, não medir saúde real.
HEALTHCHECK_INTERVAL_MIN = 60
EPG_FETCH_INTERVAL_MIN = 180  # 3h — a fonte (BrazilTVEPG) atualiza ~5x/dia

# Timeout por stream testado no health-check (segundos)
HEALTHCHECK_TIMEOUT_SEC = 6
HEALTHCHECK_MAX_WORKERS = 15

# Nomes (substring, case-insensitive) usados pra marcar canais de TV aberta nacional.
# Lista curta e manual porque "TV aberta" não é uma categoria da API do iptv-org.
BROADCAST_TV_NAME_HINTS = [
    "globo",
    "sbt",
    "record",
    "band",
    "redetv",
    "rede tv",
    "tv brasil",
    "tv cultura",
]
