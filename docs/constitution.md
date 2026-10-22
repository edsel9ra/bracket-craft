# Constitución de Bracket Craft

**Ruta:** `docs/constitution.md`
**Versión:** 1.4.0
**Última actualización:** 2026-10-22
**Ámbito:** Este documento define los principios y reglas que gobiernan el desarrollo de Bracket Craft. Tiene precedencia sobre cualquier otra guía del repositorio. `README.md` describe el producto, `AGENTS.md` describe cómo trabajar en el repositorio y `ci.yml` automatiza la verificación; ninguno puede contradecir esta constitución.

## 1. Propósito

Bracket Craft es una plataforma multi-tenant para crear y operar torneos de fútbol con reglas configurables, fases componibles y resultados en tiempo real.

Esta constitución existe para garantizar que cada cambio, hecho por una persona o por un agente, preserve cuatro cosas:

1. **Aislamiento entre organizaciones:** ninguna organización puede ver ni modificar datos de otra.
2. **Integridad deportiva:** los resultados, las tablas y las versiones publicadas son confiables y trazables.
3. **Privacidad de las personas:** los datos de jugadores se exponen solo con base y consentimiento explícitos.
4. **Reproducibilidad:** cualquiera puede levantar, verificar y desplegar el proyecto de forma consistente.

## 2. Principios Innegociables

Estos principios no se relajan por urgencia, conveniencia ni preferencia. Solo pueden cambiarse enmendando esta constitución (ver sección 5).

1. **El aislamiento por tenant lo garantiza la base de datos.** Toda tabla propiedad de un tenant usa Row Level Security. La aplicación no sustituye a RLS ni lo elude.
2. **La aplicación nunca tiene privilegios de saltarse RLS.** El rol de base de datos de la aplicación no es superusuario y no tiene `BYPASSRLS`.
3. **Lo publicado es inmutable.** Las versiones de torneo publicadas y los resultados cerrados no se editan directamente, ni siquiera desde la administración global.
4. **El historial de esquema es append-only.** Los cambios de base de datos se hacen únicamente con nuevas migraciones numeradas. Una migración aplicada nunca se edita.
5. **Lo público es una proyección mínima.** Las vistas y endpoints públicos no exponen documentos de identidad ni fechas de nacimiento. Las fotos solo se publican con consentimiento de imagen. La formación táctica solo es pública tras publicarse explícitamente.
6. **Ningún secreto por defecto fuera de desarrollo.** Los valores de `.env.example` son solo para desarrollo local. Fuera de él, los secretos se inyectan externamente y el backend rechaza los defaults conocidos.
7. **La administración global está separada y auditada.** Las acciones de plataforma viven en `/admin`, requieren pertenecer a `platform_admins` y quedan registradas en `platform_audit_logs`.
8. **Nada se da por terminado sin verificación.** Un cambio que no pasa las verificaciones de CI no está listo, y un cambio no verificado se declara como tal.
9. **El código de desarrollo no llega a producción.** Los scripts de seed y los datos demo solo corren en entornos de desarrollo/local.

## 3. Reglas de Implementación

### 3.1 Base de datos y multi-tenancy

- Llama a `set_rls_context()` dentro de la transacción y antes de cualquier consulta tenant, fijando `app.current_organization_id` y `app.current_user_id`.
- Toda tabla nueva propiedad de un tenant nace con RLS habilitado y sus políticas definidas en la misma migración.
- Cada cambio de esquema es la siguiente migración SQL numerada en `infra/postgres/migrations/`. `infra/postgres/migrate.sh` registra checksums SHA-256 y rechaza ediciones de migraciones aplicadas.
- Si una migración ya aplicada tiene un defecto, se corrige con una migración posterior, no editándola.

### 3.2 Backend

- Cada funcionalidad vive en su propio módulo bajo `backend/app/modules/`, y su router se registra en `backend/app/main.py`.
- El acceso a datos es asíncrono (SQLAlchemy async).
- Las tareas diferidas y los efectos secundarios de dominio (por ejemplo, el cierre de actas) pasan por el outbox y el worker, no por llamadas síncronas dentro del request.
- Las reglas deportivas configurables (puntuación, desempates, disciplina, sustituciones, ventana de inscripción) se expresan como configuración JSON de la versión del torneo, no como constantes en el código. Las transferencias no forman parte de la configuración: el producto no soporta traspasos entre equipos.

### 3.3 Frontend

- Toda llamada a la API usa `frontend/app/composables/useApi.ts`, que selecciona la URL base de servidor/cliente y transporta organización, cookies y CSRF.
- Las rutas públicas (`/`, `/tournaments/{id}`) no dependen de sesión. El Workspace (`/workspace`) exige sesión y organización activa validada.

### 3.4 Seguridad y configuración

- Mantén los defaults de desarrollo únicamente en `.env.example`.
- Fuera de desarrollo se cambian `JWT_SECRET`, `PLAYER_DATA_KEY`, `INVITATION_TOKEN_KEY`, las credenciales de base de datos y de almacenamiento, y se habilita `AUTH_COOKIE_SECURE`.
- Los datos personales de jugadores se almacenan protegidos con `PLAYER_DATA_KEY` y nunca se incluyen en logs ni en proyecciones públicas.
- Las dependencias deben pasar `pip-audit`, la auditoría del frontend con el filtro determinista descrito abajo y el escaneo Trivy de CI.
- La auditoría del frontend se ejecuta **desde la raíz del repositorio** con el comando efectivo de abajo, idéntico en esta constitución, `AGENTS.md`, el README y CI. Usa `pnpm --dir frontend audit --prod --json --audit-level low`, captura el estado de pnpm en lugar de una tubería, lo pasa al filtro como `--pnpm-status` y guarda el JSON en un archivo temporal fuera del repositorio que se elimina al salir con `trap`.
- El filtro `infra/scripts/audit_frontend.py` es determinista, no usa red ni reloj, no escribe archivos ni mantiene estado, y su código de salida decide el resultado del paso. **Hace fallar el job ante cualquier hallazgo accionable**: severidad `high` o `critical` con corrección publicada en `patched_versions`.
- Los hallazgos sin corrección publicada no bloquean; se muestran y se revisan en cada actualización de dependencias y en la próxima auditoría técnica, con el propietario del producto como responsable.
- Queda prohibido suprimir hallazgos con listas de CVEs, GHSA, paquetes o rutas, así como cualquier flag del gestor que persista exclusiones (por ejemplo, `--ignore-unfixable` o `audit.ignore`).

Comando efectivo:

```sh
AUDIT_JSON="/tmp/pnpm-audit.json"
trap 'rm -f "$AUDIT_JSON"' EXIT
if pnpm --dir frontend audit --prod --json --audit-level low > "$AUDIT_JSON"; then status=0; else status=$?; fi
PYTHONDONTWRITEBYTECODE=1 python3 infra/scripts/audit_frontend.py --input "$AUDIT_JSON" --pnpm-status "$status"
```

### 3.5 Infraestructura y CI

- Python 3.14, Node 24 y pnpm 12.12.1 son las versiones de referencia. Cambiarlas exige actualizar `ci.yml`, `AGENTS.md` y el README en el mismo cambio.
- Mantén `aquasecurity/trivy-action@v0.36.0` mientras no se valide una versión posterior; `v0.28.0` está roto.
- El lockfile del frontend (`pnpm-lock.yaml`) permanece versionado; la instalación usa `--frozen-lockfile`.
- `docker compose config -q` debe validar tanto la configuración de desarrollo como la de producción.

## 4. Criterios Obligatorios para Cada Cambio

Ningún cambio se fusiona sin cumplir todo lo siguiente que le aplique.

**Para todos los cambios**

- [ ] Pasa el job de CI correspondiente (`backend`, `frontend`, `infrastructure`, `security` y `e2e`; `e2e` se ejecuta en cada `pull_request` y solo en `push` a `main`).
- [ ] No introduce secretos, credenciales ni datos personales en el repositorio.
- [ ] Si altera el comportamiento observable, actualiza la documentación afectada (`README.md`, `AGENTS.md` o esta constitución).
- [ ] Tiene pruebas para el comportamiento nuevo o corregido, o documenta por qué no son posibles.

**Para cambios de base de datos**

- [ ] Es una nueva migración con el siguiente número, sin editar migraciones aplicadas.
- [ ] Las tablas tenant nuevas incluyen RLS y políticas.
- [ ] Se verificó que funciona sobre un volumen limpio y sobre uno ya migrado (ver nota sobre la migración 002 en `AGENTS.md`).
- [ ] `sh -n infra/postgres/migrate.sh` sigue pasando.

**Para cambios de API o backend**

- [ ] Las consultas tenant corren con `set_rls_context()` dentro de la transacción.
- [ ] Los endpoints públicos no exponen campos sensibles.
- [ ] El router nuevo está registrado en `backend/app/main.py`.
- [ ] `pytest -q` y `python -m compileall -q app` pasan.

**Para cambios de frontend**

- [ ] Las llamadas HTTP usan `useApi.ts`.
- [ ] `pnpm test`, `pnpm run typecheck` y `pnpm run build` pasan.

**Para cambios de infraestructura o despliegue**

- [ ] `docker compose config -q` pasa.
- [ ] No hay defaults de desarrollo accesibles en el perfil de producción.

**Para cambios de dependencias**

- [ ] Los lockfiles están actualizados y las auditorías de seguridad pasan.

## 5. Excepciones y Evolución

### 5.1 Excepciones

- Un **principio innegociable** (sección 2) no admite excepciones. Si un requerimiento lo contradice, se cambia el requerimiento o se enmienda la constitución.
- Una **regla de implementación** (sección 3) o un **criterio de cambio** (sección 4) puede exceptuarse solo si se cumple todo lo siguiente:
  1. La excepción está justificada por escrito en la descripción del cambio.
  2. Es acotada: indica qué regla se omite, dónde y por qué.
  3. Tiene un responsable y, cuando es temporal, una fecha o condición de retiro.
  4. Un revisor distinto del autor la aprueba explícitamente.
- Las excepciones temporales vencidas se tratan como incumplimiento.

### 5.2 Evolución

- Esta constitución se enmienda mediante un cambio propio, revisado y aprobado, que no se mezcla con cambios funcionales.
- Toda enmienda indica el motivo, qué reglas cambian y su impacto en el código existente.
- Versionado:
  - **Mayor (X.0.0):** se agrega, elimina o modifica un principio innegociable.
  - **Menor (0.X.0):** se agregan o cambian reglas de implementación o criterios.
  - **Parche (0.0.X):** aclaraciones y correcciones que no alteran el significado.
- Toda enmienda se registra en la sección 7 y se refleja en `AGENTS.md` y el README cuando corresponda.

## 6. Definición de Cumplimiento

Un cambio **cumple** esta constitución cuando:

1. Respeta todos los principios innegociables, sin excepción.
2. Cumple las reglas de implementación aplicables, o tiene una excepción válida según la sección 5.1.
3. Satisface todos los criterios obligatorios de la sección 4 que le apliquen.
4. Pasa todos los jobs de CI en verde.
5. Fue revisado por una persona distinta del autor. Un cambio hecho por un agente requiere revisión humana.

Un cambio **no cumple** si:

- Viola un principio innegociable.
- Omite una regla o criterio sin excepción aprobada.
- Declara una verificación como realizada sin haberla ejecutado.

Los incumplimientos detectados después de fusionar se corrigen con prioridad. Si afectan al aislamiento entre tenants, a la privacidad o a la integridad de resultados publicados, el cambio se revierte o se mitiga de inmediato, antes de continuar con trabajo funcional.

## 7. Historial de Cambios

| Versión | Fecha | Cambio | Impacto |
|---------|-------|--------|---------|
| 1.0.0 | 2026-10-14 | Creación inicial de la constitución, derivada de `README.md`, `AGENTS.md` y `ci.yml`. | Establece principios, reglas, criterios y definición de cumplimiento. |
| 1.0.1 | 2026-10-14 | Ruta de `useApi.ts` actualizada por la migración a Nuxt 4 (el código de app vive en `frontend/app/`). | Sin cambio de significado; solo actualiza referencias a su ubicación real. |
| 1.1.0 | 2026-10-19 | **Reglas afectadas:** §3.5 (Infraestructura y CI). Regulariza el cambio que ya estaba presente en el repositorio, donde §3.5 declaraba Python 3.14, Node 24 y la versión 12.12.2 de pnpm sin haber subido la versión de la constitución, y lo corrige a pnpm 12.12.1 (la 12.12.2 no existe en el registro npm; las publicadas cercanas son 12.12.0, 12.12.1, 12.13.0 y 12.14.0). **Motivo:** cerrar la deriva documental de versiones de referencia (R04 de la auditoría técnica del 2026-10-19) y dejar cabecera, §3.5 e historial coherentes. **Incremento menor** porque cambia el contenido de una regla de implementación, no una simple aclaración; no corresponde un parche. | No altera principios ni criterios. Fija una única combinación de versiones de referencia —Python 3.14, Node 24 y pnpm 12.12.1— que debe mantenerse alineada en `ci.yml`, los Dockerfiles, el `packageManager` del frontend, `AGENTS.md`, el README y esta §3.5 en el mismo cambio. La alineación técnica de esas fuentes se tramita en un commit separado de esta enmienda. Sin impacto funcional en el código existente. |
| 1.2.0 | 2026-10-19 | **Reglas afectadas:** §3.4 (Seguridad y configuración). Sustituye la exigencia literal de `pnpm audit --prod --audit-level high` por el comando efectivo —desde la raíz, `pnpm --dir frontend`, estado de pnpm capturado y pasado con `--pnpm-status`, filtro determinista `infra/scripts/audit_frontend.py` y archivo temporal limpiado con `trap`— y hace explícita la política sobre hallazgos sin corrección. **Motivo:** retirar la deuda de dependencias del frontend y hacer explícita la política de no accionables, sustituyendo el comando literal por el efectivo (spec 003, RF-009). **Incremento menor** porque cambia el contenido de una regla de implementación, no una aclaración; no corresponde un parche. | CI (paso `security`) y documentación (`AGENTS.md`, README); sin impacto funcional ni de esquema. El filtro conserva el fallo ante hallazgos accionables (≥ high con corrección publicada) y no persiste exclusiones. |
| 1.3.0 | 2026-10-20 | **Reglas afectadas:** §3.2 (Backend). Retira «transferencias» de la lista de reglas deportivas configurables y añade «sustituciones» y «ventana de inscripción»; declara que las transferencias no son configuración porque el producto no soporta traspasos entre equipos. **Motivo:** R09 de la auditoría del 2026-10-19 y spec 007 (Q1/Q2): `substitutions` pasa a aplicarse y `transfers` no tenía operación que la produjera ni consumidor. **Incremento menor** porque cambia el contenido de una regla de implementación. | Sin impacto de datos: `transfers` desaparece de las configuraciones nuevas; `substitutions` y `roster_lock_matchday` quedan como claves aplicadas. No hay cambio de esquema por esta enmienda. |
| 1.4.0 | 2026-10-22 | **Reglas afectadas:** §4 (Criterios obligatorios), primer criterio de «Para todos los cambios». Añade el job `e2e` a la lista de jobs cuyo resultado condiciona la fusión y precisa su disparador: en cada `pull_request` y solo en `push` a `main`. **Motivo:** la spec 010 introduce un quinto job independiente que verifica de extremo a extremo el reintento del tiempo real; la §4 enumeraba cuatro y quedaba desactualizada. **Incremento menor** porque añade un criterio de cambio, no una aclaración. | Sin impacto funcional ni de esquema ni migraciones. El job `e2e` forma parte del cumplimiento en cada PR y en `main`; para bloquear la fusión debe marcarse además como *required check* en la protección de rama, que es configuración del repositorio. Se refleja en `AGENTS.md`. |