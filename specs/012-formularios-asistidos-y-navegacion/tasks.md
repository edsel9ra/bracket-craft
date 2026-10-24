# Tareas 012 — Formularios asistidos, navegación, traducciones y límites de plantilla

Plan: `specs/012-formularios-asistidos-y-navegacion/plan.md`. Spec aprobada: 51 RF · 11 RNF · 79 casos · 46 criterios.

**Total: 35 tareas en cuatro hitos** — H1: 11 (`H1-T01`…`H1-T11`), H2: 4 (`H2-T01`…`H2-T04`), H3: 9 (`H3-T01`…`H3-T09`), H4: 11 (`H4-T01`…`H4-T11`). Cada hito deja la aplicación en verde y desplegable por sí mismo. En cada tarea se escriben primero las pruebas y se confirman en rojo.

---

## H1 — Navegación con direcciones propias, asistentes y plantillas

- [x] **H1-T01. Rutas nuevas y navegación del torneo.** Crear `/workspace/tournaments/{id}/calendar` y `/workspace/tournaments/{id}/rosters`; construir el índice con enlaces reales (resumen, configuración, calendario, plantillas y operación con partido), sección activa derivada de la ruta y redirección de `#calendario`/`#plantillas` con reemplazo de historial. RF-015, RF-016, RF-018, RF-019, RF-020.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/navigation.test.ts` pasa con casos de sección activa, redirección y conservación de `#resumen`, `#configuracion`, `#equipos` y `#operacion`; y `cd frontend && pnpm run typecheck` pasa.

- [x] **H1-T02. Configuración reducida y calendario con sus acciones.** Quitar de `workspace/tournaments/[id].vue` los paneles de plantillas y calendario, dejando resumen, reglas, fases y equipos con sus anclas; mover a la ruta del calendario la creación de partidos, el sorteo/regeneración con sus confirmaciones y la lista con enlace a operación, reutilizando el mismo contrato sin un segundo generador. RF-018, RF-020, RF-023, RF-024.
  Hecho cuando: `cd frontend && pnpm test` pasa (incluidas `stage-teams.test.ts` y `rules-config.test.ts` sin cambios de contrato) y `cd frontend && pnpm run build` termina sin errores.

- [x] **H1-T03. Armazón de asistente y modelo de pasos.** Crear `WizardShell`/`WizardSteps` y `utils/wizardModel.ts` con pasos, obligatoriedad, alternativas y estados (`complete`, `incomplete`, `error`, `omitted`, `alternative`), más teclado, foco al título y anuncio del cambio de paso. RF-001 (parte), RF-006, RF-012.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/wizard-model.test.ts` pasa con los tres asistentes, los estados del índice y `canConfirm`; `cd frontend && pnpm run typecheck` pasa.

- [x] **H1-T04. Paso en la dirección y borrador de pestaña.** Implementar `useWizardStep` (`?step=`, entrada inicial con `replace` y `push` por cambio de paso) y `useWizardDraft` (`sessionStorage`, clave por usuario/organización/torneo/versión), con recarga, otra pestaña, enlace directo sin datos y la tabla de navegaciones (confirmar solo al descartar o cambiar de versión/torneo). RF-004, RF-008, RF-013, RF-014, RF-015.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/wizard-step.test.ts` pasa con paso por defecto, paso desconocido, recarga simulada y política de confirmación; y ninguna escritura de red se dispara al cambiar de paso (aserción sobre el doble de `useApi`).

- [x] **H1-T05. Asistente de reglas.** Envolver `RulesEditor` en pasos (puntuación, desempates, disciplina, resolución, formato y límites —estos en H4—, sustituciones, inscripción, excepciones), conservar el modo avanzado y enviar la configuración completa, mostrando todos los errores por campo. RF-001, RF-005, RF-007, RF-009, RF-006.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/rules-config.test.ts` pasa con los errores por paso y el payload completo (incluidas claves requeridas vacías); `cd frontend && pnpm run typecheck` pasa.

- [x] **H1-T06. Asistente de fases con recuperación.** Identificación (nombre, orden, formato de fase), composición opcional (0..64) y revisión; crear la fase y después inscribir, informando el fallo parcial y permitiendo reintentar sobre la misma fase. RF-002, RF-010, RF-006.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/stage-teams.test.ts` pasa con el caso de fallo de inscripción y reintento sin duplicar fase.

- [x] **H1-T07. Asistente de equipos sin fase.** Datos (nombre y código) y vías alternativas (individual o CSV), sin `stage_id`, con revisión y conservación del CSV al cambiar de paso. RF-003, RF-011, RF-021 (alta de equipo).
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/wizard-model.test.ts tests/stage-teams.test.ts` pasa con las dos vías y la validación de filas; y `cd frontend && pnpm run build` termina sin errores.

- [x] **H1-T08. Pantalla de plantillas.** Formulario único en su ruta con lista por equipo, alta individual, importación CSV/ZIP, foto, consentimiento, aviso de cierre de inscripción (leyendo la versión publicada más reciente, sus fases y los partidos) y enlace al asistente de fases. RF-017, RF-024, RF-039 (excepción P4).
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/roster-lock.test.ts` pasa con jornada de referencia, partidos confirmados y cancelados; y `pnpm run typecheck` pasa.

- [x] **H1-T09. Operación sin alta de jugadores.** Quitar el formulario de alta de la operación, añadir el enlace a la plantilla del equipo con contexto de retorno y conservar partido, segmento y borrador local al volver. RF-021 (alta de jugador), RF-022.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/navigation.test.ts` incluye la comprobación de fuente de que la operación ya no envía `POST /rosters`, enlaza a la ruta de plantillas del equipo y conserva el enlace de retorno; `cd frontend && pnpm run build` termina sin errores.

- [x] **H1-T10. Configuración visible en solo lectura para observadores.** Mostrar la sección de configuración sin permiso de gestión, en modo lectura y sin acciones de escritura, manteniendo exactamente las capacidades del miembro con permiso. RF-038, RF-018.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/navigation.test.ts tests/labels.test.ts` pasa con los dos lados (observador y gestor) y `pnpm run typecheck` pasa.

- [x] **H1-T11. Cierre de H1 y documentación.** Actualizar `README.md` y `AGENTS.md` con las rutas nuevas, la excepción de visibilidad y el borrador de pestaña; comprobar que ninguna ruta nueva acepta identificadores de otra organización; ejecutar la verificación completa del hito. RF-040, RF-041, RNF-009.
  Hecho cuando: `cd frontend && pnpm test && pnpm run typecheck && pnpm run build && pnpm run typecheck:e2e` pasa y `cd backend && pytest -q` sigue en verde sin cambios de backend.

---

## H2 — Traducciones

- [x] **H2-T01. Fuente única de las 23 posiciones.** Crear `utils/positions.ts` con las 23 claves es/en y su lado declarado; retirar `positionLabel` de `constants/formations.ts` y su copia en la operación; usar la fuente en campo táctico, modal público, selector y listas. RF-027, RF-028.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/positions.test.ts` pasa con las 23 claves, la paridad es/en, el lado correcto y el fallback al código; `pnpm run build` termina sin errores.

- [x] **H2-T02. Roles desde una fuente única.** Completar `utils/labels.ts` para los cinco roles, incluido `owner` no editable, y eliminar cualquier código crudo en el directorio de miembros y en la invitación. RF-025, RF-026.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/labels.test.ts` pasa con los cinco roles, el rol desconocido tal cual y la ausencia de códigos crudos en las vistas.

- [x] **H2-T03. Claves ausentes y paridad del catálogo.** Añadir la clave del aviso de fallo del sorteo, barrer las claves usadas contra el catálogo y comprobar paridad y formato de fechas por idioma. RF-029, RF-030.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/labels.test.ts` incluye el barrido sin ausencias y la paridad es/en; `pnpm test` completo pasa.

- [x] **H2-T04. Traducciones de las pantallas nuevas.** Cubrir en es/en los textos de asistentes, plantillas, calendario, avisos de tamaño y de formato; sin literales duplicados ni texto fijo en otro idioma. RF-029, RNF-004.
  Hecho cuando: `cd frontend && pnpm test && pnpm run typecheck && pnpm run build` pasa y el barrido de claves sigue sin ausencias.

---

## H3 — Duración: contrato de operación y resolución prevista

- [x] **H3-T01. Backend: cuatro campos aditivos en `limits`.** Añadir `max_minute_regular`, `max_minute_extra`, `extra_time_enabled` y `penalties_enabled` resueltos con la configuración efectiva de la fase, sin cambiar los campos existentes. RF-032 (contrato), RNF-003.
  Hecho cuando: `cd backend && pytest -q tests/test_match_minutes.py tests/test_operational_schemas.py` pasa con los campos nuevos y los antiguos intactos.

- [x] **H3-T02. Backend: rechazo unificado de resolución no habilitada.** Implementar `resolution_enabled()` y el 409 `RESOLUTION_NOT_ENABLED` en el cierre, conservando el 422 de rango, sin revalidar actas cerradas ni reescribir versiones publicadas y sin tocar los límites deportivos ni el tope estructural. RF-032 (P5), RF-035, RF-036, RNF-003.
  Hecho cuando: `cd backend && pytest -q tests/test_match_minutes.py tests/test_close_substitutions.py` pasa; con base, `RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_match_resolution_db.py` (nuevo) cubre el 409 del cierre.

- [x] **H3-T03. Backend: resolución en segmento e interrupción.** Campo opcional `resolution_type` en ambas peticiones; con campo, máximo de la resolución; sin campo, máximo de fase (comportamiento actual); 409 unificado si no está habilitada y 422 de rango intacto. RF-032, RF-033, RNF-003.
  Hecho cuando: `cd backend && pytest -q tests/test_match_minutes.py` pasa sin modificar sus casos actuales y con los nuevos; `python -m compileall -q app` pasa.

- [x] **H3-T04. Frontend: resolución prevista.** Control único en la operación, máximo mostrado y enviado al crear o interrumpir segmentos y al cerrar; persistencia en la sesión de la pestaña y restauración al recargar. RF-033, RF-034.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/match-resolution.test.ts` pasa con selección, recarga simulada y envío; `pnpm run typecheck` pasa.

- [x] **H3-T05. Frontend: cambio de resolución y cierre.** Bloquear el cambio con segmentos persistidos fuera del nuevo máximo, avisar sin borrar cuando solo afecten eventos del borrador y exigir confirmación al cerrar con otra resolución compatible. RF-033, RF-034.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/match-resolution.test.ts` pasa con `ok`, `confirm` y `blocked`, y la confirmación sin la cual no se cierra.

- [x] **H3-T06. Borrador local sin la resolución prevista.** Dejar de escribir `resolution_type` en el borrador del partido y limpiar el campo de un borrador antiguo sin perder eventos ni marcador. RF-022, RF-034, RNF-011.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/match-resolution.test.ts` pasa con restauración de un borrador legacy (campo ignorado y eliminado) y con el marcador y los eventos intactos.

- [x] **H3-T07. Documentación de duración y contrato.** Documentar la regla de duración una sola vez, los campos nuevos y el 409 en `README.md`, `AGENTS.md` y `/docs`; confirmar que `docs/contrato-reglas.md` no cambia. RF-037, RNF-003, RNF-009.
  Hecho cuando: `cd backend && pytest -q` y `cd frontend && pnpm test` pasan, y la revisión de la documentación no encuentra dos descripciones distintas de la regla.

- [x] **H3-T08. Cierre de H3.** Verificación completa del hito. RF-031…RF-037.
  Hecho cuando: `cd backend && pytest -q && python -m compileall -q app`, `cd frontend && pnpm test && pnpm run typecheck && pnpm run build && pnpm run typecheck:e2e` pasan.

- [x] **H3-T09. RF-031: nomenclatura del minuto final y campo de prórroga deshabilitado.** Los minutos reglamentarios y el máximo con prórroga se nombran como el **minuto en que termina** el encuentro, y con la prórroga desactivada el campo de minutos con prórroga se **deshabilita conservando su valor**, tanto en los defaults de fase como en el override por fase (decisión **NM-1 = A** aprobada: el hueco de RF-031 que H3-T08 no cubría; se añade sin reescribir el plan). RF-031.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/rules-config.test.ts` pasa con el campo deshabilitado sin prórroga en defaults y override, habilitado con la prórroga encendida, el valor conservado al deshabilitar, las etiquetas «Minuto final reglamentario»/«Minuto final con prórroga» («Regulation final minute»/«Extra-time final minute») en es/en y la ausencia de las antiguas; `cd frontend && pnpm test && pnpm run typecheck && pnpm run build && pnpm run typecheck:e2e` pasa; y el barrido de claves de `tests/labels.test.ts` sigue sin ausencias.

---

## H4 — Formato declarativo, límites de plantilla y retiro lógico

- [x] **H4-T01. Backend: tres claves de configuración.** `game_format` (catálogo y default 11v11), `min_players_per_team` y `max_players_per_team` (≥ 0, 0/ausente = sin límite, `min ≤ max`), en el modelo y en el esquema, con `engine_version` 2026.1. RF-042, RF-044, RF-043, RNF-003.
  Hecho cuando: `cd backend && pytest -q tests/test_rules_config_compat.py` pasa con defaults, rangos, `min ≤ max`, cadena vacía 422 y configuración antigua sin claves.

- [x] **H4-T02. Backend: límites efectivos y conteo.** Funciones puras `effectiveRosterLimits`, `rosterSizeState` y `describeRosterViolations`, y la consulta de conteo activo por equipo con RLS. RF-045, RF-050.
  Hecho cuando: `cd backend && pytest -q tests/test_roster_limits.py` (nuevo) pasa con 0 = sin límite, por debajo, por encima y detalle determinista de 11 equipos.

- [x] **H4-T03. Backend: bloqueo al inscribir en fase.** 409 `ROSTER_SIZE_OUT_OF_RANGE` en `stages/{id}/teams`, lote todo o nada, 201/200/204 intactos. RF-045, RNF-003.
  Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_roster_limits_db.py` pasa con dentro de rango, bajo mínimo, sobre máximo y lote con un equipo fuera.

- [x] **H4-T04. Backend: bloqueo en el alta con fase destino.** Mismo 409 en `teams` y `teams/bulk` cuando llevan `stage_id`, sin crear el equipo. RF-045 (BX-1), RNF-003.
  Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_roster_limits_db.py` pasa con alta individual y lote con fase destino, sin filas creadas.

- [x] **H4-T05. Backend: bloqueo de la apertura.** Comprobar los dos equipos al crear el primer segmento, con el orden de validación del plan (resolución → tamaño → minuto) y sin alterar el estado del partido. RF-050, RF-032.
  Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_roster_limits_db.py` pasa con apertura bloqueada por mínimo y por máximo, sin segmento ni cambio de estado, y apertura permitida tras corregir.

- [x] **H4-T06. Backend: retiro lógico y reactivación.** `PATCH /rosters/{roster_id}/status` con modelo de lista, permiso de gestión, RLS, idempotencia, 404 entre organizaciones, 409 por jugador ya activo y por dorsal, sin auditoría, con el aislamiento de organización intacto. RF-051, RF-047, RF-048, RL-1, RA-1.
  Hecho cuando: `cd backend && RUN_DATABASE_TESTS=1 DATABASE_ADMIN_URL="$DATABASE_ADMIN_URL" pytest -q tests/test_roster_status_db.py` (nuevo) pasa con los ocho casos, y `tests/test_match_operation_audit.py` confirma que no se escribe auditoría.

- [x] **H4-T07. Frontend: paso de formato y límites y sus tres advertencias.** Añadir el paso (formato obligatorio, límites opcionales), la validación del par, la normalización del vacío a 0 y la advertencia visible en reglas, resumen y operación cuando el formato no es 11v11. RF-042, RF-043, RF-044.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/rules-config.test.ts tests/positions.test.ts` pasa con el paso, la validación y las tres claves de advertencia; `pnpm run build` termina sin errores.

- [x] **H4-T08. Frontend: estado por equipo y retiro.** Mostrar `cumple / por debajo / por encima` en plantillas y en la composición de fases, avisar sin bloquear al editar, permitir retirar y reactivar, explicar el botón de inscribir bloqueado y reflejar RA-1 en la reactivación. RF-046, RF-051, RL-1, RA-1.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/roster-limits.test.ts` (nuevo) pasa con los tres estados, edición nunca bloqueada por tamaño, retiro exento del bloqueo por jornada y reactivación sujeta a él.

- [x] **H4-T09. Frontend: apertura bloqueada y avisos en operación.** Mostrar el 409 de apertura con equipo, mínimo, máximo y cantidad, mantener el partido sin abrir y permitir reintentar tras corregir. RF-050, RF-046.
  Hecho cuando: `cd frontend && node --test --experimental-strip-types tests/match-resolution.test.ts tests/roster-limits.test.ts` pasa con el mensaje de apertura y el reintento; `pnpm run typecheck` pasa.

- [x] **H4-T10. Escenario E2E de operación y cierre.** Añadir `e2e/operationFlow.spec.ts` y su modelo/artefacto, con paso de reglas, tres advertencias, inscripción y apertura bloqueadas, retiro lógico con reactivación y accesibilidad/foco; integrarlo en el runner sin tocar el escenario de reintento ni su veredicto 0/1/2/3. RF-043, RF-045, RF-050, RF-051, RF-012, RNF-005, RNF-008.
  Hecho cuando: `cd frontend && pnpm run typecheck:e2e` pasa y, con la pila sembrada, `cd frontend && pnpm run e2e:test` termina en **0** con el escenario nuevo y el de reintento en verde; el artefacto del escenario nuevo queda en `frontend/e2e-report/`.

- [x] **H4-T11. Documentación y verificación final del cambio.** Actualizar `README.md`, `AGENTS.md`, `/docs` y la aclaración de alcance de `docs/contrato-reglas.md` (las tres claves quedan fuera del contrato cerrado; `engine_version` 2026.1); recorrer los criterios de finalización de la spec, incluido el aislamiento. RF-048, RF-049, RNF-003, RNF-009.
  Hecho cuando: `cd backend && pytest -q && python -m compileall -q app`, `cd frontend && pnpm test && pnpm run typecheck && pnpm run build && pnpm run typecheck:e2e` pasan; `pnpm run e2e:test` en verde; y no hay migraciones nuevas (`git status` sin cambios en `infra/postgres/migrations/`).

---

## Correcciones de la validación (2026-10-23)

- [x] **H-1. Confirmación solo donde toca.** La tabla única de navegaciones (`NAVIGATION_RULES`/`resolveNavigation`) decide: cambiar de paso, de sección, usar atrás, recargar o cerrar no piden confirmación y conservan el borrador; solo el descarte explícito y el cambio de versión o de torneo la piden, y cancelar no cambia la versión, el borrador ni los valores. Los tres asistentes ofrecen «Descartar cambios» con esa misma confirmación y vuelven a los valores del servidor. RF-008, criterio 10.
  Hecho cuando: `cd frontend && pnpm test` pasa con «only an explicit discard or a version or tournament change asks for confirmation», «a version or tournament change discards the draft only when accepted», «navigations that keep the draft never ask, and the explicit discard asks», «declares the navigation table of the spec in one place» y «every assistant offers an explicit discard that restores the server values».
- [x] **H-2. Cierre sin rechazo por minuto.** El escenario de operación y cierre registra un evento en el límite que muestra la pantalla (89 + 1 con máximo 90) y cierra el acta con la misma resolución prevista sin que el servidor la rechace por minuto. RF-032, criterio 20.
  Hecho cuando: `cd frontend && pnpm run e2e:test` termina en **0** con los hitos `event-at-limit` y `report-closed` y sin ningún `alert` de «supera el máximo».
- [x] **H-3. Aviso de minutos al guardar reglas.** Función pura en `utils/rulesMinutes.ts`; la página compara el máximo anterior y el nuevo por fase, lee los segmentos persistidos de partidos en juego/suspendidos y los eventos del borrador local; los segmentos piden confirmación y los eventos solo avisan, sin borrar ni reescribir. RF-035, criterio 23.
- [x] **H-4. Errores de formato y límites junto al campo.** `aria-invalid`/`aria-describedby`, mensaje con `role="alert"` y resumen del paso para el resto de problemas. RF-005, criterio 2.
- [x] **H-5. Historial de pasos.** Entrada inicial normalizada con `replace` y cada cambio de paso con `push`; atrás devuelve al paso anterior y no hay entradas espurias. Plan §3.1 corregido. RF-019, criterio 14. *Sustituido por H-14:* el `replace` inicial ahora lo hace el router y el paso se deriva de la dirección.
- [x] **H-9. Resolución prevista al abrir el cierre.** `snapshot()` en `useMatchResolution` y toma al enfocar el panel de cierre; la confirmación solo aparece si se cambia después. RF-034, criterio 22.
- [x] **H-10. Bloqueo por jornada en la inscripción.** `explainRosterEnrollment` y `StageTeamsWizard` reciben `lockActive`; el mensaje es/en nombra la causa y el retiro lógico. RF-045, caso 78.
- [x] **H-11. Vía de alta no elegida.** Se oculta al elegir la otra y conserva lo escrito; ambas direcciones probadas. RF-011.
- [x] **H-12. Edad en la tarjeta de plantilla.** Prueba equivalente en `rosters.vue`. RF-017.
- [x] **H-13. Limpieza.** `frontend/_diag.mjs` eliminado sin referencias. Sin RF.
- [x] **H-6. Equivalencia aviso de cierre ↔ 409 real.** En el E2E de operación y cierre, con la **misma** versión publicada: sin el aviso la pantalla de plantillas no lo muestra y el alta responde **201**; cuando la jornada de cierre queda confirmada (tras cerrar el acta) el aviso aparece y el alta responde **409** con el `detail` de cierre, sin `code` de tamaño y sin escribir la fila. Hitos `roster-lock-absent`, `roster-created-without-lock`, `roster-lock-visible` y `roster-create-locked`. RF-017, RF-039, criterio 13.
- [x] **H-7. Casos de backend de los límites.** Dos pruebas nuevas en `backend/tests/test_roster_limits_db.py`: (a) versión **publicada** guardada antes de las tres claves → sin límite (inscripción en el clon borrador **201** y apertura del partido publicado **201** con 0 y 50 jugadores) y la lectura (lista de versiones y resolución de límites) no reescribe `rules_config` ni `current_draft_config`; (b) editar la plantilla —alta individual, importación, consentimiento y foto— **nunca** responde `ROSTER_SIZE_OUT_OF_RANGE` con la plantilla fuera de rango. RF-044, RF-045, RF-050, criterio 39.
- [x] **H-8. Teclado y asociación de errores.** El E2E recorre **todos** los pasos de los tres asistentes solo con teclado (Tab, Home, flechas y Enter), comprueba en cada paso el foco en el título y el anuncio en `aria-live`, provoca el error de límites escribiendo con el teclado, verifica `aria-invalid` y que `aria-describedby` apunta al mensaje visible (`role="alert"`), devuelve el foco al campo con Shift+Tab, lo corrige y guarda con Enter. Hitos `wizard-keyboard-rules`, `wizard-keyboard-phases`, `wizard-keyboard-teams`, `wizard-error-associated` y `wizard-error-corrected`. RF-005, RF-012, RNF-005, criterio 8.
- [x] **H-14. Atrás del asistente con la dirección como única fuente del paso.** `useWizardStep` **deriva** el paso de `route.query.step` (sin estado interno ni vigilante): una dirección sin `?step=`, con un valor desconocido o con el paso de otro asistente muestra el **paso de entrada** (el del borrador de la pestaña o el primero, y la composición en una fase existente). Al montar se normaliza la entrada con `router.replace` —solo si la dirección no nombra ningún asistente y solo desde el primer asistente de la página— y cada cambio de paso del usuario usa `router.push`; se retira `window.history.replaceState`, que el router re-sincronizaba borrando la normalización. El modelo puro (`namesWizardStep`, `stepFromAddress`, `entryStepWrite`, `stepChangeWrite`) sustituye a `stepHistoryWrites`. Prueba de navegador real: se entra al asistente desde el listado, se avanza un paso, un `page.goBack()` muestra el **primer paso** con la dirección y el `aria-current` coincidentes y un segundo `goBack()` sale del asistente; hitos `wizard-back-navigation`. RF-019, RF-013, criterio 14.
  Hecho cuando: `cd frontend && pnpm test && pnpm run typecheck && pnpm run build && pnpm run typecheck:e2e` pasan y `cd frontend && pnpm run e2e:test` termina en **0** con el hito `wizard-back-navigation`.

Verificación (2026-10-23): `pnpm test` (484), `pnpm run typecheck`, `pnpm run build` y `pnpm run typecheck:e2e` en verde; `pytest -q` **981 passed / 256 skipped**; `RUN_DATABASE_TESTS=1 … pytest -q tests/test_roster_limits_db.py` **25 passed**; `pnpm run e2e:test` **VERDE (0)** con 5 pruebas (reintento intacto) y `operation-flow` en 60.8 s / 61.6 s en dos corridas consecutivas.
Verificación de H-1/H-2/H-14 (2026-10-23): `pnpm test` **485** (la prueba que simulaba `history` se reescribió como doble del router: paso derivado de la dirección y `replace`/`push`), `pnpm run typecheck`, `pnpm run build` y `pnpm run typecheck:e2e` en verde; `pnpm run e2e:test` **VERDE (0)** con 5 pruebas (las tres del reintento **sin cambios**) y `operation-flow` en 87.9 s con 29 transiciones y los hitos `wizard-back-navigation`, `segment-at-limit`, `event-at-limit`, `event-limit-announced`, `segment-limit-announced` y `report-closed`. Backend sin cambios: `pytest -q` no se reejecutó en esta ronda.
