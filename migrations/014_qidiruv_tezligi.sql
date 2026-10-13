-- 014_qidiruv_tezligi: search_articles() — natija o'zgarmaydi, GIN indeks ishlatiladi.
--
-- Muammo (2026-10-13): kichik Supabase serverida CPU krediti tugagach, oddiy qidiruv 2 daqiqalik
-- statement_timeout'ga tushdi. Sabab — `corpus` CTE: har chaqiruvda ≈75 ming element (tsvector bilan) to'liq
-- materializatsiya qilinib, har so'z IDF'i uchun va nomzodlar uchun qayta-qayta ko'rilardi; indeks ishlatilmasdi.
--
-- Yechim: o'sha filtrlar bilan
--   - IDF: so'z uchraydigan elementlar soni — indeks bo'yicha (`x.search_vector @@ t.q`, korrelyatsiyali);
--   - korpus hajmi — tsvector'siz count(*);
--   - nomzodlar — savol so'zlaridan birortasi bor elementlar, indeks bo'yicha.
-- Ballash, qamrov, bo'lim hajmi jarimasi, sarlavha va natija ustunlari — 009 dagidek (aynan bir xil formula).

CREATE OR REPLACE FUNCTION public.search_articles(
    p_terms      text[],
    p_trgm       text     DEFAULT NULL,
    p_lex_ids    text[]   DEFAULT NULL,
    p_statuses   text[]   DEFAULT ARRAY['amalda'],
    p_limit      integer  DEFAULT 6,
    p_candidates integer  DEFAULT 300,
    p_weights    float8[] DEFAULT NULL
)
RETURNS TABLE (
    lex_id             text,
    document_name      text,
    document_status    text,
    modda_raqami       text,        -- bo'limda NULL
    heading            text,
    heading_element_id text,
    heading_link       text,
    score              real,
    matched_terms      integer,
    matched            jsonb,
    birlik             text,        -- moddada NULL
    birlik_nomi        text
)
LANGUAGE sql STABLE
SET search_path = public, extensions
AS $$
    WITH n AS MATERIALIZED (
        SELECT greatest(count(*), 1)::float AS total
        FROM elementlar e
        JOIN hujjatlar h ON h.id = e.document_id
        WHERE e.kind IN ('article', 'text', 'table', 'footnote', 'header')
          AND (e.modda_raqami IS NOT NULL OR e.birlik IS NOT NULL)
          AND (e.kind <> 'header' OR e.birlik IS NOT NULL)
          AND h.status = ANY (p_statuses)
          AND (p_lex_ids IS NULL OR h.lex_id = ANY (p_lex_ids))
    ),
    terms AS MATERIALIZED (  -- aks holda IDF har (nomzod × so'z) jufti uchun qayta hisoblanadi
        SELECT t.term, t.q,
               t.w * greatest(ln(n.total / (1 + (
                   SELECT count(*)
                   FROM elementlar x
                   JOIN hujjatlar hx ON hx.id = x.document_id
                   WHERE x.search_vector @@ t.q
                     AND x.kind IN ('article', 'text', 'table', 'footnote', 'header')
                     AND (x.modda_raqami IS NOT NULL OR x.birlik IS NOT NULL)
                     AND (x.kind <> 'header' OR x.birlik IS NOT NULL)
                     AND hx.status = ANY (p_statuses)
                     AND (p_lex_ids IS NULL OR hx.lex_id = ANY (p_lex_ids))
               ))), 0.05) AS idf
        FROM (SELECT u.term, to_tsquery('simple', u.term) AS q, coalesce(p_weights[u.ord], 1.0) AS w
              FROM unnest(p_terms) WITH ORDINALITY AS u(term, ord)) t, n
    ),
    candidates AS MATERIALIZED (
        SELECT e.id, e.document_id, e.element_id, e.kind, e.text, e.link, e.modda_raqami, e.birlik,
               coalesce('m:' || e.modda_raqami, 'b:' || e.birlik) AS unit, e.search_vector
        FROM elementlar e
        JOIN hujjatlar h ON h.id = e.document_id
        WHERE e.search_vector @@ to_tsquery('simple',
                  (SELECT string_agg('(' || u.term || ')', ' | ') FROM unnest(p_terms) AS u(term)))
          AND e.kind IN ('article', 'text', 'table', 'footnote', 'header')
          AND (e.modda_raqami IS NOT NULL OR e.birlik IS NOT NULL)
          AND (e.kind <> 'header' OR e.birlik IS NOT NULL)
          AND h.status = ANY (p_statuses)
          AND (p_lex_ids IS NULL OR h.lex_id = ANY (p_lex_ids))
    ),
    element_scores AS (
        SELECT c.id, c.document_id, c.element_id, c.kind, c.text, c.link, c.modda_raqami, c.birlik, c.unit,
               t.term, t.idf,
               ts_rank('{0.05, 0.2, 0.5, 1.0}', c.search_vector, t.q, 1) AS r
        FROM candidates c
        JOIN terms t ON c.search_vector @@ t.q
    ),
    elements AS (
        SELECT es.id, es.document_id, es.element_id, es.kind, es.text, es.link, es.modda_raqami, es.birlik,
               es.unit, sum(es.idf * es.r) AS score
        FROM element_scores es
        GROUP BY es.id, es.document_id, es.element_id, es.kind, es.text, es.link, es.modda_raqami, es.birlik, es.unit
        ORDER BY score DESC
        LIMIT p_candidates
    ),
    coverage AS (
        SELECT es.document_id, es.unit, es.term, max(es.idf * es.r) AS best
        FROM element_scores es
        JOIN elements e ON e.id = es.id
        GROUP BY es.document_id, es.unit, es.term
    ),
    -- Bo'lim hajmi 4 000 belgidan oshsa bahosi kamayadi (bitta ulkan jadval hamma so'zni "qamrab" olmasin).
    -- Moddalar bahosi o'zgarmaydi.
    units AS (
        SELECT cv.document_id, cv.unit,
               sum(cv.best) * CASE WHEN cv.unit LIKE 'b:%' THEN 1.0 / (1.0 + ln(greatest(
                   (SELECT sum(length(e.text)) FROM elementlar e
                    WHERE e.document_id = cv.document_id AND e.birlik = substr(cv.unit, 3)), 4000) / 4000.0))
                   ELSE 1.0 END AS score,
               count(*)::int AS matched_terms,
               CASE WHEN cv.unit LIKE 'm:%' THEN substr(cv.unit, 3) END AS modda_raqami,
               CASE WHEN cv.unit LIKE 'b:%' THEN substr(cv.unit, 3) END AS birlik
        FROM coverage cv
        GROUP BY cv.document_id, cv.unit
    ),
    top_elements AS (
        SELECT e.*, row_number() OVER (PARTITION BY e.document_id, e.unit ORDER BY e.score DESC) AS rn
        FROM elements e
    )
    SELECT h.lex_id, h.name, h.status, u.modda_raqami, hd.text, hd.element_id, hd.link,
           (u.score + CASE WHEN p_trgm IS NULL OR p_trgm = '' THEN 0
                           ELSE 0.2 * word_similarity(public.norm_uz(p_trgm), public.norm_uz(hd.text)) END)::real,
           u.matched_terms,
           (SELECT jsonb_agg(jsonb_build_object(
                       'element_id', te.element_id, 'kind', te.kind, 'text', te.text,
                       'link', te.link, 'score', round(te.score::numeric, 4)) ORDER BY te.score DESC)
            FROM top_elements te
            WHERE te.document_id = u.document_id AND te.unit = u.unit AND te.rn <= 3),
           u.birlik, hd.birlik_nomi
    FROM units u
    JOIN hujjatlar h ON h.id = u.document_id
    JOIN LATERAL (
        SELECT x.text, x.element_id, x.link, x.birlik_nomi FROM (
            (SELECT e.text, e.element_id, e.link, NULL::text AS birlik_nomi, e.order_no FROM elementlar e
             WHERE u.modda_raqami IS NOT NULL AND e.document_id = u.document_id
               AND e.modda_raqami = u.modda_raqami AND e.kind = 'article'
             ORDER BY e.order_no LIMIT 1)
            UNION ALL
            (SELECT e.text, e.element_id, e.link, e.birlik_nomi, e.order_no FROM elementlar e
             WHERE u.modda_raqami IS NULL AND e.document_id = u.document_id AND e.element_id = u.birlik
             LIMIT 1)
        ) x LIMIT 1
    ) hd ON true
    ORDER BY 8 DESC
    LIMIT p_limit
$$;
