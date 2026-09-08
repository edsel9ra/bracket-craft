BEGIN;

ALTER VIEW public.v_public_match_lineups RENAME TO v_public_match_lineups_unpublished;
REVOKE ALL ON public.v_public_match_lineups_unpublished FROM PUBLIC;
REVOKE ALL ON public.v_public_match_lineups_unpublished FROM bracket_app;

CREATE VIEW public.v_public_match_lineups
WITH (security_barrier = true) AS
SELECT raw.*
FROM public.v_public_match_lineups_unpublished raw
WHERE raw.formation_code IS NOT NULL
   OR (
       raw.formation_code IS NULL
       AND NOT EXISTS (
           SELECT 1
           FROM public.match_team_lineups tl
           WHERE tl.match_id = raw.match_id
             AND tl.team_id = raw.team_id
       )
   );

REVOKE ALL ON public.v_public_match_lineups FROM PUBLIC;
GRANT SELECT ON public.v_public_match_lineups TO bracket_app;

COMMIT;
