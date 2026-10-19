BEGIN;

-- ============================================================================
-- 016 — Confirmed match results are immutable
--
-- A match with `result_confirmed = TRUE` must not change its result nor be
-- deleted through any path, including direct SQL. The existing triggers protect
-- the structure of a published version, but they do not protect scores,
-- penalties, winner, status, resolution type or reason of an already confirmed
-- result (R03 / RF-010, RF-011, RF-013).
--
-- The trigger only acts when `OLD.result_confirmed = TRUE`, so closing a report
-- (`FALSE` -> `TRUE`), the administrative resolution, the bracket advancement,
-- the double-elimination reset and the development seed keep working. There is
-- no exception for platform administrators: a correction path for a confirmed
-- result would need its own specification (constitution, principle 3).
--
-- The migration is idempotent: `CREATE OR REPLACE FUNCTION`,
-- `DROP TRIGGER IF EXISTS` and `CREATE TRIGGER`.
-- ============================================================================

CREATE OR REPLACE FUNCTION public.prevent_confirmed_match_result_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
BEGIN
    IF OLD.result_confirmed = TRUE THEN
        IF TG_OP = 'DELETE' THEN
            RAISE EXCEPTION 'Un resultado confirmado no se puede borrar'
                USING ERRCODE = '23514';
        END IF;

        IF NEW.home_score_regular IS DISTINCT FROM OLD.home_score_regular
           OR NEW.away_score_regular IS DISTINCT FROM OLD.away_score_regular
           OR NEW.home_score IS DISTINCT FROM OLD.home_score
           OR NEW.away_score IS DISTINCT FROM OLD.away_score
           OR NEW.home_penalties IS DISTINCT FROM OLD.home_penalties
           OR NEW.away_penalties IS DISTINCT FROM OLD.away_penalties
           OR NEW.winner_team_id IS DISTINCT FROM OLD.winner_team_id
           OR NEW.status IS DISTINCT FROM OLD.status
           OR NEW.resolution_type IS DISTINCT FROM OLD.resolution_type
           OR NEW.resolution_reason IS DISTINCT FROM OLD.resolution_reason
           OR NEW.result_confirmed IS DISTINCT FROM OLD.result_confirmed
        THEN
            RAISE EXCEPTION 'Un resultado confirmado es inmutable'
                USING ERRCODE = '23514';
        END IF;
    END IF;

    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

DROP TRIGGER IF EXISTS trg_protect_confirmed_match_result ON public.matches;
CREATE TRIGGER trg_protect_confirmed_match_result
BEFORE UPDATE OR DELETE ON public.matches
FOR EACH ROW EXECUTE FUNCTION public.prevent_confirmed_match_result_mutation();

COMMIT;
