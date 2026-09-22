import logging
import logging_loki

from src.config import settings

logger = logging.getLogger("eng_bot")

def setup_logging() -> logging.Logger:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    if settings.loki_url:
        auth = None
        if settings.loki_user and settings.loki_password.get_secret_value():
            auth = (settings.loki_user, settings.loki_password.get_secret_value())

        loki_handler = logging_loki.LokiHandler(
            url=settings.loki_url,
            tags={"application": "eng-learning-bot", "environment": "production"},
            auth=auth,
            version="1",
        )
        logging.getLogger("").addHandler(loki_handler)
        logger.info("Grafana Loki interceptor active.")

    return logger
