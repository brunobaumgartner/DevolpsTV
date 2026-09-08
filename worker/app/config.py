import os

DATABASE_URL = os.environ["DATABASE_URL"]

# URLs das fontes de dados e a lógica de fetch/parse ficam em sources.py

# Intervalos dos jobs (minutos)
FETCH_CHANNELS_INTERVAL_MIN = 360  # 6h
HEALTHCHECK_INTERVAL_MIN = 15
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
