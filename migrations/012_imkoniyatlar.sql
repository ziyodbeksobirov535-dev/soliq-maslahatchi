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

-- Obuna: `obunalar` (001) — har foydalanuvchiga bitta qator; tarif va amal qilish muddati qo'shiladi.
ALTER TABLE obunalar ADD COLUMN tarif text NOT NULL DEFAULT 'premium' CHECK (tarif IN ('premium'));
ALTER TABLE obunalar ADD COLUMN tugash_at timestamptz;
ALTER TABLE obunalar ADD COLUMN manba text CHECK (manba IN ('admin', 'telegram'));

CREATE TABLE tolovlar (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_id         bigint      NOT NULL,
    summa               bigint      NOT NULL CHECK (summa > 0),   -- eng kichik birlikda (tiyin)
    valyuta             text        NOT NULL,
    kun                 integer     NOT NULL CHECK (kun > 0),
    telegram_charge_id  text        NOT NULL UNIQUE,              -- takroriy xabar ikki marta hisoblanmaydi
    provider_charge_id  text,
    created_at          timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE tolovlar ENABLE ROW LEVEL SECURITY;
