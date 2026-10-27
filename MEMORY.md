# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Estado
- **Spec 019 cerrada e `implementada` (2026-10-26)**, reviewer `APROBADO`; **pendiente de PR/merge a `main`** (commit local en la rama `019-endurecimiento-de-esquemas`, sin push). Las 015–018 están en `main` (squash `48b6b98`, PR #12; 018: `3bd1655`, PR #14), con los cinco jobs de CI en verde, E2E incluido.
- Esquema en **027** (la 019 no trae migración); `engine_version` sigue en **2026.1**; constitución **1.4.0** y `main` con cinco *required checks*.
- **Pendiente de despliegue: migrar 026 y 027 antes de la imagen** (el código escribe `assist_player_id` y el motivo del W.O.); ninguna tiene rollback. La 027 relaja `chk_administrative_resolution_reason`; la obligatoriedad del motivo es de la API.

## Spec 019 — endurecimiento de esquemas (implementada)
- **Regla general `extra="forbid"`** en las **33 operaciones JSON / 34 modelos** (29 de nivel superior + 5 anidados): clave no declarada → **422** estructural (`detail` en lista, sin `code`, sin eco del valor). Corte **limpio**, sin ventana de gracia ni excepciones por ruta: el cliente que enviaba basura falla pronto en vez de ocultar el error hasta otro cambio.
- **Fuera:** las **3 multipart** (`rosters/bulk`, foto, escudo), consulta, cabeceras y rutas sin cuerpo. **Se conservan abiertos** los 3 mapas abiertos de `rules_config` (desempate, overrides por fase, bloque deprecado) y `transfers` (aceptado y promovido); el primer nivel de `rules_config` sí se cierra.
- **Precedencia por capas:** el 422 del cuerpo **gana** al 403 de permiso de ruta y al 404 de recurso ajeno (viven en el handler); middleware (400/413, origen/CSRF) y dependencias (401, 400 de organización, 403 de membresía/plataforma) conservan su código. La clave va en `loc` en los objetos que cierra el modelo; en bloques anidados de `rules_config` el camino va solo en el mensaje.
- **Cliente:** cuatro constructores puros en `frontend/app/utils/requestBodies.ts` (solo campos declarados; el estado de UI no viaja). Sin migración, endpoint ni respuesta tocados.
- **Evidencia (2026-10-26):** backend **2062 passed / 432 skipped** (repo en `/repo`); 019 + compat + catálogo **299 passed**; frontend **644 (643 pass / 1 skip)**. RNF-006 «parcial» solo porque el reviewer no ejecutó base/E2E/typecheck/build por su cuenta (evidencia en `tasks.md`).
- **Lecciones:** un criterio de «barrido» necesita **garantía automatizada por bloque** (la laguna I-3 se cerró); una prueba con la dependencia **sustituida** no prueba el orden real (se añadió el caso con la dependencia real de membresía); `__pycache__` con rutas `/repo` contamina el contenedor `api` (usa `PYTHONDONTWRITEBYTECODE=1`).

## Spec 018 — sanción única por doble amarilla (en main)
- **Una jugada = una sanción:** se absorben **todos** los umbrales de amarillas del acta que componen la doble amarilla; la roja **directa** + umbral conserva **dos**. Duración = la de expulsión (`direct_red_suspension_matches`), una vez; ninguna amarilla se descuenta y el contador no se reinicia.
- **Origen:** solo los eventos del acta que se cierra originan sanciones (el historial solo cuenta y empareja); unicidad **por evento de roja con cualquier motivo**; el tipo de roja se lee de `metadata` también en el cierre que la registra; el recuento auditado es `len(created)`. Sin migración; excepción acotada a §3.2 aprobada.
- **Evidencia:** sin base 1919/432; con base 348; frontend 628; E2E VERDE. Reviewer APROBADO (15/15 RF); sin caso propio los casos límite 22 y 24.

## Specs 015–017 (resumen)
- **017:** orden único de **14 pasos** (gana el defecto del paso anterior; los 422 estructurales prevalecen, sin `code`); 4 incoherencias numéricas **422 → 409**; `DOUBLE_YELLOW_INCONSISTENT`; resultado calculado antes de escribir; `next_segment` aditivo.
- **016:** walkover como rama propia tras el paso 5 (omite 6–12); motivo de catálogo en `resolution_reason` (027); marcador derivado de `walkover_score` y publicado en `limits.walkover_score`; sin eventos ni sanciones.
- **015:** catálogo cerrado de siete eventos y asistencia opcional del gol (026); la 019 generaliza su `extra="forbid"` a toda la API.

## Defectos resueltos
- Doble sanción y etiqueta de sanción (018); minuto de interrupción pisado en cada refresco (`applyInterruptionMinute`; el cuerpo del `POST /segments` se construye campo a campo).

## Lecciones del proceso
- Los «hecho cuando» que citan archivos deben crearlos; toda interacción crítica necesita una prueba que la ejercite; las matrices de precedencia valen lo que valen sus mutaciones.
- La documentación derivó **cuatro veces** hacia afirmaciones falsas (la última: la «ubicación de la clave» y una cita de ruta/RF): corregir un hecho exige revisar **todas** sus copias.
- El **E2E sí cubre el acta** (`operation-flow`, 31 hitos): no lo omitas por una premisa.

## Entorno local
- Backend `python:3.14-slim`; frontend en `web` (Node 24/pnpm 12.12.1); E2E en Playwright. El host no tiene `pytest` ni `node` con TS: usa los contenedores.
- Para la suite backend monta el repo en **`/repo`**; sin eso fallan 23 pruebas que leen ficheros de la raíz (falsos negativos de entorno).
- **E2E en exclusiva**: el arnés no limpia sus torneos «Copa E2E» (a 50 corridas oculta el demo por paginación), deriva `short_code` de 4 dígitos del reloj (colisiona entre corridas) y comparte `.nuxt` con el dev server (un `typecheck`/`build` concurrente da `view-timeout`). Limpia residuos y reinicia `web` tras `build`.
- `infra/scripts/test_migrate_target.sh` **rota la contraseña** de `bracket_app` del clúster de desarrollo: restáurala después.
- Si el volumen se creó con otra `BRACKET_DB_PASSWORD`, alinea `bracket_app` con `ALTER ROLE`.
