import logging
import time

from sqlalchemy.exc import OperationalError

from .db import Base, engine
from .models import Channel, Stream  # noqa: F401 (garante que os models sejam registrados)
from .scheduler import run_forever

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
logger = logging.getLogger("iptv-worker")


def _wait_for_db(max_attempts: int = 20, delay_sec: int = 3):
    for attempt in range(1, max_attempts + 1):
        try:
            Base.metadata.create_all(bind=engine)
            return
        except OperationalError:
            logger.warning("MySQL ainda não disponível (tentativa %d/%d)...", attempt, max_attempts)
            time.sleep(delay_sec)
    raise RuntimeError("Não foi possível conectar ao MySQL a tempo.")


if __name__ == "__main__":
    _wait_for_db()
    run_forever()
