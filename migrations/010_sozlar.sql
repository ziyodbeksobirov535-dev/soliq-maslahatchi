-- 010_sozlar: imlo xatolariga chidamli qidiruv va "faqat manbalar" javobi.
--
-- `sozlar` — bazadagi matn so'zlari lug'ati (search_vector leksemalari, ts_stat). Savoldagi so'z lug'atda
-- yo'q bo'lsa ("satvkasi"), eng yaqin mavjud so'z ("stavkasi") trigram nomzodlari va tahrir masofasi bilan
-- tanlanadi (app/retrieval/spelling.py). ts_stat butun korpusda ~2 s (18 800 so'z) — shuning uchun lug'at
-- alohida jadval; import job'laridan keyin `yangila_sozlar()` bilan yangilanadi.
--
-- `suhbatlar.status`: 'sources_only' — Claude ishlamaganda (kalit yo'q, kredit tugagan, xato) foydalanuvchiga
-- topilgan moddalar ro'yxati beriladi.

CREATE TABLE sozlar (
    soz   text    PRIMARY KEY,
    ndoc  integer NOT NULL
);
CREATE INDEX sozlar_trgm_idx ON sozlar USING gin (soz extensions.gin_trgm_ops);
CREATE INDEX sozlar_prefix_idx ON sozlar (soz text_pattern_ops);
ALTER TABLE sozlar ENABLE ROW LEVEL SECURITY;

CREATE OR REPLACE FUNCTION public.yangila_sozlar()
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_count integer;
BEGIN
    DELETE FROM sozlar;
    INSERT INTO sozlar (soz, ndoc)
    SELECT word, ndoc FROM ts_stat('SELECT search_vector FROM elementlar')
    WHERE length(word) >= 3 AND word !~ '^[0-9]';
    GET DIAGNOSTICS v_count = ROW_COUNT;
    RETURN v_count;
END;
$$;

REVOKE ALL ON FUNCTION public.yangila_sozlar() FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON FUNCTION public.yangila_sozlar() FROM anon, authenticated';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.yangila_sozlar() TO service_role';
    END IF;
END;
$$;

SELECT public.yangila_sozlar();

ALTER TABLE suhbatlar DROP CONSTRAINT suhbatlar_status_check;
ALTER TABLE suhbatlar ADD CONSTRAINT suhbatlar_status_check
    CHECK (status IN ('answered', 'insufficient', 'needs_clarification', 'historical_unavailable',
                      'not_found', 'error', 'limit_exceeded', 'unavailable', 'sources_only'));
