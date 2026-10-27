# Plan de implementación — Endurecimiento de esquemas de petición (spec 019)

> Complementa `spec.md` (fuente de verdad de los requisitos). No repite la justificación
> normativa: aquí solo se decide **cómo** se cumple cada RF y qué se descarta.

## 1. Alcance

**Dentro:** endurecer la validación de entrada de las **33 operaciones con cuerpo JSON** de la
API añadiendo `extra="forbid"` a los **34 modelos de petición** (29 de primer nivel + 5 anidados),
cerrar el **primer nivel** de `rules_config` y endurecer los **cuatro cuerpos** que el cliente
envía hoy expandiendo formularios reactivos, todo en un **cambio único** (RF-001, RF-002,
RF-003 y RF-005, con RF-004 como frontera de los mapas abiertos; el corte único, RNF-004(f)).

**Fuera (explícito):**

- Las **tres operaciones multipart** (`POST …/rosters/bulk`, `POST …/rosters/{id}/photo`,
  `POST …/teams/{id}/crest`), las operaciones sin cuerpo (GET/DELETE) y cualquier parámetro de
  ruta, query o cabecera (RF-006, RNF-011).
- Los **bloques internos** de `rules_config` (`points_system`, `ranking_pipeline`,
  `substitutions`, `discipline`, `stage_defaults`, `stage_overrides`), que siguen siendo
  `dict[str, Any]`/`list[dict[str, Any]]` (RF-003; `stage_overrides` es además mapa abierto de RF-004).
- Los modelos de **respuesta**, la forma del 422 (RF-010), `engine_version` 2026.1 y el contrato
  cerrado de `docs/contrato-reglas.md`.
- Migraciones, esquema de base de datos, RLS, datos (RNF-005).

## 2. Archivos afectados

### 2.1 Backend (solo `model_config` y comentarios; sin lógica de negocio)

| Archivo | Modelos de primer nivel | Anidados |
| --- | --- | --- |
| `backend/app/modules/identity/schemas.py` | `RegisterRequest`, `LoginRequest`, `GoogleStartRequest` | — |
| `backend/app/modules/invitations/schemas.py` | `CreateInvitationRequest`, `UpdateMemberRoleRequest`, `UpdateMemberActiveRequest`, `AcceptInvitationRequest` | — |
| `backend/app/modules/organizations/schemas.py` | `OrganizationCreateRequest` | — |
| `backend/app/modules/platform/schemas.py` | `OutboxReprocessRequest`, `CreateMembershipRequest`, `SetActiveRequest` | — |
| `backend/app/modules/rules_engine/schemas.py` | `CreateTournamentRequest`, `UpdateRulesConfigRequest` | `TournamentRulesConfig` |
| `backend/app/modules/tournaments/schemas.py` | `CreateTournamentTeamRequest`, `BulkTournamentTeamRequest`, `CreateStageRequest`, `AssignStageTeamsRequest`, `CreateMatchRequest`, `GenerateSingleEliminationRequest`, `CreateDraftVersionRequest`, `CreateRosterPlayerRequest`, `UpdatePhotoConsentRequest`, `UpdateRosterStatusRequest` | `BulkTournamentTeamItem` |
| `backend/app/modules/matches/schemas.py` | `SaveMatchLineupRequest`, `PublishMatchLineupRequest`, `OfficialAssignmentRequest`, `CreateMatchSegmentRequest`, `InterruptMatchSegmentRequest`, `CloseMatchReportDTO` | `MatchTeamLineupConfig`, `MatchLineupEntry`, `MatchEventPayload` (ya cerrado: solo comentario, RNF-007) |

Inventario verificado ejecutando el barrido contra la app en ejecución (§4): **29 + 5 = 34
modelos**, servidos por **33 operaciones** (`SetActiveRequest` reutilizado en 3,
`GenerateSingleEliminationRequest` en 2 y `UpdateRulesConfigRequest` en 2).

### 2.2 Backend (pruebas)

- `backend/tests/test_request_schema_strictness.py` — **nuevo**: barrido de comportamiento
  (inventario, derivación desde la app, rechazo por modelo y precedencia HTTP).
- `backend/tests/test_rules_config_compat.py` — **ampliado**: primer nivel cerrado +
  `transfers` + bloques internos todavía tolerados.
- `backend/tests/test_match_events_contract.py` — **ampliado**: el comentario de
  `MatchEventPayload` documenta que `extra="forbid"` es una propiedad del catálogo cerrado
  (RNF-007); se añade la aserción de que un `goal` con asistencia y un evento con
  `metadata.red_card_type` siguen siendo válidos.

### 2.3 Frontend

- `frontend/app/utils/requestBodies.ts` — **nuevo**: constructores puros de los cuatro cuerpos.
- `frontend/tests/request-bodies.test.ts` — **nuevo**: `node --test` de los constructores.
- `frontend/app/pages/workspace/tournaments/[id]/rosters.vue` (`createPlayer`, ~línea 284),
  `frontend/app/pages/workspace/members.vue` (`inviteMember`, ~línea 153),
  `frontend/app/pages/workspace/matches/[id].vue` (`assignOfficial`, ~línea 1130) y
  `frontend/app/pages/workspace/index.vue` (`createTournament`, ~línea 112): consumen los
  constructores.

### 2.4 Documentación

- `AGENTS.md` («Límites del Proyecto»: la regla general y las tres operaciones multipart
  excluidas), `README.md` (nota breve de compatibilidad), comentarios de los modelos cerrados y
  `MEMORY.md` al cerrar la fase.

## 3. Funciones puras y componentes sin estado

La producción no gana algoritmo: el endurecimiento es **declarativo** (una bandera por modelo).
Las únicas piezas con lógica son funciones puras y sin efectos:

- `collect_json_body_operations(api) -> list[Operation]` (test): recorre el árbol de rutas y
  devuelve `(método, plantilla, modelo)`; determinista, sin BD, sin red, sin reloj.
- `minimal_valid_body(model) -> dict`: cuerpo mínimo sintácticamente válido por modelo, a partir
  de un mapa literal por modelo (necesario para inyectar la clave extra sin tocar el resto).
- `buildRosterPlayerBody`, `buildInviteMemberBody`, `buildOfficialAssignmentBody`,
  `buildTournamentDraftBody` (frontend): reciben el estado del formulario y devuelven **solo** las
  claves declaradas del DTO. Sin acceso a `reactive`, sin `request`, sin efectos (mismo patrón que
  `buildCloseReportBody`, `frontend/app/utils/matchClose.ts:296`).

Los modelos Pydantic son tipos declarativos ya presentes; la app `FastAPI` se usa solo como
fuente de inventario en pruebas.

## 4. Pseudocódigo del barrido de comportamiento (RF-001, RF-002, RF-003; el barrido mismo, RNF-006)

```python
# backend/tests/test_request_schema_strictness.py
EXPECTED_OPERATIONS = [                       # inventario literal (biyección, §2.1)
    ("POST",   "/api/v1/auth/register",                  "identity.schemas.RegisterRequest"),
    ("PATCH",  "/api/v1/tournaments/{tournament_id}/versions/{version_id}",
                                                          "rules_engine.schemas.UpdateRulesConfigRequest"),
    ...  # 33 entradas, excluidas las 3 multipart
]

def walk_routes(routes):                     # FastAPI 0.143 anida: recursión por
    for route in routes:                     # _IncludedRouter.original_router.routes
        if isinstance(route, APIRoute):
            yield route
        inner = getattr(route, "original_router", None)
        if inner is not None:
            yield from walk_routes(inner.routes)

def body_model(route):                       # la anotación vive en field_info.annotation
    for field in route.dependant.body_params:
        yield unwrap_list_optional(field.field_info.annotation)   # list[T] / Optional[T]

# 1) biyección inventario ↔ app: una operación JSON sin modelo Pydantic o un modelo
#    no inventariado rompe la prueba con mensaje explícito (derivar de la app, no
#    de openapi.json: D-3).
# 2) por cada modelo servido: assert model_config["extra"] == "forbid"
# 3) por cada modelo: Model.model_validate(minimal_valid_body(model) | {"extra": 1})
#    -> ValidationError, error["type"] == "extra_forbidden", loc == ["extra"],
#    "extra" con el valor rechazado.
# 4) subconjunto HTTP representativo (§12, RF-009): httpx.ASGITransport sobre `api`
#    con dependency_overrides; 422 con detail en lista, sin "code" (RF-010).
```

Tres detalles medidos en el entorno real (fastAPI **0.143.1**, pydantic **2.14.1**) que el
barrido debe conocer y que este plan fija como hecho comprobado:

1. `app.main.app` es un `socketio.ASGIApp`; el `FastAPI` es `app.main.api` (línea 598).
2. `ModelField` no expone `type_`: la anotación del cuerpo está en `field_info.annotation`.
3. Las 38 entradas de cuerpo de la app menos las 5 que son multipart (3 operaciones) dan
   **exactamente las 33 operaciones JSON** de la spec; ninguna usa `dict` sin modelo.

## 5. Interfaz pública (contrato)

- **Sin endpoints nuevos ni eliminados.** La única respuesta afectada es un **422** que antes no
  existía: una clave no declarada en el cuerpo pasa de *ignorarse* a rechazarse (RF-001).
- La **forma** del 422 no cambia (RF-010): `{"detail": [ {type, loc, msg} ]}`, sin `code` y sin
  eco del valor rechazado; el saneado sigue en `backend/app/main.py:601-624` con
  `VALIDATION_ERROR_FIELDS = ("type", "loc", "msg")` (`app/main.py:67`).
- **Cambio de comportamiento visible y deliberado:** hoy una clave extra en `rules_config` se
  **descarta en silencio** (medido: `TournamentRulesConfig.model_validate({…, "zzz_extra": 1})`
  la acepta y no la persiste). Con la 019 responde **422**. Ningún otro valor semántico cambia:
  `transfers` sigue aceptándose y promoviendo `roster_lock_matchday` (RF-003).
- Modelos de respuesta y `engine_version` **2026.1** intactos (RF-007, RF-012, RNF-004(e)).

## 6. Decisiones de diseño (con la alternativa descartada)

**D-1 — Bandera explícita por modelo, no clase base compartida.**
Cada uno de los 34 modelos declara `model_config = ConfigDict(extra="forbid")` en su propio
cuerpo (los que ya la tienen, como `MatchEventPayload`, la conservan).
*Descartado:* una clase base `StrictRequestModel` en `app/core/` de la que heredaran 34 modelos:
acoplaría todos los módulos a un símbolo del core, cambiaría el MRO de modelos que ya usan
`model_validator`/`Field(exclude=True)` y convertiría la aserción del barrido (que audita una
bandera por modelo) en una auditoría de jerarquías de herencia. La bandera explícita es
*greppable*, revisable en diff y verificable por aserción directa.

**D-2 — `rules_config` cierra solo el primer nivel, en la capa Pydantic.**
`TournamentRulesConfig` gana `extra="forbid"` y mantiene tal cual su `model_validator(mode="after")`
(`schemas.py:34-47`: normaliza, promueve `transfers` a `roster_lock_matchday` y lo pone a `None`).
Los bloques internos siguen siendo `dict[str, Any]`, así que «cerrar el primer nivel» no toca
`stage_overrides` ni los parámetros de desempate (RF-004) y **su cierre efectivo es el validador
propio**. Medido en ejecución: el `model_validator(mode="after")` de `TournamentRulesConfig`
→ `normalize_rules_config` → `validate_rules_config` **sí se invoca en el camino de la petición**
para las claves **dentro de bloques** (el validador de `TournamentRulesConfig` los envuelve y
`RULES_SCHEMA` los cierra con `additionalProperties: false`); `validate_rules_config` se llama
además desde `standings/service.py:54` y `tournaments/router.py:4293` sobre configs ya
almacenadas. **Solo el primer nivel no lo alcanza:** la validación de campos ocurre **antes** del
validador (`mode="after"` se ejecuta tras ella), así que con `extra="forbid"` una clave extra de
primer nivel responde 422 sin llegar a la normalización.
*Descartado:* cerrar solo en el motor (`RULES_SCHEMA`, `engine.py:43-171`, que ya tiene
`additionalProperties: false` en la raíz) sin `extra="forbid"` en el modelo: aunque
`validate_rules_config` sí corre en la petición para los bloques, un primer nivel desconocido se
**descarta en silencio en Pydantic** antes de `mode="after"` (medido: el modelo lo acepta y no lo
persiste), así que el motor nunca lo vería y el primer nivel quedaría sin cerrar; además el motor
no produciría el 422 saneado de FastAPI. Tampoco se descarta la clave en silencio (violaría
RF-003) ni se responde 409 (clase de error equivocada).

**D-3 — El barrido es una prueba, no código de producción.**
Inventario literal (33 entradas) + derivación desde `app.routes` + aserción de biyección +
aserción de bandera por modelo + rechazo `extra_forbidden` en la capa Pydantic, con un
**subconjunto HTTP representativo** para la forma del 422 y la precedencia (§12).
*Descartado:* 33 fixtures HTTP completos: duplicarían autenticación, organización y datos por
operación, serían frágiles ante cualquier cambio de ruta y no añadirían garantía, porque FastAPI
alimenta el cuerpo por el mismo modelo Pydantic que ya se prueba (el 422 nace ahí, no en la ruta).

**D-4 — La precedencia se fija con la medición, no con la intuición (RF-009).**
Verificado empíricamente con fastAPI 0.143.1 en este entorno: (a) una **dependencia** que lanza
403 (sesión/membresía) se ejecuta **antes** de validar el cuerpo → 403/401/400 ganan; (b) un 403
o un 404 de recurso ajeno resueltos **dentro del handler** se ejecutan después → gana el 422 del
cuerpo. El plan codifica ese orden y las pruebas lo fijan (§12, RF-009). El middleware de
tamaño/CSRF sigue por delante por construcción (no se toca).

**D-5 — Un único módulo de constructores puros en el cliente.**
`frontend/app/utils/requestBodies.ts` con los cuatro constructores y sus tipos de entrada.
*Descartado:* repartirlos por los módulos de cada funcionalidad (la regla es transversal y
 cruzar cuatro áreas dispersa la auditoría); y *descartado* confiar solo en tipos TypeScript:
los tipos no limitan el payload en tiempo de ejecución, que es exactamente lo que endurece
RF-001.

**D-6 — Cambio único, sin ventana de gracia (RNF-004(f)).**
Servidor y cliente se entregan en el mismo PR: el cliente deja de expandir formularios
reactivos **antes** o **a la vez** de que el servidor rechace. No hay versión intermedia que
tolere claves extra ni cabecera de compatibilidad.
*Descartado:* despliegue en dos fases con tolerancia temporal: obligaría a un estado en el que
el servidor acepta claves basura (que es el fallo silencioso que la spec elimina) y a retirar
esa tolerancia con un segundo cambio.

**D-7 — Sin migración ni dato.**
Ningún RF de la 019 toca esquema, RLS ni datos; el estado de la base de datos es idéntico antes
y después (RNF-005). La regla completa vive en modelos Pydantic y en pruebas.

## 7. Sin base de datos, sin migraciones, sin RLS

Los modelos de petición no son `Table` de SQLAlchemy y no se persisten; la validación ocurre en
la capa HTTP antes de cualquier transacción. No se añade ni modifica migración, política, grant
ni `set_rls_context`. Ninguna prueba **nueva** de esta spec necesita `RUN_DATABASE_TESTS=1`
(`test_request_schema_strictness.py` usa `httpx.ASGITransport` con `dependency_overrides`, sin
motor de BD). Si una prueba **nueva** reclamara BD, es un error de diseño de la prueba. RNF-006 sí
exige, como regresión de la verificación final, las suites opt-in con base existentes (T10).

## 8. Backend — validación y manejo de errores (RF-001, RF-010)

- La bandera se aplica en el **modelo de petición**, que es donde FastAPI construye el 422
  saneado. No se modifica `_request_validation_exception_handler` ni `VALIDATION_ERROR_FIELDS`.
- `extra="forbid"` produce `type: "extra_forbidden"` con `loc: ["extra", …]`, que el saneado
  reduce a `type`/`loc`/`msg` (sin `input`, sin `ctx` → sin eco del valor rechazado, RF-010, RNF-002).
- Un cuerpo 100 % válido sigue respondiendo igual (200/201/204), porque `extra` no altera campos
  declarados; las pruebas de regresión existentes (contrato de eventos, sustituciones, walkover,
  cierre del acta, invitaciones, escudos) son la red de seguridad.
- `MatchEventPayload` conserva su `extra="forbid"` **actual**; solo se actualiza su comentario
  para decir que no es una excepción sino la regla general del catálogo cerrado (RNF-007).

## 9. Frontend (RF-005, RNF-004(b))

Los cuatro constructores devuelven **solo** las claves declaradas del DTO, con tipos de entrada
explícitos (sin `any`):

| Constructor | DTO del servidor | Página consumidora |
| --- | --- | --- |
| `buildRosterPlayerBody` | `CreateRosterPlayerRequest` (+`team_id`) | `rosters.vue` `createPlayer` |
| `buildInviteMemberBody` | `CreateInvitationRequest` | `members.vue` `inviteMember` |
| `buildOfficialAssignmentBody` | `OfficialAssignmentRequest` | `matches/[id].vue` `assignOfficial` |
| `buildTournamentDraftBody` | `CreateTournamentRequest` (sin `rules_config`, que trae default) | `index.vue` `createTournament` |

Ninguna página expande un `reactive()` en el `body` tras este cambio. El cuerpo del cierre del
acta ya pasa por `buildCloseReportBody` (`matchClose.ts:296`) y **no** se toca: es el patrón que
se replica. Sin cambios en `useApi.ts`, sin cambios de UI, sin cambios de i18n.

## 10. Exposición pública y privacidad

La API pública (`/api/v1/tournaments/public*`) no tiene operaciones con cuerpo: **no cambia**.
El endurecimiento **reduce** la superficie de entrada (menos claves ajenas aceptadas) y no añade
ningún dato a respuesta pública; el saneado del 422 (sin eco del valor) se conserva, de modo que
la privacidad de fecha de nacimiento y documento no se ve afectada.

## 11. Configuración, despliegue y compatibilidad (RNF-004)

- **Sin variables de entorno nuevas**, sin cambios en `docker-compose*.yml`,
  `.env.example` ni `infra/scripts/check_env_contract.py`.
- **Un solo PR** con backend, cliente y documentación (D-6). El orden de despliegue no aplica:
  no hay migración ni esquema.
- **Compatibilidad:** un cliente que solo envía campos declarados no nota nada. Un cliente que
  enviaba claves extra recibía antes un éxito silencioso con la clave descartada (o, en
  `rules_config`, una configuración sin esa clave); ahora recibe **422** (la clave en `loc` en los objetos que cierra el modelo de la petición; en los
  bloques anidados de `rules_config`, el camino solo en el mensaje), que es la corrección buscada. Los cuatro cuerpos del cliente oficial se corrigen en
  el mismo cambio.

## 12. Estrategia de pruebas (RF-005, RF-008, RF-009, RF-010)

**Backend (todo sin BD, en el contenedor `api`):**

1. `test_request_schema_strictness.py` (nuevo):
   - **Inventario:** 33 operaciones JSON; biyección con `app.routes` (faltan o sobran → fallo
     con detalle). RNF-006.
   - **Bandera:** los 34 modelos con `extra == "forbid"`. RF-001, RF-002.
   - **Rechazo por modelo:** `model_validate(cuerpo_minimo | {"extra": 1})` → `extra_forbidden`,
     sin eco del valor. RF-001, RF-002.
   - **Precedencia HTTP** (subconjunto representativo: reglas, creación de torneo, alta en
     roster, evento de partido):
     * dependencia de membresía reemplazada que lanza 403 + cuerpo inválido → **403**;
     * dependencia de sesión ausente → **401**; cabecera de organización inválida → **400**;
     * recurso ajeno resuelto en el handler + cuerpo inválido → **422** (gana el cuerpo);
     * cuerpo inválido + handler que lanza 403 de permiso → **422**;
     * el 422 es `{"detail": [ {type, loc, msg} ]}` sin `code` y sin `input`. RF-009, RF-010.
2. `test_rules_config_compat.py` (ampliado): primer nivel con clave extra → **422** (antes
   silencioso); `transfers` sigue aceptado y promueve `roster_lock_matchday`; un
   `stage_overrides` con claves internas arbitrarias sigue tolerado. RF-003, RF-004.
3. `test_match_events_contract.py` (ampliado): un `goal` con `assist_player_id` y un
   `red_card` con `metadata.red_card_type` siguen siendo válidos (no regresión del catálogo).
   RF-008.
4. Regresión: la suite completa del backend, que ya cubre sustituciones, walkover, cierre del
   acta, sanciones, invitaciones, escudos y contratos públicos.

**Frontend (fuera de Docker, `pnpm`):**

5. `frontend/tests/request-bodies.test.ts` (`node --test`): cada constructor devuelve exactamente
   las claves declaradas (uso de `Object.keys` ordenado), ignora claves extra del formulario de
   entrada, no muta su argumento y produce el objeto esperado para un caso de cada uno.
   RF-005, RNF-004(b).
6. `pnpm run typecheck` y `pnpm run build` (los `.vue` ya no expanditen `reactive`).

**Comandos de verificación (RNF-006):**

```sh
docker compose exec -T api pytest -q tests/test_request_schema_strictness.py \
  tests/test_rules_config_compat.py tests/test_match_events_contract.py
docker compose exec -T api pytest -q                       # regresión completa
cd frontend && pnpm test && pnpm run typecheck && pnpm run build
# (en la práctica del proyecto los comandos de frontend se ejecutan dentro del
#  contenedor `web`, que es donde está el Node con TypeScript: T10 los fija)
```

## 13. Trazabilidad RF → plan → prueba

| RF | Dónde se cumple | Prueba |
| --- | --- | --- |
| RF-001 | §6 D-1, §8 | `test_request_schema_strictness` (rechazo de clave de primer nivel en los 29 modelos) |
| RF-002 | §2.1, §6 D-1, §12.1 | `test_request_schema_strictness` (rechazo recursivo en los 5 anidados; mapa abierto excluido) |
| RF-003 | §5, §6 D-2, §12.2 | `test_rules_config_compat` (422 de primer nivel, `transfers` y bloques anidados intactos) |
| RF-004 | §1 «Fuera», §12.2 | `test_rules_config_compat` (los mapas abiertos siguen admitiendo claves) |
| RF-005 | §9, §12.5 | `frontend/tests/request-bodies.test.ts` (constructores con prueba propia) |
| RF-006 | §1 «Fuera», §12.1 | aserción de que las 3 multipart no aparecen en el inventario |
| RF-007 | §5, §8 | modelos de respuesta sin tocar, handler sin cambios y regresión completa |
| RF-008 | §8, §12.3 | `test_match_events_contract` (catálogo, `metadata` y asistencia intactos) + regresión |
| RF-009 | §6 D-4, §12.1 | `test_request_schema_strictness` (precedencia por capas) |
| RF-010 | §5, §8, §12.1 | 422 con `detail` en lista `type/loc/msg`, sin `code` y sin eco del valor |
| RF-011 | §7 | pruebas sin BD ni transacción propia; el rechazo no consulta datos |
| RF-012 | §1, §11 | sin endpoint, permiso ni evento nuevo; `engine_version` intacta: regresión y `git status` |
| RNF-001 | §7, §10 | sin consulta de datos de organización; la API pública sin cuerpo no cambia |
| RNF-002 | §8, §12.1 | saneado sin `input`/`ctx`; el nombre de la clave solo viaja al cliente que la envió |
| RNF-003 | §6 D-1, §12 | sin consultas ni llamadas nuevas: solo `model_config` por modelo, coste lineal |
| RNF-004 | §5, §11 | (a)-(d) y (f) declarados como cambio; (e) intacto y verificado por regresión |
| RNF-005 | §7, §11 | sin migración; sin cambios en `infra/` |
| RNF-006 | §4, §12 | barrido derivado de las rutas + comandos ejecutados y evidenciados (T10) |
| RNF-007 | §2.2, §2.4, §8 | comentario de `MatchEventPayload`, `AGENTS.md`, `README.md` y comentarios de los modelos |
| RNF-008 | §8 | ningún rechazo escribe auditoría; ninguna acción auditada nueva |
| RNF-009 | §8, §12.3 | sin eventos de outbox ni mensajes nuevos: regresión de outbox y relay |
| RNF-010 | §8, §12.1 | el rechazo no deja rastro y repetir la petición inválida da la misma respuesta |
| RNF-011 | §1 «Fuera», §14 | multipart, query y cabeceras excluidos y declarados como riesgo aceptado |

## 14. Riesgos y mitigaciones

1. **Derivar el inventario mal por detalles de FastAPI 0.143** (`_IncludedRouter`,
   `field_info.annotation`, `list[T]`): ya medidos en §4; el barrido los trata y una operación
   sin modelo Pydantic rompe la prueba con mensaje explícito en lugar de silenciarse.
2. **Que un modelo de respuesta herede o comparta configuración con uno de petición**: verificado
   en §2.1 (ningún modelo de petición hereda de otro; los de respuesta son clases distintas). La
   aserción de bandera audita solo los 34 servidos como cuerpo.
3. **`rules_config` deja de tolerar claves extra en borradores guardados en `sessionStorage`**
   de asistentes antiguos: el cliente los construye solo con claves declaradas (§9) y el
   `wizardDraft` se normaliza al cargar; si un borrador heredado trajera una clave ajena, el
   422 señala la clave (en `loc` o, en un bloque anidado de `rules_config`, en el mensaje) y el operador la retira (riesgo aceptable y buscado, RF-003).
4. **Duplicar inventario en el test y olvidarlo al añadir un endpoint**: la biyección falla en
   ambos sentidos (endpoint nuevo sin inventario y modelo inventado sin endpoint), así que la
   desviación se detecta en la siguiente tarea, no en producción.
5. **El cliente oficial enviara una clave extra no detectada**: los constructores devuelven
   claves literales y `node --test` lo comprueba; además `typecheck` y `build` cubren los `.vue`.

## 15. Verificación de la constitución (obligatoria)

Contra `docs/constitution.md` (v1.4.0), §2 (principios) y §4 (criterios):

| Criterio | Estado | Evidencia |
| --- | --- | --- |
| §2.1 Claridad y reversibilidad | ✔ | Sin migración ni dato: revertir el PR revierte el comportamiento. |
| §2.2 Verdad ejecutable | ✔ | El inventario se deriva de la app en ejecución (§4), no de un documento. |
| §2.3 Un solo camino | ✔ | Una bandera por modelo (D-1), una capa de rechazo (modelo Pydantic, D-2). |
| §2.4 Separación de responsabilidades | ✔ | Sin lógica de negocio nueva; solo validación de forma en la capa HTTP. |
| §2.5 Contratos explícitos | ✔ | El 422 saneado y su precedencia quedan fijados por pruebas (RF-009/RF-010). |
| §2.6 Riesgos visibles | ✔ | §14 y RNF-011 (multipart excluido, declarado). |
| §2.7 Mínimo movimiento | ✔ | 34 modelos + 4 constructores; sin refactor adyacente. |
| §2.8 Sin atajos | ✔ | Sin flags de compatibilidad ni ventana de gracia (D-6). |
| §2.9 Decisiones registradas | ✔ | §6 con alternativas descartadas; `MEMORY.md` al cerrar. |
| §4.1 Suite completa verde | ✔ | `docker compose exec -T api pytest -q` y `cd frontend && pnpm test` (T10). |
| §4.2 Verificaciones locales | ✔ | §12 comandos + `pnpm run typecheck` + `pnpm run build` (T10). |
| §4.3 E2E cuando aplica | ✔ | E2E de operación y cierre en exclusividad («Copa E2E») en T10: la pantalla de operación cambia. |
| §4.4 Sin datos sensibles | ✔ | El saneado del 422 conserva la ausencia de `input`/`ctx` (RF-010). |
| §4.5 RNF-006 evidenciado | ✔ | T10 con los comandos exactos de §12 y su salida resumida. |
