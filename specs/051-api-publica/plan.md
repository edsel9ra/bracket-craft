# Plan — Spec 051: API pública documentada para terceros (F15)

Estado: aprobado el 2026-11-27 («Apruebo el plan y las tareas»). Spec aprobada el 2026-11-27 («Apruebo la spec 051»).

## 1. Resumen

Sin migraciones, sin campos públicos nuevos y sin cambios en el frontend. Todo vive en el backend y en la documentación:

- Un catálogo puro con las 9 lecturas del contrato `v1` (RF-001).
- `GET /api/v1/public/openapi.json`: documento OpenAPI generado por FastAPI a partir de las rutas del catálogo, y nada más (RF-002).
- Una copia de referencia del contrato en el repositorio y una comprobación de compatibilidad (RF-005–RF-007).
- Un middleware CORS propio solo para el catálogo y su documento: cualquier origen, solo `GET`, sin credenciales (RF-009, RF-009b).
- Guía ES/EN con ejemplos validados y una configuración de ejemplo del proxy con límite por IP (RF-003, RF-011).

## 2. Decisiones

| # | Decisión | Alternativa descartada y motivo |
|---|---|---|
| D1 | El documento público se genera con `fastapi.openapi.utils.get_openapi()` sobre las rutas del catálogo, en cada arranque, y se guarda en memoria. | Escribirlo a mano: se desincroniza del código. Filtrar el `/openapi.json` completo: arrastraría esquemas de componentes privados. |
| D2 | Ruta `GET /api/v1/public/openapi.json`, sin sesión. | `/api/v1/tournaments/public/openapi.json`: choca con `/public/{tournament_id}`. |
| D3 | El catálogo se identifica por plantilla de ruta (`/api/v1/tournaments/public/{tournament_id}/standings`…) y método `GET`. Para CORS, cada parámetro de ruta se compara con una expresión de UUID. | Un prefijo: abriría también las tres imágenes `…/share-image` y `/public/share-image` (DA-1). |
| D4 | La copia de referencia es `docs/api-publica/openapi-v1.json`. Un script `backend/scripts/public_api_reference.py` la compara (`--check`) o la actualiza (`--update`). `--update` se niega si hay un cambio incompatible. | Solo exigir igualdad: un cambio incompatible pasaría regenerando la referencia sin aviso. |
| D5 | Middleware ASGI `PublicReadCorsMiddleware`, exterior a `CORSMiddleware`. En el catálogo, para cualquier origen no configurado (o sin `Origin`), responde él mismo a la comprobación previa (solo `GET` y cabeceras simples, 204) y, en `GET`, fija `Access-Control-Allow-Origin: *`, elimina `Access-Control-Allow-Credentials` y conserva `Vary: Origin`. Los orígenes de `CORS_ALLOWED_ORIGINS` pasan intactos a `CORSMiddleware`, porque el sitio llama con `credentials: 'include'` y un `*` lo rompería; `Vary: Origin` evita que una caché sirva una respuesta a otro origen. Fuera del catálogo no toca nada. | Añadir `*` a `CORS_ALLOWED_ORIGINS`: `config.py` lo rechaza con credenciales y abriría el Workspace. |
| D6 | Validación OpenAPI 3.1 con `openapi-spec-validator`, versión exacta con más de 30 días publicada, solo en `requirements-dev.txt`. | Un validador propio: no garantiza RNF-002. |
| D7 | La configuración de ejemplo del proxy es Nginx (`limit_req_zone` por `$binary_remote_addr`, 429 y `Retry-After`) con una expresión de `location` que cubre solo el catálogo. El SSR usa `NUXT_API_INTERNAL_BASE` y no pasa por el proxy (RF-011b). | Límite en la aplicación: descartado por el usuario (DA-4). |

## 3. Backend

Módulo nuevo `backend/app/modules/public_api/`:

- `catalog.py` (puro): `PUBLIC_API_V1 = (("GET", "/api/v1/tournaments/public"), …)` con las 9 rutas; `OPENAPI_PATH = "/api/v1/public/openapi.json"`; `is_public_read(method, path) -> bool`, con las plantillas compiladas a expresiones con UUID por parámetro.
- `openapi.py`: `build_public_openapi(app) -> dict` toma de `app.routes` las que están en el catálogo y llama a `get_openapi(title="Bracket Craft — API pública", version="v1", openapi_version="3.1.0", routes=…)`. Añade `info.description` con el enlace a la guía y `servers: [{"url": "/"}]`. Falla al arrancar si falta una ruta del catálogo.
- `compat.py` (puro): `incompatibilities(reference, current) -> list[str]`, sobre el documento con los `$ref` resueltos:
  - **Incompatible:** quitar una ruta u operación; quitar un parámetro o volverlo obligatorio; añadir un parámetro obligatorio; cambiar el tipo o el formato de un parámetro; quitar un código de respuesta; quitar una propiedad de una respuesta, quitarla de `required`, cambiar su tipo o formato, volverla anulable o añadir valores a un `enum` de respuesta.
  - **Compatible:** añadir una ruta del catálogo, una propiedad nueva no obligatoria o un valor nuevo en un parámetro opcional.
- `router.py`: `GET /public/openapi.json` devuelve el documento de D1, sin dependencia de sesión ni de base de datos. Se registra en `main.py` con `prefix="/api/v1"`.
- `cors.py`: `PublicReadCorsMiddleware` (D5). En `main.py` envuelve a la API por fuera de `CORSMiddleware` y por dentro de `SecurityHeadersMiddleware`.

Las 9 lecturas no cambian: mismas consultas, `set_rls_context()`, RLS y «no encontrado».

## 4. Interfaz

- `GET /api/v1/public/openapi.json` → 200 `application/json`, OpenAPI 3.1 con 9 rutas.
- Comprobación previa (`OPTIONS`) de una ruta del catálogo con `Origin` cualquiera y `Access-Control-Request-Method: GET` → 204, `Access-Control-Allow-Origin: *`, `Access-Control-Allow-Methods: GET`, sin `Access-Control-Allow-Credentials`. Con otro método → 400, como hoy.
- `GET` de una ruta del catálogo con `Origin` → la misma respuesta de hoy más `Access-Control-Allow-Origin: *`.
- Cualquier otra ruta, incluidas las imágenes `…/share-image`, conserva el CORS actual.

## 5. Documentación

- `docs/api-publica.md` (ES) y `docs/api-publica.en.md` (EN): URL base, autenticación (ninguna), CORS, idioma de los textos, paginación (`limit` y `offset`), errores (404 indistinguible, 422 de parámetros, 429 del proxy), fotos y escudos firmados que caducan, política de versiones y un historial. Un ejemplo de respuesta por lectura en un bloque `json` precedido de `<!-- ejemplo: <operación> -->`.
- `docs/despliegue-proxy-tiempo-real.md`: sección «Límite de la API pública» con el bloque Nginx de D7.
- README, AGENTS, `docs/informe-funciones-adicionales.md` (F15 implementada) y MEMORY.

## 6. Tests

- `tests/test_public_api_catalog.py` (puro): el catálogo tiene exactamente las 9 rutas; cada una existe en `api.routes` como `GET` sin dependencia de sesión; `is_public_read` acepta las 9 con UUID y rechaza `…/share-image`, `/public/share-image`, otros métodos y rutas del Workspace.
- `tests/test_public_api_openapi.py`: el documento tiene solo las 9 rutas; ninguna ruta ni componente del Workspace; las propiedades de cada esquema de respuesta están en `EXPECTED_FIELDS` de `test_public_field_allowlist.py` (RF-004); `openapi-spec-validator` lo valida (RNF-002); `GET /api/v1/public/openapi.json` responde sin cookies.
- `tests/test_public_api_compat.py` (puro): un caso por regla de `compat.py`, compatible e incompatible; el documento actual es compatible con `docs/api-publica/openapi-v1.json` e igual a ella.
- `tests/test_public_api_cors.py`: comprobación previa y `GET` desde un origen no configurado en las 9 rutas y en el documento; sin credenciales; `POST` rechazado; las imágenes y una ruta del Workspace no reciben `*`; el origen configurado del sitio sigue recibiendo su CORS con credenciales, dentro y fuera del catálogo; un torneo no visible da el mismo 404 con o sin `Origin` (BD).
- `tests/test_public_api_docs.py` (puro): cada guía tiene un ejemplo por operación y cada ejemplo valida contra su modelo de respuesta; las dos guías tienen las mismas operaciones; la expresión de `location` del bloque Nginx acepta las 9 rutas y rechaza las imágenes y el Workspace.
- Tests del script en `tests/test_public_api_compat.py`: `--check` falla ante diferencias y `--update` se niega ante un cambio incompatible.

## 7. Cobertura

| Parte | RF |
|---|---|
| `catalog.py` | RF-001, RF-005 |
| `openapi.py` y router | RF-002, RF-004, RNF-002 |
| `compat.py`, referencia y script | RF-006, RF-007 |
| `cors.py` | RF-008, RF-009, RF-009b |
| Lecturas sin cambios | RF-010, RF-012, RNF-001 |
| Guías y ejemplo del proxy | RF-003, RF-011, RF-011b, RNF-003 |
| Dependencia de desarrollo | RNF-004 |

## 8. Verificación de constitución

| Principio o criterio | Aplica | Cómo se cumple |
|---|---|---|
| 1. Aislamiento multi-tenant por RLS | Sí | Las lecturas no cambian: `set_rls_context()` y RLS como hoy; el documento no lee la base de datos. |
| 2–4. Reglas, motor, fases e inmutabilidad | No | Solo lectura y documentación. |
| 5. Lo público es una proyección mínima | Sí | Sin campos nuevos; el test de RF-004 limita el documento a la lista cerrada de la 020. |
| Migraciones append-only | No | Sin migración. |
| §3.4 Seguridad: CORS y credenciales | Sí | `*` solo en `GET` del catálogo y sin credenciales; el resto conserva `CORS_ALLOWED_ORIGINS` con credenciales; test con origen no configurado. |
| §3.4 Dependencias: `pip-audit`, auditoría pnpm y Trivy | Sí | `openapi-spec-validator` con versión exacta, solo en desarrollo; `pip-audit` y Trivy en CI. Sin cambios en el frontend. |
| Rutas públicas sin sesión | Sí | El documento y las lecturas no dependen de sesión ni de cookies. |
| Todo cambio con pruebas | Sí | §6, en rojo antes de implementar. |
| Frontend vía `useApi.ts` | No | Sin cambios en el frontend. |
| ES/EN | Sí | Guía en los dos idiomas con las mismas operaciones. |
| Documentación coherente (README, AGENTS, manual) | Sí | T5 actualiza README, AGENTS, informe y MEMORY; el manual de usuario no cambia porque no hay pantallas nuevas. |
