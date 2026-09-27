-- 008_topilgan_hujjatlar: Lex.uz qidiruvi orqali topilgan amaldagi hujjatlar (eski farmon/qarorlar,
-- faoliyat yuritish tartiblari, imtiyozlar). RSS faqat yangi hujjatlarni beradi — bu jadval eskilarini qamraydi.
-- Har bir hujjat bir marta (lex_id bo'yicha UPSERT); `queries` — uni topgan qidiruvlar.
-- Import kunlik limit bilan bosqichma-bosqich; import qilinganlari haftalik yangilashda kuzatiladi.
CREATE TABLE topilgan_hujjatlar (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lex_id            text        NOT NULL UNIQUE CHECK (lex_id ~ '^-?[0-9]+$'),
    title             text        NOT NULL,
    doc_type          text,
    number            text,
    reg_number        text,
    adoption_date     date,
    url               text        NOT NULL CHECK (url LIKE 'https://lex.uz/docs/%'),
    site_status       text,       -- qidiruv sahifasidagi belgi ("y", "r"); yakuniy holat kartochkadan
    queries           text[]      NOT NULL DEFAULT '{}',
    keyword_hits      text[]      NOT NULL DEFAULT '{}',
    relevant          boolean     NOT NULL DEFAULT false,
    imported          boolean     NOT NULL DEFAULT false,
    import_attempts   integer     NOT NULL DEFAULT 0,
    last_error        text,
    last_seen         timestamptz NOT NULL DEFAULT now(),
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX topilgan_hujjatlar_pending_idx ON topilgan_hujjatlar (adoption_date DESC NULLS LAST)
    WHERE relevant AND NOT imported;
CREATE TRIGGER topilgan_hujjatlar_updated_at BEFORE UPDATE ON topilgan_hujjatlar
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE topilgan_hujjatlar ENABLE ROW LEVEL SECURITY;
