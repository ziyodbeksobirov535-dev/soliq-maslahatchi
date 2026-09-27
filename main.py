"""Kirish nuqtasi: Telegram botni ishga tushiradi.

    python main.py            # bot (TELEGRAM_BOT_TOKEN, SUPABASE_DB_URL kerak; ANTHROPIC_* bo'lmasa faqat /modda)
    python main.py --check    # faqat sozlama va logging tekshiruvi
"""

import argparse
import asyncio
import logging

from app.config import get_settings
from app.utils.logging import request_context, setup_logging


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="faqat sozlamalarni tekshirish")
    args = parser.parse_args()

    settings = get_settings()
    setup_logging(settings.log_level, settings.secret_values())
    if args.check:
        with request_context():
            logging.getLogger("main").info("Sozlamalar yuklandi (timezone=%s)", settings.timezone)
        return

    from app.bot.app import run_bot

    asyncio.run(run_bot(settings))


if __name__ == "__main__":
    main()
