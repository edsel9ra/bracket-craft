# Plan — Spec 049: Roles por torneo (F7)

Estado: borrador, pendiente de aprobación. Spec aprobada el 2026-11-26.

## 1. Resumen

Una migración nueva (069) crea la tabla tenant `tournament_member_roles`, con RLS forzado, y una función SQL única, `tournament_operator_allows`, que decide si el usuario de la sesión es operador del torneo de un partido para uno de los tres permisos del rol. Las cuatro comprobaciones de autorización por partido que hoy existen la usan:

1. `require_permission(..., match_id=...)` en Python, usado por la operación clásica, las alineaciones y el cierre del acta.
2. `match_live_has_permission` (056), usado por el partido en vivo, sus triggers, la elegibilidad (058), la pausa automática (057) y la autorización privada del tiempo real (`authorize_realtime_recipients`, 056).
3. `sanction_can_operate_match` (040), usado al abrir sanciones al cerrar (041) y en las lecturas operativas (042, 043).

Un módulo backend nuevo, `tournament_roles`, sirve la lista, la asignación y la retirada, con auditoría. El Workspace añade la sección «Equipo del torneo» y usa el rol para mostrar las acciones de operación. No cambia nada público.

## 2. Decisiones

| # | Decisión | Alternativa descartada | Motivo |
|---|---|---|---|
| D1 | Tabla nueva `tournament_member_roles` con `role_code` cerrado por `CHECK (role_code IN ('tournament_operator'))`. | Reutilizar `roles`/`role_definitions` o recrear `tournament_user_roles`. | La 019 retiró `tournament_user_roles` y sus tests vigilan que no vuelva. Un código cerrado evita que un rol por torneo herede por error los permisos editables de un rol de organización (RF-001, RF-001a). |
| D2 | Los permisos del rol son una constante: `VIEW_MATCH_LIVE_DRAFT`, `OPERATE_MATCH_LIVE` y `CLOSE_MATCH_REPORT`, en SQL (`tournament_operator_allows`) y en Python (`catalog.py`), con un test que compara ambas. | Guardar los permisos en la fila. | RF-001 fija el catálogo. Ninguna fila puede ampliar el rol (RF-001a). |
| D3 | Una sola función SQL, `tournament_operator_allows(org, match, permission)`, `SECURITY INVOKER`, que lee el usuario de `app.current_user_id`, exige miembro y usuario activos (RF-007) y busca la asignación en el torneo del partido. Las tres funciones existentes se redefinen con `CREATE OR REPLACE` añadiendo `OR tournament_operator_allows(...)`; `require_permission` la llama también. | Duplicar la consulta en cada sitio. | Un único criterio para HTTP, triggers, sanciones y tiempo real (RF-008–RF-010). |
| D4 | `require_permission` solo acepta el rol por torneo con `match_id` y sin `role_codes`. La resolución administrativa (`role_codes=("owner","administrator")`) y los permisos sin partido no cambian. La firma no cambia. | Añadir un parámetro de torneo. | RF-001a y RF-009. El torneo se deduce del partido, así que `test_permissions_signature.py` sigue vigilando que no vuelva el parámetro retirado. |
| D5 | Gestionan el equipo quienes tienen `MANAGE_MEMBERS` (por defecto, dueño y administrador). | Exigir los códigos de rol `owner`/`administrator`. | Es el permiso que ya gobierna los miembros (DA-3). |
| D6 | `PUT /tournaments/{id}/team/{organization_user_id}` es idempotente: 201 si crea, 200 si ya existía (sin nueva auditoría). Usa `INSERT … ON CONFLICT DO NOTHING RETURNING`. | `POST` con 409 si existe. | RF-006 y dobles pulsaciones. |
| D7 | Un miembro inactivo, inexistente o de otra organización da el mismo 404 `Miembro no encontrado`; un torneo ajeno o inexistente, `Torneo no encontrado`. Se puede asignar en un torneo archivado: la operación sigue bloqueada por el estado del torneo, como hoy (caso límite 3). | Rechazar torneos archivados. | RF-005 y CL-3, sin regla nueva. |
| D8 | `adds_permissions` (DA-4) es puro: falso si el rol de organización mostrado es `owner`, `administrator` u `operator`; verdadero para `referee`, `viewer` u otro. | Calcularlo por permisos. | Es el mismo criterio que hoy da operación en todos los partidos (`rd.code IN ('owner','administrator','operator')`). |
| D9 | `GET /organizations/current/access` añade `operated_tournament_ids: list[UUID]` (solo miembros activos). El Workspace decide con eso si muestra la operación clásica; la operación en vivo ya usa `GET /matches/{id}/live/access`, que hereda D3. | Un endpoint de acceso por partido para la operación clásica. | Cambio mínimo. Si el rol se retira con la página abierta, el servidor rechaza la siguiente acción (RF-004, caso límite 2). |
| D10 | Auditoría (RF-013): `ASSIGN_TOURNAMENT_OPERATOR` y `REMOVE_TOURNAMENT_OPERATOR`, entidad `tournaments` (id del torneo), `payload = {"organization_user_id", "role_code"}`, en la misma transacción. | Entidad nueva. | La 041 ya muestra la entidad «Torneo»; el miembro se muestra con el tipo `member` como en los oficiales. Sin correo. |
| D11 | La lista (`GET`) la ve cualquier miembro y devuelve solo `organization_user_id`, `full_name`, `organization_role_code`, `role_code`, `is_active`, `adds_permissions` y `assigned_at`, ordenada por nombre e id. | Reutilizar `GET /organizations/members`. | Esa lista exige `MANAGE_MEMBERS` y trae el correo. El selector de alta sí usa `GET /organizations/members`, porque solo lo ve quien tiene `MANAGE_MEMBERS`. |

## 3. Base de datos — migración 069

`infra/postgres/migrations/069_tournament_roles.sql`, idempotente:

```sql
CREATE TABLE IF NOT EXISTS public.tournament_member_roles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES public.organizations(id) ON DELETE RESTRICT,
    tournament_id UUID NOT NULL,
    organization_user_id UUID NOT NULL,
    role_code TEXT NOT NULL CHECK (role_code IN ('tournament_operator')),
    created_by_member_id UUID NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT CURRENT_TIMESTAMP,
    CONSTRAINT uq_tournament_member_role UNIQUE (tournament_id, organization_user_id, role_code),
    FOREIGN KEY (tournament_id, organization_id) REFERENCES public.tournaments(id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (organization_user_id, organization_id) REFERENCES public.organization_users(id, organization_id) ON DELETE CASCADE,
    FOREIGN KEY (created_by_member_id, organization_id) REFERENCES public.organization_users(id, organization_id) ON DELETE RESTRICT
);
CREATE INDEX IF NOT EXISTS idx_tournament_member_roles_member
    ON public.tournament_member_roles (organization_id, organization_user_id, tournament_id);
```

- RLS `ENABLE` + `FORCE`; política `tournament_member_roles_tenant` `FOR ALL TO bracket_app` con `USING`/`WITH CHECK` sobre `app.current_organization_id`. Permisos: `SELECT, INSERT, DELETE` a `bracket_app`, sin `UPDATE`.
- `tournament_operator_allows(p_org UUID, p_match UUID, p_permission TEXT) RETURNS BOOLEAN` (`STABLE`, `SECURITY INVOKER`, `search_path` fijo):

```text
p_permission ∈ {VIEW_MATCH_LIVE_DRAFT, OPERATE_MATCH_LIVE, CLOSE_MATCH_REPORT}
AND p_org = app.current_organization_id
AND EXISTS matches m
    JOIN tournament_member_roles t ON t.tournament_id = m.tournament_id AND t.organization_id = m.organization_id
    JOIN organization_users ou ON ou.id = t.organization_user_id AND ou.organization_id = t.organization_id AND ou.is_active
    JOIN users u ON u.id = ou.user_id AND u.is_active
    WHERE m.id = p_match AND m.organization_id = p_org
      AND t.role_code = 'tournament_operator'
      AND ou.user_id = app.current_user_id
```

- `CREATE OR REPLACE` de `match_live_has_permission` y `sanction_can_operate_match` con el cuerpo actual más `OR public.tournament_operator_allows(...)` dentro de la comprobación de miembro. `authorize_realtime_recipients` no cambia: ya llama a `match_live_has_permission` con `app.current_user_id` fijado por destinatario.
- Verificación: volumen limpio (`docker compose down -v && up`) y volumen migrado (aplicar la 069 dos veces); `sh -n infra/postgres/migrate.sh`.

## 4. Backend

Módulo `backend/app/modules/tournament_roles/`, router en `backend/app/main.py` con `prefix="/api/v1"`.

| Archivo | Responsabilidad | RF |
|---|---|---|
| `catalog.py` | Puro. `TOURNAMENT_OPERATOR = "tournament_operator"`, `TOURNAMENT_ROLE_CODES`, `TOURNAMENT_OPERATOR_PERMISSIONS`, `adds_permissions(organization_role_code)` y `audit_payload(member_id, role_code)`. | RF-001, RF-001a, RF-003b |
| `schemas.py` | `TournamentTeamMember` (`extra="forbid"`, D11). | RF-012 |
| `service.py` | `TournamentRoleService`: `set_rls_context()` en cada transacción; torneo de la organización o 404; `require_permission(MANAGE_MEMBERS)` para escribir (403 si no); miembro activo o 404; alta idempotente y retirada con auditoría (D6, D10). | RF-003–RF-007, RF-003a, RF-011, RF-013 |
| `router.py` | `GET /tournaments/{id}/team`, `PUT` y `DELETE /tournaments/{id}/team/{organization_user_id}`. | RF-003, RF-004, RF-012 |
| `core/permissions.py` | Rama del rol por torneo (D4) con `SELECT tournament_operator_allows(...)`; docstring actualizado. | RF-008, RF-009 |
| `core/realtime_policy.py` | El espejo puro `decide_private_delivery` acepta el hecho `tournament_operator` para alinearse con la 056 redefinida. | RF-010 |
| `invitations/router.py` + `schemas.py` | `operated_tournament_ids` en el acceso (D9). | RF-012a |
| `organization_audit/catalog.py` | Las dos acciones de D10: `ActionSpec("tournaments", (_field("member", "member", "organization_user_id"), _field("role_code", "code")))`. | RF-013 |

## 5. Interfaz

| Método y ruta | Quién | Respuesta |
|---|---|---|
| `GET /api/v1/tournaments/{id}/team` | Miembro activo | 200 `list[TournamentTeamMember]`; 404 si el torneo no es de la organización. |
| `PUT /api/v1/tournaments/{id}/team/{organization_user_id}` | `MANAGE_MEMBERS` | 201 o 200 `TournamentTeamMember`; 403; 404 torneo o miembro. |
| `DELETE /api/v1/tournaments/{id}/team/{organization_user_id}` | `MANAGE_MEMBERS` | 204; 403; 404 si no hay asignación. |
| `GET /api/v1/organizations/current/access` | Miembro activo | Añade `operated_tournament_ids`. |

## 6. Frontend

- `utils/tournamentTeam.ts` (puro): `canOperateMatch(access, match, officials)` con la regla actual más `operated_tournament_ids.includes(match.tournament_id)`; orden y textos de la lista.
- `composables/useTournamentTeam.ts`: lista, asignación y retirada solo con `useApi`; descarta respuestas tras cambiar de organización; al cambiar el equipo propio recarga el acceso.
- `useMatchOperationState.ts` usa `canOperateMatch`.
- Página `pages/workspace/tournaments/[id]/team.vue` («Equipo del torneo»): tabla con nombre, rol de organización, estado y aviso «No añade permisos» si `adds_permissions` es falso; con `MANAGE_MEMBERS`, selector nativo de miembros activos y botón «Asignar»; «Retirar» con `useConfirm({ singleFlight: true })`. Mensajes con `role="status"`/`role="alert"`.
- Navegación: sección `team` en `tournamentNavigation.ts` y `WorkspaceShell`, después de «Exportaciones».
- i18n ES/EN `tournamentTeam.*`, `shell.team` y `audit.action.*`; espejo de acciones en `utils/organizationAudit.ts`.

## 7. Tests

- **Migración (BD):** `test_migration_069.py`: RLS entre organizaciones (no se ve ni se inserta en otra), unicidad, `CHECK` del rol, cascadas, sin `UPDATE`, reaplicación idempotente y `tournament_operator_allows` (permiso fuera del rol, otro torneo, miembro o usuario inactivo).
- **Autorización (BD):** con miembros en varios torneos (caso límite 6), un observador operador del torneo A guarda alineaciones, abre segmentos y cierra el acta de un partido de A (con sanción por roja abierta al cerrar); en B recibe 403; la resolución administrativa y `MANAGE_TOURNAMENTS` (oficiales, calendario, publicación) siguen en 403; desactivado → 403; reactivado → vuelve.
- **En vivo y tiempo real (BD):** `/live/access` con `can_view/can_operate/can_close` en A y falso en B; un comando aceptado en A; tras retirar, el comando siguiente da 403 y `authorize_realtime_recipients` pasa de `ALLOW` a `DENY` para `MATCH_LIVE_UPDATED`.
- **API (BD):** lista para cualquier miembro y sin correo; `PUT` 201/200 sin doble auditoría; 403 sin `MANAGE_MEMBERS`; 404 indistinguibles; `DELETE` 204/404; auditoría en la misma transacción; `operated_tournament_ids`.
- **Puros:** `catalog.py` (espejo SQL ↔ Python), `adds_permissions`, `realtime_policy`.
- **Frontend:** `canOperateMatch`, composable (solo `useApi`, cambio de organización), página (permisos, aviso DA-4, confirmación single-flight), navegación, paridad ES/EN y espejo de auditoría.
- **E2E:** `e2e/tournament-team.spec.ts` con teclado y axe en ambos temas a 1440 y 390 px.

## 8. Cobertura

| RF | Dónde |
|---|---|
| RF-001, RF-001a, RF-002 | D1, D2, D4; `catalog.py`; tests de autorización |
| RF-003–RF-007 (con RF-003a) | `service.py`, migración 069; tests de API y de migración |
| RF-008, RF-009 | `tournament_operator_allows`, `require_permission`, 056 y 040 redefinidas |
| RF-008a | Sin cambios en lecturas; test de que la lista de torneos no cambia |
| RF-010 | 056 redefinida; test de `authorize_realtime_recipients` |
| RF-011 | RLS de la 069; tests entre organizaciones |
| RF-012, RF-012a | Endpoints, acceso y Workspace |
| RF-013 | D10 y catálogo 041 |
| RNF-001–RNF-003 | Sin vistas públicas; i18n, E2E y `useConfirm` |

## 9. Bloques y despliegue

- Bloque A (backend, T1–T5) y bloque B (Workspace, E2E y documentación, T6–T8), en PR apilados.
- Despliegue: migración 069 antes de la API y el worker. Sin variables nuevas.

## 10. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 1. Aislamiento por RLS | Sí | Tabla con RLS forzado y política en la 069; `set_rls_context()` en cada transacción; tests entre organizaciones. |
| 2. Sin `BYPASSRLS` | Sí | `bracket_app` no cambia; la función nueva es `SECURITY INVOKER`. |
| 3. Lo publicado es inmutable | Sí | El rol solo autoriza las mismas acciones de hoy; el cierre conserva sus triggers. |
| 4. Migraciones append-only | Sí | Migración 069 nueva; la 040 y la 056 se redefinen con `CREATE OR REPLACE`, sin editarlas. |
| 5. Proyección pública mínima | Sí | Nada público nuevo; la lista no trae correo. |
| 6. Sin secretos por defecto | No | Sin variables nuevas. |
| 7. Administración global separada | No | Sin cambios en `/admin`. |
| 8. Verificación | Sí | §7 y CI 7/7 en cada PR. |
| 9. Seed fuera de producción | No | Sin datos demo nuevos. |
| §3.2 Módulo y router en `main.py` | Sí | `tournament_roles`. |
| §3.3 `useApi` y Workspace con sesión | Sí | `useTournamentTeam`. |
| §4 BD: volumen limpio y migrado, `migrate.sh` | Sí | §3. |
| §4 Documentación | Sí | T8: README (modelo de acceso y endpoints), AGENTS, manual («Equipo del torneo»), informe (F7) y MEMORY; spec 006 enlazada como antecedente. |
