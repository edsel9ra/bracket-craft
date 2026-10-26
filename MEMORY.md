# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Specs 015, 016, 017 y 018 cerradas e `implementadas`** (2026-10-25), con reviewer `APROBADO`; **tanda de operación de partidos cerrada y en `main`** (squash `48b6b98`, PR #12) con los cinco jobs de CI en verde, E2E incluido.
- Esquema en **027**; `engine_version` sigue en **2026.1**; constitución **1.4.0** y `main` con cinco *required checks*. Última cerrada antes de la tanda: **014** (escudos).
- **Pendiente de despliegue: migrar 026 y 027 antes de la imagen** (el código escribe `assist_player_id` y el motivo del W.O.); ninguna tiene rollback. La **027** (016) relaja `chk_administrative_resolution_reason`; la obligatoriedad del motivo es de la API.

## Spec 018 — sanción única por doble amarilla (8/8 tareas, termina T8)
- **Una jugada = una sanción:** se absorben **todos** los umbrales que crucen las amarillas del acta que compone la expulsión (la primera o la última, y dos umbrales); no se absorbe nada de otra jugada ni de un acta anterior. La roja **directa** + umbral conserva **dos** (fuera de alcance).
- **Duración:** la de la sanción **por expulsión** (`direct_red_suspension_matches` de la versión publicada), aplicada **una vez**. Ninguna amarilla se descuenta y el contador no se reinicia con la roja.
- **Etiqueta y origen:** la sanción se deriva del **tipo de roja registrado también en el cierre que la registra** (el `RETURNING` devuelve `metadata`); **solo los eventos del acta que se cierra** originan sanciones (el historial solo cuenta y empareja) y la unicidad es **por evento de roja con cualquier motivo**, con una lectura acotada que no se ejecuta sin rojas. El recuento auditado es `len(created)` (`RETURNING id`).
- **Sin migración** (esquema **027**), **sin superficie nueva**, y excepción acotada a §3.2 declarada y aprobada (regla fija en el motor).
- **Evidencia (T8, 2026-10-25):** sin base **1919 passed / 432 skipped**; con base, conjunto de siete archivos **348 passed** (195.0 s) —la suite completa con base es la de T5: **2350 passed**, 8m30s—; frontend **628 (627 pass / 1 skipped preexistente)**; `typecheck`/`build` **0** (build 34.9 s, `web` reiniciado); E2E **VERDE (0)**, `operation-flow` 31/31 hitos. Sin tocar `infra/postgres/` ni `frontend/`.
- **Validación 2026-10-25: @reviewer APROBADO** (15/15 RF y 17/17 criterios; diferencial viejo-vs-nuevo sobre 6 144 casos sin sanciones nuevas fuera de RNF-004). Aplicados los tres puntos opcionales útiles: prueba de aislamiento de la lectura de rojas registradas (13 casos con base), cita del plan corregida y evidencia de sensibilidad de T1 registrada; quedan sin caso propio los casos límite 22 y 24.

## Spec 017 — cierre de actas y segmentos (10/10 tareas)
- **Orden único de validación de 14 pasos**: gana el defecto del paso anterior y un fallo no escribe nada; los **422 estructurales** prevalecen y no llevan `code`.
- **8 → 9** (el error del asistente se retiene hasta terminar el paso 8), **422 → 409** en las cuatro incoherencias numéricas del marcador y `DOUBLE_YELLOW_INCONSISTENT` como único `code` nuevo.
- **Resultado calculado antes de escribir** (paso 13) con los eventos de la petición; **`next_segment`** = `{segment_number, minute_start, derived}` y el cliente ya no calcula el número ni pisa el minuto editado. El **walkover** de esta spec se delegó íntegro a la 016.

## Spec 016 — walkover (10/10 tareas)
- **Rama propia tras el paso 5** de la 017: omite los pasos 6–12 y no carga plantilla ni bloquea jugadores; autorización, **la misma conjunción** del cierre.
- **Motivo de catálogo** obligatorio en `resolution_reason`; **marcador derivado** de `walkover_score` (default 3-0, override por fase) publicado en `limits.walkover_score`; los tres **409 con `code`** y `winner <= loser` en **422** al guardar o publicar.
- **Efecto:** tabla (los goles del W.O. **cuentan**), avance de llave, sin eventos ni sanciones, mismo outbox de tres eventos. La prueba de paridad del catálogo se **omite** en el contenedor `web`.
- **Evidencia** (en los `tasks.md`): backend **1779/376** y **2155**; **1899/419** y **63**; frontend **610** y **627 + 1 skip**; `typecheck`/`build` 0; **E2E VERDE (0)**.

## Defectos registrados
- **Doble sanción (resuelto en la 018):** amarillas acumuladas + roja por doble amarilla sumaban **2 partidos** por la misma jugada; ahora es **uno** con la duración de expulsión.
- **Etiqueta de sanción (resuelto en la 018):** el `INSERT` de eventos ya devuelve `metadata`, así que una roja recién registrada se etiqueta bien en su primer cierre (antes `direct_red_card`).
- **Minuto de interrupción** (sin dueño): se pisa en el refresco del socket (la 017 arregló el del segmento). **`minuteDirty`** viaja en el cuerpo del `POST /segments` (hoy ignorado; rompería con `extra="forbid"`).

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
