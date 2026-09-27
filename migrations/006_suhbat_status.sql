-- 006_suhbat_status: javob natijasi turi (/stat va monitoring uchun).
-- Qiymatlar app/services/answer.py FinalAnswer.status bilan bir xil.
ALTER TABLE suhbatlar ADD COLUMN status text
    CHECK (status IN ('answered', 'insufficient', 'needs_clarification', 'historical_unavailable',
                      'not_found', 'error', 'limit_exceeded', 'unavailable'));
CREATE INDEX suhbatlar_created_idx ON suhbatlar (created_at DESC);
