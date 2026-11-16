BEGIN;

-- ============================================================================
-- Spec 038 (F16, T1): proyección interna de inscripciones para la ficha
-- pública del jugador y para el indicador `profile_available` (RF-003,
-- RF-007, RF-009, CL-11).
--
-- Aditiva: solo crea una vista nueva. Filtra por torneo visible mediante
-- `v_public_tournaments` (estado público, versión publicada y organización
-- activa) y anula la clave de la foto sin consentimiento de imagen. Expone
-- `valid_from` y `start_date` para elegir la inscripción representativa y
-- ordenar la trayectoria; ninguna columna se publica tal cual. No toca
-- `v_public_tournament_rosters` ni sus consumidores (022, 037).
-- ============================================================================

CREATE OR REPLACE VIEW public.v_public_player_profile_rosters
WITH (security_barrier = true) AS
SELECT
    vt.organization_id,
    r.tournament_id,
    vt.name AS tournament_name,
    vt.start_date,
    r.team_id,
    t.name AS team_name,
    r.player_id,
    p.first_name,
    p.last_name,
    r.is_active,
    r.valid_from,
    r.photo_consent,
    CASE WHEN r.photo_consent THEN r.photo_object_key ELSE NULL END AS photo_object_key
FROM public.rosters r
JOIN public.v_public_tournaments vt
  ON vt.id = r.tournament_id
 AND vt.organization_id = r.organization_id
JOIN public.players p
  ON p.id = r.player_id
 AND p.organization_id = r.organization_id
JOIN public.teams t
  ON t.id = r.team_id
 AND t.organization_id = r.organization_id;

REVOKE ALL ON public.v_public_player_profile_rosters FROM PUBLIC;
GRANT SELECT ON public.v_public_player_profile_rosters TO bracket_app;

COMMIT;
