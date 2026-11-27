# Tareas — Spec 051: API pública documentada para terceros (F15)

Estado: aprobadas el 2026-11-27 («Apruebo el plan y las tareas»).

Un solo PR de implementación (sin frontend), apilado sobre el PR de la spec.

- [ ] **T1. Catálogo y documento OpenAPI público.** RF-001, RF-002, RF-004, RF-005, RNF-002, RNF-004
- Hecho cuando: `modules/public_api/{catalog,openapi,router}.py` y la ruta registrada en `main.py`; `openapi-spec-validator` fijado en `requirements-dev.txt`; `tests/test_public_api_catalog.py` y `tests/test_public_api_openapi.py` fallan primero y pasan con `cd backend && pytest -q tests/test_public_api_catalog.py tests/test_public_api_openapi.py`; `pip-audit -r requirements.txt -r requirements-dev.txt` sin hallazgos.
- [ ] **T2. Referencia y compatibilidad de `v1`.** RF-006, RF-007
- Hecho cuando: `compat.py`, `docs/api-publica/openapi-v1.json` e `infra/scripts/public_api_reference.py`; `tests/test_public_api_compat.py` falla primero y pasa; `python infra/scripts/public_api_reference.py --check` termina con 0.
- [ ] **T3. CORS del catálogo.** RF-008, RF-009, RF-009b, RF-010
- Hecho cuando: `cors.py` montado en `main.py`; `tests/test_public_api_cors.py` falla primero y pasa con `RUN_DATABASE_TESTS=1`; `tests/test_security_headers.py` sigue pasando.
- [ ] **T4. Guías ES/EN y límite del proxy.** RF-003, RF-007, RF-011, RF-011b, RNF-003
- Hecho cuando: `docs/api-publica.md`, `docs/api-publica.en.md` y la sección del proxy; `tests/test_public_api_docs.py` falla primero y pasa.
- [ ] **T5. Documentación, validación y PR.** RF-012, RNF-001, RNF-004
- Hecho cuando: README, AGENTS, informe (F15 implementada) y MEMORY actualizados; pasan la suite backend completa con BD, Ruff, Bandit y compileall; PR con la CI en verde.
