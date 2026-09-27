-- 003_import_rpc: hujjat importi baza ichidagi funksiya orqali.
--
-- Sabab: import ikki xil muhitdan bajariladi — to'g'ridan-to'g'ri Postgres ulanishi (server,
-- testlar) va faqat HTTPS mavjud muhit (Supabase REST / PostgREST, service_role kaliti bilan).
-- Mantiq bitta joyda bo'lishi uchun:
--   1) elementlar `import_staging` ga bo'laklab yoziladi (katta hujjat bitta so'rovga sig'maydi);
--   2) `finish_import(import_id, doc, today)` hammasini BITTA tranzaksiyada bajaradi:
--      hujjat UPSERT, eski/yangi farqi, `ozgarishlar` jurnali (birinchi importda emas),
--      elementlar UPSERT (o'zgarmaganlari qayta yozilmaydi), yo'qolganlarini o'chirish,
--      versiya yozuvi, staging tozalash.
-- Holat (`status`) Python tomonida `lexuz.resolve_status` bilan hisoblanadi va shu yerga beriladi.

CREATE TABLE import_staging (
    import_id   uuid        NOT NULL,
    seq         integer     NOT NULL CHECK (seq > 0),
    element     jsonb       NOT NULL,
    created_at  timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (import_id, seq)
);

ALTER TABLE import_staging ENABLE ROW LEVEL SECURITY;

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

    DELETE FROM import_staging WHERE import_id = p_import_id;

    RETURN jsonb_build_object(
        'document_id', v_document_id, 'lex_id', p_doc ->> 'lex_id',
        'status', coalesce(p_doc ->> 'status', 'noma''lum'), 'first_import', v_inserted,
        'total', v_total, 'added', v_added, 'changed', v_changed, 'removed', v_removed);
END;
$$;

-- Faqat backend chaqira oladi: public API (anon/authenticated) uchun yopiq.
REVOKE ALL ON FUNCTION public.finish_import(uuid, jsonb, date) FROM PUBLIC;
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'anon') THEN
        EXECUTE 'REVOKE ALL ON FUNCTION public.finish_import(uuid, jsonb, date) FROM anon, authenticated';
        EXECUTE 'REVOKE ALL ON TABLE public.import_staging FROM anon, authenticated';
    END IF;
    IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'service_role') THEN
        EXECUTE 'GRANT EXECUTE ON FUNCTION public.finish_import(uuid, jsonb, date) TO service_role';
        EXECUTE 'GRANT SELECT, INSERT, DELETE ON TABLE public.import_staging TO service_role';
    END IF;
END;
$$;
