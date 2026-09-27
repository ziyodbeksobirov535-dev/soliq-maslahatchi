"""Sxema testlari (spec 26: insert, upsert, duplicate prevention, versioning, status)."""

import uuid
from datetime import date
from pathlib import Path

import asyncpg
import pytest

import lexuz
from app.database import migrate as migrate_mod
from app.database.connection import connect
from tests.conftest import run
from tests.test_lexuz_parser import SK_ID, soliq_kodeksi

TABLES = {
    "import_staging",
    "yangiliklar",
    "hujjatlar",
    "hujjat_versiyalari",
    "elementlar",
    "versiya_elementlari",
    "bilimlar",
    "foydalanuvchilar",
    "suhbatlar",
    "ozgarishlar",
    "obunalar",
    "schema_migrations",
}

UPSERT_ELEMENT = """
INSERT INTO elementlar (element_id, document_id, parent_element_id, order_no, type, kind, bob,
                        modda, modda_raqami, text, text_hash, amendment_note, future_version,
                        link, element_path)
VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
ON CONFLICT (element_id, document_id) DO UPDATE SET
    parent_element_id = EXCLUDED.parent_element_id, order_no = EXCLUDED.order_no,
    type = EXCLUDED.type, kind = EXCLUDED.kind, bob = EXCLUDED.bob, modda = EXCLUDED.modda,
    modda_raqami = EXCLUDED.modda_raqami, text = EXCLUDED.text, text_hash = EXCLUDED.text_hash,
    amendment_note = EXCLUDED.amendment_note, future_version = EXCLUDED.future_version,
    link = EXCLUDED.link, element_path = EXCLUDED.element_path
WHERE elementlar.text_hash IS DISTINCT FROM EXCLUDED.text_hash
   OR elementlar.order_no IS DISTINCT FROM EXCLUDED.order_no
"""


def element_row(e: lexuz.Element, document_id: int) -> tuple:
    return (
        e.element_id, document_id, e.parent_element_id, e.order_no, e.type, e.kind, e.bob,
        e.modda, e.modda_raqami, e.text, e.text_hash, e.amendment_note, e.future_version,
        e.link, e.element_path,
    )


async def with_conn(dsn, fn):
    conn = await connect(dsn)
    try:
        return await fn(conn)
    finally:
        await conn.close()


async def new_document(conn, lex_id: str | None = None, **fields) -> int:
    lex_id = lex_id or str(-abs(uuid.uuid4().int % 10**9))
    values = {"name": "Test hujjat", "url": f"https://lex.uz/docs/{lex_id}", **fields}
    cols = ", ".join(["lex_id", *values])
    params = ", ".join(f"${i}" for i in range(1, len(values) + 2))
    return await conn.fetchval(
        f"INSERT INTO hujjatlar ({cols}) VALUES ({params}) RETURNING id", lex_id, *values.values()
    )


# --- migration runner ---------------------------------------------------


def test_all_tables_created(db):
    async def check(conn):
        rows = await conn.fetch("SELECT tablename FROM pg_tables WHERE schemaname = 'public'")
        return {r["tablename"] for r in rows}

    assert TABLES <= run(with_conn(db, check))


def test_migrate_is_idempotent(db):
    assert run(migrate_mod.migrate(db)) == []
    assert run(migrate_mod.status(db)) == [("001_init", True), ("002_hardening", True), ("003_import_rpc", True), ("004_search", True), ("005_search_weights", True), ("006_suhbat_status", True), ("007_yangiliklar", True)]


def test_changed_applied_migration_is_rejected(db, tmp_path):
    original = migrate_mod.MIGRATIONS_DIR / "001_init.sql"
    (tmp_path / "001_init.sql").write_text(original.read_text() + "\n-- edited\n")
    with pytest.raises(migrate_mod.MigrationError):
        run(migrate_mod.migrate(db, tmp_path))


def test_bad_migration_rolls_back(empty_db, tmp_path):
    (tmp_path / "001_ok.sql").write_text("CREATE TABLE t_ok (id int);")
    (tmp_path / "002_bad.sql").write_text("CREATE TABLE t_bad (id int); SELECT * FROM missing_table;")
    with pytest.raises(asyncpg.PostgresError):
        run(migrate_mod.migrate(empty_db, tmp_path))

    async def check(conn):
        tables = {r["tablename"] for r in await conn.fetch("SELECT tablename FROM pg_tables")}
        versions = {r["version"] for r in await conn.fetch("SELECT version FROM schema_migrations")}
        return tables, versions

    tables, versions = run(with_conn(empty_db, check))
    assert "t_ok" in tables and "t_bad" not in tables
    assert versions == {"001_ok"}


def test_bad_migration_name(tmp_path):
    (tmp_path / "init.sql").write_text("SELECT 1;")
    with pytest.raises(migrate_mod.MigrationError):
        migrate_mod.discover(tmp_path)


def test_trgm_extension_moved_out_of_public(db):
    async def check(conn):
        return await conn.fetchval(
            "SELECT n.nspname FROM pg_extension e JOIN pg_namespace n ON n.oid = e.extnamespace "
            "WHERE e.extname = 'pg_trgm'"
        )

    assert run(with_conn(db, check)) == "extensions"


def test_rls_enabled_everywhere(db):
    async def check(conn):
        rows = await conn.fetch(
            "SELECT relname, relrowsecurity FROM pg_class WHERE relname = ANY($1::text[])",
            list(TABLES - {"schema_migrations"}),
        )
        return {r["relname"]: r["relrowsecurity"] for r in rows}

    result = run(with_conn(db, check))
    assert len(result) == len(TABLES) - 1
    assert all(result.values())


# --- hujjatlar / status -------------------------------------------------


def test_document_defaults_to_unknown_status(db):
    async def check(conn):
        doc_id = await new_document(conn)
        return await conn.fetchrow("SELECT status, text_available FROM hujjatlar WHERE id = $1", doc_id)

    row = run(with_conn(db, check))
    assert row["status"] == "noma'lum"
    assert row["text_available"] is False


@pytest.mark.parametrize("status", ["amalda", "kuchga_kirmagan", "kuchini_yoqotgan", "noma'lum"])
def test_valid_statuses(db, status):
    run(with_conn(db, lambda conn: new_document(conn, status=status)))


def test_invalid_status_rejected(db):
    with pytest.raises(asyncpg.CheckViolationError):
        run(with_conn(db, lambda conn: new_document(conn, status="active")))


def test_duplicate_lex_id_rejected(db):
    async def insert_twice(conn):
        await new_document(conn, lex_id="-111")
        await new_document(conn, lex_id="-111")

    with pytest.raises(asyncpg.UniqueViolationError):
        run(with_conn(db, insert_twice))


def test_updated_at_trigger(db):
    async def check(conn):
        doc_id = await new_document(conn)
        before = await conn.fetchval("SELECT updated_at FROM hujjatlar WHERE id = $1", doc_id)
        await conn.execute("SELECT pg_sleep(0.01)")
        await conn.execute("UPDATE hujjatlar SET status = 'amalda' WHERE id = $1", doc_id)
        after = await conn.fetchval("SELECT updated_at FROM hujjatlar WHERE id = $1", doc_id)
        return before, after

    before, after = run(with_conn(db, check))
    assert after > before


# --- elementlar: real parser natijasi bilan --------------------------------


def test_parsed_tax_code_upsert_is_idempotent(db):
    doc = soliq_kodeksi()

    async def scenario(conn):
        await conn.execute("DELETE FROM hujjatlar WHERE lex_id = $1", SK_ID)  # boshqa modullar qoldirgan bo'lishi mumkin
        doc_id = await new_document(conn, lex_id=SK_ID, name=doc.name, adoption_date=doc.adoption_date)
        rows = [element_row(e, doc_id) for e in doc.elements]
        await conn.executemany(UPSERT_ELEMENT, rows)
        first = await conn.fetchval("SELECT count(*) FROM elementlar WHERE document_id = $1", doc_id)
        stamp = await conn.fetchval("SELECT max(updated_at) FROM elementlar WHERE document_id = $1", doc_id)
        await conn.executemany(UPSERT_ELEMENT, rows)  # collector qayta ishga tushdi
        second = await conn.fetchval("SELECT count(*) FROM elementlar WHERE document_id = $1", doc_id)
        stamp2 = await conn.fetchval("SELECT max(updated_at) FROM elementlar WHERE document_id = $1", doc_id)

        # Bitta element matni o'zgardi → faqat o'sha yangilanadi.
        target = next(e for e in doc.elements if e.element_id == "-7966265")
        changed = element_row(target, doc_id)
        changed = changed[:9] + ("yangi matn", "hash-yangi") + changed[11:]
        await conn.execute(UPSERT_ELEMENT, *changed)
        updated = await conn.fetch(
            "SELECT element_id FROM elementlar WHERE document_id = $1 AND updated_at > $2", doc_id, stamp2
        )
        article = await conn.fetch(
            "SELECT element_id, link FROM elementlar WHERE document_id = $1 AND modda_raqami = '461' "
            "ORDER BY order_no",
            doc_id,
        )
        return first, second, stamp, stamp2, [r["element_id"] for r in updated], article

    first, second, stamp, stamp2, updated, article = run(with_conn(db, scenario))
    assert first == second == len(doc.elements)
    assert stamp == stamp2  # o'zgarmagan qatorlar qayta yozilmadi
    assert updated == ["-7966265"]
    assert article[0]["element_id"] == "-4688907"
    assert article[0]["link"] == "https://lex.uz/docs/-4674902#-4688907"


def test_full_text_and_trigram_search(db):
    async def scenario(conn):
        doc_id = await new_document(conn)
        el = lexuz.Element(
            element_id="-1", doc_id="-1", order_no=1, type="ACT_TEXT", kind="text",
            text="Aylanmadan olinadigan soliqni toʻlovchilar deb quyidagilar eʼtirof etiladi",
            link="https://lex.uz/docs/-1#-1", modda="461-modda. Soliq toʻlovchilar", modda_raqami="461",
        )
        await conn.execute(UPSERT_ELEMENT, *element_row(el, doc_id))
        fts = await conn.fetchval(
            "SELECT count(*) FROM elementlar WHERE document_id = $1 "
            "AND search_vector @@ plainto_tsquery('simple', 'aylanmadan soliqni')",
            doc_id,
        )
        trgm = await conn.fetchval(
            "SELECT similarity(text, 'aylanmadan olinadigan soliq') > 0.2 FROM elementlar WHERE document_id = $1",
            doc_id,
        )
        return fts, trgm

    fts, trgm = run(with_conn(db, scenario))
    assert fts == 1
    assert trgm is True


def test_invalid_element_link_rejected(db):
    async def scenario(conn):
        doc_id = await new_document(conn)
        el = lexuz.Element("-5", "-1", 1, "ACT_TEXT", "text", "matn", "https://lex.uz/docs/123456789")
        await conn.execute(UPSERT_ELEMENT, *element_row(el, doc_id))

    with pytest.raises(asyncpg.CheckViolationError):
        run(with_conn(db, scenario))


def test_elements_deleted_with_document(db):
    async def scenario(conn):
        doc_id = await new_document(conn)
        el = lexuz.Element("-5", "-1", 1, "ACT_TEXT", "text", "matn", "https://lex.uz/docs/-1#-5")
        await conn.execute(UPSERT_ELEMENT, *element_row(el, doc_id))
        await conn.execute("DELETE FROM hujjatlar WHERE id = $1", doc_id)
        return await conn.fetchval("SELECT count(*) FROM elementlar WHERE document_id = $1", doc_id)

    assert run(with_conn(db, scenario)) == 0


# --- versiyalar -----------------------------------------------------------


def test_versioning_unique_per_token(db):
    async def scenario(conn):
        doc_id = await new_document(conn)
        sql = (
            "INSERT INTO hujjat_versiyalari (document_id, version_token, on_date, text_hash, source_url) "
            "VALUES ($1, $2, $3, $4, $5) ON CONFLICT (document_id, version_token) "
            "DO UPDATE SET text_hash = EXCLUDED.text_hash RETURNING id"
        )
        a = await conn.fetchval(sql, doc_id, "12.12.2026", date(2026, 12, 12), "h1", "u")
        b = await conn.fetchval(sql, doc_id, "12.12.2026 01", date(2026, 12, 12), "h2", "u")
        c = await conn.fetchval(sql, doc_id, "12.12.2026", date(2026, 12, 12), "h3", "u")
        # So'ralgan sana holatidagi versiya
        picked = await conn.fetchval(
            "SELECT version_token FROM hujjat_versiyalari WHERE document_id = $1 AND on_date <= $2 "
            "ORDER BY on_date DESC, version_token DESC LIMIT 1",
            doc_id, date(2026, 12, 31),
        )
        return a, b, c, picked

    a, b, c, picked = run(with_conn(db, scenario))
    assert a == c != b
    assert picked == "12.12.2026 01"


def test_invalid_version_token_rejected(db):
    async def scenario(conn):
        doc_id = await new_document(conn)
        await conn.execute(
            "INSERT INTO hujjat_versiyalari (document_id, version_token, on_date, source_url) "
            "VALUES ($1, '2024-12-01', '2024-12-01', 'u')",
            doc_id,
        )

    with pytest.raises(asyncpg.CheckViolationError):
        run(with_conn(db, scenario))


# --- o'zgarishlar ---------------------------------------------------------


def test_change_log_has_no_duplicates(db):
    async def scenario(conn):
        doc_id = await new_document(conn)
        sql = (
            "INSERT INTO ozgarishlar (document_id, element_id, old_hash, new_hash, change_type) "
            "VALUES ($1, $2, $3, $4, $5) ON CONFLICT DO NOTHING"
        )
        await conn.execute(sql, doc_id, "-1", None, "h1", "qo'shilgan")
        await conn.execute(sql, doc_id, "-1", None, "h1", "qo'shilgan")  # qayta ishga tushish
        await conn.execute(sql, doc_id, "-1", "h1", "h2", "o'zgargan")
        return await conn.fetchval("SELECT count(*) FROM ozgarishlar WHERE document_id = $1", doc_id)

    assert run(with_conn(db, scenario)) == 2


@pytest.mark.parametrize(
    "old_hash,new_hash,change_type",
    [("h1", "h1", "o'zgargan"), (None, "h1", "o'zgargan"), ("h1", None, "qo'shilgan"), ("h1", "h2", "changed")],
)
def test_inconsistent_change_rejected(db, old_hash, new_hash, change_type):
    async def scenario(conn):
        doc_id = await new_document(conn)
        await conn.execute(
            "INSERT INTO ozgarishlar (document_id, element_id, old_hash, new_hash, change_type) "
            "VALUES ($1, '-1', $2, $3, $4)",
            doc_id, old_hash, new_hash, change_type,
        )

    with pytest.raises(asyncpg.CheckViolationError):
        run(with_conn(db, scenario))


# --- foydalanuvchilar, suhbatlar, obunalar, bilimlar ------------------------


def test_user_subscription_and_conversation(db):
    async def scenario(conn):
        tg = 100_000_000 + uuid.uuid4().int % 1_000_000
        await conn.execute(
            "INSERT INTO foydalanuvchilar (telegram_id) VALUES ($1) ON CONFLICT (telegram_id) DO NOTHING", tg
        )
        await conn.execute(
            "INSERT INTO foydalanuvchilar (telegram_id) VALUES ($1) ON CONFLICT (telegram_id) DO NOTHING", tg
        )
        await conn.execute("INSERT INTO obunalar (telegram_id) VALUES ($1)", tg)
        rid = uuid.uuid4()
        await conn.execute(
            "INSERT INTO suhbatlar (request_id, telegram_id, question, retrieved_element_ids) "
            "VALUES ($1, $2, 'savol', $3)",
            rid, tg, [1, 2, 3],
        )
        users = await conn.fetchval("SELECT count(*) FROM foydalanuvchilar WHERE telegram_id = $1", tg)
        today = await conn.fetchval(
            "SELECT count(*) FROM suhbatlar WHERE telegram_id = $1 AND created_at >= date_trunc('day', now())", tg
        )
        with pytest.raises(asyncpg.UniqueViolationError):
            await conn.execute(
                "INSERT INTO suhbatlar (request_id, telegram_id, question) VALUES ($1, $2, 'x')", rid, tg
            )
        return users, today

    assert run(with_conn(db, scenario)) == (1, 1)


def test_subscription_requires_user(db):
    with pytest.raises(asyncpg.ForeignKeyViolationError):
        run(with_conn(db, lambda conn: conn.execute("INSERT INTO obunalar (telegram_id) VALUES (1)")))


def test_knowledge_record_key_unique_and_lex_check_default(db):
    async def scenario(conn):
        sql = (
            "INSERT INTO bilimlar (record_key, topic, text, source) VALUES ($1, $2, $3, $4) "
            "ON CONFLICT (record_key) DO UPDATE SET text = EXCLUDED.text RETURNING id, lex_check_required"
        )
        a = await conn.fetchrow(sql, "bilimlar-bazasi.md#qqs", "QQS chegarasi", "v1", "skill-bilimlar")
        b = await conn.fetchrow(sql, "bilimlar-bazasi.md#qqs", "QQS chegarasi", "v2", "skill-bilimlar")
        return a, b

    a, b = run(with_conn(db, scenario))
    assert a["id"] == b["id"]
    assert a["lex_check_required"] is True


def test_migrations_dir_contains_init():
    assert [m.version for m in migrate_mod.discover()] == ["001_init", "002_hardening", "003_import_rpc", "004_search", "005_search_weights", "006_suhbat_status", "007_yangiliklar"]
    assert Path(migrate_mod.MIGRATIONS_DIR).name == "migrations"
