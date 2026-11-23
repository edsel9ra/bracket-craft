# Plan — Spec 041: Auditoría organizacional visible (F5)

Estado: aprobado por el usuario el 2026-11-22 («Apruebo el plan y las tareas.»).

## 1. Alcance y dependencias

- Lectura de la tabla tenant existente `administrative_audit_logs` (001, actor de plataforma desde la 036). No se crea tabla nueva ni se cambia ningún escritor de auditoría.
- Separada de `platform_audit_logs` y de `/admin/audit`, que no cambian.
- Una migración nueva, `064_organization_audit_permission.sql`. No se edita ninguna migración aplicada.
- Sin eventos de outbox ni Socket.IO: la consulta se recarga a petición.

## 2. Archivos y responsabilidades

### Base de datos (`infra/postgres/migrations/064_organization_audit_permission.sql`)
- Permiso `VIEW_ORGANIZATION_AUDIT` añadido a `role_definitions.system_permissions` de `owner` y `administrator` y a los `roles` ya materializados de esos dos roles (mismo patrón idempotente que la 014). Las organizaciones nuevas lo heredan porque sus roles se copian de `role_definitions` (002 y alta de miembros). Ningún otro rol lo recibe (RF-013).
- Índice `(organization_id, performed_at DESC, id DESC)` sobre `administrative_audit_logs` para el orden y la paginación (RF-001, RNF-001).
- Sin cambios de RLS: la tabla ya tiene `ENABLE`+`FORCE` y política de tenant; `bracket_app` conserva sus privilegios actuales.

### Backend (`backend/app/modules/organization_audit/`, nuevo)
- `catalog.py` (funciones puras): catálogo cerrado `acción → tipo de entidad + campos declarados` y `project_details(action, payload)`. Nunca devuelve el JSON guardado completo.
- `schemas.py`: `AuditListQuery` y respuestas con `extra="forbid"` y `hide_input_in_errors=True`.
- `service.py`: `OrganizationAuditService.list` y `.actors`, con `set_rls_context()` dentro de la transacción y `require_permission(..., "VIEW_ORGANIZATION_AUDIT")`.
- `router.py`, registrado en `backend/app/main.py` con prefijo `/api/v1`.

### Frontend
- `utils/organizationAudit.ts` (puro): etiquetas ES/EN de acciones y campos, formato de valores, construcción de la consulta (fechas locales → UTC inclusivas) y enlace por entidad.
- `composables/useOrganizationAudit.ts`: solo `useApi`; descarta respuestas al cambiar de organización o de usuario, como los composables de sanciones.
- `pages/workspace/audit.vue` (middleware `auth`), `components/workspace/audit/AuditFilters.vue`, `AuditEntryTable.vue` (sobre `ui/DataTable`) y `AuditEntryDialog.vue` (`<dialog>` nativo con `showModal`, como `PublicLineupModal`).
- `components/WorkspaceShell.vue`: enlace «Auditoría» solo con `auth.hasPermission('VIEW_ORGANIZATION_AUDIT')` (RF-011).
- Textos en `composables/useI18n.ts` (ES/EN).

### Tests
- Backend: `test_migration_064.py` (opt-in BD), `test_organization_audit_catalog.py` (puras), `test_organization_audit_routes.py` (BD) y actualización del inventario de esquemas estrictos de la 019.
- Frontend: `organization-audit.test.ts` y extensión de `workspace-layout.test.ts`.
- E2E: `e2e/organization-audit.spec.ts` en el proyecto `workspace`, con contratos ficticios y axe en ambos temas.

## 3. Funciones puras (`catalog.py`)

- `CATALOG: dict[str, ActionSpec]`, con `ActionSpec(entity_type, fields)` y cada campo `(clave, ruta en el payload, tipo)`; tipos `text`, `number`, `boolean`, `code` y `member`.
- `project_details(action, payload, member_names) -> list[{"key", "value"}] | None`:
  ```
  si action no está en CATALOG: devolver None            # RF-008
  para cada campo declarado, en orden:
      valor = leer ruta; si falta o es null: omitir
      si el tipo no coincide (p. ej., un objeto donde se espera texto): omitir
      member: sustituir el ID por el nombre del miembro, o omitir si no es de la organización
      text: recortar a 1000 caracteres
  devolver la lista
  ```
- `assert_catalog_safe()`: ninguna ruta declarada contiene `email`, `token`, `url`, `link`, `document`, `birth` ni `platform_admin`. Lo comprueba un test (RF-007).

Catálogo inicial (campos entre paréntesis; «—» = sin contenido mostrado):

| Entidad | Acciones |
|---|---|
| `matches` | `CLOSE_MATCH_REPORT` y `ADMINISTRATIVE_MATCH_RESOLUTION` (estado anterior y final, tipo de resolución, marcador, motivo del walkover o de la resolución, nota del acta, n.º de suspensiones); `INTERRUPT_MATCH_SEGMENT` (motivo, minuto); `MATCH_LIVE_COMMAND` (tipo, revisión); `SAVE_MATCH_LINEUP` (equipos, inscritos, titulares, suplentes); `PUBLISH_MATCH_LINEUP` y `UNPUBLISH_MATCH_LINEUP` (pública sí/no); `ASSIGN_MATCH_OFFICIAL` y `REMOVE_MATCH_OFFICIAL` (miembro, función); `REQUEST_MATCH_REPORT_RECTIFICATION` (versión base); `DECIDE_MATCH_REPORT_RECTIFICATION` (decisión); `GRANT_RECTIFICATION_AUTHORIZATION` y `REVOKE_RECTIFICATION_AUTHORIZATION` (—) |
| `sanction_cases` | `DECIDE_SANCTION_CASE` (decisión); `GRANT_SANCTION_AUTHORIZATION` y `REVOKE_SANCTION_AUTHORIZATION` (—) |
| `competitive_impact_procedures` | `OPEN_COMPETITIVE_IMPACT` y `CLOSE_COMPETITIVE_IMPACT` (resolución) |
| `organization_users` | `CHANGE_MEMBER_ROLE` (rol); `SET_MEMBER_ACTIVE` (activo sí/no) |
| `organization_invitations` | `ACCEPT_INVITATION` (rol); `REOPEN_INVITATION` (estado anterior, rol) |
| `teams` | `SET_TEAM_CREST` y `REMOVE_TEAM_CREST` (—) |
| `stage_slot_resolutions` | `STAGE_SLOTS_RESOLVED` (—) |

Un test de inventario recorre `backend/app` y `infra/postgres/migrations`, extrae cada acción escrita en `administrative_audit_logs` y exige que esté en el catálogo, para que una acción futura no quede sin etiqueta por olvido.

## 4. Interfaz

Bajo `/api/v1`, con cabecera `X-Organization-ID`. `get_auth_context` responde 403 si no hay membresía; después se exige `VIEW_ORGANIZATION_AUDIT` con un 403 idéntico (RF-002). Sin `POST`, `PUT`, `PATCH` ni `DELETE` (RF-009).

| Método y ruta | Respuesta |
|---|---|
| `GET /organization-audit?action=…&action=…&actor_member_id=…&from=…&to=…&limit=50&offset=0` | `200 {items, total, limit, offset}`; `422` si hay una acción fuera del catálogo, una fecha sin zona o inválida, `from > to`, `limit` fuera de 1–100, `offset < 0` o un campo no declarado (RF-004, RF-005) |
| `GET /organization-audit/actors` | `200 [{member_id, name}]` con los miembros de la organización, para el filtro de responsable |

Cada `item`: `id`, `performed_at`, `action`, `cataloged`, `entity_type`, `entity_id`, `entity_available`, `actor {kind: "member" | "platform", member_id | null, name | null}` y `details` (lista o `null` si la acción no está catalogada).

Consulta (una sola sentencia para la página y otra para el total):
```
FROM administrative_audit_logs l
LEFT JOIN organization_users ou ON ou.id = l.performed_by_member_id
LEFT JOIN organization_users ou_user ON ou.id IS NULL AND ou_user.user_id = l.performed_by_user_id
     AND ou_user.organization_id = l.organization_id
LEFT JOIN users u ON u.id = COALESCE(ou.user_id, ou_user.user_id)
WHERE l.organization_id = :org
  AND (:actions IS NULL OR l.action = ANY(:actions))
  AND (:actor IS NULL OR COALESCE(ou.id, ou_user.id) = :actor)
  AND (:from IS NULL OR l.performed_at >= :from) AND (:to IS NULL OR l.performed_at <= :to)
ORDER BY l.performed_at DESC, l.id DESC LIMIT :limit OFFSET :offset
```
- El responsable es el miembro de `performed_by_member_id` o, si falta, el miembro de esa organización con `performed_by_user_id` (por ejemplo, el propietario que concede una autorización). Si ninguno existe, es la «Administración de plataforma» sin nombre ni ID (RF-006).
- `entity_available` se calcula con `EXISTS` bajo RLS solo para `matches` y `sanction_cases`; para el resto vale `false` (RF-012).
- Los nombres de miembro de los campos `member` se resuelven en la misma transacción con una consulta por página, no por fila.
- Solo hay sentencias `SELECT`: consultar no escribe auditoría (RF-009).

Pantalla `/workspace/audit`:
- Filtros: acciones (selección múltiple del catálogo), responsable, desde y hasta (fecha local que se convierte a UTC con el inicio y el fin del día, inclusivos). Los filtros viven en la query de la URL.
- Tabla paginada y navegable por teclado, en orden descendente, con fecha, acción, entidad y responsable. El detalle se abre en un diálogo modal: el foco entra al título, Escape lo cierra y el foco vuelve a la fila de origen (RNF-003).
- Enlaces: un partido lleva a `/workspace/matches/{id}` si `entity_available`; un caso de sanción lleva a `/workspace/sanctions?case={id}` si además el usuario tiene `VIEW_SANCTION_CASES`. Si no, se muestra solo el ID (RF-012).
- Estados de carga, vacío (RF-010), error y sin permiso, en ES/EN y ambos temas, con tokens y componentes de `components/ui/`.

## 5. Decisiones justificadas

| Decisión | Alternativa descartada | Motivo |
|---|---|---|
| Detalle incluido en cada entrada | Endpoint de detalle por ID | Los campos son pocos y ya están filtrados; con 100 entradas por página no compensa una petición más por entrada |
| Paginación por `limit`/`offset` con `total` | Cursor | Es el contrato de las bandejas 033 (`/rectifications`); el volumen esperado por organización lo permite con el índice nuevo |
| Endpoint propio `actors` | Reutilizar `GET /organizations/members` | Ese endpoint exige `MANAGE_MEMBERS` y devuelve correos; el filtro necesita solo nombre e ID bajo el permiso de auditoría |
| Catálogo en el backend y etiquetas en el frontend | Etiquetas en el backend | El i18n vive en `useI18n.ts`; el backend solo decide qué campos salen |
| Actor resuelto por miembro o por usuario de la organización | Solo `performed_by_member_id` | Las autorizaciones de sanción guardan solo `performed_by_user_id` del propietario, que debe verse como miembro y no como plataforma |
| Test de inventario de acciones | Revisión manual | Evita que una acción nueva aparezca como «no catalogada» sin que nadie lo decida |

## 6. Estrategia de tests

- Cada tarea: test en rojo, código mínimo y verde.
- BD (`RUN_DATABASE_TESTS=1`): permiso solo en propietario y administrador, existentes y nuevos; orden y desempate por ID; paginación y límites; cada filtro y su combinación; aislamiento con dos organizaciones (un `actor_member_id` de otra organización da una página vacía); 403 sin membresía y sin permiso (operador, árbitro y observador); 422 por cada valor inválido sin ejecutar la consulta; responsable de plataforma sin identidad; acción desconocida sin `details`; `entity_available` en partido existente y en entidad borrada o ajena; el número de filas de auditoría no cambia tras consultar; mismo número de sentencias con 1 y con 100 entradas por página (RNF-001).
- Puras: proyección por acción, tipos no coincidentes, recorte de texto, nombres de miembro, catálogo seguro e inventario.
- Frontend (Vitest): utilidades, composable (descarte al cambiar de organización), visibilidad del enlace en el menú, estados y enlaces.
- E2E: filtros, paginación, diálogo de detalle con foco y teclado, y axe sin violaciones en tema claro y oscuro, a 1440 y 390 px.

## 7. RF cubiertos por parte

| Parte | RF |
|---|---|
| Migración 064 | RF-001, RF-013, RNF-001 |
| `catalog.py` | RF-007, RF-008 |
| `schemas.py`, `service.py` y `router.py` | RF-001 a RF-006, RF-009, RF-012 (disponibilidad), RNF-001, RNF-002, RNF-004 |
| Pantalla, componentes y menú | RF-006, RF-007, RF-008, RF-010, RF-011, RF-012, RNF-003 |

## 8. Exposición pública

No aplica: no hay rutas ni proyecciones públicas nuevas. La consulta es privada y nunca devuelve correos, tokens, enlaces de invitación, documentos, fechas de nacimiento ni la identidad del administrador de plataforma.

## 9. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 2.1 Aislamiento por RLS | Sí | `set_rls_context()` en la transacción y `organization_id = :org` explícito; test con dos organizaciones y filtros con IDs ajenos |
| 2.2 Sin `BYPASSRLS` | Sí | Solo `SELECT` con `bracket_app`; ninguna función `SECURITY DEFINER` nueva |
| 2.3 Lo publicado es inmutable | No | Solo lectura; no toca torneos ni actas |
| 2.4 Migraciones append-only | Sí | Migración 064 nueva e idempotente; ninguna aplicada se edita |
| 2.5 Proyección pública mínima | No | Sin superficie pública (§8) |
| 2.6 Sin secretos por defecto | No | Sin variables ni secretos nuevos |
| 2.7 Administración global | Sí | `/admin/audit` y `platform_audit_logs` no cambian; la plataforma aparece solo como responsable anónimo |
| 2.8 Verificación | Sí | Tests en rojo y luego verde en cada tarea y cinco jobs de CI |
| 2.9 Código de desarrollo | No | Sin seeds ni rutas de desarrollo nuevas |
| 3.1 Rectificaciones append-only | No | Solo se leen sus entradas de auditoría |
| 3.2 Efectos por worker | No | Sin efectos asíncronos |
| 3.3 `useApi.ts` | Sí | `useOrganizationAudit` |
| 3.4 Seguridad | Sí | Permiso específico, 403 indistinguible, esquemas `extra="forbid"` y `hide_input_in_errors=True`, catálogo cerrado con test de seguridad |
| §4 BD | Sí | Volumen limpio 001→064 y salto 063→064 en `test_migration_064.py`; `sh -n infra/postgres/migrate.sh` |
| §4 Backend | Sí | Router en `main.py`; `pytest -q`, `python -m compileall -q app`, ruff y bandit |
| §4 Frontend | Sí | `pnpm test`, `pnpm run typecheck`, `pnpm run build`, `pnpm run lint` |
| §4 Infraestructura | No | Sin cambios de Compose |
| §4 Documentación | Sí | README (permiso, endpoint y runbook de la 064), AGENTS, manual y MEMORY en T7 |

## 10. Notas de despliegue

Aplicar la 064 antes de la API. Sin la 064, nadie tiene el permiso y la consulta responde 403. No se rompe nada existente.
