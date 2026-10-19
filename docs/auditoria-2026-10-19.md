# Auditoría técnica integral — Bracket Craft (2026-10-19)

**Alcance:** estado real del working tree, solo lectura. **Método:** tres pasadas en paralelo (backend/datos/reglas · API/seguridad/pruebas · frontend/infra) contrastadas contra `docs/constitution.md`, `README.md`, `AGENTS.md`, código, migraciones 001-014, CI y compose.

## 1. Resumen ejecutivo

- **Arquitectura madura y por encima del estándar en aislamiento**: RLS `FORCE` verificado ruta por ruta, FKs compuestas anti cross-tenant, rol de BD sin `BYPASSRLS`, migraciones append-only con checksum, acceso HTTP 100% centralizado en `useApi.ts`.
- **Sin hallazgos críticos explotables vía API**, pero **4 hallazgos ALTOS**: fuga potencial de PII cross-tenant (`players` sin RLS), compose de producción que no anula puertos/volúmenes de desarrollo, inmutabilidad de resultados cerrados sin garantía en BD, y deriva documental de versiones.
- **Tema transversal 1 — brecha configuración/comportamiento:** reglas y mecanismos declarados que no están implementados (sustituciones/transferencias, scoping por torneo, selectores entre fases, estados `live`/`suspended`, eventos en vivo). Generan falsa confianza.
- **Tema transversal 2 — deriva documental:** constitución (working tree: 3.14/12.12.2; commiteada: Node 22/11.8.0), AGENTS.md (3.12/12.11.2) y `ci.yml` (3.12/Node 24/12.11.2) se contradicen, en violación de la propia §3.5.
- **Pruebas:** ≈87 tests backend + 15 frontend; lógica pura bien cubierta, pero integración crítica (publicación, cierre contra BD, aislamiento cross-tenant) sin cubrir, y los únicos tests con RLS real se saltan siempre en CI.
- **`specs/` está vacío**: no existen artefactos SDD contra los que validar requisitos.

## 2. Inventario de funcionalidades existentes

**Backend (FastAPI + SQLAlchemy async)** — 6 routers (`main.py:432-437`), 63 rutas HTTP:

| Grupo | Rutas | Contenido |
|---|---|---|
| `/auth/*` | 5 | registro, login, Google OAuth, logout, CSRF bootstrap |
| organizaciones/membresías | 9 | lista, contexto, invitaciones (CRUD/reenviar), miembros (rol/estado), acceso |
| invitaciones públicas | 2 | preview y aceptación por token |
| torneos workspace | 20 | versiones (clonado profundo), fases, equipos, plantillas CSV/ZIP + fotos + consentimiento, calendario (RR/grupos/eliminación/Swiss), publicación |
| torneos públicos | 4 | listado, detalle, standings, partidos (planilla y alineación publicada) |
| partidos | 9 | cierre de acta, operación, segmentos/interrupción, planilla y publicación de formación, oficiales |
| plataforma `/platform` | 10 | usuarios, organizaciones, miembros, auditoría, reproceso outbox |
| salud + Socket.IO | 3+ | healthchecks y relay ASGI |

**Servicios internos sin router:** `rules_engine` (JSON Schema, outcomes, suspensiones), `standings` (+head-to-head estricto), `advancement` (winner/loser, bracket reset), `scheduling` (seed determinista). **Core:** RLS context, tenancy, JWT revocable, CSRF, rate limit Redis, permisos, storage S3, config con rechazo de defaults. **Worker outbox** con claim/reintentos y relay a Socket.IO.

**Datos:** ~35 tablas — identidad/sesiones, orgs/membresías/roles, torneos/versiones/fases/edges/grupos/slots, equipos/plantillas/jugadores (documento cifrado), partidos/segmentos/interrupciones/planillas/eventos/suspensiones, standings, advancement_links, invitaciones, outbox, auditorías (org y plataforma), platform_admins. RLS `FORCE` + FKs compuestas + vistas públicas `security_barrier`. 14 migraciones con checksum SHA-256 y advisory lock.

**Frontend (Nuxt 4, `frontend/app/`):** 10 páginas (portada, login, torneo público, workspace ×4, admin, invitación, forbidden); componentes WorkspaceShell, RulesEditor, LanguageSwitcher, MatchPitch, PublicBracket, PublicLineupModal; stores auth/tournaments; composables `useApi`/`useRealtime`/`useI18n` (608 claves es/en con paridad verificada); middlewares auth/platform; realtime con polling de respaldo a 30 s.

**Infraestructura:** compose dev con 7 servicios (db, db-migrate, api, worker, redis, storage/SeaweedFS, web); overlay de producción con `:?` en secretos y `AUTH_COOKIE_SECURE`; CI con 4 jobs (backend, frontend, infrastructure, security).

## 3. Fortalezas principales

1. RLS sistemático y fail-closed, verificado endpoint por endpoint (los aparentes huecos son delegaciones correctas).
2. FKs compuestas `(id, organization_id)` en toda la cadena: aislamiento incluso con bug de aplicación.
3. Rol BD `NOSUPERUSER…NOBYPASSRLS`, validado al arranque; funciones SECURITY DEFINER con `search_path` fijo.
4. Inmutabilidad de la **estructura** publicada a nivel BD (triggers) + 409 en app para todo lo publicado.
5. Privacidad: `national_id` cifrado write-only (fuera del `GRANT SELECT`) + HMAC para dedupe; `photo_url` solo con consentimiento; vistas públicas sin documentos ni fechas de nacimiento.
6. Sesiones revocables (`jti` + `user_sessions`) con revocación masiva auditada (migración 004).
7. Hardening perimetral: CSRF doble submit con allowlist de origen, rate limit atómico, límite de cuerpo, CORS sin `*`, rechazo de secretos de desarrollo fuera de dev.
8. Cierre de acta con locks ordenados (anti-deadlock), idempotencia por `client_event_id` y outbox en la misma transacción.
9. Outbox `SKIP LOCKED` con recuperación de eventos estancados, reintentos y requeue manual.
10. Standings deterministas: advisory lock por fase, desempate reproducible (SHA-256), h2h conservador.
11. Frontend robusto: anti-carreras con generaciones, guards revalidados contra API, `safeInternalRedirect` anti open-redirect, realtime con reconexión y limpieza, accesibilidad notable (skip-link, `<dialog>` nativo, gestión de foco, `role="alert"`).
12. Migraciones disciplinadas; el gotcha histórico init/02 vs 012 está resuelto.

## 4. Matriz de riesgos consolidada

### 4.1 ALTOS

| ID | Hallazgo | Evidencia | Recomendación |
|---|---|---|---|
| R01 | Catálogo global `players` sin RLS: el alta reutiliza jugadores por HMAC sin filtro de organización → una org puede obtener nombre/apellidos/`birth_date` de jugadores de otra org registrando su documento | `005:3-24`, `tournaments/router.py:1123-1141`, sin `ENABLE RLS` en `players` | RLS en `players`, o dedupe con `organization_id` en la clave, o tabla puente sin PII cross-tenant |
| R02 | El overlay de producción **no anula** puertos ni volúmenes (Compose fusiona secuencias añadiendo): db/redis/storage quedarían expuestos en el host y `./frontend:/app` sombrearía la build (el contenedor ejecutaría código del host) | `docker-compose.production.yml:3,40-41,52,61-62`; bases `docker-compose.yml:10-11,81-85,114-115,122-124,144-149` | `!reset []`/`!override` (Compose ≥2.24) o overlay autocontenido; validar el merge en CI |
| R03 | Inmutabilidad de **resultados cerrados** solo en código de aplicación: los triggers protegen la estructura pero permiten actualizar marcadores/estado de partidos terminados | `init/03:217-286`; `matches/service.py:47`; checks solo de forma (`init/01:400-415`) | Trigger `BEFORE UPDATE` que bloquee marcadores/penales/winner/status si `OLD.result_confirmed` (migración 015) |
| R04 | Deriva documental de versiones: constitución sin commit (3.14/12.12.2), constitución commiteada (3.12/Node 22/11.8.0), AGENTS.md y ci.yml (3.12/Node 24/12.11.2) | `docs/constitution.md:63` + `git diff`; `ci.yml:18,37,40,73,80` | Enmienda de parche, commit y alineación de las tres fuentes (§3.5) |

### 4.2 MEDIOS

| ID | Hallazgo | Evidencia | Recomendación |
|---|---|---|---|
| R05 | `birth_date` en claro, sin `PLAYER_DATA_KEY` (incumple §3.4) | `tournaments/router.py:1143-1168`; `005:3-24` | Cifrar; conservar `public_age` derivada |
| R06 | Scoping por torneo muerto: `require_permission` no usa `tournament_id`; `tournament_user_roles` sin consumo | `core/permissions.py:15-51`; `011:7` | Implementarlo o retirarlo y documentar el modelo real |
| R07 | Tests con BD y RLS real siempre saltados en CI | `test_invitations.py:48`; `ci.yml:25` | Job con Postgres de servicio + `RUN_DATABASE_TESTS=1` |
| R08 | CI no valida el merge de producción | `ci.yml:63-64`; §3.5 | Paso `-f docker-compose.yml -f docker-compose.production.yml config -q` |
| R09 | Reglas declaradas no aplicadas: sustituciones, transferencias y `roster_lock_matchday` sin consumo; `match_segment_team_state` nunca se escribe | `rules_engine/defaults.py:12,20-24`; `init/01:549-562` | Implementar en el cierre o retirar del schema |
| R10 | Constantes hardcodeadas: 90/120 min, códigos `GF1/GF2`, 4 formaciones | `matches/service.py:16-17,294-298,347`; `matches/schemas.py:18`; `advancement/service.py:53,64` | Derivar del `rules_config`; doble eliminación por configuración |
| R11 | Ciclo de vida incompleto: `live`/`suspended` inalcanzables o sin salida; sin eventos de partido por API (solo al cierre); torneo `published→live→finished` sin productor | greps exhaustivos; `matches/service.py:47`; `seed_demo.py:1281` | Implementar transiciones o recortar CHECKs; definir alcance "tiempo real" |
| R12 | Avance entre fases sin motor: `selector_type`/`source_type` sin consumo; clasificación entre fases manual | `init/01:180-224`; `tournaments/router.py:437-469`; `advancement/service.py:11-49` | Implementar llenado `stage_rank` o documentar alcance |
| R13 | Redis sin `MAXLEN` y relay arranca en `0-0`: memoria ilimitada y re-emisión histórica en cada reinicio | `workers/outbox.py:36`; `main.py:212` | `XADD MAXLEN` + arranque en id reciente |
| R14 | Entrega at-least-once sin `event_id` en payloads (el frontend no puede deduplicar) | `workers/outbox.py:36-57`; `main.py:167-196` | Incluir el id del outbox en stream y emit |
| R15 | Firma de fotos jugador a jugador con cliente boto3 nuevo por fila en el endpoint público | `tournaments/router.py:3057-3065`; `core/storage.py:33-49,115-128` | Cliente cacheado + firma en lote |
| R16 | Swiss con backtracking exponencial y sin tope de equipos en el request path | `scheduling.py:269-290`; `router.py:2296-2306` | Tope de equipos / fallback greedy acotado |
| R17 | Sin `statement_timeout`, `idle_in_transaction_session_timeout` ni pool dimensionado | `core/database.py:12` | Timeouts en conninfo + pool explícito |
| R18 | Botón "Reintentar" del realtime es un no-op (el guard devuelve temprano) | `useRealtime.ts:61-67`; `tournaments/[id].vue:206`; `workspace/index.vue:169`; `matches/[id].vue:887` | Forzar `disconnect()`→`connect()` o reintento de handshake |
| R19 | Contenedor `web` corre como root (el backend sí es no-root) | `frontend/Dockerfile:12-24` vs `backend/Dockerfile:13-16` | Usuario no-root en stage runtime |
| R20 | Drift `.env.example` vs `environment` del servicio api: 7 variables sin efecto en Docker; 2 de compose sin documentar | `.env.example:8,20-23,34-35` vs `docker-compose.yml:38-73,51-52` | Sincronizar o documentar |

### 4.3 BAJOS

| ID | Hallazgo | Evidencia |
|---|---|---|
| R21 | CSRF no aplica a POST públicos sin credenciales (p. ej. aceptar invitación sin sesión) | `main.py:362-372` |
| R22 | GET con efecto secundario: listar invitaciones marca vencidas | `invitations/router.py:172-181` |
| R23 | GET de operación toma `FOR UPDATE` del partido (~8 consultas en la transacción) | `matches/router.py:73,187` |
| R24 | Migración 013 reescribe funciones por regex sobre `pg_get_functiondef` (frágil y silencioso) | `013:5-31` |
| R25 | Auditoría organizacional incompleta: oficiales, planilla y publicación de formación sin log | `matches/router.py:773-927,469-656,659-734` |
| R26 | Sin anti-duplicado de emparejamientos manuales (distorsiona el h2h estricto) | `tournaments/router.py:2649-2756`; `head_to_head.py:72-76` |
| R27 | `matches_events.minute` sin tope en BD | `init/01:575` vs `matches/schemas.py:32-33` |
| R28 | pytest/pytest-asyncio en requirements de producción | `backend/requirements.txt:15-16` |
| R29 | Hardcodeos i18n en members/invitations (roles/estados en inglés, `role_code` crudo) | `members.vue:42-46,203,212,235`; `invitations/[token].vue:105` |
| R30 | Puerto de api publicado en `0.0.0.0` en dev (resto en loopback) | `docker-compose.yml:82` |
| R31 | Sin healthchecks en api/web/worker; `depends_on` sin condición | `docker-compose.yml:35-149,142-143` |
| R32 | Menores: `access_token` en cuerpo de `accept_invitation`; rol mostrado por `MIN(rd.code)`; login devuelve solo la 1.ª org; `app.version` fija; `public_age`/`v_public_tournament_players` sin consumir; relay emite todo a `organization:*` sin filtro de rol (riesgo futuro); naming "MinIO" residual; buffer continúa con cuerpo parcial en `disconnect`; línea HTML comentada | varios (ver informe fuente) |

## 5. Cobertura de pruebas por flujo crítico

- **Cubierto (unitario):** CSRF/rate limit/límite de cuerpo · secretos fuera de dev · standings y head-to-head · scheduling (RR, llaves, Swiss, doble elim.) · importación de rosters (incl. firma/traversal).
- **Parcial:** login/sesión (sin BD real) · invitaciones (BD real, pero saltadas en CI — R07) · actas (lógica del rules engine 18 tests, pero el `POST /matches/{id}/close` contra BD no tiene test) · proyecciones públicas (sin aserción a nivel de vista) · outbox (sin test de `process_once`) · plataforma (sin escrituras con BD).
- **Sin cubrir:** aislamiento cross-tenant vía API (org A vs org B) · publicación de versiones (readiness, inmutabilidad 409) · gating de publicación de alineación · consentimiento de foto (alta y retirada) · handshake/revocación de Socket.IO · componentes Vue y middlewares (solo 4 archivos de utils, ~177 líneas).

## 6. Plan de acción priorizado

- **P0 (ahora):** R01 aislar `players` · R02 corregir overlay de producción y validar su merge en CI (cierra R08) · R03 migración 015 con trigger de inmutabilidad de resultados · R04 enmendar y commitear constitución alineando versiones.
- **P1 (antes de operar torneos reales):** R05 cifrar `birth_date` · R06 y R12 resolver o documentar scoping por torneo y avance entre fases · R09/R10 alinear reglas declaradas vs aplicadas · R07 tests de BD en CI · R13/R14 outbox (MAXLEN + event_id) · R15/R16/R17 rendimiento (firmas en lote, tope Swiss, timeouts/pool).
- **P2 (higiene):** R11 definir ciclo de vida o recortar CHECKs · R18-R32 (no-root en web, botón reintentar, env drift, auditoría de lineup/oficiales, únicos de emparejamiento, semántica GET, healthchecks, i18n, menores).

## 7. Límites de la auditoría (no verificado)

No ejecutados por limitaciones del entorno (sin venv/toolchain/Docker): `pytest`, tests frontend (`node --test` con Node 22 de la distro falla), `docker compose config` (ni dev ni merge), `pip-audit`/`pnpm audit`/Trivy, y ninguna prueba contra servicios (RLS en runtime, volumen limpio, Socket.IO, URLs presignadas). `compileall` backend: OK. Conteo de tests por análisis estático. La constitución del working tree está sin commitear (afecta R04). Contraste WCAG no evaluado numéricamente. `specs/` vacío: no hay RF contra los que validar.
