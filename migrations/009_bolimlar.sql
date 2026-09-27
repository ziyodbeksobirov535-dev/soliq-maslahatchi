-- 009_bolimlar: moddasiz hujjatlar (farmon, qaror, nizom) ham qidiruvda qatnashadi.
--
-- Muammo: search_articles() faqat modda (`modda_raqami`, `kind='article'` sarlavha) bo'yicha ishlardi.
-- Farmon/qarorlarda modda yo'q — raqamli bandlar, boblar va ilovalar bor (real hujjatlarda tekshirilgan:
-- kodekslardan tashqari 33 hujjatdan 32 tasida modda yo'q). Ular bazada bor, lekin savol-javobda chiqmasdi.
--
-- Yechim: moddaga kirmagan matn elementlari "bo'lim"larga ajratiladi va bo'lim modda o'rnida qidiriladi.
-- Bo'lim chegarasi: bob sarlavhasi (`kind='header'`), ilova boshi (`kind='other'`, "1-ILOVA"), hujjat
-- sarlavhasi va moddalar. Bo'lim = chegaradan keyingi text/table/footnote elementlari; bob sarlavhasi
-- bo'limning sarlavhasi. `birlik` — bo'lim birinchi elementining Lex.uz ID'si, `birlik_nomi` —
-- "1-ilova, 2-bob. ..." yoki "Asosiy qism". Moddalar avvalgidek (birlik = NULL).
-- Katta bo'lim bo'laklanadi: ~4 000 belgidan keyin keyingi raqamli band boshida (8 000 dan oshsa — darhol),
-- nomi "..., 12-band". Mezon — kodeks moddalari hajmi (mediana ~1 100, 90% ≤ 3 000 belgi).
-- Iqtibos va havolalar o'zgarmaydi: element darajasida, bazadagi canonical havola bilan.

ALTER TABLE elementlar ADD COLUMN birlik text, ADD COLUMN birlik_nomi text;
CREATE INDEX elementlar_birlik_idx ON elementlar (document_id, birlik) WHERE birlik IS NOT NULL;

CREATE OR REPLACE FUNCTION public.hisobla_birliklar(p_document_id bigint)
RETURNS integer
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    r         record;
    v_start   text;
    v_nomi    text;
    v_ilova   text;
    v_header  text;
    v_hdr_pos integer;                                  -- sarlavha: bo'limga faqat undan keyin matn kelsa qo'shiladi
    v_hdr_eid text;
    v_base    text;                                     -- bo'lim nomi (bo'laklarda ham asos)
    v_chars   integer := 0;
    v_band    text;
    v_ids     bigint[] := '{}';
    v_birlik  text[]   := '{}';
    v_nomlar  text[]   := '{}';
    v_changed integer;
BEGIN
    FOR r IN
        SELECT id, element_id, kind, text, modda_raqami FROM elementlar
        WHERE document_id = p_document_id ORDER BY order_no
    LOOP
        IF r.modda_raqami IS NOT NULL OR r.kind = 'article' THEN
            v_start := NULL; v_header := NULL; v_hdr_pos := NULL;  -- modda ichi — modda bo'yicha qidiriladi
        ELSIF r.kind = 'other' AND r.text ~ '(^|\s)(\d+-)?ILOVA(\s|$)' THEN
            v_ilova := lower(substring(r.text FROM '(\d+-ILOVA|ILOVA)'));
            v_start := NULL; v_header := NULL; v_hdr_pos := NULL;
        ELSIF r.kind = 'title' THEN
            v_start := NULL; v_header := NULL; v_hdr_pos := NULL;
        ELSIF r.kind = 'header' THEN
            v_header := r.text; v_hdr_eid := r.element_id; v_start := NULL;
            v_ids := v_ids || r.id; v_birlik := v_birlik || NULL::text; v_nomlar := v_nomlar || NULL::text;
            v_hdr_pos := cardinality(v_ids);                -- birlik keyinroq (matn kelsa) yoziladi
            CONTINUE;
        ELSIF r.kind IN ('text', 'table', 'footnote') THEN
            v_band := substring(r.text FROM '^\s*(\d{1,3}(?:\.\d{1,3})*)[.)]\s');
            IF v_start IS NOT NULL AND v_hdr_pos IS NULL
               AND ((v_chars >= 4000 AND v_band IS NOT NULL) OR v_chars >= 8000) THEN
                v_start := r.element_id;                    -- katta bo'limning keyingi bo'lagi
                v_nomi := v_base || coalesce(', ' || v_band || '-band', ' (davomi)');
                v_chars := 0;
            END IF;
            IF v_start IS NULL THEN
                v_nomi := concat_ws(', ', v_ilova, left(v_header, 150));
                IF v_nomi = '' THEN v_nomi := 'Asosiy qism'; END IF;
                v_base := v_nomi; v_chars := 0;
                IF v_hdr_pos IS NOT NULL THEN               -- bob sarlavhasi — bo'lim sarlavhasi
                    v_start := v_hdr_eid;
                    v_birlik[v_hdr_pos] := v_start; v_nomlar[v_hdr_pos] := v_nomi;
                    v_hdr_pos := NULL;
                ELSE
                    v_start := r.element_id;
                END IF;
            END IF;
            v_ids := v_ids || r.id; v_birlik := v_birlik || v_start; v_nomlar := v_nomlar || v_nomi;
            v_chars := v_chars + length(r.text);
            CONTINUE;
        END IF;
        -- izohlar (amendment, edition_note, lexuz_comment), imzo va boshqa 'other' qatorlar bo'limga kirmaydi
        v_ids := v_ids || r.id; v_birlik := v_birlik || NULL::text; v_nomlar := v_nomlar || NULL::text;
    END LOOP;

    UPDATE elementlar e SET birlik = u.b, birlik_nomi = u.n
    FROM unnest(v_ids, v_birlik, v_nomlar) AS u(id, b, n)
    WHERE e.id = u.id AND (e.birlik, e.birlik_nomi) IS DISTINCT FROM (u.b, u.n);
    GET DIAGNOSTICS v_changed = ROW_COUNT;
    RETURN v_changed;
END;
$$;

-- import har safar bo'limlarni qayta hisoblaydi (003 dagi funksiya, faqat PERFORM qatori qo'shilgan).
CREATE OR REPLACE FUNCTION public.finish_import(p_import_id uuid, p_doc jsonb, p_today date)
RETURNS jsonb
LANGUAGE plpgsql
SECURITY INVOKER
SET search_path = public
AS $$
DECLARE
    v_document_id  bigint;
    v_inserted     boolean;
    v_had_elements boolean;
    v_total        integer;
    v_added        integer;
    v_changed      integer;
    v_removed      integer;
BEGIN
    IF p_doc ->> 'lex_id' IS NULL OR p_doc ->> 'name' IS NULL OR p_doc ->> 'url' IS NULL THEN
        RAISE EXCEPTION 'finish_import: lex_id, name va url majburiy';
    END IF;

    -- Staging'dagi elementlar (bir import ichida element_id takrorlanmasligi kerak).
    DROP TABLE IF EXISTS _new;
    CREATE TEMP TABLE _new ON COMMIT DROP AS
    SELECT e.*
    FROM import_staging s,
         jsonb_to_record(s.element) AS e(
             element_id text, parent_element_id text, order_no integer, type text, kind text,
             bob text, modda text, modda_raqami text, text text, text_hash text,
             amendment_note text, future_version text, link text, element_path text)
    WHERE s.import_id = p_import_id;

    SELECT count(*) INTO v_total FROM _new;
    IF (SELECT count(DISTINCT element_id) FROM _new) <> v_total THEN
        RAISE EXCEPTION 'finish_import: takrorlangan element_id (import %)', p_import_id;
    END IF;

    INSERT INTO hujjatlar AS h (
        lex_id, name, type, number, adoption_date, effective_date, status, status_raw,
        status_checked_at, current_version, url, source_url, last_loaded, last_successful_load,
        content_hash, text_available, repeal_date)
    VALUES (
        p_doc ->> 'lex_id', p_doc ->> 'name', p_doc ->> 'type', p_doc ->> 'number',
        (p_doc ->> 'adoption_date')::date, (p_doc ->> 'effective_date')::date,
        coalesce(p_doc ->> 'status', 'noma''lum'), p_doc ->> 'status_raw',
        CASE WHEN p_doc ->> 'status_raw' IS NULL THEN NULL ELSE now() END,
        p_doc ->> 'current_version', p_doc ->> 'url', p_doc ->> 'source_url', now(), now(),
        p_doc ->> 'content_hash', coalesce((p_doc ->> 'text_available')::boolean, false),
        (p_doc ->> 'repeal_date')::date)
    ON CONFLICT (lex_id) DO UPDATE SET
        name = EXCLUDED.name, type = EXCLUDED.type, number = EXCLUDED.number,
        adoption_date = EXCLUDED.adoption_date, effective_date = EXCLUDED.effective_date,
        status = EXCLUDED.status, status_raw = EXCLUDED.status_raw,
        status_checked_at = EXCLUDED.status_checked_at, current_version = EXCLUDED.current_version,
        url = EXCLUDED.url, source_url = EXCLUDED.source_url, last_loaded = EXCLUDED.last_loaded,
        last_successful_load = EXCLUDED.last_successful_load, content_hash = EXCLUDED.content_hash,
        text_available = EXCLUDED.text_available, repeal_date = EXCLUDED.repeal_date
    RETURNING h.id, (h.xmax = 0) INTO v_document_id, v_inserted;

    SELECT EXISTS (SELECT 1 FROM elementlar WHERE document_id = v_document_id) INTO v_had_elements;

    SELECT count(*) INTO v_added
    FROM _new n
    WHERE NOT EXISTS (SELECT 1 FROM elementlar e WHERE e.document_id = v_document_id AND e.element_id = n.element_id);

    SELECT count(*) INTO v_changed
    FROM _new n JOIN elementlar e ON e.document_id = v_document_id AND e.element_id = n.element_id
    WHERE e.text_hash <> n.text_hash;

    SELECT count(*) INTO v_removed
    FROM elementlar e
    WHERE e.document_id = v_document_id AND NOT EXISTS (SELECT 1 FROM _new n WHERE n.element_id = e.element_id);

    -- O'zgarishlar jurnali: faqat oldin elementlari bo'lgan hujjat uchun.
    IF NOT v_inserted AND v_had_elements THEN
        INSERT INTO ozgarishlar (document_id, element_id, old_hash, new_hash, old_text, new_text, change_type)
        SELECT v_document_id, n.element_id, NULL, n.text_hash, NULL, n.text, 'qo''shilgan'
        FROM _new n
        WHERE NOT EXISTS (SELECT 1 FROM elementlar e WHERE e.document_id = v_document_id AND e.element_id = n.element_id)
        UNION ALL
        SELECT v_document_id, n.element_id, e.text_hash, n.text_hash, e.text, n.text, 'o''zgargan'
        FROM _new n JOIN elementlar e ON e.document_id = v_document_id AND e.element_id = n.element_id
        WHERE e.text_hash <> n.text_hash
        UNION ALL
        SELECT v_document_id, e.element_id, e.text_hash, NULL, e.text, NULL, 'o''chirilgan'
        FROM elementlar e
        WHERE e.document_id = v_document_id AND NOT EXISTS (SELECT 1 FROM _new n WHERE n.element_id = e.element_id)
        ON CONFLICT DO NOTHING;
    END IF;

    DELETE FROM elementlar e
    WHERE e.document_id = v_document_id AND NOT EXISTS (SELECT 1 FROM _new n WHERE n.element_id = e.element_id);

    INSERT INTO elementlar AS el (
        element_id, document_id, parent_element_id, order_no, type, kind, bob, modda, modda_raqami,
        text, text_hash, amendment_note, future_version, link, element_path)
    SELECT n.element_id, v_document_id, n.parent_element_id, n.order_no, n.type, n.kind, n.bob,
           n.modda, n.modda_raqami, n.text, n.text_hash, n.amendment_note, n.future_version,
           n.link, coalesce(n.element_path, '')
    FROM _new n
    ON CONFLICT (element_id, document_id) DO UPDATE SET
        parent_element_id = EXCLUDED.parent_element_id, order_no = EXCLUDED.order_no,
        type = EXCLUDED.type, kind = EXCLUDED.kind, bob = EXCLUDED.bob, modda = EXCLUDED.modda,
        modda_raqami = EXCLUDED.modda_raqami, text = EXCLUDED.text, text_hash = EXCLUDED.text_hash,
        amendment_note = EXCLUDED.amendment_note, future_version = EXCLUDED.future_version,
        link = EXCLUDED.link, element_path = EXCLUDED.element_path
    WHERE (el.text_hash, el.order_no, el.parent_element_id, el.amendment_note, el.future_version,
           el.element_path, el.kind, el.type, el.bob, el.modda, el.modda_raqami, el.link)
          IS DISTINCT FROM
          (EXCLUDED.text_hash, EXCLUDED.order_no, EXCLUDED.parent_element_id, EXCLUDED.amendment_note,
           EXCLUDED.future_version, EXCLUDED.element_path, EXCLUDED.kind, EXCLUDED.type, EXCLUDED.bob,
           EXCLUDED.modda, EXCLUDED.modda_raqami, EXCLUDED.link);

    IF p_doc ->> 'current_version' IS NOT NULL AND p_doc ->> 'version_date' IS NOT NULL THEN
        INSERT INTO hujjat_versiyalari (document_id, version_token, on_date, text_hash, loaded_at, source_url)
        VALUES (v_document_id, p_doc ->> 'current_version', (p_doc ->> 'version_date')::date,
                p_doc ->> 'content_hash', now(), coalesce(p_doc ->> 'source_url', p_doc ->> 'url'))
        ON CONFLICT (document_id, version_token) DO UPDATE SET
            text_hash = EXCLUDED.text_hash, loaded_at = EXCLUDED.loaded_at, source_url = EXCLUDED.source_url;
    END IF;

    -- 009: moddasiz matnni bo'limlarga ajratish (qidiruv birligi).
    PERFORM public.hisobla_birliklar(v_document_id);

    DELETE FROM import_staging WHERE import_id = p_import_id;

    RETURN jsonb_build_object(
        'document_id', v_document_id, 'lex_id', p_doc ->> 'lex_id',
        'status', coalesce(p_doc ->> 'status', 'noma''lum'), 'first_import', v_inserted,
        'total', v_total, 'added', v_added, 'changed', v_changed, 'removed', v_removed);
END;
$$;


-- search_articles: modda yoki bo'lim bo'yicha. Qaytariladigan ustunlarga `birlik`, `birlik_nomi` qo'shildi
-- (bo'limda modda_raqami = NULL, heading = bo'limning birinchi elementi).
DROP FUNCTION IF EXISTS public.search_articles(text[], text, text[], text[], integer, integer, float8[]);

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
    WITH corpus AS (
        SELECT e.id, e.document_id, e.element_id, e.kind, e.text, e.link, e.modda_raqami, e.birlik,
               coalesce('m:' || e.modda_raqami, 'b:' || e.birlik) AS unit, e.search_vector
        FROM elementlar e
        JOIN hujjatlar h ON h.id = e.document_id
        WHERE e.kind IN ('article', 'text', 'table', 'footnote', 'header')
          AND (e.modda_raqami IS NOT NULL OR e.birlik IS NOT NULL)
          AND (e.kind <> 'header' OR e.birlik IS NOT NULL)
          AND h.status = ANY (p_statuses)
          AND (p_lex_ids IS NULL OR h.lex_id = ANY (p_lex_ids))
    ),
    n AS (SELECT greatest(count(*), 1)::float AS total FROM corpus),
    terms AS (
        SELECT t.term, t.q,
               t.w * greatest(ln(n.total / (1 + (SELECT count(*) FROM corpus c WHERE c.search_vector @@ t.q))), 0.05) AS idf
        FROM (SELECT u.term, to_tsquery('simple', u.term) AS q, coalesce(p_weights[u.ord], 1.0) AS w
              FROM unnest(p_terms) WITH ORDINALITY AS u(term, ord)) t, n
    ),
    any_q AS (SELECT to_tsquery('simple', string_agg('(' || term || ')', ' | ')) AS q FROM terms),
    element_scores AS (
        SELECT c.id, c.document_id, c.element_id, c.kind, c.text, c.link, c.modda_raqami, c.birlik, c.unit,
               t.term, t.idf,
               ts_rank('{0.05, 0.2, 0.5, 1.0}', c.search_vector, t.q, 1) AS r
        FROM corpus c
        CROSS JOIN any_q
        JOIN terms t ON c.search_vector @@ t.q
        WHERE c.search_vector @@ any_q.q
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

REVOKE ALL ON FUNCTION public.search_articles(text[], text, text[], text[], integer, integer, float8[]) FROM PUBLIC;
REVOKE ALL ON FUNCTION public.hisobla_birliklar(bigint) FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON FUNCTION public.search_articles(text[], text, text[], text[], integer, integer, float8[]) FROM anon, authenticated';
        EXECUTE 'REVOKE ALL ON FUNCTION public.hisobla_birliklar(bigint) FROM anon, authenticated';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.search_articles(text[], text, text[], text[], integer, integer, float8[]) TO service_role';
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.hisobla_birliklar(bigint) TO service_role';
    END IF;
END;
$$;

-- Mavjud hujjatlar uchun bir martalik hisob.
SELECT public.hisobla_birliklar(id) FROM hujjatlar;
