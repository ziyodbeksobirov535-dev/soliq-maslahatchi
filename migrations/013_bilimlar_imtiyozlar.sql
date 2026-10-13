-- 013_bilimlar_imtiyozlar: bilimlar bazasi (spec 19) — rasmiy soliq imtiyozlari ro'yxati va skill bilimlari.
--
-- Yozuv — yo'naltiruvchi, manba emas (spec 2: Lex.uz ustun): imtiyoz bandi qaysi modda/hujjatga tegishli ekanini
-- ko'rsatadi, javobda esa o'sha moddaning Lex.uz matni manba bo'ladi (`lex_check_required`).
-- - turi: 'imtiyoz' (skill-bilimlar/kodeks-toliq/soliq-imtiyozlari-FAOL.csv) yoki 'bilim' (skill .md fayllari);
-- - lex_id, modda_raqami — imtiyoz Soliq kodeksi moddasiga tegishli bo'lsa ("(СК 379-м.)");
-- - hujjat — asl hujjat raqami ("PQ-179", "SK-379"); amal_muddati — shundan keyin ko'rsatilmaydi;
-- - asl_matn — kirill asli (text — lotinga o'girilgani, o'qish va qidiruv uchun).
-- search_vector — norm_uz() bilan (elementlar kabi: "toʻlov" = "to'lov").

ALTER TABLE bilimlar ADD COLUMN turi text NOT NULL DEFAULT 'bilim' CHECK (turi IN ('bilim', 'imtiyoz'));
ALTER TABLE bilimlar ADD COLUMN lex_id text;
ALTER TABLE bilimlar ADD COLUMN modda_raqami text;
ALTER TABLE bilimlar ADD COLUMN hujjat text;
ALTER TABLE bilimlar ADD COLUMN amal_muddati date;
ALTER TABLE bilimlar ADD COLUMN asl_matn text;

DROP INDEX IF EXISTS bilimlar_search_idx;
ALTER TABLE bilimlar DROP COLUMN search_vector;
ALTER TABLE bilimlar ADD COLUMN search_vector tsvector GENERATED ALWAYS AS (
    setweight(to_tsvector('simple', public.norm_uz(topic)), 'A') ||
    setweight(to_tsvector('simple', public.norm_uz(text)), 'B')
) STORED;
CREATE INDEX bilimlar_search_idx ON bilimlar USING gin (search_vector);
CREATE INDEX bilimlar_turi_idx ON bilimlar (turi, amal_muddati);
