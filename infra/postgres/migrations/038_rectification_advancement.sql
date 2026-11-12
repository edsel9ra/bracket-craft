BEGIN;

CREATE FUNCTION public.rectification_slot_rejection(p_old public.matches, p_team UUID, p_side TEXT, p_version UUID)
RETURNS TEXT LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    v RECORD;
    source public.matches;
    link RECORD;
    prior RECORD;
    previous_winner UUID;
    expected_old UUID;
    expected_new UUID;
BEGIN
    SELECT rv.*, rv.xmin::text AS insertion_xid, r.status AS request_status
    INTO v FROM public.match_report_versions rv
    JOIN public.match_report_rectification_requests r
      ON r.id = rv.request_id AND r.organization_id = rv.organization_id
    WHERE rv.id = p_version AND rv.organization_id = p_old.organization_id;
    IF NOT FOUND OR v.request_status <> 'pending'
       OR pg_xact_status(v.insertion_xid::xid8) IS DISTINCT FROM 'in progress'
       OR v.id IS DISTINCT FROM NULLIF(current_setting('app.rectification_version_id', true), '')::uuid
       OR v.published_by_user_id::text IS DISTINCT FROM current_setting('app.current_user_id', true)
       OR p_old.organization_id::text IS DISTINCT FROM current_setting('app.current_organization_id', true)
    THEN
        RETURN 'publication_context';
    END IF;
    SELECT * INTO source FROM public.matches
    WHERE id = v.match_id AND organization_id = p_old.organization_id;
    IF NOT FOUND OR NOT source.result_confirmed OR source.id = p_old.id
       OR source.tournament_id <> p_old.tournament_id
       OR source.tournament_version_id <> p_old.tournament_version_id
       OR NOT EXISTS (SELECT 1 FROM public.tournament_versions tv
           WHERE tv.id = source.tournament_version_id AND tv.organization_id = source.organization_id
             AND tv.status = 'published')
       OR EXISTS (SELECT 1 FROM public.match_report_versions later
           WHERE later.match_id = source.id AND later.organization_id = source.organization_id
             AND later.version_number > v.version_number)
    THEN
        RETURN 'publication_context';
    END IF;
    IF p_old.result_confirmed THEN RETURN 'confirmed'; END IF;
    IF EXISTS (SELECT 1 FROM public.match_segments ms
        WHERE ms.match_id = p_old.id AND ms.organization_id = p_old.organization_id)
    THEN RETURN 'segments'; END IF;
    IF p_old.status <> 'scheduled' THEN RETURN 'status'; END IF;
    IF (SELECT count(*) FROM public.advancement_links al
        WHERE al.organization_id = p_old.organization_id AND al.target_match_id = p_old.id
          AND al.target_side = p_side) <> 1
    THEN RETURN 'manual'; END IF;
    SELECT * INTO link FROM public.advancement_links
    WHERE organization_id = p_old.organization_id AND target_match_id = p_old.id
      AND target_side = p_side AND source_match_id = source.id;
    IF NOT FOUND THEN RETURN 'manual'; END IF;
    SELECT * INTO prior FROM public.match_slot_assignments
    WHERE organization_id = p_old.organization_id AND match_id = p_old.id AND side = p_side
    ORDER BY assigned_at DESC, id DESC LIMIT 1;
    IF NOT FOUND OR prior.origin NOT IN ('advancement_link', 'rectification')
       OR prior.advancement_link_id IS DISTINCT FROM link.id
       OR prior.team_id IS DISTINCT FROM (CASE WHEN p_side = 'home' THEN p_old.home_team_id ELSE p_old.away_team_id END)
       OR (prior.origin = 'rectification' AND NOT EXISTS (
           SELECT 1 FROM public.match_report_versions pv
           WHERE pv.id = prior.match_report_version_id AND pv.organization_id = source.organization_id
             AND pv.match_id = source.id AND pv.version_number < v.version_number))
    THEN RETURN 'manual'; END IF;
    IF v.supersedes_version_number = 1 THEN
        previous_winner := source.winner_team_id;
    ELSE
        SELECT winner_team_id INTO previous_winner FROM public.match_report_versions
        WHERE organization_id = source.organization_id AND match_id = source.id
          AND version_number = v.supersedes_version_number;
    END IF;
    expected_old := CASE WHEN link.outcome = 'winner' THEN previous_winner
        WHEN previous_winner = source.home_team_id THEN source.away_team_id
        WHEN previous_winner = source.away_team_id THEN source.home_team_id END;
    IF previous_winner IS NULL
       OR (previous_winner IS DISTINCT FROM source.home_team_id AND previous_winner IS DISTINCT FROM source.away_team_id)
       OR prior.team_id IS DISTINCT FROM expected_old
    THEN RETURN 'wrong_origin'; END IF;
    expected_new := CASE WHEN link.outcome = 'winner' THEN v.winner_team_id
        WHEN v.winner_team_id = source.home_team_id THEN source.away_team_id
        WHEN v.winner_team_id = source.away_team_id THEN source.home_team_id END;
    IF v.winner_team_id IS NULL
       OR (v.winner_team_id IS DISTINCT FROM source.home_team_id AND v.winner_team_id IS DISTINCT FROM source.away_team_id)
       OR p_team IS NULL OR p_team IS DISTINCT FROM expected_new
    THEN RETURN 'wrong_team'; END IF;
    IF EXISTS (
        SELECT 1 FROM public.stages current_stage JOIN public.stages later
          ON later.organization_id = current_stage.organization_id
          AND later.tournament_version_id = current_stage.tournament_version_id
          AND later.tournament_id = current_stage.tournament_id AND later.stage_order > current_stage.stage_order
        JOIN public.stage_teams st ON st.stage_id = later.id AND st.organization_id = later.organization_id
        WHERE current_stage.id = source.stage_id AND current_stage.organization_id = source.organization_id
    ) THEN RETURN 'later_phase'; END IF;
    RETURN NULL;
END;
$$;

CREATE FUNCTION public.apply_rectification_slot(p_old public.matches, p_new public.matches, p_side TEXT)
RETURNS BOOLEAN LANGUAGE plpgsql SET search_path = pg_catalog, public AS $$
DECLARE
    publication_id UUID;
    p_team UUID;
    prior RECORD;
    source_id UUID;
BEGIN
    IF p_new.status <> 'scheduled' OR p_new.result_confirmed THEN RETURN FALSE; END IF;
    p_team := CASE WHEN p_side = 'home' THEN p_new.home_team_id ELSE p_new.away_team_id END;
    publication_id := NULLIF(current_setting('app.rectification_version_id', true), '')::uuid;
    IF publication_id IS NULL THEN RETURN FALSE; END IF;
    PERFORM id FROM public.matches
    WHERE id = p_old.id AND organization_id = p_old.organization_id FOR UPDATE;
    IF public.rectification_slot_rejection(p_old, p_team, p_side, publication_id) IS NOT NULL
    THEN RETURN FALSE; END IF;
    SELECT * INTO prior FROM public.match_slot_assignments
    WHERE organization_id = p_old.organization_id AND match_id = p_old.id AND side = p_side
    ORDER BY assigned_at DESC, id DESC LIMIT 1;
    SELECT match_id INTO source_id FROM public.match_report_versions
    WHERE id = publication_id AND organization_id = p_old.organization_id;
    IF NOT EXISTS (
        SELECT 1 FROM public.match_report_rectification_effects e
        WHERE e.organization_id = p_old.organization_id AND e.version_id = publication_id
          AND e.effect_type = 'advancement' AND e.entity_type = 'match' AND e.entity_id = p_old.id
          AND e.payload @> jsonb_build_object(
              'original_match_id', source_id::text, 'version_id', publication_id::text,
              'source_match_id', source_id::text, 'target_match_id', p_old.id::text,
              'side', p_side, 'advancement_link_id', prior.advancement_link_id::text,
              'before_assignment_id', prior.id::text, 'before_team_id', prior.team_id::text,
              'after_team_id', p_team::text)
    ) THEN RETURN FALSE; END IF;
    INSERT INTO public.match_slot_assignments
        (organization_id,tournament_id,match_id,side,team_id,origin,advancement_link_id,match_report_version_id,assigned_at)
    VALUES (p_old.organization_id,p_old.tournament_id,p_old.id,p_side,p_team,'rectification',
        prior.advancement_link_id,publication_id,clock_timestamp());
    RETURN TRUE;
EXCEPTION
    WHEN invalid_text_representation THEN RETURN FALSE;
END;
$$;

CREATE OR REPLACE FUNCTION prevent_published_match_structure_mutation()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $$
DECLARE
    old_version_status VARCHAR(20);
    new_version_status VARCHAR(20);
BEGIN
    IF TG_OP = 'INSERT' THEN
        SELECT status INTO new_version_status
        FROM tournament_versions
        WHERE id = NEW.tournament_version_id
          AND organization_id = NEW.organization_id;
        IF new_version_status IN ('published', 'archived') THEN
            RAISE EXCEPTION 'La estructura de partidos de una versión publicada o archivada es inmutable';
        END IF;
    ELSIF TG_OP = 'DELETE' THEN
        SELECT status INTO old_version_status
        FROM tournament_versions
        WHERE id = OLD.tournament_version_id
          AND organization_id = OLD.organization_id;
        IF old_version_status IN ('published', 'archived') THEN
            RAISE EXCEPTION 'La estructura de partidos de una versión publicada o archivada es inmutable';
        END IF;
    ELSE
        SELECT status INTO old_version_status
        FROM tournament_versions
        WHERE id = OLD.tournament_version_id
          AND organization_id = OLD.organization_id;
        SELECT status INTO new_version_status
        FROM tournament_versions
        WHERE id = NEW.tournament_version_id
          AND organization_id = NEW.organization_id;
        IF OLD.tournament_version_id IS DISTINCT FROM NEW.tournament_version_id THEN
            RAISE EXCEPTION 'Un partido no puede cambiar de versión';
        END IF;
        IF old_version_status IN ('published', 'archived')
           OR new_version_status IN ('published', 'archived')
        THEN
            IF NEW.organization_id IS DISTINCT FROM OLD.organization_id
               OR NEW.tournament_id IS DISTINCT FROM OLD.tournament_id
               OR NEW.tournament_version_id IS DISTINCT FROM OLD.tournament_version_id
               OR NEW.stage_id IS DISTINCT FROM OLD.stage_id
               OR NEW.group_id IS DISTINCT FROM OLD.group_id
               OR (
                     NEW.home_team_id IS DISTINCT FROM OLD.home_team_id
                     AND NOT (OLD.home_team_id IS NULL AND NEW.home_team_id IS NOT NULL)
                     AND NOT public.apply_rectification_slot(OLD, NEW, 'home')
                   )
               OR (
                     NEW.away_team_id IS DISTINCT FROM OLD.away_team_id
                     AND NOT (OLD.away_team_id IS NULL AND NEW.away_team_id IS NOT NULL)
                     AND NOT public.apply_rectification_slot(OLD, NEW, 'away')
                   )
               OR NEW.home_slot_id IS DISTINCT FROM OLD.home_slot_id
               OR NEW.away_slot_id IS DISTINCT FROM OLD.away_slot_id
               OR NEW.replacement_match_id IS DISTINCT FROM OLD.replacement_match_id
               OR NEW.matchday IS DISTINCT FROM OLD.matchday
               OR NEW.bracket_code IS DISTINCT FROM OLD.bracket_code
            THEN
                RAISE EXCEPTION 'La estructura de un partido publicado o archivado es inmutable';
            END IF;
        END IF;
    END IF;
    RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$;

COMMIT;
