-- 004_search: PostgreSQL qidiruvi (spec 7, Phase 1: tsvector 'simple' + pg_trgm).
--
-- Muammo: Lex.uz matnida o'zbek tutuq belgisi U+02BB ("toʻlov"), foydalanuvchi esa odatda
-- ASCII "'" yozadi ("to'lov"); 'simple' parser ularni turlicha bo'ladi. Yechim — `norm_uz()`:
-- kichik harf + barcha tutuq/apostrof variantlarini olib tashlash ("toʻlov" → "tolov").
-- search_vector shu normallashtirilgan matndan qayta quriladi: A = modda sarlavhasi,
-- B = element matni, C = bob/bo'lim yo'li (kontekst).
--
-- `search_articles()` — nomzod elementlarni topadi va ularni moddalar bo'yicha guruhlab
-- baholaydi; faqat berilgan holatdagi (sukut: 'amalda') hujjatlar qidiriladi. Izoh turlari
-- (amendment, edition_note, lexuz_comment) va sarlavhalar nomzod bo'lmaydi.
-- So'rov tahlili (stop-so'zlar, qo'shimchalarni kesish, sinonimlar) Python'da:
-- app/retrieval/query.py.

CREATE OR REPLACE FUNCTION public.norm_uz(t text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE
SET search_path = ''
AS $$
    SELECT translate(lower(coalesce(t, '')), 'ʻʼ''‘’`´', '')
$$;

DROP INDEX IF EXISTS elementlar_search_idx;
DROP INDEX IF EXISTS elementlar_text_trgm_idx;
ALTER TABLE elementlar DROP COLUMN search_vector;
ALTER TABLE elementlar ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', public.norm_uz(modda)), 'A') ||
    setweight(to_tsvector('simple', public.norm_uz(text)), 'B') ||
    setweight(to_tsvector('simple', public.norm_uz(element_path)), 'C')
) STORED;
CREATE INDEX elementlar_search_idx ON elementlar USING gin (search_vector);
CREATE INDEX elementlar_norm_trgm_idx ON elementlar USING gin (public.norm_uz(text) extensions.gin_trgm_ops);

DROP INDEX IF EXISTS versiya_elementlari_search_idx;
ALTER TABLE versiya_elementlari DROP COLUMN search_vector;
ALTER TABLE versiya_elementlari ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', public.norm_uz(modda)), 'A') ||
    setweight(to_tsvector('simple', public.norm_uz(text)), 'B') ||
    setweight(to_tsvector('simple', public.norm_uz(element_path)), 'C')
) STORED;
CREATE INDEX versiya_elementlari_search_idx ON versiya_elementlari USING gin (search_vector);

CREATE OR REPLACE FUNCTION public.search_articles(
    p_terms      text[],                                -- har biri to_tsquery('simple') bo'lagi: 'soli:*', '(qosh:* & qiymat:*)'
    p_trgm       text     DEFAULT NULL,                 -- trigram uchun so'rov matni
    p_lex_ids    text[]   DEFAULT NULL,                 -- faqat shu hujjatlar (NULL = hammasi)
    p_statuses   text[]   DEFAULT ARRAY['amalda'],
    p_limit      integer  DEFAULT 6,
    p_candidates integer  DEFAULT 300
)
RETURNS TABLE (
    lex_id             text,
    document_name      text,
    document_status    text,
    modda_raqami       text,
    heading            text,
    heading_element_id text,
    heading_link       text,
    score              real,
    matched_terms      integer,     -- moddada uchragan so'rov bo'laklari soni
    matched            jsonb        -- [{element_id, kind, text, link, score}] eng yaxshi 3 tasi
)
LANGUAGE sql STABLE
SET search_path = public, extensions
AS $$
    WITH corpus AS (
        SELECT e.id, e.document_id, e.element_id, e.kind, e.text, e.link, e.modda_raqami, e.search_vector
        FROM elementlar e
        JOIN hujjatlar h ON h.id = e.document_id
        WHERE e.kind IN ('article', 'text', 'table', 'footnote')
          AND e.modda_raqami IS NOT NULL
          AND h.status = ANY (p_statuses)
          AND (p_lex_ids IS NULL OR h.lex_id = ANY (p_lex_ids))
    ),
    n AS (SELECT greatest(count(*), 1)::float AS total FROM corpus),
    -- IDF: kam uchraydigan so'z (norezident, aylanma) keng tarqalganidan (soliq) ko'proq vazn oladi.
    terms AS (
        SELECT t.term, t.q,
               greatest(ln(n.total / (1 + (SELECT count(*) FROM corpus c WHERE c.search_vector @@ t.q))), 0.05) AS idf
        FROM (SELECT term, to_tsquery('simple', term) AS q FROM unnest(p_terms) AS term) t, n
    ),
    any_q AS (SELECT to_tsquery('simple', string_agg('(' || term || ')', ' | ')) AS q FROM terms),
    element_scores AS (
        SELECT c.id, c.document_id, c.element_id, c.kind, c.text, c.link, c.modda_raqami, t.term, t.idf,
               -- {D,C,B,A}: sarlavha (A) > matn (B) > bob yo'li (C); normalization 1 — uzun matn ustunligini kamaytiradi
               ts_rank('{0.05, 0.2, 0.5, 1.0}', c.search_vector, t.q, 1) AS r
        FROM corpus c
        CROSS JOIN any_q
        JOIN terms t ON c.search_vector @@ t.q
        WHERE c.search_vector @@ any_q.q
    ),
    elements AS (
        SELECT es.id, es.document_id, es.element_id, es.kind, es.text, es.link, es.modda_raqami,
               sum(es.idf * es.r) AS score
        FROM element_scores es
        GROUP BY es.id, es.document_id, es.element_id, es.kind, es.text, es.link, es.modda_raqami
        ORDER BY score DESC
        LIMIT p_candidates
    ),
    -- Modda bahosi: har bir so'rov bo'lagi uchun moddadagi eng yaxshi element (qamrov),
    -- ya'ni savolning turli qismlari moddaning turli bandlarida bo'lsa ham hisobga olinadi.
    coverage AS (
        SELECT es.document_id, es.modda_raqami, es.term, max(es.idf * es.r) AS best
        FROM element_scores es
        JOIN elements e ON e.id = es.id
        GROUP BY es.document_id, es.modda_raqami, es.term
    ),
    articles AS (
        SELECT cv.document_id, cv.modda_raqami, sum(cv.best) AS score, count(*)::int AS matched_terms
        FROM coverage cv
        GROUP BY cv.document_id, cv.modda_raqami
    ),
    top_elements AS (
        SELECT e.*, row_number() OVER (PARTITION BY e.document_id, e.modda_raqami ORDER BY e.score DESC) AS rn
        FROM elements e
    )
    SELECT h.lex_id, h.name, h.status, a.modda_raqami, hd.text, hd.element_id, hd.link,
           (a.score + CASE WHEN p_trgm IS NULL OR p_trgm = '' THEN 0
                           ELSE 0.2 * word_similarity(public.norm_uz(p_trgm), public.norm_uz(hd.text)) END)::real,
           a.matched_terms,
           (SELECT jsonb_agg(jsonb_build_object(
                       'element_id', te.element_id, 'kind', te.kind, 'text', te.text,
                       'link', te.link, 'score', round(te.score::numeric, 4)) ORDER BY te.score DESC)
            FROM top_elements te
            WHERE te.document_id = a.document_id AND te.modda_raqami = a.modda_raqami AND te.rn <= 3)
    FROM articles a
    JOIN hujjatlar h ON h.id = a.document_id
    JOIN LATERAL (
        SELECT e.text, e.element_id, e.link FROM elementlar e
        WHERE e.document_id = a.document_id AND e.modda_raqami = a.modda_raqami AND e.kind = 'article'
        ORDER BY e.order_no LIMIT 1
    ) hd ON true
    ORDER BY 8 DESC
    LIMIT p_limit
$$;

REVOKE ALL ON FUNCTION public.search_articles(text[], text, text[], text[], integer, integer) FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON FUNCTION public.search_articles(text[], text, text[], text[], integer, integer) FROM anon, authenticated';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.search_articles(text[], text, text[], text[], integer, integer) TO service_role';
    END IF;
END;
$$;
