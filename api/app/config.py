import os

DATABASE_URL = os.environ["DATABASE_URL"]

# credenciais do painel de admin (cadastro de links VOD) — trocadas a cada
# subida a partir do .env, que é a fonte de verdade (ver ARQUITETURA.md secao 9)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

# TODO: mover para o próprio API_PORT via env quando formos além do teste local
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")

# dataset publico do IMDb (title.basics.tsv.gz + title.akas.tsv.gz), usado pra
# classificar genero por titulo real (nao por palavra-chave) — ver
# api/app/imdb_classifier.py. Baixado manualmente em datasets.imdbws.com, não
# versionado no git (são ~750MB juntos). Ausente = feature simplesmente
# aparece indisponível no dashboard, sem quebrar nada.
IMDB_DATA_DIR = os.environ.get("IMDB_DATA_DIR", "/app/data/imdb")
