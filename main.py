"""Kirish nuqtasi. PHASE 0: faqat sozlama va logging tekshiruvi; bot keyingi bosqichlarda."""

import logging

from app.config import get_settings
from app.utils.logging import request_context, setup_logging


def main() -> None:
    settings = get_settings()
    setup_logging(settings.log_level, settings.secret_values())
    with request_context():
        logging.getLogger("main").info(
            "Sozlamalar yuklandi (timezone=%s). Telegram bot hali qurilmagan — PHASE 5.",
            settings.timezone,
        )


if __name__ == "__main__":
    main()
