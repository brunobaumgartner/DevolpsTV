import os

DATABASE_URL = os.environ["DATABASE_URL"]

# TODO: mover para o próprio API_PORT via env quando formos além do teste local
FRONTEND_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "frontend")
