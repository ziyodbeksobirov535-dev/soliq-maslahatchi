#!/usr/bin/env bash
# Health check (cron har 10 daqiqada). Muammo bo'lsa adminga Telegram xabar yuboradi.
set -uo pipefail
cd "$(dirname "$0")/.."
# .env ni `source` qilmaymiz (parolda &, $ kabi belgilar bo'lishi mumkin) — faqat kerakli qiymatlarni o'qiymiz.
envval() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }
TELEGRAM_BOT_TOKEN=$(envval TELEGRAM_BOT_TOKEN)
ADMIN_TELEGRAM_IDS=$(envval ADMIN_TELEGRAM_IDS)
OUT=$(.venv/bin/python -m app.health --bot 2>&1) && exit 0
ADMIN=${ADMIN_TELEGRAM_IDS%%,*}
ADMIN=${ADMIN// /}
if [ -n "${TELEGRAM_BOT_TOKEN:-}" ] && [ -n "$ADMIN" ]; then
  curl -s -m 20 "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
       --data-urlencode "chat_id=${ADMIN}" --data-urlencode "text=⚠️ Soliq bot health check: ${OUT:0:3500}" >/dev/null
fi
echo "$OUT" >&2
exit 1
