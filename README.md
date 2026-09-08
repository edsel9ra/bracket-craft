# Bracket Craft

Plataforma multi-tenant para crear y operar torneos de futbol con reglas configurables, fases componibles y resultados en tiempo real.

## Stack

- Backend: FastAPI, SQLAlchemy Async y PostgreSQL.
- Frontend: Nuxt 3, Vue 3 y Pinia.
- Procesamiento: Redis y worker asíncrono de outbox.
- Tiempo real: Socket.IO.
- Infraestructura: Docker Compose.

## Inicio local

1. Copiar `.env.example` a `.env`.
2. Ejecutar `docker compose up --build`.
3. Abrir `http://localhost:3000`.
4. Consultar la documentación en `http://localhost:8000/docs`.

La inicialización PostgreSQL se ejecuta en el primer arranque del volumen. Las migraciones numeradas de `infra/postgres/migrations` se aplican una sola vez y quedan registradas en `schema_migrations` por el servicio `db-migrate`.

La portada y las rutas `/tournaments/{id}` son públicas. El Workspace de gestión está disponible en `/workspace` después de iniciar sesión y validar una organización activa.

Las proyecciones públicas de torneos, tablas y partidos se sirven desde `/api/v1/tournaments/public`, `/api/v1/tournaments/public/{id}/standings` y `/api/v1/tournaments/public/{id}/matches`. Los partidos incluyen la planilla pública cuando existe; la formación táctica solo aparece después de publicarse explícitamente desde el Workspace.

La configuración local incluye MinIO en `http://localhost:9001`. La importación de plantillas acepta CSV/TXT con `first_name`, `last_name`, `national_id`, `birth_date` y `dorsal_number`; `photo_filename` vincula imágenes JPG, PNG o WEBP incluidas en un ZIP opcional. La proyección pública solo devuelve `photo_url` cuando el roster tiene consentimiento de imagen.

Para ejecutar únicamente el frontend fuera de Docker:

```bash
cd frontend
pnpm install
pnpm dev
```

## Alcance inicial

- Registro y login por email/password.
- Preparación de Google OAuth mediante `auth_identities`.
- Organizaciones con membresías y RBAC.
- Torneos y versiones inmutables.
- Configuración privada de versiones, fases, equipos y partidos.
- Configuración JSON de puntuación, desempates, disciplina y transferencias.
- Cierre de actas con goles, tarjetas, suspensiones y outbox.
- Clasificación Round Robin.
- Estructura de fases lista para grupos y playoffs.

## Seguridad

El backend establece `app.current_organization_id` y `app.current_user_id` dentro de cada transacción. Las tablas tenant-owned tienen RLS y las vistas públicas no exponen documentos ni fechas de nacimiento.

La administración global está separada del workspace en `/admin`. Requiere un registro en `platform_admins`; para el primer arranque local se puede indicar `PLATFORM_ADMIN_EMAIL` en `.env` después de registrar la cuenta. Las acciones de usuarios, organizaciones y membresías se auditan en `platform_audit_logs` y no permiten editar directamente resultados ni versiones publicadas.

Las credenciales de desarrollo (`bracket_app`, `POSTGRES_PASSWORD`, `JWT_SECRET` y `PLAYER_DATA_KEY`) incluidas en `.env.example` son únicamente para desarrollo local. En producción deben inyectarse mediante secretos externos y `APP_ENV=production`; el backend rechazará los defaults conocidos. El perfil `docker-compose.production.yml` elimina los volúmenes de código, desactiva `--reload`, construye el frontend estático y exige los secretos y URLs de producción.
