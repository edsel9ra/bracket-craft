# MEMORY.md — Bracket Craft
Memoria del proyecto entre sesiones. Máximo ~50 líneas: resume o elimina lo que ya no aporte.

## Spec 005 — Rendimiento: firmas, Swiss y conexión (2026-10-20)
- **Implementada y validada por @reviewer (APROBADA, 2026-10-20); pendiente de T010: CI en `main` y revisión humana.**
- Evidencia local: **391 passed / 108 skipped**; `compileall` y `git diff --check` OK; sin cambios de config, Compose, migraciones ni frontend. La opt-in no se ejecutó con el rol de aplicación (credenciales del PostgreSQL local); con rol admin pasaron el pool real y una prueba de Swiss.
- Fotos: firma, subida y borrado siempre fuera de transacción; subidas con compensación (incluida cancelación). Público `photo_url: null` (200), Workspace 503, un aviso por respuesta y cliente de firma cacheado (rotar credenciales exige reiniciar el proceso).
- Swiss: 64 equipos (422), 50 000 evaluaciones (40 000 búsqueda + 10 000 reserva) y timeout 10 s en ejecutor dedicado de 2 hilos; un fallback fallido tras agotar la búsqueda es `budget_exhausted`. 409 por presupuesto, sorteo imposible, timeout o estado cambiado; `ValueError` de validación intacto. RLS re-fijado y estado revalidado con `FOR UPDATE` en la escritura.
- Conexión: 15 s / 30 s, pool 10+10 con espera 10 s y 503 por agotamiento con un aviso; 2 × 20 + 20 = 60 conexiones con `API_WORKERS=2` y worker frente a 100 por defecto.

## Riesgo residual
- Dos sorteos Swiss simultáneos en frío (ronda 1 sin filas) podrían insertar calendarios duplicados: `FOR UPDATE` no bloquea filas inexistentes y `bracket_code` no es único. Aceptado por el usuario en la spec 005.
- `braces` 3.0.3 (GHSA-vfj7-8cjw-p6xm) y `node-forge` 1.4.0 (GHSA-86w9-cpqp-85rv), altos y sin parche upstream; revisar en cada actualización.

## Specs anteriores
- 001 (correctivos P0: `players` con RLS, overlay de producción, inmutabilidad de resultados), 002 (cifrado de fecha 017/018, backfill y `MIGRATION_TARGET`) y 003 (deuda de dependencias; CI 39361295825): cerradas.
- 004 (outbox y tiempo real): implementada y aprobada; stream de mejor esfuerzo (`MAXLEN` 10 000), `event_id` aditivo, `RESYNC` y deduplicación 200 en el cliente; API HTTP como fuente de verdad.

## Entorno local
- Sin Python ni pnpm en el host: tests con la imagen `bc-api-t007` sobre copia en `/tmp` (sin `__pycache__` en el repo); `compileall` sobre copia.
- Docker 29.8.2 / Compose 5.5.1. El PostgreSQL local tiene credenciales desalineadas con `.env` desde el volumen: la suite opt-in (`RUN_DATABASE_TESTS=1`) no se ejecuta; hay que declararlo, no cambiar la base.
- Constitución en CRLF: usar `git -c core.whitespace=cr-at-eol diff --check`. Trivy `aquasec/trivy:0.70.0`; `trivy-action@v0.36.0`.

## Pendiente
- Cerrar la spec 005 (T010): CI en `main` y revisión humana distinta del autor; la suite local ya está en verde.
- Ejecutar la opt-in con el rol de aplicación cuando haya credenciales válidas (timeouts 15 s/30 s y frontera con sesión real).
- Hallazgos menores no bloqueantes de 005: ventana de compensación en cancelación durante `put_bytes`/commit; borrado del objeto anterior fuera del `finally`; tests de cancelación real con `task.cancel()`; revocación de permiso en la escritura de importación; validación opcional de `team_id` antes de subir.
- Confirmar la revocación de la segunda clave de Context7 y exportar `CONTEXT7_API_KEY`.
