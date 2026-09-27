-- 011_xabarlar: yangilik va o'zgarish xabarlari — admin tasdig'i bilan foydalanuvchilarga yuborish.
--
--   RSS / haftalik yangilash → xabar tayyorlanadi (holat 'kutilmoqda') → adminga ko'rinish [✅ Yuborish] [❌ Bekor]
--   → 'tasdiqlandi' → kunduzi (NEWS_SEND_START_HOUR..NEWS_SEND_END_HOUR) hamma foydalanuvchiga → 'yuborildi'.
--
-- - `kalit` — idempotentlik: 'yangilik:<lex_id>', 'ozgarish:<document_id>:<oxirgi ozgarishlar.id>'.
--   Job qayta ishga tushsa, bir xil xabar ikkinchi marta yaratilmaydi.
-- - `xabar_yuborishlar` — kimga yuborilgani (PK: xabar + foydalanuvchi). Bot yuborish o'rtasida qayta ishga
--   tushsa, hech kimga ikki marta ketmaydi.
-- - `foydalanuvchilar.bloklagan` — botni bloklagan foydalanuvchiga yuborilmaydi; u yana yozsa — false.
-- - `ozgarishlar.xabar_id` — qaysi o'zgarishlar xabarga kiritilgani (bir o'zgarish bir marta xabar bo'ladi).
-- Keyinchalik kanalga yuborish (hozir emas) — `xabar_yuborishlar.telegram_id` ga kanal chat_id'si yoziladi.

CREATE TABLE xabarlar (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    turi                text        NOT NULL CHECK (turi IN ('yangilik', 'ozgarish')),
    kalit               text        NOT NULL UNIQUE,
    lex_id              text        NOT NULL CHECK (lex_id ~ '^-?[0-9]+$'),
    matn                text        NOT NULL,                 -- tayyor Telegram HTML
    havola              text        NOT NULL CHECK (havola LIKE 'https://lex.uz/docs/%'),
    tugmalar            jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- [[matn, callback_data], ...] (modda tugmalari)
    usul                text        NOT NULL CHECK (usul IN ('llm', 'matndan')),
    holat               text        NOT NULL DEFAULT 'kutilmoqda'
                                    CHECK (holat IN ('kutilmoqda', 'tasdiqlandi', 'bekor', 'yuborildi')),
    admin_xabarlar      jsonb       NOT NULL DEFAULT '[]'::jsonb,  -- [[chat_id, message_id], ...] ko'rinishlar
    hal_qilgan          bigint,                               -- tasdiqlagan/bekor qilgan admin
    hal_qilingan_at     timestamptz,
    yuborish_boshlangan timestamptz,
    yuborildi_at        timestamptz,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX xabarlar_holat_idx ON xabarlar (holat, created_at);
CREATE TRIGGER xabarlar_updated_at BEFORE UPDATE ON xabarlar
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE xabarlar ENABLE ROW LEVEL SECURITY;

CREATE TABLE xabar_yuborishlar (
    xabar_id     bigint      NOT NULL REFERENCES xabarlar (id) ON DELETE CASCADE,
    telegram_id  bigint      NOT NULL,
    natija       text        NOT NULL CHECK (natija IN ('ok', 'bloklangan', 'xato')),
    sent_at      timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (xabar_id, telegram_id)
);
ALTER TABLE xabar_yuborishlar ENABLE ROW LEVEL SECURITY;

ALTER TABLE foydalanuvchilar ADD COLUMN bloklagan boolean NOT NULL DEFAULT false;

ALTER TABLE ozgarishlar ADD COLUMN xabar_id bigint REFERENCES xabarlar (id) ON DELETE SET NULL;
CREATE INDEX ozgarishlar_xabarsiz_idx ON ozgarishlar (document_id) WHERE xabar_id IS NULL;
