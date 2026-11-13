# Integration Handoff: Soliq maslahatchi → Marketolog AI

- **Prepared:** 2026-11-12, by inspecting the local checkout, the local `.env` (variable names only), local logs and the GitHub remote.
- **Audience:** the implementation agent of the separate *Marketolog AI* project. That project creates Uzbek accounting marketing content and video prompts, publishes to Telegram/Instagram, and collects customer inquiries.
- **Production access during this handoff:** none.
  - The Supabase database was **not** queried.
  - The bot was **not** started.
  - No Telegram message was sent.
  - Facts about the production database come from code, migrations, `PROGRESS.md` and local logs. Each such fact is marked accordingly.
- **Repository:** https://github.com/ziyodbeksobirov535-dev/soliq-maslahatchi

> Read §10 (limitations) before building anything. The data source is currently **stale and offline** (see §1.4).

---

## 1. Repository state, runtime, startup

### 1.1 Git state (verified 2026-11-12)

| Item | Value |
|---|---|
| Local branch | `claude/ux-yaxshilash` (no upstream configured; it is pushed manually to the remote branch below) |
| HEAD commit | `1ae2b24caf354222e14e68defb14199a0c64b29d` (2026-10-16, "News: detailed update … daily admin report") |
| Remote branch with the same commit | `origin/claude/charming-cori-jsmqbv` = `1ae2b24` |
| GitHub default branch | `main` = `357e863`. It is **48 commits behind** `claude/charming-cori-jsmqbv` and was last merged 2026-09-27. |
| Other remote branch | `origin/claude/wizardly-gauss-wdl68v` = `480ba12` (2026-09-27, deployment phase; older) |
| Working tree | Clean before this file was added. The only change is this file, which is not committed. |
| Stale local branch | Local `claude/charming-cori-jsmqbv` points to an old commit `677e8d8`. **Do not use it.** Use `origin/claude/charming-cori-jsmqbv`. |

**Use commit `1ae2b24`** (`origin/claude/charming-cori-jsmqbv`). Code on `main` lacks the news pipeline fixes, the multi-provider LLM chain, section-level search and everything after 2026-09-27.

### 1.2 Runtime

- **Python:** 3.12.14 in `.venv` (Homebrew Python). `pyproject.toml` requires ≥3.11. The system `python3` is 3.9.6 and **will not work**.
- **Dependencies** (`requirements.txt`): `httpx`, `beautifulsoup4`, `lxml`, `pydantic-settings`, `aiogram 3`, `asyncpg`, `anthropic`, `APScheduler 3`. Dev extra: `pytest`.
- **Database:** PostgreSQL 15+ (production is Supabase Postgres 17, region eu-central-1). Migrations `001`–`014` are applied in production according to `PROGRESS.md`.
- **Timezone:** `Asia/Tashkent` (`TIMEZONE`).

### 1.3 Startup commands

```bash
python main.py --check                       # load settings only
python main.py                               # bot + in-process scheduler (needs TELEGRAM_BOT_TOKEN, SUPABASE_DB_URL)
python -m app.database.migrate --status      # list applied migrations (read-only)
python -m app.health --bot                   # JSON health check; exit 1 on problems
python -m app.collector.jobs {rss|future|refresh|discover|import-found|vocab|reclassify}   # one-off jobs (these WRITE to the DB)
python -m app.ai.console --no-llm "QQS stavkasi qancha?"     # retrieval only, no AI
```

On the owner's Mac, the bot was started detached:

```bash
nohup .venv/bin/python main.py >> .cache/bot.log 2>&1 < /dev/null & disown
```

### 1.4 Current operational status (verified from local process list and logs)

- **The bot and its scheduler are NOT running.**
  - The last start was 2026-10-16 19:24 (+05).
  - The process received SIGTERM at 2026-10-19 00:33 (+05).
  - The last heartbeat was 2026-10-19 00:29 (+05).
  - No `main.py` process existed on 2026-11-12.
- **Nothing in the scheduler has run since 2026-10-19.** That covers RSS, refresh and the daily report. The data is at least ~24 days stale.
- **The Supabase project is on the Free tier.** It paused once already (2026-09-29 → restored 2026-10-12) after 7 days without activity. Its current state is **unverified**. Assume it may be paused.

---

## 2. What works vs. mocked-only vs. unverified

| Capability | Evidence level | Notes |
|---|---|---|
| Lex.uz fetch/parse (`lexuz.py`): documents, cards, versions, RSS, search | **Live-verified** (Sept–Oct 2026) plus fixture tests on real HTML | The parser is built only from real samples in `tests/fixtures/lexuz/` |
| Import into Postgres (`finish_import`), change log `ozgarishlar` | **Live-verified** | Weekly refresh of 494 documents ran 2026-10-18. Example log: `refresh lex_id=-8477023 changed=1` |
| Status re-check for not-yet-effective and textless documents | **Live-verified** 2026-10-18 07:40 | |
| Discovery of older acts (`topilgan_hujjatlar`) and limited import | **Live-verified** | 466 documents and 75 455 elements on 2026-10-12. The weekly refresh on 2026-10-18 covered 494 documents. |
| Retrieval (`search_articles`, reranking, tax-structure routing) | **Live-verified** on a production copy | Internal benchmark (`scripts/sohalar_sinovi.py`): 143/156 questions top-1, 155/156 top-6 (2026-10-13) |
| Q&A with Gemini, citation validation | **Live-verified** via Telegram (2026-10-14..16) | Uzbek and Russian answers |
| RSS ingestion | **Live-verified manually** (last successful run 2026-10-16) | **The scheduled run on 2026-10-17 hung for ~41 h** and blocked every later run (§10, D2) |
| News drafts for textless documents (title-only) | **Live-verified** 2026-10-16 | 15 drafts were sent to the admin |
| `newsworthy()` admin-queue filter | Evaluated offline on those 15 real items (6 kept); unit tests | Never ran in production after deploy |
| "Detailed update" news when text appears later (`prepare_news_updates`) | **Mocked/DB tests only** | |
| `/eslatma` admin notes, 24 h answer cache | **Mocked/DB tests only** | |
| Daily admin report | **Live**: succeeded 2026-10-18 | It failed on 2026-10-17 because a DB connection dropped |
| Historical (point-in-time) legal text | **Not implemented**: `versiya_elementlari` is never populated | Historical questions return `historical_unavailable` |
| Server deployment (systemd unit, backup, healthcheck scripts in `deploy/`) | **Written, never deployed** | |
| Telegram channel posting (`NEWS_CHANNEL`), payments | Code and tests exist; `NEWS_CHANNEL` and payment token are unset locally | Never used live |
| `app/collector/marketolog.py` | **Does not exist** on any local or remote branch (checked all refs and history) | See §11 |

---

## 3. Entry points

| Concern | Entry point | File |
|---|---|---|
| RSS collection | `process_rss(pool, client, llm, today)` → keyword filter → optional LLM classification → full import of relevant documents (≤20 per run) → `yangiliklar` upsert | `app/collector/news.py` |
| Recent news (read) | `recent_news(conn, today, days=7, limit=15)` | `app/collector/news.py` |
| Document refresh | `refresh_document()`, `weekly_refresh_job()`, `future_recheck_job()`, `tracked_documents()` | `app/collector/jobs.py` |
| Import and diff | `import_document(conn, doc, card, today)` → SQL `finish_import()` (one transaction: upsert document, diff elements, write `ozgarishlar`, upsert version row, compute sections) | `app/collector/importer.py`, `migrations/009_bolimlar.sql` |
| Discovery of older acts | `discover()`, `import_pending()` | `app/collector/discovery.py` |
| Core documents list | `CORE_DOCUMENTS` (Tax, Labour, Civil I/II, Customs codes; Accounting law) | `app/collector/core_documents.py` |
| Lex.uz client/parser | `LexUzClient`, `load()`, `load_card()`, `parse_doc()`, `parse_card()`, `parse_rss()`, `resolve_status()`, `pick_version()` | `lexuz.py` (do not refactor; other modules depend on it) |
| Retrieval (no AI) | `retrieve(conn, question, today)` → `SearchResult(hits, direct_article, status)`; `search_articles()`; SQL `search_articles(...)` | `app/retrieval/search.py`, `migrations/014_qidiruv_tezligi.sql` |
| Exact provision fetch | `get_article(conn, number, lex_id)`, `get_section(conn, lex_id, birlik)` | `app/retrieval/articles.py` |
| Answer generation | `answer_question()` (AI) / `answer_without_llm()` | `app/services/answer.py` |
| Citation validation | `validate_answer(output, articles)`: accepts only `source_id`s present in the context, strips every model-written URL, and takes links from the DB | `app/ai/validation.py` |
| News/change message drafts | `build_news_draft()`, `build_change_draft()`, `prepare_news()`, `prepare_changes()`, `publish()` | `app/services/xabarlar.py` |

---

## 4. Database tables

Migrations live in `migrations/`. RLS is enabled on every table with no policies, so the Supabase anon/authenticated REST API returns nothing. The backend connects directly with `SUPABASE_DB_URL`.

### 4.1 Legal content (safe to export: public Lex.uz data)

**`hujjatlar`** — one row per Lex.uz act.

| Field | Meaning |
|---|---|
| `lex_id` | Lex.uz document ID (text, may be negative, e.g. `-4674902`). Stable key. |
| `name`, `type`, `number` | Title; form (from the card, Russian, e.g. `Указ`, or the page header label); number (`PF-100`, `100`, …) |
| `adoption_date`, `effective_date` | From the Lex.uz card (preferred) or the page header. **Document-level only.** |
| `status` | `amalda` (in force), `kuchga_kirmagan` (not yet effective), `kuchini_yoqotgan` (repealed), `noma'lum` (unknown). Derived by `lexuz.resolve_status(card, today)`. |
| `status_raw` | Card value as published (e.g. `Действующий`) |
| `status_checked_at` | When the card was last read |
| `current_version` | Lex.uz version token of the stored text, `DD.MM.YYYY` or `DD.MM.YYYY NN` |
| `url`, `source_url` | Canonical URL; versioned URL (`?ONDATE=<token>`) |
| `last_loaded`, `last_successful_load` | Fetch timestamps. Use `last_successful_load` for staleness. |
| `content_hash` | sha256 over (element_id, text) of all elements |
| `text_available` | `false` if Lex.uz published only requisites so far (common for the first days) |
| `repeal_date` | Card repeal date, if any |

**`elementlar`** — current text only, one row per Lex.uz paragraph or element.

| Field | Meaning |
|---|---|
| `element_id` | Lex.uz anchor ID (`-8237064`, `edi-8444418`). Unique per document. Basis of citation links. |
| `kind` | `title`, `header`, `article` (article heading), `text`, `table`, `footnote`, `amendment` (source-of-change note), `edition_note` ("see previous edition"), `lexuz_comment`, `other` |
| `type` | Raw Lex.uz CSS class |
| `modda_raqami`, `modda` | Article number (`461`, `121-1`) and heading text; NULL outside articles |
| `birlik`, `birlik_nomi` | Section key and name for acts without articles (decrees, resolutions). Computed by `hisobla_birliklar()`. |
| `bob`, `element_path` | Chapter / structural path text |
| `text`, `text_hash` | Exact element text (Uzbek Latin in most acts); sha256 of `text` |
| `amendment_note` | Free text of the amendment/edition notes attached to this element (e.g. "…PF-175-sonli Farmoni tahririda…") |
| `future_version` | Version token of a **future** edition announced on Lex.uz for this element (pending amendment) |
| `link` | Canonical deep link `https://lex.uz/docs/<lex_id>#<element_id>`. Always built by the parser, never by AI. |

**`hujjat_versiyalari`** stores `(document_id, version_token, on_date, text_hash, loaded_at, source_url)` for each version actually loaded. It holds metadata only.

**`versiya_elementlari`** is meant for historical text but is **always empty** (§10, D4).

**`ozgarishlar`** — change log written by `finish_import` on re-import of a document that already had elements.

| Field | Meaning |
|---|---|
| `element_id` | Affected element |
| `change_type` | `qo'shilgan` (added), `o'zgargan` (changed), `o'chirilgan` (removed) |
| `old_hash`/`new_hash`, `old_text`/`new_text` | Before/after. A unique key prevents duplicate rows. |
| `detected_at` | When the refresh noticed it. This is **not** the legal effective date. |
| `xabar_id` | The change message it was bundled into |

**`yangiliklar`** — Lex.uz RSS items, upserted by `lex_id`.

| Field | Meaning |
|---|---|
| `title`, `doc_type`, `number`, `adoption_date`, `effective_date`, `url`, `pub_date` | From RSS |
| `keyword_hits` | Matched keyword prefixes |
| `relevant` | Accounting/tax relevance |
| `relevance_method` | `keyword` or `llm` |
| `topics`, `summary` | **AI-generated** when `llm`; not evidence |
| `imported` | Whether the full text was imported into `hujjatlar`/`elementlar` |

**`topilgan_hujjatlar`** — older in-force acts found by Lex.uz search.

| Field | Meaning |
|---|---|
| `queries`, `keyword_hits`, `relevant` | Search provenance and relevance |
| `imported`, `import_attempts`, `last_error` | Import state |

**`bilimlar`** — internal knowledge records. These are pointers, not sources.

- Types (`turi`): `imtiyoz` (official tax-benefit list) and `bilim` (curated notes, `record_key` `skill:…` or `admin:eslatma:N`).
- Columns `lex_id`/`modda_raqami`/`hujjat` point to the real provision.
- Treat the content as guidance, never as a citation.

**`sozlar`** is a spelling vocabulary. It has no export value.

### 4.2 Operational and messaging (export only with care)

**`xabarlar`** — prepared Telegram messages.

| Field | Meaning |
|---|---|
| `turi` | `yangilik` or `ozgarish` |
| `kalit` | Idempotency key: `yangilik:<lex_id>`, `yangilik-batafsil:<lex_id>`, `ozgarish:<document_id>:<max change id>` |
| `matn` | Telegram HTML, AI- or template-written. **Not evidence.** |
| `usul` | `llm` or `matndan` |
| `holat` | `kutilmoqda`, `tasdiqlandi`, `bekor`, `yuborildi` |
| `hal_qilgan` | Admin Telegram ID. **Personal.** |

`holat IN ('tasdiqlandi','yuborildi')` is a useful "human-approved topic" signal.

### 4.3 Personal data — DO NOT EXPORT

These tables contain Telegram IDs, questions, payments and delivery records:

- `foydalanuvchilar`
- `suhbatlar` (raw user questions and answers)
- `obunalar`
- `tolovlar`
- `xabar_yuborishlar`
- `eslatmalar_yuborilgan`

Marketolog must collect its own customer inquiries; it must not reuse these tables.

---

## 5. Retrieving recent news and the exact supporting provisions

All queries below are **read-only**. Run them in a `BEGIN TRANSACTION READ ONLY` transaction (or `SET default_transaction_read_only = on`).

### 5.1 Recent relevant news with document state

```sql
SELECT y.lex_id, y.title, y.doc_type, y.number, y.adoption_date, y.effective_date, y.url, y.pub_date,
       y.keyword_hits, y.relevance_method, y.topics, y.summary, y.imported,
       h.status, h.status_raw, h.status_checked_at, h.current_version, h.text_available,
       h.repeal_date, h.last_successful_load, h.content_hash
FROM yangiliklar y
LEFT JOIN hujjatlar h ON h.lex_id = y.lex_id
WHERE y.relevant
  AND coalesce(y.pub_date, y.created_at) >= now() - make_interval(days => $1)
ORDER BY coalesce(y.pub_date, y.created_at) DESC;
```

Optionally keep only items an admin approved:

```sql
AND EXISTS (SELECT 1 FROM xabarlar x WHERE x.kalit = 'yangilik:' || y.lex_id AND x.holat IN ('tasdiqlandi','yuborildi'))
```

`app.services.xabarlar.newsworthy(row)` is a stricter Python filter used for the admin queue:

- Presidential acts, laws and codes always pass.
- Cabinet resolutions pass only with a core tax/accounting keyword.
- Ministry acts pass only with that keyword in the title.

### 5.2 Provisions of a news document (evidence text)

```sql
SELECT e.element_id, e.kind, e.modda_raqami, e.birlik, e.birlik_nomi, e.element_path,
       e.text, e.text_hash, e.link, e.amendment_note, e.future_version
FROM elementlar e JOIN hujjatlar h ON h.id = e.document_id
WHERE h.lex_id = $1 AND e.kind IN ('article','text','table')
ORDER BY e.order_no;
```

If this returns zero rows and `hujjatlar.text_available = false`, the text is not yet published on Lex.uz. Do not invent content.

### 5.3 Provisions supporting a proposed content topic (no AI needed)

```python
from app.retrieval.search import retrieve
from app.retrieval.articles import get_article, get_section

result = await retrieve(conn, "aylanmadan olinadigan soliq stavkasi", today)   # Uzbek (Latin/Cyrillic) or Russian
# result.status: ok | not_found | needs_clarification | historical_unavailable
for hit in result.hits:          # ranked; only documents with status 'amalda'
    hit.lex_id, hit.document_name, hit.modda_raqami or hit.birlik_nomi, hit.heading_link, hit.score
    for m in hit.matched:        # matched elements = exact evidence excerpts
        m.element_id, m.text, m.link
article = await get_article(conn, "461", "-4674902")   # full article: heading, body, notes (amendments)
```

**Rules for marketing use:**

1. Cite `link` values from the DB only.
2. Quote `text` verbatim as evidence.
3. Treat any AI-written claim as a draft that needs human review. Citation validation proves only that the cited element was **in the context**, not that it **supports** the claim (§10, D7).

---

## 6. Amendments, effective dates, repeal, staleness

| Concept | Representation today | Gaps |
|---|---|---|
| **Document effective date** | `hujjatlar.effective_date`; status `kuchga_kirmagan` until then. Re-checked daily at 07:40 by `future_recheck_job`. | No per-provision effective dates. Phrases like "2026-yil 1-iyundan" exist only inside `text`. |
| **Document repeal** | `status = 'kuchini_yoqotgan'` (card says repealed, or `repeal_date ≤ today`); `repeal_date` | Repealed documents are **excluded from search** but kept in the DB |
| **Unknown status** | `noma'lum` when the card is missing or ambiguous; excluded from search | |
| **Current edition** | `hujjatlar.current_version` (token) + `source_url`; one `hujjat_versiyalari` row per loaded token | Only the current text is stored |
| **Past amendment of a provision** | `elementlar.amendment_note` (free text, e.g. "…PF-175-sonli Farmoni tahririda…") and separate `kind='amendment'`/`'edition_note'` elements | The amending act's lex_id is parsed (`Element.refs`) but **not persisted** |
| **Pending (future) amendment** | `elementlar.future_version` = token of the announced future edition | Future text is not loaded |
| **Text changes detected by refresh** | `ozgarishlar` rows (`qo'shilgan`/`o'zgargan`/`o'chirilgan`, old/new text, `detected_at`) | Only for documents refreshed after their first import. `detected_at` ≠ legal date. If Lex.uz renumbers element IDs, this shows as remove + add. |
| **Repealed provision inside an in-force act** | The element disappears from `elementlar`; an `o'chirilgan` row appears in `ozgarishlar` | No "repealed" flag on elements |
| **Staleness** | `hujjatlar.last_successful_load`, `status_checked_at`; `yangiliklar.updated_at` | Refresh cadence is weekly (Sunday 03:20) for tracked documents. **The current data was last refreshed 2026-10-18** (bot down since 2026-10-19). |
| **Code vs. newer decree** | Example: Tax Code 461 still says 1 bn UZS while PF-100 item 2 sets 12 000 BHM from 2026-06-01. Handled by curated `bilimlar` notes plus prompt rule 5. | Not machine-detectable in data; needs human review |

---

## 7. Operations without paid AI APIs

Current local configuration:

- `LLM_PROVIDER=gemini` (Google AI Studio free tier).
- `LLM_FALLBACKS=groq:fast` (Groq free tier; used only for short tasks).
- `ANTHROPIC_API_KEY` is set but unused unless `LLM_PROVIDER=anthropic`.

| Works with **no AI at all** | Needs an AI provider (free tier currently) |
|---|---|
| Lex.uz fetch/parse, RSS ingestion (keyword-only relevance: only "strong" keywords count; `topics`/`summary` empty) | RSS relevance for "domain" keywords, `topics`, `summary` |
| Import, diff, weekly refresh, discovery, status re-check | Query rewriting (better recall) |
| Retrieval (`retrieve`, `search_articles`, `get_article`, `get_section`), `/modda`, "sources only" answers | Natural-language answers with validated citations |
| Change messages (`build_change_draft`, template) | News digest with AI wording (`usul='llm'`) |
| News drafts from document text (`NEWS_REQUIRE_AI=false`) and title-only drafts for textless acts | — |

**A read-only export (§11) needs no AI.**

---

## 8. Scheduling, deployment, local Mac dependencies

All jobs run **inside the bot process** (APScheduler, `Asia/Tashkent`). They have `max_instances=1`, `coalesce=True` and a 1 h misfire grace. When the bot is down, nothing runs.

| Job | Schedule | Writes |
|---|---|---|
| `rss` | 07:10, 12:10, 17:10 | `yangiliklar`, imports |
| `future_recheck` | 07:40 | status / text of not-yet-effective and textless (≤30 days) acts |
| `import_found` | 08:10 (`DISCOVERY_DAILY_LIMIT`=50) | imports |
| `discover` | Sat 04:10 | `topilgan_hujjatlar` |
| `weekly_refresh` | Sun 03:20 | all tracked documents, `ozgarishlar` |
| `publish` | every 15 min, effective 09:00–20:00 | `xabarlar`; sends to admins (`NEWS_AUDIENCE=admins`) |
| `reminders` | 09:30 | tax-calendar reminders to opted-in users |
| `daily_report` | 20:05 | admin report (read-only DB) |
| `heartbeat` | 5 min | `.cache/heartbeat` |

**Deployment today:**

- The bot runs on the owner's MacBook via `nohup` (§1.3), with the database on Supabase Free.
- `deploy/soliq-bot.service` (systemd), `deploy/backup.sh` (pg_dump) and `deploy/healthcheck.sh` exist but are **not deployed** to any server.

**Mac dependencies and risks:**

- Mac sleep or shutdown stops the bot and every job. After 7+ inactive days, Supabase Free pauses.
- Network drops on the Mac caused DB timeouts and a hung job (§10, D2).
- `.cache/` holds the log (`bot.log`), heartbeat and Lex.uz HTML cache. It is git-ignored.
- A local PostgreSQL 17 (Homebrew, port 5433) is used **only for tests**:

  ```bash
  LC_ALL=en_US.UTF-8 /opt/homebrew/opt/postgresql@17/bin/pg_ctl -D /opt/homebrew/var/postgresql@17 \
    -o "-p 5433 -c listen_addresses=127.0.0.1" -l /opt/homebrew/var/postgresql@17/test-server.log start
  ```

- Git pushes from this Mac need the Homebrew `gh` credential helper. The global gitconfig points to a removed temporary `gh` binary.

---

## 9. Tests and meaningful checks

There are 22 test files and 372 test functions. Many are parametrized. **Last full run: 549 passed on 2026-10-16 at commit `1ae2b24`**, on Python 3.12 with local Postgres 17. The suite was **not re-run** for this handoff.

| Category | Files |
|---|---|
| Pure / no DB | `test_lexuz_parser`, `test_lexuz_fetch` (fake HTTP), `test_collector` (RSS/search/discovery fixtures, scheduler), `test_chain`, `test_gemini`, `test_openai_compat` (fake HTTP), `test_kalkulyator`, `test_structure`, `test_sinov` |
| Need `TEST_DATABASE_URL` (a temporary DB is created and dropped) | `test_database` (migrations), `test_import_and_article`, `test_sections`, `test_search`, `test_answer` (fake LLM), `test_bot` (real aiogram dispatcher, fake Telegram session), `test_xabarlar` (fake bot), `test_bilimlar`, `test_imtiyozlar`, `test_kalendar`, `test_obuna`, `test_references` |
| Live / benchmark (needs a DB with real data; reads only) | `scripts/sohalar_sinovi.py` (156 retrieval questions), `scripts/sinov_javob.py`, `python -m app.ai.console --no-llm` |

**All LLM and Telegram behaviour in tests is mocked. There is no CI** (no `.github/`).

```bash
.venv/bin/python -m pytest -q                                                             # DB tests are skipped
TEST_DATABASE_URL=postgresql://<user>@127.0.0.1:5433/postgres .venv/bin/python -m pytest -q   # full suite (local test DB only)
.venv/bin/python -m pytest -q tests/test_lexuz_parser.py tests/test_collector.py          # parser + collector
```

**Never point `TEST_DATABASE_URL` at production.** The fixture creates and drops databases.

---

## 10. Known limitations, defects, incomplete work

**Operational and data freshness**

- **D1 — Source offline and stale.**
  - The bot has been stopped since 2026-10-19. The last refresh was 2026-10-18; the last successful RSS run was 2026-10-16 (manual).
  - The Supabase state is unknown and possibly paused.
  - Marketolog must check freshness before every use (§12 `stale_source`).
- **D2 — RSS job hang.**
  - The scheduled `rss_job` started 2026-10-17 07:35 and blocked on a DB call during network trouble. It never finished.
  - With `max_instances=1`, all later RSS runs were skipped ("maximum number of running instances reached") until SIGTERM ~41 h later.
  - The pool has `command_timeout=60`, but connection release hung. There is no overall job timeout.
  - **Not fixed.**
- **D3 — Laptop dependency.** There is no server deployment, no backups are running and there is no monitoring alerting.

**Data model gaps**

- **D4 — No historical text.**
  - `versiya_elementlari` is never written, so point-in-time text is unavailable.
  - Previous wording survives only in `ozgarishlar.old_text`.
  - Side effect: if `versiya_elementlari` ever became non-empty, `retrieve()` would search *current* text for historical questions. That would be wrong; the guard checks only for table emptiness.
- **D5 — Dates and repeal granularity.**
  - There are no provision-level effective or repeal dates.
  - Amending-act references are not persisted (`Element.refs` is dropped in `element_payload`).
  - `amendment_note` is unstructured text.
- **D6 — Element IDs come from Lex.uz.** If Lex.uz re-anchors an element, it shows as remove + add. There is no fuzzy matching.

**Correctness and relevance**

- **D7 — Citation validation is structural only.**
  - It checks ID membership and strips URLs.
  - It does **not** check that the quoted element entails the claim. AI answers can still misstate thresholds; one real case was the Tax Code vs. PF-100 threshold, now mitigated by a curated note.
- **D8 — Relevance is heuristic.**
  - Keyword lists (`news.KUCHLI_SOZLAR`, `SOHA_SOZLARI`) and an optional LLM decide relevance.
  - `topics`/`summary` are AI output.
  - The `newsworthy()` filter is not stored in the DB.
  - Some Lex.uz titles and fields are Cyrillic or Russian (`status_raw`, card `form`).
- **D9 — Textless acts.**
  - New acts are often published without text for days. `text_available=false` and there are no elements.
  - A title-only draft is produced after `NEWS_TEXT_WAIT_DAYS`.
  - A later "detailed update" exists but is tested only with mocks.

**Infrastructure and process**

- **D10 — No read-only DB role.** Only the owner connection string exists. Creating a role is a write operation that needs owner approval.
- **D11 — Supabase Free CPU credits.** Heavy unindexed queries hit `statement_timeout` (2026-10-13). Exports should use indexed filters and small batches.
- **D12 — Branch confusion.** `main` is 48 commits behind, and the local branch name differs from the remote branch name.
- **D13 — No Marketolog code exists** (no `app/collector/marketolog.py` on any branch). There is therefore nothing to review for provision selection, revision handling or duplicate prevention. Existing building blocks:
  - Duplicate prevention: `yangiliklar.lex_id` UNIQUE, `xabarlar.kalit` UNIQUE, `ozgarishlar` unique (document, element, old_hash, new_hash).
  - Revision tracking: `current_version`, `content_hash`, `text_hash`.
  - Provision selection: `retrieve()`.

---

## 11. Integration options and recommendation

| Option | Pros | Cons |
|---|---|---|
| **A. Read-only export CLI in this repo → versioned JSONL files** | No production writes, no new credentials for Marketolog, explicit schema, easy to diff/replay, excludes personal data by construction | Needs a small new module and periodic runs |
| B. Dedicated read-only Postgres role used by Marketolog directly | Live data | Needs a DB write to create the role (owner approval), couples Marketolog to internal schema, exposes RLS-bypassing connection |
| C. Import this Python package into Marketolog | Reuses `retrieve()` | Tight coupling, shared dependencies, still needs DB credentials |
| D. Supabase REST | — | RLS blocks anon; the service-role key bypasses everything. **Do not share it.** |
| E. Read the bot's Telegram messages/channel | — | Lossy HTML, no evidence or IDs; the channel is not even configured |

**Status (2026-11-14): Option A is implemented** as `app/export/legal_feed.py` (`python -m app.export.legal_feed --since 7d --out <dir>`). It emits `news_item` and `provision_changed` events, keeps `event_revision` state in `.cache/legal_feed_state.json` (do not delete it: losing it resets revisions to 1 and Marketolog will reject changed content under the same revision), and writes `<file>.sha256` before the atomically renamed `.jsonl`. `document_snapshot`, `provision_snapshot` (topic mode) and `status_changed` are not emitted yet. A live read-only run on 2026-11-14 produced 8 `news_item` events, all accepted by Marketolog's `packets.validate`.

**Recommendation: Option A, minimal and read-only.**

1. **New module** `app/export/legal_feed.py`, with CLI `python -m app.export.legal_feed --since 7d --out exchange/` (to be implemented):
   - opens one connection with `default_transaction_read_only=on`;
   - reads only the tables in §4.1;
   - emits `legal-feed-v1-<UTC timestamp>.jsonl` plus a `manifest.json` (schema version, commit, counts, max `last_successful_load`, generation time, sha256 of the file).
2. **Contents:**
   - recent relevant news (§5.1);
   - for each imported document, its provisions (`article`/`text`/`table` elements; optionally only items whose text matches the news keywords);
   - `ozgarishlar` rows detected since `--since`;
   - status changes.
3. **Optional topic mode:** `--topic "<Uzbek query>"` uses `retrieve()` (no AI) and emits `provision_snapshot` events for the top hits.
4. **Safeguards:**
   - No personal tables, no `xabarlar.matn`/`hal_qilgan`.
   - No AI calls.
   - No Telegram.
   - Deterministic IDs (§12) so re-runs are idempotent.
5. **Run it** manually first, from the owner's machine, against a **restored or confirmed-active** database. Schedule it only after server deployment.
6. **Marketolog side:** treat every event as **input for a human-reviewed draft**, never as an auto-publishable legal statement.

---

## 12. Proposed exchange format — `soliq.legal-feed/1.0`

- **Encoding:** UTF-8 JSON Lines, one event per line.
- **Times:** ISO 8601 with offset. Dates are `YYYY-MM-DD`.
- **Text:** exact Lex.uz text, never paraphrased.

### 12.1 Envelope

```jsonc
{
  "schema": "soliq.legal-feed/1.0",
  "event_id": "slf1-<32 hex>",            // sha256("soliq.legal-feed/1|type|lex_id|version_token|element_id|hash")[:32]
  "event_type": "news_item | document_snapshot | provision_snapshot | provision_changed | status_changed",
  "event_revision": 1,                      // +1 when the same event_id is re-emitted with corrected metadata
  "emitted_at": "...",
  "producer": {"system": "soliq-maslahatchi", "commit": "1ae2b24", "exporter_version": "0.1.0"},
  "document": {
    "lex_id": "...", "title": "...", "doc_type": "...", "doc_form_raw": "...", "number": "...",
    "adoption_date": "...", "effective_date": "...", "repeal_date": null,
    "status": "amalda | kuchga_kirmagan | kuchini_yoqotgan | noma'lum", "status_raw": "...",
    "status_checked_at": "...", "url": "...",
    "version": {"token": "...", "date": "...", "url": "...", "content_hash": "..."},
    "text_available": true, "last_successful_load": "..."
  },
  "news": {"pub_date": "...", "relevance_method": "keyword | llm", "keyword_hits": [], "topics": [],
           "ai_summary": null, "admin_approved": false},
  "provisions": [{
    "element_id": "...", "kind": "text", "unit": {"type": "article | section", "article_number": null,
    "section_key": "...", "section_name": "..."}, "path": "...",
    "evidence_text": "...", "text_hash": "...", "link": "...",
    "amendment_note": null, "amended_by": [], "future_version_token": null,
    "provision_effective_date": null,
    "change": {"type": "added | changed | removed", "old_hash": "...", "new_hash": "...",
               "old_text": "...", "detected_at": "..."}
  }],
  "retrieval": {"retrieved_at": "...", "method": "db_snapshot | retrieve | lexuz_cache",
                "query": null, "score": null},
  "uncertainty": {"flags": []}
}
```

**Uncertainty flags:**

| Flag | Meaning |
|---|---|
| `text_not_published` | No text available yet |
| `status_unknown` | Document status is unknown |
| `not_yet_effective` | Effective date is in the future |
| `future_amendment_pending` | `future_version` is set |
| `repealed` | The document or provision is repealed |
| `stale_source` | `last_successful_load` older than 8 days, or the export source is older than the consumer's threshold |
| `keyword_relevance_only` | Relevance came from keywords only |
| `ai_summary_unverified` | The summary is AI output |
| `code_may_conflict_with_decree` | A curated note exists for this topic |
| `historical_text_unavailable` | Point-in-time text is not stored |
| `element_renumbering_possible` | A remove + add pair in the same document within one refresh |
| `citation_not_semantically_verified` | Always set for any AI-derived claim |
| `synthetic_fixture` | Test data only; consumers must never publish it |

### 12.2 Field availability

| Field | Status | Source |
|---|---|---|
| `lex_id`, `title`, `doc_type`, `number`, `adoption_date`, `effective_date`, `repeal_date`, `status`, `status_raw`, `status_checked_at`, `url` | **Available now** | `hujjatlar` / `yangiliklar` |
| `version.token`, `version.url`, `version.content_hash`, `text_available`, `last_successful_load` | **Available now** | `hujjatlar.current_version`, `source_url`, `content_hash`, … |
| `version.date` | **Available now** | `hujjat_versiyalari.on_date` or `lexuz.version_date(token)` |
| `news.*` (`pub_date`, `relevance_method`, `keyword_hits`, `topics`, `ai_summary`) | **Available now** | `yangiliklar` |
| `news.admin_approved` | **Derivable now** | `xabarlar.holat` by `kalit` |
| `provisions[].element_id/kind/path/evidence_text/text_hash/link/amendment_note/future_version_token`, `unit.*` | **Available now** | `elementlar` |
| `provisions[].change.*` | **Available now** for refreshed documents | `ozgarishlar` |
| `retrieval.query/score` (topic mode) | **Available now** via `retrieve()` | runtime |
| `event_id`, `event_revision`, `emitted_at`, `producer`, `manifest` | **Requires implementation** | exporter |
| `retrieval.retrieved_at` per event | **Requires implementation**. Today only document-level `last_successful_load`. | exporter |
| Most `uncertainty.flags` | **Derivable**, but the logic must be implemented in the exporter | computed |
| `provisions[].amended_by` (lex_id of the amending act) | **Requires implementation** (persist `Element.refs` or parse `amendment_note`) | parser + migration |
| `provisions[].provision_effective_date` | **Requires implementation** (text extraction; low reliability). Leave `null`. | — |
| Historical point-in-time `evidence_text` | **Requires implementation** (populate `versiya_elementlari`) | collector |
| `status_changed` events | **Requires implementation**. Status history is not stored, only the current status plus `status_checked_at`. | migration/exporter |

**Idempotency and revisions:**

- Consumers dedupe on `event_id`.
- A changed provision text yields a new `text_hash`, therefore a new `event_id`. The old event stays valid as history.
- The same `event_id` with a higher `event_revision` supersedes metadata only (e.g. a corrected status).

### 12.3 Example grounded in real public data (historical snapshot)

> **Provenance:**
> - Built offline by parsing two public Lex.uz HTML pages from this machine's cache (`.cache/lexuz/`), fetched **2026-10-13T11:56+05:00**: the PF-100 document page and its card.
> - **This is not a new legal update.** The act was adopted 2026-05-26.
> - Status `amalda` was resolved on 2026-10-13 and has **not** been re-verified since. Re-fetch from Lex.uz before any use.
> - `event_id` was computed with the proposed formula. Fields marked "requires implementation" are filled as the exporter would fill them.

```json
{
  "schema": "soliq.legal-feed/1.0",
  "event_id": "slf1-07c228e4b39acdd693beb3c4513972e7",
  "event_type": "provision_snapshot",
  "event_revision": 1,
  "emitted_at": "2026-11-12T00:00:00+05:00",
  "producer": {"system": "soliq-maslahatchi", "commit": "1ae2b24", "exporter_version": "example"},
  "document": {
    "lex_id": "-8236831",
    "title": "Kichik biznes subyektlarining oʻsishi uchun yanada qulay iqtisodiy va maʼmuriy shart-sharoitlar yaratish toʻgʻrisida",
    "doc_type": "Oʻzbekiston Respublikasi Prezidentining Farmoni",
    "doc_form_raw": "Указ",
    "number": "PF-100",
    "adoption_date": "2026-05-26",
    "effective_date": "2026-05-28",
    "repeal_date": null,
    "status": "amalda",
    "status_raw": "Действующий",
    "status_checked_at": "2026-10-13T11:56:06+05:00",
    "url": "https://lex.uz/docs/-8236831",
    "version": {"token": "28.08.2026", "date": "2026-08-28",
                "url": "https://lex.uz/docs/-8236831?ONDATE=28.08.2026",
                "content_hash": "88d0cfb7648da142465148810ec03cd24c74bc1477980928c587c07a80a30522"},
    "text_available": true,
    "last_successful_load": "2026-10-13T11:56:06+05:00"
  },
  "news": null,
  "provisions": [{
    "element_id": "-8237064",
    "kind": "text",
    "unit": {"type": "section", "article_number": null, "section_key": null,
             "section_name": "II. Biznes oʻsishini ragʻbatlantirish va umumiy soliq rejimiga oʻtishni yumshatish"},
    "path": "II. Biznes oʻsishini ragʻbatlantirish va umumiy soliq rejimiga oʻtishni yumshatish",
    "evidence_text": "2. 2026-yil 1-iyundan boshlab soliq solishning umumbelgilangan tartibiga oʻtish uchun belgilangan chegaraviy miqdor bazaviy hisoblash miqdorining oʻn ikki ming baravari etib belgilansin.",
    "text_hash": "962a44bbea78801f887531c5adaea09ae5c30fff923acb2bc9ae666e2f2758d9",
    "link": "https://lex.uz/docs/-8236831#-8237064",
    "amendment_note": null,
    "amended_by": [],
    "future_version_token": null,
    "provision_effective_date": null,
    "change": null
  }],
  "retrieval": {"retrieved_at": "2026-10-13T11:56:06+05:00", "method": "lexuz_cache", "query": null, "score": null},
  "uncertainty": {"flags": ["stale_source", "code_may_conflict_with_decree"]}
}
```

**Notes on the example:**

- `section_key` is `null` because section keys are computed in the DB (`hisobla_birliklar`), which was not queried.
- `stale_source` is set because the page was fetched 30 days ago.
- `code_may_conflict_with_decree` is set because Tax Code art. 461 still states 1 bn UZS. A curated note in `skill-bilimlar/loyiha-tasdiqlangan-bilimlar.md` covers this.
- The provision text itself says "from 2026-06-01". `provision_effective_date` stays `null` because the system does not extract it.

**Revision illustration from the same cached page** (real data, same caveats):

- Element `-8444419` (item 3 "a", paragraph ii) carries the amendment note: "(3-band “a” kichik bandining ii xatboshisi … 2026-yil 27-avgustdagi PF-175-sonli Farmoni tahririda — … 28.08.2026-y., 06/26/175/0878-son)".
- The page lists versions `28.08.2026` and `28.05.2026`.
- The parser saw a link to the amending act (`https://lex.uz/docs/8442717?ONDATE=28.08.2026 00#8443063`), but this link is **not stored** in the DB today. This is why `amended_by` requires implementation.

### 12.4 Synthetic fixture (NOT real data)

> **SYNTHETIC — for parser and contract tests only. Not a legal update. IDs and text are invented.**

```json
{"schema":"soliq.legal-feed/1.0","event_id":"slf1-00000000000000000000000000000001","event_type":"provision_changed","event_revision":1,"emitted_at":"2026-01-01T00:00:00+05:00","producer":{"system":"soliq-maslahatchi","commit":"0000000","exporter_version":"fixture"},"document":{"lex_id":"-1","title":"SYNTHETIC TEST DOCUMENT","doc_type":"TEST","doc_form_raw":null,"number":"TEST-1","adoption_date":"2026-01-01","effective_date":"2026-02-01","repeal_date":null,"status":"kuchga_kirmagan","status_raw":null,"status_checked_at":"2026-01-01T00:00:00+05:00","url":"https://lex.uz/docs/-1","version":{"token":"01.01.2026","date":"2026-01-01","url":"https://lex.uz/docs/-1?ONDATE=01.01.2026","content_hash":"0000"},"text_available":true,"last_successful_load":"2026-01-01T00:00:00+05:00"},"news":null,"provisions":[{"element_id":"-2","kind":"text","unit":{"type":"article","article_number":"1","section_key":null,"section_name":null},"path":"","evidence_text":"SYNTHETIC TEXT","text_hash":"1111","link":"https://lex.uz/docs/-1#-2","amendment_note":null,"amended_by":[],"future_version_token":null,"provision_effective_date":null,"change":{"type":"changed","old_hash":"2222","new_hash":"1111","old_text":"SYNTHETIC OLD TEXT","detected_at":"2026-01-01T00:00:00+05:00"}}],"retrieval":{"retrieved_at":"2026-01-01T00:00:00+05:00","method":"db_snapshot","query":null,"score":null},"uncertainty":{"flags":["not_yet_effective","synthetic_fixture"]}}
```

---

## Environment variables (names and purpose only; no values)

| Variable | Purpose |
|---|---|
| `SUPABASE_DB_URL` | Postgres connection string (owner role; RLS bypass). **Secret.** Required by the bot, jobs and the exporter. |
| `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY` | Supabase project URL; service key for the REST import path (unset locally). **Key is secret.** |
| `TELEGRAM_BOT_TOKEN` | Bot token. **Secret.** Not needed for the export. |
| `ADMIN_TELEGRAM_IDS` | Admin user IDs (personal data) |
| `LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`, `LLM_MAIN_MODEL`, `LLM_FAST_MODEL` | Primary AI provider (currently Gemini). Key is **secret**. |
| `LLM_FALLBACKS`, `GROQ_API_KEY`, `GROQ_MAIN_MODEL`, `GROQ_FAST_MODEL`, `OPENROUTER_API_KEY`, `OPENROUTER_MAIN_MODEL`, `OPENROUTER_FAST_MODEL` | Fallback AI chain. Keys are **secret**. |
| `ANTHROPIC_API_KEY`, `ANTHROPIC_MAIN_MODEL`, `ANTHROPIC_FAST_MODEL`, `ANTHROPIC_EFFORT`, `ANTHROPIC_MAX_TOKENS`, `ANTHROPIC_REFUSAL_FALLBACK` | Claude provider (unused while `LLM_PROVIDER=gemini`). Key is **secret**. |
| `DAILY_QUESTION_LIMIT`, `PREMIUM_DAILY_LIMIT`, `PREMIUM_PRICE_UZS`, `PREMIUM_DAYS`, `PAYMENT_PROVIDER_TOKEN`, `PAYMENT_CONTACT` | Usage limits and payments. Token is **secret**. |
| `MAX_CONCURRENT_QUESTIONS`, `DB_POOL_MAX` | Concurrency |
| `TIMEZONE` | `Asia/Tashkent` |
| `LEXUZ_DELAY_SECONDS`, `LEXUZ_MAX_RETRIES`, `LEXUZ_TIMEOUT_SECONDS`, `LEXUZ_CACHE_DIR`, `LEXUZ_CACHE_TTL_HOURS` | Polite Lex.uz client (1.5 s delay between requests; do not lower) |
| `DISCOVERY_DAILY_LIMIT` | Daily import cap for discovered acts |
| `NEWS_SEND_START_HOUR`, `NEWS_SEND_END_HOUR`, `NEWS_MAX_AGE_DAYS`, `NEWS_AUDIENCE`, `NEWS_REQUIRE_AI`, `NEWS_TEXT_WAIT_DAYS`, `NEWS_CHANNEL` | News message pipeline |
| `REQUIRED_CHANNEL`, `REQUIRED_CHANNEL_URL` | Mandatory channel membership (off locally) |
| `LOG_LEVEL` | Logging |
| `TEST_DATABASE_URL` | Tests only. **Must point to a disposable local DB.** |

---

## Pre-connection checklist for Marketolog

1. **Confirm the source is alive.** The Supabase project must be active, and the export manifest's max `last_successful_load` must be recent. Otherwise mark everything `stale_source` and do not publish.
2. **Use only a read-only path** (Option A files, or a read-only role approved by the owner). Never use `SUPABASE_SERVICE_ROLE_KEY` or the bot token.
3. **Re-verify every legal claim against the live Lex.uz `link`** before publishing. Check status, effective date, `future_version` and newer decrees vs. the code.
4. **Keep a human approval step** before Telegram or Instagram publication. This repo never auto-publishes news either.
5. **Do not import or derive anything from the personal tables** (§4.3).
6. **Dedupe on `event_id`;** treat a higher `event_revision` as a metadata update.
