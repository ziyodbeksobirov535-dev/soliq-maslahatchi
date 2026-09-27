// import-proxy: raw TCP yopiq muhitdan (cloud dev) hujjat importi uchun vaqtinchalik Edge Function.
//
// PostgREST'ning importer ishlatadigan uchta endpoint'ini taqlid qiladi, shuning uchun Python
// tomonda `import_document_rest(function_url, token, ...)` o'zgarishsiz ishlaydi:
//   POST   .../rest/v1/import_staging          — staging bo'lagi
//   POST   .../rest/v1/rpc/finish_import       — bitta tranzaksiyali import (migrations/003)
//   DELETE .../rest/v1/import_staging?import_id=eq.<uuid>
// Bazaga Supabase ichki ulanishi (SUPABASE_DB_URL) orqali yoziladi — service_role kaliti kerak emas.
//
// Himoya: verify_jwt o'chiq, o'rniga Authorization: Bearer <token>; kodda faqat tokenning
// SHA-256 hash'i saqlanadi. Token importni bajargan muhitda qoladi va repoga yozilmaydi.
// Boshqa hech qanday SQL bajarilmaydi. Import tugagach funksiya o'chiriladi yoki bloklanadi.

import postgres from "npm:postgres@3.4.5";

const TOKEN_SHA256 = "505ce717d1d4c08347debaba12abeed853c5fbcefb908d65d1666e3a7cb6a1de";
const UUID_RE = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

const sql = postgres(Deno.env.get("SUPABASE_DB_URL")!, { prepare: false, max: 1 });

async function sha256Hex(text: string): Promise<string> {
  const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
  return Array.from(new Uint8Array(digest)).map((b) => b.toString(16).padStart(2, "0")).join("");
}

function safeEqual(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } });
}

Deno.serve(async (req: Request) => {
  const auth = req.headers.get("authorization") ?? "";
  const token = auth.startsWith("Bearer ") ? auth.slice(7) : "";
  if (!token || !safeEqual(await sha256Hex(token), TOKEN_SHA256)) {
    return json(401, { message: "unauthorized" });
  }

  const url = new URL(req.url);
  const path = url.pathname;
  try {
    if (req.method === "POST" && path.endsWith("/rest/v1/import_staging")) {
      const rows = await req.json();
      if (!Array.isArray(rows) || rows.length === 0 || rows.length > 2000) {
        return json(400, { message: "rows: 1..2000 ta element kerak" });
      }
      for (const r of rows) {
        if (!UUID_RE.test(String(r?.import_id)) || !Number.isInteger(r?.seq) || typeof r?.element !== "object") {
          return json(400, { message: "noto'g'ri qator" });
        }
      }
      await sql`
        INSERT INTO import_staging (import_id, seq, element)
        SELECT t.import_id, t.seq, t.element
        FROM jsonb_to_recordset(${sql.json(rows)}) AS t(import_id uuid, seq integer, element jsonb)`;
      return new Response(null, { status: 201 });
    }

    if (req.method === "POST" && path.endsWith("/rest/v1/rpc/finish_import")) {
      const body = await req.json();
      if (!UUID_RE.test(String(body?.p_import_id)) || !/^\d{4}-\d{2}-\d{2}$/.test(String(body?.p_today))) {
        return json(400, { message: "noto'g'ri parametrlar" });
      }
      const [row] = await sql`
        SELECT finish_import(${body.p_import_id}::uuid, ${sql.json(body.p_doc)}, ${body.p_today}::date) AS r`;
      return json(200, row.r);
    }

    if (req.method === "DELETE" && path.endsWith("/rest/v1/import_staging")) {
      const importId = (url.searchParams.get("import_id") ?? "").replace(/^eq\./, "");
      if (!UUID_RE.test(importId)) return json(400, { message: "import_id kerak" });
      await sql`DELETE FROM import_staging WHERE import_id = ${importId}::uuid`;
      return new Response(null, { status: 204 });
    }

    return json(404, { message: "not found" });
  } catch (err) {
    // Faqat Postgres xabari (stack trace emas) qaytariladi.
    return json(500, { message: String((err as Error)?.message ?? err) });
  }
});
