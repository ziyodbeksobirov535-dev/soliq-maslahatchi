#!/usr/bin/env bash
# Kunlik zaxira nusxa (Supabase Free'da avtomatik backup yo'q). cron: docs/DEPLOYMENT.md (7-qadam).
# Hujjatlar matnini Lex.uz'dan qayta yuklash mumkin; asosiy qiymat — foydalanuvchilar va suhbatlar.
set -euo pipefail
cd "$(dirname "$0")/.."
# .env ni `source` qilmaymiz (parolda &, $ kabi belgilar bo'lishi mumkin) — faqat kerakli qiymatlarni o'qiymiz.
envval() { grep -E "^$1=" .env | tail -n1 | cut -d= -f2- | sed -e 's/^"//' -e 's/"$//'; }
SUPABASE_DB_URL=$(envval SUPABASE_DB_URL)
: "${SUPABASE_DB_URL:?SUPABASE_DB_URL .env da topilmadi}"
DIR=/opt/soliq-backups
KEEP_DAYS=14
mkdir -p "$DIR"
FILE="$DIR/soliq-$(date +%Y%m%d-%H%M).dump"
pg_dump --format=custom --no-owner --no-privileges --schema=public "$SUPABASE_DB_URL" -f "$FILE"
find "$DIR" -name 'soliq-*.dump' -mtime +"$KEEP_DAYS" -delete
echo "backup ok: $FILE ($(du -h "$FILE" | cut -f1))"
