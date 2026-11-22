BEGIN;

-- ============================================================================
-- Spec 041 (F5, T1): permiso de consulta de la auditoría organizacional e
-- índice para su orden y paginación. La tabla, su RLS y los privilegios de
-- bracket_app no cambian.
-- ============================================================================

-- Solo propietario y administrador. Se actualizan el catálogo (del que se
-- copian los roles de las organizaciones nuevas) y los roles ya materializados.
UPDATE public.role_definitions
SET system_permissions = system_permissions || '["VIEW_ORGANIZATION_AUDIT"]'::jsonb
WHERE code IN ('owner', 'administrator')
  AND NOT system_permissions @> '["VIEW_ORGANIZATION_AUDIT"]'::jsonb;

UPDATE public.roles r
SET permissions = r.permissions || '["VIEW_ORGANIZATION_AUDIT"]'::jsonb
FROM public.role_definitions rd
WHERE rd.id = r.role_definition_id
  AND rd.code IN ('owner', 'administrator')
  AND NOT r.permissions @> '["VIEW_ORGANIZATION_AUDIT"]'::jsonb;

CREATE INDEX IF NOT EXISTS idx_administrative_audit_logs_org_performed
    ON public.administrative_audit_logs (organization_id, performed_at DESC, id DESC);

COMMIT;
