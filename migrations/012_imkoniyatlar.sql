-- 012_imkoniyatlar: kanalga joylash, obuna (tarif), soliq kalendari eslatmalari.
--
-- - `xabarlar.kanal_xabar_id` — tasdiqlangan xabar kanalga joylangan bo'lsa, kanal ichidagi message_id
--   (NEWS_CHANNEL; bir marta joylanadi, qayta ishga tushishda takrorlanmaydi).
-- - `obunalar` — pullik obuna: tarif ('premium'), amal qilish muddati, to'lov manbai (admin / telegram to'lovi).
--   Obunasi bo'lmagan foydalanuvchi — bepul tarif (DAILY_QUESTION_LIMIT).
-- - `tolovlar` — Telegram Payments to'lovlari (charge id bo'yicha takrorlanmaydi).
-- - `foydalanuvchilar.eslatma` — soliq kalendari eslatmalariga rozilik; `eslatmalar_yuborilgan` — bir muddat
--   bo'yicha bir foydalanuvchiga bir marta.

ALTER TABLE xabarlar ADD COLUMN kanal_xabar_id bigint;

ALTER TABLE foydalanuvchilar ADD COLUMN eslatma boolean NOT NULL DEFAULT false;

CREATE TABLE eslatmalar_yuborilgan (
    telegram_id  bigint      NOT NULL,
    kalit        text        NOT NULL,   -- app/services/kalendar.py DEADLINES kaliti
    muddat       date        NOT NULL,
    qolgan_kun   integer     NOT NULL,
    sent_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (telegram_id, kalit, muddat, qolgan_kun)
);
ALTER TABLE eslatmalar_yuborilgan ENABLE ROW LEVEL SECURITY;
