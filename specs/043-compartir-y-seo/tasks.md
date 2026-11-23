# Tareas — Spec 043: Compartir y SEO (F14)

Estado: aprobado por el usuario el 2026-11-23 («Apruebo el plan, las tareas y la excepción. Empieza con T1»), incluida la excepción §3.3 del sitemap.

## Bloque A — backend (PR de implementación 1)

- [x] **T1. Composición de imágenes y política de compartibles.** RF-003, RF-004, RF-014, RNF-002, RNF-003
- Hecho cuando: `pillow==13.0.0` y la fuente Archivo (OFL) están añadidas; `share_image.py`, `share_policy.py` y `brand-fallback.png` existen; `cd backend && pytest -q tests/test_share_image.py tests/test_share_policy.py` pasa tras confirmarlos en rojo; `pip-audit -r requirements.txt` limpio.
- Evidencia (2026-11-23): ambos archivos fallaron primero en la colección (módulos inexistentes); después 30 passed. `pip-audit -r requirements.txt -r requirements-dev.txt` sin vulnerabilidades; `ruff check .` limpio. Desviación: el plan fijaba `pillow==12.3.0`, que `pip-audit` rechaza por avisos corregidos en la 13.0.0; se fija la 13.0.0. Fuente `app/assets/fonts/Archivo[wdth,wght].ttf` con `OFL.txt`; `brand-fallback.png` se compara píxel a píxel con `brand_card("es")`.
- [x] **T2. Lectura pública de un partido.** RF-006, RF-007, RF-013
- Hecho cuando: `GET /public/{id}/matches/{match_id}` devuelve la misma fila que la lista (incluido el suspendido de 14 claves) y el mismo 404 en los demás casos; `RUN_DATABASE_TESTS=1 pytest -q tests/test_public_share.py -k match_read` y los tests existentes de `public_matches` pasan.
- Evidencia (2026-11-23): `test_public_share.py -k match_read` (3 tests) y el inventario de rutas (41 operaciones) fallaron primero (404/422 y 40 rutas); después pasan, junto con `test_match_live_public.py`, la matriz pública, la lista cerrada de campos, cronología y escudos. La consulta de la lista se extrae a `_public_match_rows` con filtro opcional por partido, de modo que la lectura individual reutiliza exactamente la misma SQL, firmas y recorte del suspendido; `test_crest_public.py` inspecciona ahora esa función. Suite backend completa con `RUN_DATABASE_TESTS=1` en verde; `ruff check .`, `bandit -r app -ll` y `compileall` limpios.
- [ ] **T3. Endpoints de imagen.** RF-003–RF-005, RNF-001, RNF-002, RNF-004
- Hecho cuando: las tres rutas `share-image` responden según el plan §3 (caché, 404 idéntico, 422 de `lang`, respaldo ante fallo, aislamiento); `RUN_DATABASE_TESTS=1 pytest -q tests/test_public_share.py`, suite backend completa, `python -m compileall -q app`, `ruff check .` y `bandit -r app -ll` pasan; PR del bloque A con CI 7/7.

## Bloque B — frontend, E2E y documentación (PR de implementación 2)

- [ ] **T4. Origen público y utilidades de metadatos.** RF-001, RF-002, RF-006–RF-008, RF-012, RF-014
- Hecho cuando: `siteUrl` está en `nuxt.config.ts`, Compose y `.env.example`; `utils/publicSeo.ts` existe; `cd frontend && pnpm test` (con `public-seo.test.ts` primero en rojo) pasa; `docker compose config -q` y `docker compose -f docker-compose.production.yml config -q` (con variables de ejemplo) pasan.
- [ ] **T5. Sitemap y `robots.txt`.** RF-009, RF-010, RF-012, RNF-001
- Hecho cuando: `server/utils/seoDocuments.ts` y las dos rutas Nitro existen; `seo-documents.test.ts` pasa; `pnpm run build` pasa y `curl` local a `/sitemap.xml` y `/robots.txt` devuelve el contenido esperado.
- [ ] **T6. Metadatos en inicio, torneo y ficha; enlace de partido.** RF-001, RF-002, RF-006–RF-008
- Hecho cuando: las tres páginas usan las utilidades; `?match=` válido abre la cronología y cerrar la limpia; inválido no abre nada; `pnpm test`, `pnpm run typecheck` y `pnpm run lint` pasan.
- [ ] **T7. Botón «Compartir».** RF-011, RNF-005
- Hecho cuando: `PublicShareButton.vue` y `utils/publicShare.ts` existen con claves ES/EN, integrados en torneo, diálogo de resultado y ficha; `public-share.test.ts` y `ui-component-imports.test.ts` pasan.
- [ ] **T8. E2E de SEO y compartir.** RNF-005, RNF-006, criterios 1–5
- Hecho cuando: `e2e/public-seo.spec.ts` está en el proyecto `public` y pasa contra la pila local (`pnpm exec playwright test e2e/public-seo.spec.ts --project public`), con axe sin violaciones en ambos temas a 1440 y 390 px; `pnpm run typecheck:e2e` pasa.
- [ ] **T9. Documentación, validación y cierre.** Criterio 6
- Hecho cuando: README (endpoints, variable, límites del proxy para las rutas nuevas, excepción §3.3), AGENTS, manual, informe (F14 implementada) y MEMORY están actualizados; frontend `pnpm test`, `typecheck`, `lint`, `build` y suite backend pasan; PR del bloque B con CI 7/7 y la excepción §3.3 descrita en la descripción.
