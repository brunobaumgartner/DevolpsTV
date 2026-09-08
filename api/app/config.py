import os

DATABASE_URL = os.environ["DATABASE_URL"]

# credenciais do painel de admin (cadastro de links VOD) — trocadas a cada
# subida a partir do .env, que é a fonte de verdade (ver ARQUITETURA.md secao 9)
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD")

# TODO: mover para o próprio API_PORT via env quando formos além do teste local
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
