-- 001_init: asosiy sxema (spec 5-bo'lim).
--
-- Spec'dan farqlar (sabablari PROGRESS.md da):
--   * `o'zgarishlar` → `ozgarishlar` (apostrofli jadval nomi SQL'da doim qo'shtirnoq talab qiladi).
--   * hujjat_versiyalari.version_token — Lex.uz faqat ro'yxatdagi versiya sanasini qabul qiladi
--     ("27.07.2026", "12.12.2026 01"), shuning uchun token alohida saqlanadi.
--   * versiya_elementlari — tarixiy versiya matni (javobda iqtibos keltirish uchun kerak;
--     elementlar jadvalidagi UNIQUE (element_id, document_id) bitta versiyaga mo'ljallangan).
--   * elementlar: kind, text_hash, future_version; bilimlar: record_key, search_vector qo'shildi.
--   * Barcha jadvallarda RLS yoqilgan: Supabase anon/authenticated API orqali o'qiy olmaydi,
--     backend (postgres / service role) RLS'ni chetlab o'tadi.

CREATE EXTENSION IF NOT EXISTS pg_trgm;

CREATE OR REPLACE FUNCTION set_updated_at() RETURNS trigger
LANGUAGE plpgsql AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

-- ---------------------------------------------------------------------------
-- hujjatlar
-- ---------------------------------------------------------------------------
CREATE TABLE hujjatlar (
    id                    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lex_id                text        NOT NULL UNIQUE CHECK (lex_id ~ '^-?[0-9]+$'),
    name                  text        NOT NULL,
    type                  text,
    number                text,
    adoption_date         date,
    effective_date        date,
    status                text        NOT NULL DEFAULT 'noma''lum'
                          CHECK (status IN ('amalda', 'kuchga_kirmagan', 'kuchini_yoqotgan', 'noma''lum')),
    status_raw            text,       -- kartochkadagi asl qiymat ("Действующий", "Amalda", ...)
    status_checked_at     timestamptz,
    current_version       text,       -- Lex.uz versiya tokeni, masalan "06.08.2026"
    url                   text        NOT NULL,
    source_url            text,
    last_loaded           timestamptz,
    last_successful_load  timestamptz,
    content_hash          text,
    text_available        boolean     NOT NULL DEFAULT false,
    repeal_date           date,
    created_at            timestamptz NOT NULL DEFAULT now(),
    updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX hujjatlar_status_idx ON hujjatlar (status);
CREATE INDEX hujjatlar_effective_date_idx ON hujjatlar (effective_date) WHERE status = 'kuchga_kirmagan';
CREATE TRIGGER hujjatlar_updated_at BEFORE UPDATE ON hujjatlar
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- hujjat_versiyalari
-- ---------------------------------------------------------------------------
CREATE TABLE hujjat_versiyalari (
    id             bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id    bigint      NOT NULL REFERENCES hujjatlar (id) ON DELETE CASCADE,
    version_token  text        NOT NULL CHECK (version_token ~ '^[0-9]{2}\.[0-9]{2}\.[0-9]{4}( [0-9]{2})?$'),
    on_date        date        NOT NULL,
    text_hash      text,
    loaded_at      timestamptz,
    source_url     text        NOT NULL,
    created_at     timestamptz NOT NULL DEFAULT now(),
    UNIQUE (document_id, version_token)
);

CREATE INDEX hujjat_versiyalari_lookup_idx ON hujjat_versiyalari (document_id, on_date DESC);

-- ---------------------------------------------------------------------------
-- elementlar (joriy versiya)
-- ---------------------------------------------------------------------------
CREATE TABLE elementlar (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    element_id         text        NOT NULL CHECK (element_id ~ '^(-?[0-9]+|edi-?[0-9]+)$'),
    document_id        bigint      NOT NULL REFERENCES hujjatlar (id) ON DELETE CASCADE,
    parent_element_id  text,
    order_no           integer     NOT NULL CHECK (order_no > 0),
    type               text        NOT NULL,  -- Lex.uz klassi: CLAUSE_DEFAULT, ACT_TEXT, COMMENT, ...
    kind               text        NOT NULL,  -- lexuz.KIND_*: article, text, table, amendment, ...
    bob                text,
    modda              text,
    modda_raqami       text,
    text               text        NOT NULL,
    text_hash          text        NOT NULL,
    amendment_note     text,
    future_version     text,
    link               text        NOT NULL CHECK (link LIKE 'https://lex.uz/docs/%#%'),
    element_path       text        NOT NULL DEFAULT '',
    search_vector      tsvector GENERATED ALWAYS AS (
                           setweight(to_tsvector('simple', coalesce(modda, '')), 'A') ||
                           setweight(to_tsvector('simple', text), 'B')
                       ) STORED,
    created_at         timestamptz NOT NULL DEFAULT now(),
    updated_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (element_id, document_id)
);

CREATE INDEX elementlar_search_idx ON elementlar USING gin (search_vector);
CREATE INDEX elementlar_text_trgm_idx ON elementlar USING gin (text gin_trgm_ops);
CREATE INDEX elementlar_article_idx ON elementlar (document_id, modda_raqami);
CREATE INDEX elementlar_order_idx ON elementlar (document_id, order_no);
CREATE TRIGGER elementlar_updated_at BEFORE UPDATE ON elementlar
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- versiya_elementlari (tarixiy versiyalar matni)
-- ---------------------------------------------------------------------------
CREATE TABLE versiya_elementlari (
    id                 bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    version_id         bigint      NOT NULL REFERENCES hujjat_versiyalari (id) ON DELETE CASCADE,
    element_id         text        NOT NULL CHECK (element_id ~ '^(-?[0-9]+|edi-?[0-9]+)$'),
    parent_element_id  text,
    order_no           integer     NOT NULL CHECK (order_no > 0),
    type               text        NOT NULL,
    kind               text        NOT NULL,
    bob                text,
    modda              text,
    modda_raqami       text,
    text               text        NOT NULL,
    text_hash          text        NOT NULL,
    amendment_note     text,
    link               text        NOT NULL,  -- ?ONDATE=<token>#<element_id>
    element_path       text        NOT NULL DEFAULT '',
    search_vector      tsvector GENERATED ALWAYS AS (
                           setweight(to_tsvector('simple', coalesce(modda, '')), 'A') ||
                           setweight(to_tsvector('simple', text), 'B')
                       ) STORED,
    created_at         timestamptz NOT NULL DEFAULT now(),
    UNIQUE (version_id, element_id)
);

CREATE INDEX versiya_elementlari_search_idx ON versiya_elementlari USING gin (search_vector);
CREATE INDEX versiya_elementlari_article_idx ON versiya_elementlari (version_id, modda_raqami);

-- ---------------------------------------------------------------------------
-- bilimlar (ichki bilim — Lex.uz o'rnini bosmaydi)
-- ---------------------------------------------------------------------------
CREATE TABLE bilimlar (
    id                  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    record_key          text        NOT NULL UNIQUE,  -- deterministik: "<fayl>#<bo'lim>"
    topic               text        NOT NULL,
    text                text        NOT NULL,
    source              text        NOT NULL,
    source_url          text,
    checked_date        date,
    expiry_type         text,
    lex_check_required  boolean     NOT NULL DEFAULT true,
    search_vector       tsvector GENERATED ALWAYS AS (
                            setweight(to_tsvector('simple', topic), 'A') ||
                            setweight(to_tsvector('simple', text), 'B')
                        ) STORED,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX bilimlar_search_idx ON bilimlar USING gin (search_vector);
CREATE TRIGGER bilimlar_updated_at BEFORE UPDATE ON bilimlar
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- foydalanuvchilar
-- ---------------------------------------------------------------------------
CREATE TABLE foydalanuvchilar (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_id  bigint      NOT NULL UNIQUE,
    profile      jsonb       NOT NULL DEFAULT '{}'::jsonb,
    language     text        NOT NULL DEFAULT 'uz',
    daily_limit  integer     CHECK (daily_limit IS NULL OR daily_limit >= 0),  -- NULL → DAILY_QUESTION_LIMIT
    active       boolean     NOT NULL DEFAULT true,
    created_at   timestamptz NOT NULL DEFAULT now(),
    updated_at   timestamptz NOT NULL DEFAULT now()
);

CREATE TRIGGER foydalanuvchilar_updated_at BEFORE UPDATE ON foydalanuvchilar
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

-- ---------------------------------------------------------------------------
-- suhbatlar (audit va monitoring)
-- ---------------------------------------------------------------------------
CREATE TABLE suhbatlar (
    id                       bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    request_id               uuid        NOT NULL UNIQUE,
    telegram_id              bigint      NOT NULL,
    question                 text        NOT NULL,
    search_queries           jsonb       NOT NULL DEFAULT '[]'::jsonb,
    retrieved_element_ids    bigint[]    NOT NULL DEFAULT '{}',
    retrieved_knowledge_ids  bigint[]    NOT NULL DEFAULT '{}',
    answer                   text,
    used_sources             jsonb       NOT NULL DEFAULT '[]'::jsonb,
    extra_needed_queries     jsonb       NOT NULL DEFAULT '[]'::jsonb,
    model                    text,
    input_tokens             integer,
    output_tokens            integer,
    cache_read_tokens        integer,
    cache_creation_tokens    integer,
    estimated_cost           numeric(12, 6),
    processing_ms            integer,
    rating                   smallint,
    created_at               timestamptz NOT NULL DEFAULT now()
);

-- Kunlik limitni sanash uchun.
CREATE INDEX suhbatlar_user_day_idx ON suhbatlar (telegram_id, created_at);

-- ---------------------------------------------------------------------------
-- ozgarishlar (spec: o'zgarishlar)
-- ---------------------------------------------------------------------------
CREATE TABLE ozgarishlar (
    id           bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    document_id  bigint      NOT NULL REFERENCES hujjatlar (id) ON DELETE CASCADE,
    element_id   text        NOT NULL,
    old_hash     text,
    new_hash     text,
    old_text     text,
    new_text     text,
    change_type  text        NOT NULL CHECK (change_type IN ('qo''shilgan', 'o''zgargan', 'o''chirilgan')),
    detected_at  timestamptz NOT NULL DEFAULT now(),
    -- Collector qayta ishga tushsa bir xil o'zgarish ikki marta yozilmaydi.
    UNIQUE NULLS NOT DISTINCT (document_id, element_id, old_hash, new_hash),
    CHECK (
        (change_type = 'qo''shilgan'  AND old_hash IS NULL     AND new_hash IS NOT NULL) OR
        (change_type = 'o''chirilgan' AND old_hash IS NOT NULL AND new_hash IS NULL) OR
        (change_type = 'o''zgargan'   AND old_hash IS NOT NULL AND new_hash IS NOT NULL AND old_hash <> new_hash)
    )
);

CREATE INDEX ozgarishlar_detected_idx ON ozgarishlar (detected_at DESC);

-- ---------------------------------------------------------------------------
-- obunalar
-- ---------------------------------------------------------------------------
CREATE TABLE obunalar (
    id            bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    telegram_id   bigint      NOT NULL UNIQUE REFERENCES foydalanuvchilar (telegram_id) ON DELETE CASCADE,
    frequency     text        NOT NULL DEFAULT 'kunlik' CHECK (frequency IN ('kunlik', 'haftalik')),
    active        boolean     NOT NULL DEFAULT true,
    last_sent_at  timestamptz,
    created_at    timestamptz NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- RLS: Supabase public API orqali to'g'ridan-to'g'ri kirishni yopish (policy yo'q = hamma rad etiladi).
-- ---------------------------------------------------------------------------
ALTER TABLE hujjatlar           ENABLE ROW LEVEL SECURITY;
ALTER TABLE hujjat_versiyalari  ENABLE ROW LEVEL SECURITY;
ALTER TABLE elementlar          ENABLE ROW LEVEL SECURITY;
ALTER TABLE versiya_elementlari ENABLE ROW LEVEL SECURITY;
ALTER TABLE bilimlar            ENABLE ROW LEVEL SECURITY;
ALTER TABLE foydalanuvchilar    ENABLE ROW LEVEL SECURITY;
ALTER TABLE suhbatlar           ENABLE ROW LEVEL SECURITY;
ALTER TABLE ozgarishlar         ENABLE ROW LEVEL SECURITY;
ALTER TABLE obunalar            ENABLE ROW LEVEL SECURITY;
