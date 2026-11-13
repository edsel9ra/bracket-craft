# Despliegue del filtro privado (035, PR B/C)

Este procedimiento no acredita un despliegue ni la aceptación de F8/R32f.
Requiere los gates y revisión de B/C antes de declarar completada la validación.
F8 sigue pendiente de aceptación y R32f abierto hasta T49. F1 sigue sin emitir
borradores y F9 conserva sus handlers HTTP/correo fuera de Socket.IO.

## Orden obligatorio

1. Respaldar la base y registrar la revisión de API, worker y frontend. Aplicar
   las migraciones pendientes **hasta 055** con el runner administrativo habitual
   (`infra/postgres/migrate.sh`). Verificar sus checksums y la función
   `authorize_realtime_recipients`, `SECURITY INVOKER`, sin EXECUTE de PUBLIC.
   La recuperación reutiliza **032**, también invocadora; no hay 056 ni cambio
   de políticas, permisos HTTP o roles por torneo.
2. Publicar el frontend B. Comunicar una recarga completa del Workspace para
   pestañas con JavaScript anterior: reconectar el transporte no actualiza el
   código que antes descartaba una recarga terminal u ocupada. Los controles
   siguen usando motivos compatibles; no se exige interpretar datos de negocio.
3. Drenar y **terminar todos** los procesos API anteriores antes de permitir el
   canal organizativo nuevo. Incluye cada réplica y worker Uvicorn que conserve
   conexiones actualizadas a WebSocket. Cambiar el balanceador o retirar una
   réplica de readiness no termina esas conexiones: hay que cerrarlas y comprobar
   que no queda ningún proceso anterior atendiendo sockets. Preferir una ventana
   de mantenimiento a una mezcla de APIs que aún difundan al room organizativo.
4. Arrancar todas las API B con 055 ya aplicada y sustituir el worker por la misma
   revisión. No desplegar estados intermedios de B. La primera resincronización
   organizativa va dirigida por sid después de 032; el cliente vuelve a leer por
   HTTP. El carril público conserva sus rooms y contratos.
5. Comprobar readiness y un receptor por tenant: lectura HTTP equivalente,
   invalidación privada de tres IDs solo para autorizados y RESYNC dirigido.
   Comprobar también público anónimo, retirada confirmada y recuperación después
   de un error de autorización, sin publicar otro evento ni reconectar el válido.

## Compatibilidad y fallo cerrado

- Las filas históricas pueden conservar `version_id`, `scope` y `rectified_at`.
  Se resuelven/validan internamente y **no** se vuelven a emitir esos campos.
  Las nuevas publicaciones rectificativas conservan tres eventos e IDs distintos.
- Catálogo desconocido, sobre incoherente o referencia ajena: denegación. La sonda
  operativa no es un evento de producto. No hay fallback al room organizativo.
- Si falta 055 o falla una evaluación, se suspenden las entregas privadas
  afectadas, se avanza el cursor y no se guarda backlog de negocio. HTTP y público
  no dependen de esa evaluación. El mantenimiento reintenta 032 por lotes; un error
  o fila ausente mantiene suspensión. El válido recibe `RESYNC RELAY_START`, el
  inválido recibe el tratamiento de sesión existente. No hay replay ni gracia.
- Una autorización iniciada antes de una retirada confirmada puede terminar en
  tránsito; las iniciadas después deben observarla. No se promete retirar frames
  ya enviados.

## Contingencia y rollback

**Nunca volver a una API anterior al filtro:** restauraría el broadcast vulnerable.
No deshacer 055/032, borrar outbox ni rebobinar Redis para recuperar eventos privados.
Ante una regresión, conservar el binario B fail-closed o detener las API afectadas
en mantenimiento hasta disponer de una corrección revisada. Un fallo de la función
de autorización ya suspende el canal privado sin desconectar masivamente ni impedir
el carril público/HTTP; no usar el arnés E2E como opción operativa de contingencia.

El arnés `frontend/e2e/docker-compose.realtime.yml` sustituye el entrypoint **solo
en pruebas** por `backend/tests/realtime_e2e_server.py`. Rechaza APP_ENV fuera de
development/dev/local antes de instalar adaptadores; no añade rutas ni variables
productivas. Usa sesiones reales, outbox/worker/Redis y archivos IPC efímeros bajo
`frontend/.auth/realtime` (ignorados, no publicar). La cadencia de mantenimiento de
dos segundos y las barreras/fallos solo viven allí; producción conserva 30 segundos.
CI y el runner local aplican explícitamente ese override, nunca el perfil productivo.
