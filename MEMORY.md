# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Specs 015, 016 y 017 cerradas e `implementadas` (2026-10-25)**, aprobadas por el usuario y con reviewer `APROBADO` en las tres. **Tanda de operación de partidos cerrada.**
- **Tanda de operación de partidos completa.** Esquema en **027**; `engine_version` sigue en 2026.1.
- **Migración 027** (spec 016): `chk_administrative_resolution_reason` solo permitía `resolution_reason` en la resolución administrativa, así que el motivo del W.O. (DU-7) no tenía dónde guardarse. La 027 solo **relaja** el CHECK (acepta `NULL` o catálogo en `walkover`); la obligatoriedad es de la API. Orden **027 → código**, sin rollback, aplicada en local.
- Última cerrada antes de la tanda: **014** (escudos). Constitución **1.4.0**; `main` con cinco *required checks*; esquema en **027** (025 → 026 con la 015 → 027 con la 016).

## Spec 017 — cierre de actas y segmentos (10/10 tareas)
- **Orden único de validación de 14 pasos**: entre defectos de dominio gana el del paso anterior y un fallo no escribe nada. Los 422 estructurales prevalecen y no llevan `code`.
- **8 → 9**: el asistente se valida en el paso 9 y su error se **retiene** hasta terminar el paso 8 (una sola pasada del motor, sin duplicar reglas).
- **422 → 409** en las cuatro incoherencias numéricas del marcador (`detail` cadena, **sin `code`**); `DOUBLE_YELLOW_INCONSISTENT` es el único código nuevo (exactamente dos amarillas previas, orden canónico).
- **Resultado calculado antes de escribir** (paso 13), con los eventos de la petición; la idempotencia garantiza la equivalencia.
- **`next_segment`** = `{segment_number, minute_start, derived}`, nulo en partido terminal o versión no publicada; el cliente ya no calcula el número y **no pisa** el minuto editado (`minuteDirty`/`forceMinute`).
- **Walkover**: el usuario decidió (2026-10-25) que su rama pertenece **íntegramente a la 016**; la 017 delega y su criterio 16 queda «no aplicable hasta la 016». *(Histórico: en la 017 un W.O. aún exigía segmento y plantilla; la 016 lo derogó.)*
- **Evidencia final:** backend **1779/376** sin base y **2155** con base; frontend **610**; `typecheck`/`build` 0; E2E **VERDE (0)** (31 hitos); infra y seguridad 0.

## Spec 016 — walkover (10/10 tareas)
- **Rama propia tras el paso 5** de la 017: **omite los pasos 6–12** —no exige segmento activo ni plantilla, no valida tiempos, sustituciones, doble amarilla, marcador contra eventos ni sanciones— y no carga plantilla ni bloquea jugadores. Autorización: **la misma conjunción** del cierre.
- **Motivo de catálogo** (`no_show`/`withdrawal`/`insufficient_players`/`sanction`) obligatorio en `resolution_reason`; **marcador derivado** de `walkover_score` (default 3-0, override por fase) y publicado en `limits.walkover_score` (novena clave).
- **Códigos:** `WALKOVER_STATE_NOT_ALLOWED` → `WALKOVER_CONFIG_INCONSISTENT` → `WALKOVER_SCORE_MISMATCH` (409 con `code`). Guardar/publicar `winner <= loser` es 422 y **no** se valida en `validate_rules_config` (corre al cerrar, clasificar y clonar).
- **Efecto:** tabla (los goles del W.O. **cuentan** para la diferencia), avance de llave, sin eventos, sin sanciones servidas ni creadas, mismo outbox de tres eventos. Un segmento activo queda `completed` en su `minute_start`.
- **Evidencia (2026-10-25, estado final):** backend **1899/419** sin base y **63** con base (`test_migration_027` + `test_match_resolution_db`); frontend **627 + 1 skip**; `typecheck`/`build` 0; **E2E VERDE (0)** re-ejecutado por el reviewer sobre el código final; infra 0.
- **Nota:** la prueba de paridad del catálogo de motivos se **omite** dentro del contenedor `web` (solo monta `frontend`) y compara cuando el repo está alcanzable, como en CI. Se revirtió un montaje `./backend` que se había añadido a `docker-compose.yml` para hacerla pasar.

## Defectos fuera de alcance (registrados, sin dueño)
- **Doble sanción:** amarillas acumuladas + roja por doble amarilla = **2 partidos** por la misma jugada. Merece spec propia con prioridad.
- **Etiqueta de sanción:** el `INSERT` de eventos no devuelve `metadata`, así que una roja por doble amarilla recién registrada se etiqueta `direct_red_card`; reutilizar la fila la etiqueta bien.
- **Minuto de interrupción**: se pisa en el refresco del socket (la 017 arregló el del segmento). **`minuteDirty`** viaja en el cuerpo del `POST /segments` (hoy ignorado; rompería con `extra="forbid"`).

## Lecciones del proceso (operación de partidos)
- T5 de la 015 citó un archivo de pruebas que no existía y se dio por completa: **los «hecho cuando» que citan archivos deben crearlos**.
- T9 de la 015 perdió el botón «Añadir evento» sin que las pruebas de utilidad lo notaran: **toda interacción crítica necesita una prueba que la ejercite** (hoy hay guardián).
- La documentación derivó **tres veces** hacia afirmaciones falsas (spec, plan, tasks): corregir un hecho exige revisar **todas** sus copias.
- El **E2E sí cubre el acta** (`operation-flow`, 31 hitos). No lo omitas por una premisa: una premisa falsa dejó pasar una regresión real.
- El reviewer detectó que «gana el paso anterior» se cumplía solo en el papel; las matrices de precedencia valen lo que valen sus mutaciones.

## Entorno local
- Backend `python:3.14-slim`; frontend en `web` (Node 24/pnpm 12.12.1); E2E en Playwright. El host no tiene `pytest` ni `node` con TS: usa los contenedores.
- Para la suite backend monta el repo en **`/repo`**; sin eso fallan 23 pruebas que leen ficheros de la raíz (falsos negativos de entorno).
- **E2E en exclusiva**: el arnés no limpia sus torneos «Copa E2E» (a 50 corridas oculta el demo por paginación), deriva `short_code` de 4 dígitos del reloj (colisiona entre corridas) y comparte `.nuxt` con el dev server (un `typecheck`/`build` concurrente da `view-timeout`). Limpia residuos y reinicia `web` tras `build`.
- `infra/scripts/test_migrate_target.sh` **rota la contraseña** de `bracket_app` del clúster de desarrollo: restáurala después.
- Si el volumen se creó con otra `BRACKET_DB_PASSWORD`, alinea `bracket_app` con `ALTER ROLE`.
