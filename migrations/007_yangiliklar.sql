-- 007_yangiliklar: Lex.uz RSS yangiliklari (spec 17: daily RSS, spec 20: /yangiliklar).
-- Har bir RSS elementi bir marta (lex_id bo'yicha UPSERT). relevant/summary — keyword filtri va
-- (bo'lsa) fast model tasnifi natijasi; summary faqat hujjat nomi/metadata/matnidan, faktlarga asoslangan.
CREATE TABLE yangiliklar (
    id                bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    lex_id            text        NOT NULL UNIQUE CHECK (lex_id ~ '^-?[0-9]+$'),
    title             text        NOT NULL,
    doc_type          text,
    number            text,
    adoption_date     date,
    effective_date    date,
    url               text        NOT NULL CHECK (url LIKE 'https://lex.uz/docs/%'),
    pub_date          timestamptz,
    keyword_hits      text[]      NOT NULL DEFAULT '{}',
    relevant          boolean     NOT NULL DEFAULT false,
    relevance_method  text        NOT NULL DEFAULT 'keyword' CHECK (relevance_method IN ('keyword', 'llm')),
    topics            text[]      NOT NULL DEFAULT '{}',
    summary           text,
    imported          boolean     NOT NULL DEFAULT false,
    created_at        timestamptz NOT NULL DEFAULT now(),
    updated_at        timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX yangiliklar_recent_idx ON yangiliklar (pub_date DESC) WHERE relevant;
CREATE TRIGGER yangiliklar_updated_at BEFORE UPDATE ON yangiliklar
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
ALTER TABLE yangiliklar ENABLE ROW LEVEL SECURITY;
