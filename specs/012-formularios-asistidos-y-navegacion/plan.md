# Plan 012 — Formularios asistidos, navegación independiente, traducciones y límites de plantilla

Estado: propuesto (pendiente de aprobación del usuario). Specs de referencia: `specs/012-formularios-asistidos-y-navegacion/spec.md` (aprobada, 51 RF · 11 RNF · 79 casos · 46 criterios).

Este plan **no reabre** ninguna de las 27 decisiones cerradas (DU-1, WP-1, NAV-1, WIZ-1, PLT-1, POS-1, CT-1, AT-1, IN-1, CI-1, RP-1, SG-1, P1, P2, P3, P4, P5, P6, FMT-1, MIN-1, MIN-2, AP-1, RC-1, RL-1, RA-1, BX-1, EV-1). Cuando una decisión obliga a elegir un detalle de implementación, se registra aquí con su alternativa descartada.

## 0. Estrategia

La spec es grande y toca tres superficies distintas (navegación y formularios, presentación, dominio de operación y plantilla). Se entrega en **cuatro hitos independientes**, cada uno con la aplicación en verde y desplegable, aprobables por separado:

| Hito | Alcance | RF | Depende de |
|---|---|---|---|
| **H1** | Navegación con direcciones propias, asistentes (reglas, fases, equipos), pantalla de plantillas y limpieza de la operación | RF-001…RF-024, RF-038 | — |
| **H2** | Traducciones: roles, 23 posiciones y claves | RF-025…RF-030 | — (paralelo a H1) |
| **H3** | Duración: límites por resolución expuestos, segmentos e interrupciones, resolución prevista y cierre | RF-031…RF-037 | H1 (pantalla de operación) |
| **H4** | Formato declarativo, límites de plantilla, tres bloqueos, retiro lógico y escenario E2E | RF-042…RF-051 | H1 y H3 |

H1 va primero porque introduce las rutas, el armazón de asistente y la pantalla de plantillas sobre los que trabajan H3 y H4. H2 es independiente y puede ejecutarse en paralelo, pero se numera después para no mezclar refactor de rutas con catálogo de textos. H3 antes de H4 porque ambos modifican `POST /segments`, y conviene que el campo de resolución y sus pruebas existan antes de añadir el bloqueo por plantilla en la apertura.

Cada hito cierra con: pruebas nuevas en verde, `typecheck`/`build`, y la documentación afectada actualizada. El escenario E2E nuevo se añade en H4, cuando ya existen todas las piezas que debe recorrer.

## 1. Arquitectura y archivos

### 1.1 Backend (se reutiliza lo existente; no hay módulo nuevo)

| Archivo | Responsabilidad | Estado |
|---|---|---|
| `backend/app/modules/rules_engine/engine.py` | Esquema de `rules_config` (tres claves nuevas), validación `min ≤ max`, límites efectivos de plantilla y comprobación de resolución habilitada | Modificar |
| `backend/app/modules/rules_engine/schemas.py` | `TournamentRulesConfig` gana `game_format`, `min_players_per_team`, `max_players_per_team` con defaults | Modificar |
| `backend/app/modules/rules_engine/defaults.py` | Defaults (`11v11`, sin límite) | Modificar |
| `backend/app/modules/matches/router.py` | `limits` con los cuatro campos aditivos; `resolution_type` opcional en segmento e interrupción; bloqueo de apertura por tamaño; orden de validaciones | Modificar |
| `backend/app/modules/matches/service.py` | `resolution_enabled()`, reutilización de `maximum_minute_for_resolution()` y del cálculo de límites | Modificar |
| `backend/app/modules/tournaments/router.py` | Bloqueo por tamaño en inscripción y en alta con `stage_id`; endpoint de estado de plantilla | Modificar |
| `backend/app/modules/tournaments/roster_status.py` | **Nuevo**: funciones puras de conteo/violación y la escritura de actividad (con RLS en la transacción) | Crear |
| `backend/app/main.py` | Sin cambios: no hay router nuevo; el endpoint de plantilla vive en el router de torneos ya registrado | Sin cambios |

No se crea un módulo de funcionalidad nuevo porque no hay una capacidad de dominio nueva completa: los tres bloques y el retiro lógico pertenecen a torneos y a la operación del partido, que ya tienen módulo y router.

### 1.2 Frontend

| Archivo | Responsabilidad | Estado |
|---|---|---|
| `frontend/app/pages/workspace/tournaments/[id].vue` | Pasa a ser **solo configuración**: resumen, reglas (asistente), fases (asistente), equipos (asistente) | Reducir |
| `frontend/app/pages/workspace/tournaments/[id]/calendar.vue` | **Nuevo**: calendario (crear, sortear, listar, enlazar a operación) | Crear |
| `frontend/app/pages/workspace/tournaments/[id]/rosters.vue` | **Nuevo**: administración de plantillas (formulario único, retiro lógico, avisos) | Crear |
| `frontend/app/pages/workspace/matches/[id].vue` | Conserva segmentos, planilla, oficiales, eventos y cierre; pierde el alta de jugadores; gana resolución prevista, bloques y avisos | Modificar |
| `frontend/app/components/WorkspaceShell.vue` | Índice con resumen/configuración/calendario/plantillas y operación con partido; sección activa; visibilidad de configuración para observadores | Modificar |
| `frontend/app/components/wizard/WizardShell.vue` | **Nuevo**: contenedor del asistente (índice, paso, acciones) | Crear |
| `frontend/app/components/wizard/WizardSteps.vue` | **Nuevo**: índice accesible con estados por paso | Crear |
| `frontend/app/components/rules/RulesWizard.vue` | **Nuevo**: envuelve los bloques actuales de `RulesEditor` en pasos | Crear (reutiliza `RulesEditor`) |
| `frontend/app/components/rules/RulesEditor.vue` | Se conserva como cuerpo de pasos y modo avanzado; gana el bloque de formato y límites | Modificar |
| `frontend/app/components/StageTeamsWizard.vue` | **Nuevo**: identificación, composición y revisión de la fase | Crear |
| `frontend/app/components/TeamsWizard.vue` | **Nuevo**: datos, vía de alta (individual o CSV) y revisión | Crear |
| `frontend/app/components/roster/RosterTable.vue` | **Nuevo**: lista con estado por equipo, retiro y reactivación | Crear |
| `frontend/app/components/roster/RosterSizeNotice.vue` | **Nuevo**: aviso destacado por tamaño y por cierre de inscripción | Crear |
| `frontend/app/components/FormatWarning.vue` | **Nuevo**: advertencia de formato frente a planilla de once | Crear |
| `frontend/app/composables/useWizardDraft.ts` | **Nuevo**: borrador en el almacenamiento de sesión de la pestaña | Crear |
| `frontend/app/composables/useWizardStep.ts` | **Nuevo**: paso en la dirección y navegación entre pasos | Crear |
| `frontend/app/composables/useMatchResolution.ts` | **Nuevo**: resolución prevista de la pestaña y su envío | Crear |
| `frontend/app/composables/useRosterLimits.ts` | **Nuevo**: límites efectivos de la versión y estado por equipo (lectura) | Crear |
| `frontend/app/composables/useApi.ts` | **Sin cambios**: todas las llamadas siguen pasando por aquí | Reutilizar |
| `frontend/app/stores/tournaments.ts`, `stores/auth.ts` | **Sin cambios** de contrato; el borrador no va a Pinia porque es por pestaña | Reutilizar |
| `frontend/app/utils/wizardModel.ts` | **Nuevo**: pasos, tipos y estados (funciones puras) | Crear |
| `frontend/app/utils/rosterLimits.ts` | **Nuevo**: límites, conteo y estado por equipo (puro) | Crear |
| `frontend/app/utils/rosterLock.ts` | **Nuevo**: aviso de cierre de inscripción (regla duplicada declarada) | Crear |
| `frontend/app/utils/matchResolution.ts` | **Nuevo**: máximos por resolución y resultado del cambio (puro) | Crear |
| `frontend/app/utils/positions.ts` | **Nuevo**: única fuente de las 23 etiquetas y su lado | Crear |
| `frontend/app/utils/labels.ts` | Se amplía con la fuente única de roles (ya existe) | Modificar |
| `frontend/app/constants/formations.ts` | Pierde `positionLabel`; conserva rejilla y códigos | Modificar |
| `frontend/app/composables/useI18n.ts` | Catálogo único es/en con las claves nuevas | Modificar |

## 2. Funciones puras

Regla general: ninguna lee el reloj, el entorno ni el almacenamiento; reciben los datos como parámetro. Las que sí tocan el almacenamiento o la red son envoltorios finos y probados aparte.

| Función | Firma | Para qué |
|---|---|---|
| `resolutionEnabled(minutes, resolution)` | `(MatchMinutes, Resolution) → boolean` | Decide si una resolución está habilitada por la fase (RF-032, RF-050) |
| `maximumMinuteFor(minutes, resolution)` | ya existe en `service.py`; se expone al cliente en `limits` | Máximo efectivo |
| `effectiveRosterLimits(config)` | `(RulesConfig) → { min: number; max: number }` con `0 = sin límite` | Límites de plantilla (RF-044, RF-045) |
| `rosterSizeState(count, limits)` | `(number, RosterLimits) → 'ok' \| 'below' \| 'above'` | Estado por equipo (RF-046) |
| `describeRosterViolations(rows)` | `(Array<{team, count}>, RosterLimits) → string` determinista (todos ≤ 10; si no, 10 por nombre+id y el total) | `detail` del 409 (RF-045) |
| `wizardSteps(wizard, t)` | `(WizardKind, Translate) → StepDefinition[]` | Pasos, obligatoriedad y alternativa |
| `stepState(step, values, errors)` | `(StepDefinition, Values, Errors) → 'complete' \| 'incomplete' \| 'error' \| 'omitted' \| 'alternative'` | Índice (RF-006) |
| `canConfirm(wizard, states)` | `(WizardKind, StepState[]) → { ok: boolean; blockedBy: string[] }` | Confirmación (RF-006) |
| `navigationConfirmation(kind, hasChanges)` | `(NavigationKind, boolean) → boolean` | Tabla de navegaciones de la spec (RF-008) |
| `parseStep(search, wizard)` / `stepUrl(base, step)` | `(string, WizardKind) → StepId` / `(string, StepId) → string` | Paso en la dirección (RF-013) |
| `isRosterLockActive(config, stages, matches)` | `(RulesConfig, Stage[], Match[]) → boolean` | Aviso de cierre (P4) |
| `resolutionChangeOutcome(persistedSegments, draftEvents, newMax)` | `(…, number) → 'ok' \| 'confirm' \| 'blocked'` | Cambio de resolución (RF-033, P2) |
| `matchLimitsFor(limits, resolution)` | `(OperationLimits, Resolution) → { maxMinute, addedMax }` | Eventos y segmentos (RF-032) |
| `positionKey(code)` / `roleKey(code)` | `(string) → string` (clave i18n o el propio código) | Etiquetas con fallback (RF-025…RF-028) |

## 3. Pseudocódigo

### 3.1 Máquina de estados de un asistente

```
estado = {
  wizard, versionId, phaseId?, values, errors,
  step  (de la dirección; por defecto el paso de entrada),
  dirty (valores ≠ valores del servidor)
}

al abrir:
  step = parseStep(url.search, wizard) o entryStep(wizard)
         # entryStep es el paso de entrada propio del asistente:
         # reglas y equipos, el del borrador de la pestaña o el primero;
         # fases, la composición cuando se trabaja sobre una fase existente (RF-002)
  valores = servidor(versionId)                  # siempre, también con enlace directo
  si hay borradorDeSesion(wizard, torneo, versión):
      si trae valores: valores = borrador.valores   # sin valores → solo recuerda el paso
      step = borrador.step
  si step depende de un dato ausente (fase, en pases):
      pasoBloqueado(step, enlaceAlPasoQueLoAporta)

al cambiar de paso:
  guardarBorrador()          # con cambios: paso y valores; sin cambios: solo el paso
  step = paso de la dirección  # la dirección es la única fuente del paso
  url.push(stepUrl(nuevo))   # una entrada de historial por paso del usuario
  # el navegador atrás devuelve al paso anterior, que la dirección nombra

al abrir (cliente):
  si la dirección no nombra ningún asistente:
      url.replace(stepUrl(paso de entrada))   # borrador o primero; sin historial

al escribir:
  errors = validarPaso(step, values)          # todos los errores del paso
  índice[step] = stepState(...)

al confirmar:
  si ¬canConfirm(...): llevar al primer paso que lo impide; STOP
  enviar(configuración completa o llamadas del asistente)

al guardar con éxito:
  valores = respuesta del servidor
  borrarBorrador(); dirty = false; step = primero

al recargar: el estado se reconstruye desde el borrador (misma pestaña)
al cambiar de versión/torneo: confirmar descarte y borrar borrador
al cerrar la pestaña: el navegador descarta el almacenamiento de sesión
```

El paso se persiste **también sin cambios** (solo el paso, sin valores): volver de otra sección devuelve al último paso visitado. Un borrador con solo paso no aporta valores —los del servidor mandan— y no sustituye el paso que la dirección nombra.

### 3.2 Fases: creación y composición no atómicas

```
crearFase(datos):
  fase = POST /stages
  si falla: mostrar error; STOP
  si hay equipos elegidos:
      r = POST /stages/{fase.id}/teams
      si r es 409 ROSTER_SIZE_OUT_OF_RANGE:
          avisar "fase creada sin estos equipos" + motivo
          conservar selección; ofrecer reintentar sobre fase.id
      si r es otro error: mismo aviso; reintento sobre la misma fase
  recargar y mostrar resultado por separado
```

### 3.3 Límites efectivos y detección de plantilla fuera de rango (servidor)

```
limites(config) = { min: config.min ?? 0, max: config.max ?? 0 }   # 0 = sin límite

cuenta(equipo) = SELECT count(*) FROM rosters
                 WHERE tournament_id, team_id, is_active = TRUE    # RLS fijado

estado(equipo) =
  below si limites.min > 0 y cuenta < limites.min
  above si limites.max > 0 y cuenta > limites.max
  ok    en otro caso

rechazo(equipos):
  filas = equipos con estado ≠ ok
  si filas vacío: continuar
  detalle = describeRosterViolations(filas, limites)   # determinista
  409 { detail: detalle, code: "ROSTER_SIZE_OUT_OF_RANGE" }
```

Superficies y orden de validación (decisión 8 de §9):

```
inscripción en fase / alta con stage_id:
  sesión y organización → torneo → versión en borrador (409 si publicada)
  → permiso de gestión → límites → insertar
apertura (primer segmento):
  sesión → partido y estado → permiso de operación
  → resolución habilitada (409 RESOLUTION_NOT_ENABLED)
  → límites de plantilla (409 ROSTER_SIZE_OUT_OF_RANGE)
  → minuto (422)
  → insertar segmento
```

### 3.4 Aviso de cierre de inscripción (regla duplicada, P4)

```
avisoActivo = isRosterLockActive(config, stages, matches)
# config = versión publicada más reciente; stages y matches = lecturas existentes
# regla copiada: jornada de referencia = primera fase por stage_order (id desempata);
# bloqueo si hay ≥1 partido no cancelado en esa jornada y TODOS están confirmados.

si avisoActivo: mostrar aviso antes de enviar
# el servidor sigue siendo la autoridad: si el cliente se equivoca,
# el 409 real manda y el mensaje se muestra igual.
```

La equivalencia se prueba contra el 409 real: con el mismo torneo, cuando el aviso aparece el alta responde 409; cuando no aparece, no hay 409 por ese motivo. La réplica es informativa y nunca impide guardar.

### 3.5 Cambio de resolución prevista

```
elegir(res):
  max = maximumMinuteFor(limitesEfectivos, res)
  segmentosPersistidos = los del servidor
  eventosBorrador = los del borrador local
  resultado = resolutionChangeOutcome(segmentosPersistidos, eventosBorrador, max)
  si 'blocked': no cambiar; explicar que hay segmentos guardados fuera del nuevo límite
  si 'confirm': cambiar y avisar de los eventos afectados (sin borrarlos)
  si 'ok': cambiar
  guardar la resolución en la sesión de la pestaña

al cerrar:
  enviar resolution_type = resolución prevista
  si el operador elige otra compatible: aviso + confirmación explícita; sin confirmar, no cerrar
```

## 4. Interfaz

### 4.1 Rutas

| Ruta | Contenido | Notas |
|---|---|---|
| `/workspace/tournaments/{id}` | Configuración: resumen, reglas (asistente), fases (asistente), equipos (asistente) | Conserva `#resumen`, `#configuracion`, `#equipos`; el paso del asistente va en `?step=` |
| `/workspace/tournaments/{id}/calendar` | Calendario: crear partido, sortear/regenerar, listar y enlazar a operación | `?stage=` opcional |
| `/workspace/tournaments/{id}/rosters` | Plantillas: lista por equipo, alta, importación, foto, consentimiento, retiro/reactivación | `?team=` opcional |
| `/workspace/matches/{id}` | Operación: segmentos, planilla, oficiales, eventos, cierre | Sin alta de jugadores; con resolución prevista |

Enlaces antiguos: `#calendario` y `#plantillas` **redirigen** (reemplazando la entrada de historial) a las rutas nuevas; `#resumen`, `#configuracion`, `#equipos` y `#operacion` siguen resolviendo como anclas de configuración/listado. `#calendario` conserva además `?stage=` si la dirección antigua lo traía.

### 4.2 Contratos exactos (los nueve puntos de RNF-003)

| # | Endpoint | Cambio | Efecto y compatibilidad |
|---|---|---|---|
| 1 | `GET /api/v1/matches/{match_id}/operation` | `limits` gana `max_minute_regular`, `max_minute_extra` (nulo si la prórroga no está habilitada), `extra_time_enabled`, `penalties_enabled` | Aditivo; los cuatro campos existentes conservan significado; un cliente que los ignore funciona |
| 2 | `POST /api/v1/matches/{match_id}/segments` | Campo opcional `resolution_type`; en el **primer** segmento, bloqueo por tamaño | Con campo → máximo de la resolución; sin campo → máximo de fase; 409 `RESOLUTION_NOT_ENABLED` y 409 `ROSTER_SIZE_OUT_OF_RANGE`; 422 de rango intacto |
| 3 | `POST /api/v1/matches/{match_id}/segments/{segment_id}/interrupt` | Mismo campo opcional | Idéntica regla para el minuto final |
| 4 | `POST /api/v1/matches/{match_id}/close` | Sin cambio de petición | Nuevo 409 `RESOLUTION_NOT_ENABLED`; el resto de validaciones y códigos igual |
| 5 | `POST /api/v1/tournaments/{tournament_id}/stages/{stage_id}/teams` | — | 409 `ROSTER_SIZE_OUT_OF_RANGE`; el lote no inscribe a nadie; 201/200/204 intactos |
| 6 | `POST /api/v1/tournaments/{tournament_id}/teams` | — | Mismo 409 cuando lleva `stage_id`; no crea el equipo |
| 7 | `POST /api/v1/tournaments/{tournament_id}/teams/bulk` | — | Mismo 409 con `stage_id`; lote todo o nada |
| 8 | `PATCH /api/v1/tournaments/{tournament_id}/versions/{version_id}/rules` | Tres claves aditivas | 422 de configuración inválida para `min > max`, negativos, decimales y **cadena vacía**; defaults si faltan |
| 9 | `PATCH /api/v1/tournaments/{tournament_id}/rosters/{roster_id}/status` | **Endpoint nuevo** | Cuerpo `{ "is_active": boolean }`; respuesta con el modelo de la **lista** (`player_id` y `age` incluidos); 200 idempotente; 404 entre organizaciones; 409 por `uq_active_player_tournament` y por dorsal ocupado; sin auditoría |

Reglas transversales de los 409 nuevos: `detail` es cadena legible y el `code` es aditivo; los 409 existentes sin `code` no cambian; ningún cliente que ignore `code` altera su comportamiento.

## 5. Backend

### 5.1 Registro, contexto y permisos

- No se registra ningún router nuevo: los nueve puntos viven en routers ya incluidos en `backend/app/main.py` (`tournaments`, `matches`).
- Toda ruta nueva o modificada abre su transacción con `set_rls_context(db, context.organization_id, context.user_id)` **antes** de consultar, como el resto del módulo.
- Permisos: gestión de torneos para reglas, equipos, plantillas, retiro y reactivación; operación del partido para segmentos, interrupción y cierre. No se añade ningún permiso.
- El retiro lógico no escribe auditoría: no está entre las acciones auditadas y no se añade.

### 5.2 Configuración de reglas

- `TournamentRulesConfig` gana los tres campos tipados; `RULES_SCHEMA` gana sus propiedades y mantiene `additionalProperties: false`.
- Defaults: `game_format = "11v11"`, mínimo y máximo ausentes (0 = sin límite). Una configuración guardada sin las claves se lee con defaults y **no se reescribe** hasta que el usuario guarde.
- Validación nueva: enteros ≥ 0; `min ≤ max` solo cuando ambos > 0; la cadena vacía en la API es 422. `engine_version` sigue en `2026.1` y el contrato cerrado no se toca (EV-1).
- El cliente replica la validación para dar mensajes inmediatos; el servidor sigue siendo la autoridad.

### 5.3 Dónde se aplican los tres bloqueos

1. **Inscripción en fase** (`stages/{id}/teams`): antes de insertar, cuenta la plantilla activa de cada equipo del lote.
2. **Alta con fase destino** (`teams` y `teams/bulk` con `stage_id`): misma comprobación, antes de crear el equipo.
3. **Apertura** (`segments` cuando es el primero): comprueba los dos equipos participantes antes de crear el segmento.

Con límites en 0 no se ejecuta ninguna comprobación. Un equipo por encima del máximo se corrige con retiro lógico; por debajo, con alta o importación (sujetas al bloqueo por jornada).

### 5.4 Sin migraciones (justificación)

- **No hay migración.** Los tres límites viven en `tournament_versions.rules_config` (JSONB), que ya existe.
- El retiro lógico usa `rosters.is_active`, columna existente desde `infra/postgres/init/01_schema.sql:270-295`, y sus índices parciales ya definidos: `uq_active_player_tournament` (`(tournament_id, player_id) WHERE is_active`) y `uq_active_roster_dorsal` (`(tournament_id, team_id, dorsal_number) WHERE is_active`). No hace falta índice nuevo porque las consultas filtran por torneo, equipo y actividad, que ya están cubiertos.
- No se añaden políticas RLS: las tablas implicadas ya las tienen y el endpoint reutiliza el contexto fijado en la transacción.
- Consecuencia: la base instalada en 023 es válida sin pasos de despliegue.

## 6. Frontend

- **HTTP:** todas las llamadas (reglas, fases, equipos, plantillas, retiro, operación, segmentos, cierre) pasan por `frontend/app/composables/useApi.ts`; no se añade ningún `$fetch` directo ni un cliente paralelo.
- **Rutas y navegación:** el índice del torneo se construye con enlaces reales (no anclas) a configuración, calendario y plantillas; operación solo con partido en contexto. La sección activa se deriva de la ruta. `#equipos` sigue funcionando como ancla dentro de configuración.
- **Asistentes:** un armazón común con índice accesible (`aria-current`, anuncio del cambio de paso, foco al título), pasos declarados por una función pura y estado por paso calculado, no almacenado. El cuerpo de reglas reutiliza `RulesEditor` sin duplicar sus controles.
- **Borrador:** `useWizardDraft` guarda en `sessionStorage` con clave `bc_wizard:{wizard}:{userId}:{orgId}:{tournamentId}:{versionId}` y descarta al confirmar, al descartar y al cerrar la pestaña. Nunca contiene valores en la dirección. `useWizardStep` **deriva el paso de `?step=`** (la dirección es la única fuente, también en servidor): una dirección que no nombra el asistente muestra su paso de entrada (el del borrador de la pestaña o el primero) y se normaliza al montar con `router.replace`, sin añadir historial; cada cambio de paso del usuario usa `router.push`, de modo que el botón atrás devuelve al paso anterior que la dirección nombra y el segundo atrás sale del asistente (RF-019, criterio 14). Nunca se usa `window.history.replaceState`: el router re-sincroniza la entrada y borraría la normalización.
- **Resolución prevista:** `useMatchResolution` usa `sessionStorage` con clave `bc_match_resolution:{userId}:{orgId}:{matchId}`; no toca el borrador local del partido.
- **Borrador local del partido:** se mantiene tal cual (eventos y formulario de cierre) y **deja de escribir** `resolution_type`; al restaurar, un campo antiguo se ignora y se elimina sin romper eventos ni marcador.
- **i18n:** una sola fuente para roles (`utils/labels.ts`) y para las 23 posiciones (`utils/positions.ts`), que devuelven **clave** i18n y nunca texto; el fallback es el propio código recibido. Los catálogos es/en viven solo en `useI18n.ts` y una prueba comprueba paridad y cobertura de las 23 claves. `constants/formations.ts` deja de formatear etiquetas.
- **SSR/hidratación:** el paso se resuelve en servidor desde `?step=` y los valores del formulario salen del servidor; el borrador de sesión se aplica en el cliente tras montar, con una bandera para no provocar desajuste de hidratación. Ningún acceso a `sessionStorage`/`localStorage` se ejecuta fuera de `import.meta.client`.
- **Arnés E2E:** se conservan todas las anclas de `frontend/e2e/labels.ts` (`E2E_LABELS` y `REALTIME_STATUS_TEXT`). El nuevo escenario usa texto y nombre accesible, no atributos de prueba.

## 7. Exposición pública

- No cambian los campos de ninguna respuesta pública ni se añaden documentos ni fechas de nacimiento. Las tres claves nuevas viven en la configuración de la versión y solo se muestran en el Workspace; el formato no se publica.
- El retiro lógico **no** cambia ninguna respuesta pública: las alineaciones publicadas conservan su instantánea. Sí cambia la **proyección interna** `v_public_tournament_players`, que filtra `is_active = TRUE` (migración 017) y deja de listar al jugador mientras esté retirado; no se consume desde ningún endpoint y no se expone.
- La foto sigue dependiendo del consentimiento y el documento y la fecha de nacimiento siguen fuera de las proyecciones.

## 8. Configuración y secretos

No hay variables de entorno nuevas ni cambios en `.env.example`, `docker-compose*.yml` o el contrato de entorno: todo el cambio es de código y de configuración de torneo. No se añaden dependencias.

## 9. Decisiones justificadas

1. **Navegación: direcciones propias solo para calendario y plantillas (NAV-1 A).** El resto sigue en configuración con anclas. *Descartada:* una ruta por sección, que multiplica superficie y riesgo sobre el arnés sin mejorar la tarea principal.
2. **Persistencia del asistente: almacenamiento de sesión de la pestaña + paso en la dirección (WP-1 A).** Recargar conserva paso y datos sin servidor ni disco persistente. *Descartadas:* solo memoria (pierde todo al recargar) y borrador en servidor (tabla, contratos y limpieza).
3. **Aviso de cierre de inscripción duplicado en el cliente (P4).** Se acepta la réplica para evitar un tercer cambio de contrato y se verifica por equivalencia con el 409 real. *Descartada:* endpoint de estado de inscripción, que sería contrato nuevo.
4. **Contrato aditivo y acotado (CT-1, SG-1, P5, BX-1, RC-1, EV-1).** Cuatro campos en `limits`, un campo opcional en dos peticiones, dos `code` de 409 y un endpoint nuevo de estado de plantilla. *Descartadas:* deducir los máximos en el cliente (duplica la regla) y un máximo único por fase (cambia el significado de la resolución).
5. **Retiro lógico frente a borrado (RC-1).** Se desactiva la fila y se conserva el histórico; la reactivación es la reversión si el jugador no tiene ya otra fila activa. *Descartado:* borrado físico, que rompería alineaciones, eventos y resultados.
6. **Bloqueo de apertura en la creación del primer segmento (AP-1).** No se inventa un endpoint de apertura: se usa el que ya pone el partido en juego. *Descartada:* un endpoint `start` nuevo, que añadiría contrato y un estado que hoy no existe.
7. **La reactivación se comporta como un alta (RA-1).** Suma un jugador activo: sujeta al bloqueo por jornada y a la unicidad. *Descartada:* eximirla, que reabriría el bloqueo por la puerta de atrás.
8. **Orden de validación en la apertura (decisión de implementación).** Resolución habilitada antes que tamaño de plantilla, y ambas antes del minuto. *Descartada:* tamaño primero, que ocultaría un error de configuración de resolución que el operador debe corregir igualmente.

## 10. Estrategia de tests

### 10.1 Backend (pytest, sin base salvo lo indicado)

| Prueba | Cubre |
|---|---|
| `test_rules_config_compat.py` (ampliar) | RF-044: defaults sin claves, enteros ≥ 0, `min ≤ max`, cadena vacía 422, `engine_version` 2026.1 |
| `test_match_minutes.py` (ampliar sin cambiar lo existente) | RF-032, RF-033: sin `resolution_type` → máximo de fase; con reglamentario; con prórroga; 422 de rango; `resolutionEnabled` y 409 `RESOLUTION_NOT_ENABLED` en segmento, interrupción y cierre |
| `test_roster_lock.py` (sin cambios) | RF-046: el bloqueo por jornada sigue igual para alta e importación |
| nuevo `test_roster_limits.py` | RF-045, RF-050: límites efectivos, conteo activo, violaciones y `detail` determinista (puro) |
| `test_match_operation_audit.py` (ampliar) | RF-051: el retiro no escribe auditoría |
| `test_error_sanitization.py` / `test_api_access.py` (ampliar) | RF-048: 404 entre organizaciones y mensajes sin datos sensibles |

### 10.2 Integración opt-in con PostgreSQL (`RUN_DATABASE_TESTS=1` y `DATABASE_ADMIN_URL`)

- `test_roster_limits_db.py`: inscripción en fase bloqueada y permitida; alta individual y lote con `stage_id`; apertura bloqueada sin crear segmento ni cambiar estado; apertura tras retiro lógico; 409 determinista con 11 equipos.
- `test_roster_status_db.py`: retiro y reactivación con bloqueo por jornada activo; idempotencia; 404 entre organizaciones; 409 por `uq_active_player_tournament` y por dorsal; ausencia de auditoría; y `v_public_tournament_players` deja de listar al retirado.
- `test_match_resolution_db.py`: operación con los cuatro campos; segmento e interrupción con y sin resolución; cierre con resolución no habilitada; comportamiento idéntico al actual sin el campo (comparado con la prueba existente).

### 10.3 Frontend (`node:test`, sin DOM)

- `tests/wizard-model.test.ts`: pasos por asistente, obligatorio/opcional/alternativo, estados, confirmación, tabla de navegaciones.
- `tests/wizard-step.test.ts`: `parseStep`/`stepUrl`, paso ausente, paso inválido, enlace compartido, paso de entrada por asistente, `entryStepWrite`/`stepChangeWrite` sobre un **doble del router** (una entrada por cambio de paso y atrás al paso anterior), y el borrador de la pestaña: recuerdo del paso **sin cambios** (solo el paso, sin valores), con cambios (paso y valores) y sin valores vacíos.
- `tests/roster-limits.test.ts`: límites, estado por equipo, `0` = sin límite, mensajes.
- `tests/roster-lock.test.ts`: regla duplicada — jornada de referencia, todos confirmados, no cancelados.
- `tests/match-resolution.test.ts`: máximos por resolución, `resolutionChangeOutcome` (ok/confirm/blocked), borrador local sin resolución.
- `tests/positions.test.ts`: 23 claves, paridad es/en, lado declarado y fallback.
- `tests/labels.test.ts` (ampliar): roles desde una fuente, `owner` incluido, código desconocido tal cual.
- `tests/navigation.test.ts` (ampliar): sección activa, redirecciones y anclas conservadas.
- `tests/rules-config.test.ts` (ampliar): tres claves, `min ≤ max`, defaults y paridad de claves.
- El modelo del paso es puro y sin estado de sesión: `createWizardSession` y `resolveWizardStart` se retiran por no tener ningún consumidor en la aplicación; la cobertura se mantiene sobre las funciones vivas (`stepFromAddress`, `namesWizardStep`, `stepChangeWrite`, `entryStepWrite`) y la tabla de navegaciones.

### 10.4 Navegador y compilación

- `pnpm run typecheck`, `pnpm run build`, `pnpm run typecheck:e2e` en cada hito.
- **Escenario E2E nuevo** `e2e/operationFlow.spec.ts` (proyecto propio, `retries: 0`, Chromium): paso de reglas con cuatro opciones y 11v11 por defecto; solo lectura en versión publicada; las tres advertencias de formato; inscripción bloqueada; apertura bloqueada; retiro lógico con reactivación; y accesibilidad/foco de los asistentes. Deja su artefacto y no modifica el escenario de reintento ni su veredicto 0/1/2/3. Se ejecuta con `pnpm run e2e` (con pila) y `pnpm run e2e:test` (sin arrancar la pila).

### 10.5 Qué no se puede automatizar

- La semántica real de un lector de pantalla (se verifica rol, foco y anuncio, no la locución).
- El aspecto visual exacto de los avisos y del índice en cada resolución (se comprueba presencia, texto y que el índice no desplace el contenido en 1280×800).
- La sensación de latencia; solo se mide que no aumenten las lecturas por sección.
- El comportamiento real de dos dispositivos distintos (se simula con dos contextos de navegador).

## 11. Riesgos

1. **Refactor de la página de configuración** (1.330 líneas) puede romper sorteo, publicación o edición de fases. Mitigación: T02 sin cambios de lógica, pruebas existentes de `stage-teams` y E2E de humo; hitos separados.
2. **Hidratación con borrador de sesión.** Mitigación: paso desde la URL en servidor, valores del servidor al renderizar y borrador aplicado tras montar.
3. **Deriva de la regla duplicada del cierre de inscripción.** Mitigación: prueba de equivalencia contra el 409 real y una sola función pura reutilizada por las dos pantallas que muestran el aviso.
4. **Pydantic y claves nuevas.** `TournamentRulesConfig` no prohíbe campos extra por sí mismo; el rechazo real lo da `RULES_SCHEMA`. Mitigación: declarar los campos en ambos sitios y probar que una clave desconocida sigue fallando.
5. **Doble modificación de `POST /segments`** en H3 y H4. Mitigación: H3 define el campo y H4 solo añade la comprobación de tamaño, con orden de validación documentado.
6. **Presupuesto E2E** (job 25 min, vista 4 min). Mitigación: escenario acotado, sin esperas fijas y con `retries: 0`.
7. **Retiro y proyección interna.** Confundir «respuestas públicas sin cambios» con «proyección interna sin cambios». Mitigación: prueba explícita de que `v_public_tournament_players` deja de listar al retirado.

## 12. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 1. Aislamiento garantizado por RLS | Sí | Toda ruta nueva o modificada fija `set_rls_context()` en la transacción; el endpoint de retiro y los tres bloqueos filtran por `organization_id`; prueba de 404 entre organizaciones |
| 2. La aplicación no salta RLS | Sí | No se añaden roles ni políticas; se usa el rol de aplicación existente |
| 3. Lo publicado es inmutable | Sí | Las tres claves y los límites se leen de la versión publicada y no se reescriben; actas cerradas y estructura publicada intactas (RF-035, RF-047) |
| 4. Historial de esquema append-only | Sí | **No hay migraciones**: se reutiliza `rosters.is_active` y los índices existentes |
| 5. Lo público es una proyección mínima | Sí | No se añaden campos públicos; documento y fecha siguen fuera; el retiro solo afecta a una proyección interna |
| 6. Ningún secreto por defecto fuera de desarrollo | Sí | No hay variables ni secretos nuevos |
| 7. Administración global separada y auditada | No aplica | No se toca `/admin` ni la auditoría de plataforma |
| 8. Nada se da por terminado sin verificación | Sí | Cada hito cierra con pytest, typecheck, build y, en H4, el escenario E2E; lo no ejecutable se declara |
| 9. El código de desarrollo no llega a producción | Sí | No se añaden seeds ni datos demo; las pruebas usan la organización demo solo en local |
| §4 · CI `backend`/`frontend`/`infrastructure`/`security`/`e2e` | Sí | Se ejecutan los jobs que apliquen; `e2e` en cada PR y en `main`; el escenario nuevo no altera el de reintento |
| §4 · Sin secretos ni datos personales en el repo | Sí | Solo datos ficticios de desarrollo; nada en artefactos |
| §4 · Documentación actualizada si cambia el comportamiento | Sí | `README.md`, `AGENTS.md`, `/docs` y la aclaración de `docs/contrato-reglas.md` en H3/H4 |
| §4 · Pruebas del comportamiento nuevo | Sí | Matriz de §10; lo no automatizable se declara |
| §4 · API: público sin campos sensibles | Sí | Sin cambios en respuestas públicas |
| §4 · API: router registrado | No aplica | No hay router nuevo; el endpoint nuevo usa el de torneos |
| §4 · Frontend: HTTP por `useApi.ts` y `pnpm test`/`typecheck`/`build` | Sí | Todas las llamadas por `useApi`; los tres comandos en verde |
| §4 · Base de datos: RLS y volumen limpio/migrado | No aplica | Sin migraciones |
| §5.1 Excepciones | No aplica | No se necesita ninguna |

## 13. Orden de ejecución

`H1-T01…T11` → `H2-T01…T04` (paralelizable tras H1-T01) → `H3-T01…T08` → `H4-T01…T11`.

## 14. Trazabilidad RF → hito → tarea

| RF | Hito | Tareas |
|---|---|---|
| RF-001…RF-015 | H1 | H1-T03…H1-T07 |
| RF-016…RF-021 | H1 | H1-T01, H1-T02, H1-T08, H1-T09 |
| RF-022 | H1, H3 | H1-T09, H3-T06 |
| RF-023, RF-024 | H1 | H1-T02, H1-T08 |
| RF-025…RF-030 | H2 | H2-T01…H2-T04 |
| RF-031…RF-037 | H3 | H3-T01…H3-T08 |
| RF-031 | H3 | H3-T09 (nomenclatura del minuto final y campo de prórroga deshabilitado; NM-1 = A) |
| RF-038 | H1 | H1-T10 |
| RF-039…RF-041 | H1, H3, H4 | H1-T08 (P4), H1-T11, H3-T07, H4-T11 |
| RF-042…RF-049 | H4 | H4-T01…H4-T11 |
| RF-050 | H4 | H4-T05, H4-T09 |
| RF-051 | H4 | H4-T06, H4-T08 |
