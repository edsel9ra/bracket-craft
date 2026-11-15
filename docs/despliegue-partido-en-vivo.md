# Despliegue coordinado del partido en vivo (036, F1)

Este procedimiento no acredita un despliegue productivo; la implementación queda
pendiente de la aceptación humana explícita de F1 (T84). Describe el orden y los
límites del ensayo local controlado registrado en la evidencia de T81.

## Orden obligatorio

1. Respaldar la base y registrar la revisión de API, worker y frontend. Aplicar
   las migraciones pendientes **hasta 059** con el runner administrativo
   (`infra/postgres/migrate.sh`) y verificar sus checksums. La 056 crea el estado
   del borrador (`match_live_state`, comandos, revisiones y la vista interna de
   selección); la 059 solo añade `bracket_code` a esa vista — ninguna reescribe
   datos ni exige backfill. **056/059 antes del backend**: el código nuevo puede
   leer el esquema nuevo, pero un API nueva sobre un esquema sin la vista falla
   las lecturas públicas/relacionadas.
2. Pausar las escrituras del torneo afectado o preferir una ventana de
   mantenimiento: los partidos en curso conservan su borrador, pero la ventana
   evita que un cierre clásico compita con el primer comando F1.
3. Drenar y **terminar todos** los procesos API y relay anteriores. Cerrar las
   conexiones WebSocket vivas — cambiar el balanceador o retirar readiness no
   las termina. No hay despliegue rolling mixto: un API antigua no entiende
   `MATCH_LIVE_UPDATED` ni el cierre con `live_review_id`.
4. Arrancar todas las API con la misma revisión y sustituir el worker del outbox
   por la misma revisión. Los consumidores compatibles (filtro privado 035,
   público del torneo, cliente del Workspace) no cambian de contrato: el aviso
   privado sigue siendo los tres IDs, el público añade `MATCH_LIVE_PUBLIC_UPDATED`
   con los mismos tres IDs y la lectura pública añade la variante `suspended`
   discriminada por `status`.
5. Reapertura: comprobar readiness, un receptor autorizado por tenant (lectura
   `/live/access` + invalidación de tres IDs), el público anónimo y la
   recuperación tras un fallo de autorización (suspensión + `RESYNC` dirigido,
   sin replay).

## Compatibilidad y fail-closed

- Un cliente clásico **no puede cerrar** un partido F1: `POST /matches/{id}/close`
  sin `live_review_id` responde `409 LIVE_REVIEW_REQUIRED` y un recibo ajeno,
  fabricado o caducado responde `409 LIVE_REVIEW_STALE`. Verificado por
  `test_legacy_bypass_classic_client_cannot_close_live` en
  `tests/test_match_live_close_db.py`: sin revisión, con UUID inexistente y con
  revisión válida hecha obsoleta por un evento posterior — en los tres casos el
  acta no se confirma y no se escriben eventos.
- Un partido **sin** borrador F1 se cierra por la vía clásica exactamente igual
  (`test_classic_consolidation_regression_without_live_state`): el despliegue no
  cambia el contrato del cierre existente.
- Si la evaluación de autorización falla, los sockets afectados quedan
  suspendidos sin gracia; `recover` resuscribe solo los vigentes mediante 032 +
  `RESYNC` dirigido. La lectura HTTP y el carril público no dependen de esa
  evaluación.
- Las sesiones caducadas o revocadas nunca se resuscriben; una autorización
  iniciada antes de una retirada confirmada puede terminar en tránsito — las
  iniciadas después la observan.

## Límite de rollback

**Volver a una versión anterior después de haber creado un borrador F1 no está
soportado**: el código antiguo ignora `match_live_state`, permitiría el cierre
clásico sobre un partido con borrador y dejaría marcador/estado incoherentes.
La corrección es **hacia delante**: suspender el partido, revisar el conjunto y
cerrar con la revisión vigente (o completar/corregir el borrador con comandos),
nunca borrar `match_live_state`, sus comandos ni las migraciones 056–059. Si la
regresión ocurre **antes** de que exista cualquier borrador F1, el binario
anterior sigue siendo compatible con el esquema — pero preferir mantenimiento
hasta disponer de la corrección revisada.
