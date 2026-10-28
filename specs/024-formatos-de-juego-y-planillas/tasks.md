# Tareas 024 — Formatos de juego y planillas

Spec: `specs/024-formatos-de-juego-y-planillas/spec.md` (13 RF, aprobada). Plan: `specs/024-formatos-de-juego-y-planillas/plan.md`. Esquema: **031** (sin migración). `engine_version` sigue en **2026.1**.

Orden de dependencia: T1 → T2 → T3 → T4 → T5 → T6 → T7 → T8 → T9 → T10.

- [ ] **T1. Códigos de dominio `FORMATION_NOT_SUPPORTED_FOR_FORMAT` y `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED`.** RF-002, RF-006, RF-011, RNF-001
  - Hecho cuando: `backend/app/modules/matches/errors.py` define `FormationNotSupportedForFormat` (409, `code = "FORMATION_NOT_SUPPORTED_FOR_FORMAT"`) y `PublishedFormationMustBeUnpublished` (409, `code = "PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED"`), siguiendo el patrón de `WalkoverStateNotAllowed` (`detail` cadena + `code` aditivo); `backend/app/main.py` las registra con `_coded_exception_handler`; y `cd backend && python -m compileall -q app` pasa.

- [ ] **T2. Rechazar publicar/seleccionar/aplicar formación táctica en formato no 11v11.** RF-002, RF-003, RF-005, RF-006, RF-013
  - Hecho cuando: en `publish_match_lineup`, tras autorización y estado del recurso y **antes** de validar titulares/posiciones, si `game_format_of(match["rules_config"]) != "11v11"` se lanza `FormationNotSupportedForFormat` sin escribir; en `save_match_lineup`, si `payload.team_lineups` no está vacío en formato no 11v11 se lanza el mismo error; la planilla sin posiciones sigue permitida en todos los formatos; el formato ausente se resuelve como `11v11`; y `cd backend && pytest -q` pasa.

- [ ] **T3. Permitir despublicar formación en cualquier formato.** RF-002, RF-003
  - Hecho cuando: `publish_match_lineup` con `is_public=False` sigue funcionando en 5v5/7v7/9v9 (no se aplica el rechazo de T2 a la despublicación); cubierto por prueba en `backend/tests/` (nueva o ampliada) y `cd backend && pytest -q` pasa.

- [ ] **T4. Rechazar cambio de formato a no 11v11 con formación táctica publicada.** RF-011, RF-008, RNF-001
  - Hecho cuando: en `_update_version_rules_record`, si el nuevo `game_format != "11v11"` y existe al menos una fila `is_public = true` en `match_team_lineups` de esa versión (acotada por `organization_id` y `tournament_version_id`), se lanza `PublishedFormationMustBeUnpublished` (409) sin escribir; tras despublicar, el cambio se permite; y `cd backend && pytest -q` pasa.

- [ ] **T5. Frontend: retirar la advertencia genérica en los tres lugares.** RF-004, RNF-003, RNF-004
  - Hecho cuando: se eliminan los usos de `<FormatWarning>` (o su equivalente genérico) en `RulesEditor.vue`, `workspace/tournaments/[id]/index.vue` y `workspace/matches/[id].vue`; no aparece el texto «la planilla soportada es de once…» ni claves `format.notice.*` genéricas; y se muestra información contextual veraz sobre el formato cuando no es 11v11 (ej. «Formato 7v7 · alineación sin esquema táctico») en español e inglés; `pnpm test` y `pnpm run typecheck` pasan dentro del contenedor `web`.

- [ ] **T6. Frontend: guardar plantilla con avisos sin bloqueo por formato/tamaño.** RF-005, RF-006, RNF-004
  - Hecho cuando: la edición de plantilla (alta individual, importación CSV/ZIP, foto, consentimiento) sigue guardándose con incumplimientos de tamaño o formato, mostrando avisos que identifican el motivo (mínimo, máximo y cantidad actual) en el idioma activo; ningún endpoint de edición devuelve rechazo por formato o tamaño; cubierto por pruebas de fuente existentes y `pnpm test` verde.

- [ ] **T7. Pruebas backend de los dos códigos nuevos.** RF-002, RF-003, RF-011, RF-013
  - Hecho cuando: existe/actualiza prueba (pura o con base) que cubre: publicar formación en 7v7 → 409 `FORMATION_NOT_SUPPORTED_FOR_FORMAT` sin escritura; despublicar en 7v7 → 200; guardar lineup con `team_lineups` en 5v5 → 409; cambiar formato con formación publicada → 409 `PUBLISHED_FORMATION_MUST_BE_UNPUBLISHED`; formato ausente → 11v11; y `cd backend && pytest -q` pasa (suites opt-in se declaran no ejecutadas si no hay PostgreSQL).

- [ ] **T8. Pruebas frontend actualizadas al nuevo contrato.** RF-004, RF-005, RF-006
  - Hecho cuando: `frontend/tests/rules-config.test.ts` (y barridos de pantalla) dejan de exigir `<FormatWarning` genérico en los 3 lugares y pasan con `docker compose exec -T web pnpm test`; las claves i18n genéricas se retiran o marcan sin uso; paridad es/en mantenida.

- [ ] **T9. Documentación.** RF-001, RF-004, RNF-005
  - Hecho cuando: `README.md` y `AGENTS.md` reflejan que el formato deja de ser solo declarativo y que la advertencia genérica se retira, sin contradecir la constitución; `docs/contrato-reglas.md` no cambia (o solo aclara que el formato sigue fuera del contrato cerrado).

- [ ] **T10. Verificación final.** Todos los RF
  - Hecho cuando: pasan, en este orden, y se declara lo no ejecutable:
    `cd backend && pytest -q`,
    `cd backend && python -m compileall -q app`,
    `sh -n infra/postgres/migrate.sh`,
    `docker compose exec -T web pnpm test`,
    `docker compose exec -T web pnpm run typecheck`,
    `docker compose exec -T web pnpm run build`,
    `docker compose config -q`.
  - Además: no se añadieron migraciones, endpoints ni campos nuevos; `engine_version` sigue en 2026.1 y `schema_version` sin cambios.