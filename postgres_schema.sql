-- AnimaRH Candidates schema for Postgres / Supabase
-- Migration target from candidates.json (per-vaga JSON files) to a unified Postgres table
-- Demonstrates: relational design, JSONB for flexible fields, indexes for common queries,
-- row-level security (Supabase pattern), and audit triggers.
--
-- Apply to Supabase:
--   1. Create new project at supabase.com (free tier)
--   2. SQL Editor → paste this file → Run
--   3. Test: INSERT INTO candidates (vaga_id, email, score_final) VALUES ('VAGA-X', 'a@b.com', 7.5);

-- ---------------------------------------------------------------------------
-- Schema
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS vagas (
    vaga_id          TEXT PRIMARY KEY,                          -- e.g. 'VAGA-OPERA-GERENTE-TI-2026-04'
    client_name      TEXT NOT NULL,                             -- e.g. 'OPERA' (sanitized in public exports)
    role_title       TEXT NOT NULL,
    status_pipeline  TEXT NOT NULL CHECK (status_pipeline IN
        ('SOURCING','TRIAGEM','ENTREVISTAS','SHORTLIST','FECHADA','PAUSADA','CANCELADA')),
    briefing         JSONB,                                     -- full briefing.md as JSON
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS candidates (
    candidate_id     UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    vaga_id          TEXT NOT NULL REFERENCES vagas(vaga_id) ON DELETE CASCADE,
    email            TEXT NOT NULL,                             -- chave primária per AnimaRH rule
    name             TEXT,
    score_final      NUMERIC(3,1),                              -- 0.0 to 10.0
    rating           TEXT CHECK (rating IN ('A','A-','B+','B','DISCARD')),
    status_pipeline  TEXT,
    grid_scores      JSONB,                                     -- per-criterion breakdown
    cv_path          TEXT,                                      -- relative or signed URL
    cv_extracted     TEXT,                                      -- parsed CV text
    contact          JSONB,                                     -- {phone, whatsapp, linkedin}
    salary           JSONB,                                     -- {regime, current, expected}
    observations     JSONB,                                     -- timestamped notes array
    last_action      TEXT,                                      -- last touch type (form/email/wa/cv)
    last_action_at   TIMESTAMPTZ,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE (vaga_id, email)                                     -- one record per email per vaga
);

CREATE INDEX IF NOT EXISTS idx_candidates_vaga          ON candidates (vaga_id);
CREATE INDEX IF NOT EXISTS idx_candidates_score         ON candidates (vaga_id, score_final DESC);
CREATE INDEX IF NOT EXISTS idx_candidates_status        ON candidates (status_pipeline);
CREATE INDEX IF NOT EXISTS idx_candidates_email         ON candidates (email);
CREATE INDEX IF NOT EXISTS idx_candidates_grid_gin      ON candidates USING GIN (grid_scores);

-- ---------------------------------------------------------------------------
-- Audit log (anchored evidence — file/row/timestamp pattern from AnimaRH SOP-INTEGRITY-001)
-- ---------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS candidate_audit (
    audit_id         BIGSERIAL PRIMARY KEY,
    candidate_id     UUID NOT NULL REFERENCES candidates(candidate_id) ON DELETE CASCADE,
    field            TEXT NOT NULL,
    old_value        JSONB,
    new_value        JSONB,
    actor            TEXT,                                      -- 'human:rafael', 'agent:claude', 'cron:daily'
    reason           TEXT,                                      -- e.g. 'antonio_feedback_classified_GOSTOU'
    created_at       TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_audit_candidate ON candidate_audit (candidate_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- Auto-update updated_at trigger (Postgres-native, no app code needed)
-- ---------------------------------------------------------------------------

CREATE OR REPLACE FUNCTION touch_updated_at() RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS candidates_touch ON candidates;
CREATE TRIGGER candidates_touch BEFORE UPDATE ON candidates
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

DROP TRIGGER IF EXISTS vagas_touch ON vagas;
CREATE TRIGGER vagas_touch BEFORE UPDATE ON vagas
    FOR EACH ROW EXECUTE FUNCTION touch_updated_at();

-- ---------------------------------------------------------------------------
-- Row Level Security (Supabase pattern)
-- ---------------------------------------------------------------------------

ALTER TABLE vagas ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidates ENABLE ROW LEVEL SECURITY;
ALTER TABLE candidate_audit ENABLE ROW LEVEL SECURITY;

-- Read access: only service-role key (server-side) for now. UI clients deny by default.
-- Adapt these policies when you add per-recruiter scoping.
CREATE POLICY "service_role_read_vagas"      ON vagas        FOR SELECT TO service_role USING (true);
CREATE POLICY "service_role_write_vagas"     ON vagas        FOR ALL    TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_read_candidates" ON candidates   FOR SELECT TO service_role USING (true);
CREATE POLICY "service_role_write_candidates"ON candidates   FOR ALL    TO service_role USING (true) WITH CHECK (true);
CREATE POLICY "service_role_audit"           ON candidate_audit FOR ALL TO service_role USING (true) WITH CHECK (true);

-- ---------------------------------------------------------------------------
-- Useful query examples (paste into SQL Editor to verify)
-- ---------------------------------------------------------------------------

-- Top 10 candidates per vaga, sorted by score
-- SELECT vaga_id, email, name, score_final, rating
-- FROM candidates
-- WHERE vaga_id = 'VAGA-X-2026-04'
-- ORDER BY score_final DESC NULLS LAST
-- LIMIT 10;

-- Cross-vaga A/A- candidates available for re-routing
-- SELECT vaga_id, email, name, score_final, rating
-- FROM candidates
-- WHERE rating IN ('A','A-')
--   AND status_pipeline NOT IN ('FECHADA','DESCARTADO','SEM_RESPOSTA')
-- ORDER BY score_final DESC;

-- Audit trail for one candidate
-- SELECT field, old_value, new_value, actor, reason, created_at
-- FROM candidate_audit
-- WHERE candidate_id = '<uuid>'
-- ORDER BY created_at DESC;
