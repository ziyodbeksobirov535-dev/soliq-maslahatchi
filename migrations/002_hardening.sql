-- 002_hardening: Supabase security advisor ogohlantirishlari.
--   * extension_in_public: pg_trgm `extensions` sxemasiga ko'chiriladi. Indekslar OID orqali
--     bog'langan, ular ishlashda davom etadi. similarity()/% ishlatadigan ulanishlarda
--     search_path ga `extensions` kiritilgan bo'lishi kerak (app/database/connection.py).
--   * function_search_path_mutable: trigger funksiyasi uchun search_path qat'iy belgilanadi.

CREATE SCHEMA IF NOT EXISTS extensions;
ALTER EXTENSION pg_trgm SET SCHEMA extensions;
ALTER FUNCTION public.set_updated_at() SET search_path = '';
