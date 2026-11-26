# Bracket Craft — Funciones adicionales propuestas

**Fecha:** 2026-11-12 · **Base:** `main` en `133d53db` (tras #58–#60) · **Tipo:** informe de revisión, sin cambios en el repositorio.

**Fuentes revisadas:** `docs/constitution.md` 1.5.0, `README.md`, `AGENTS.md`, `MEMORY.md`, `docs/manual-usuario.md`, `docs/auditoria-2026-10-19.md` (R01–R32), `docs/auditoria-2026-11.md` (H1–H12), auditoría backend A1–A10 (#58/#59), `docs/inspeccion-accesibilidad.md`, `docs/auditoria-tema-claro-032.md` y la sección «Fuera de alcance» de las specs 001–032.

## 1. Resumen

- Las auditorías de seguridad e infraestructura están cerradas (R01–R32 tratadas en 001–011; H1–H12 resueltas o mitigadas; A1–A10 integradas). Lo que queda **no son correcciones, sino funciones aplazadas a propósito**: cada spec las dejó como «spec propia».
- Mi lectura: el hueco más grande es el **ciclo de vida del partido en vivo (R11)**. El producto promete «resultados en tiempo real», pero hoy el tiempo real solo publica el resultado al cerrar el acta. Le siguen el **avance automático entre fases** (R12/spec 006) y la **gestión de cuenta** (recuperar contraseña, que no existe).
- Hay varias propuestas que tocan la constitución (§2.3 inmutabilidad, §3.2 transferencias). Las marco aparte porque exigen una enmienda (§5.2) en su propio PR antes de la spec.

## 2. Restricciones que condicionan cualquier propuesta

| Principio / regla | Efecto en las propuestas |
|---|---|
| §2.1–2.2 RLS en la BD, sin `BYPASSRLS` | Toda tabla nueva (notificaciones, roles por torneo, sedes, etc.) nace con RLS en su misma migración. |
| §2.3 Lo publicado es inmutable | Corregir o reabrir actas, y anular W.O. o sanciones, exige una enmienda constitucional. |
| §2.5 Lo público es mínimo | Fichas de jugador, cronología pública, API para terceros y SEO pasan por la matriz de la spec 020 (RF-013–RF-018). |
| §3.2 Efectos laterales por outbox | Notificaciones, correo y webhooks salen del worker, nunca del request. |
| §3.2 Reglas en JSON, sin transferencias | Los traspasos exigen enmienda. Las reglas nuevas cambian `engine_version` 2026.1 y `docs/contrato-reglas.md`. |

## 3. Propuestas priorizadas

Impacto: valor para organizadores y público. Esfuerzo: S ≈ 1 spec pequeña / 1–2 PR; M ≈ 1 spec / 3–4 PR; L ≈ varias specs.

### P1 — Núcleo del producto

| # | Función | Origen documental | Qué incluiría | Impacto | Esfuerzo | ¿Enmienda? |
|---|---|---|---|---|---|---|
| F1 | **Partido en vivo: ciclo `live`/`suspended` y eventos incrementales** | R11 (audit. 2026-10-19); excluido en 007, 008, 015, 016 y 017 | Transiciones `scheduled→live→finished/suspended` (los CHECK ya existen); API de eventos durante el partido (gol, tarjeta, cambio) como borrador privado, consolidado en el cierre atómico actual; marcador en vivo por Socket.IO (`PUBLIC_REALTIME_EVENTS`); reloj de segmento. | Muy alto | L | No, si los eventos en vivo siguen siendo borrador hasta el cierre. |
| F2 | **Avance automático entre fases** | R12; fuera de alcance en 006, 008 y 020 | Llenar `phase_slots` desde `standings.stage_rank` (1.º/2.º de grupo, mejores terceros), sembrado automático de llaves y vista previa antes de confirmar. Hoy es manual (`/stages/{id}/teams`). | Alto | M–L | No (es configuración de fase; puede rozar `engine_version`). |
| F3 | **Recuperar y cambiar la contraseña** | Fuera de alcance en 013; no existe en el código | Flujo «olvidé mi contraseña» con token de un solo uso con hash (mismo patrón que las invitaciones tras A3), con rate limit y cambio desde la cuenta. Ya hay `core/email.py`. | Alto | S–M | No |
| F4 | **Corrección de actas confirmadas** | 001, 016, 017 y 018 («exige enmienda y spec propia») | Corrección mediante una **acta rectificativa** (nueva versión del resultado con motivo y auditoría), nunca editando la anterior. Recalcula la clasificación y el avance. | Alto (hoy un error de acta no tiene vía) | L | **Sí** (§2.3) |

### P2 — Valor operativo para organizadores

| # | Función | Origen | Qué incluiría | Impacto | Esfuerzo | ¿Enmienda? |
|---|---|---|---|---|---|---|
| F5 | **Pantalla de auditoría organizacional** | 008, 009 y 011 («sin interfaz ni endpoint de consulta») | Lectura paginada de los logs de la organización que ya se registran (oficiales, planilla, invitaciones, reaperturas), con filtros. Solo lectura y RBAC. | Medio–alto | S | No |
| F6 | **Notificaciones (correo / in-app / webhooks)** | 016, 020 y 022 («notificaciones, correo o webhooks») | Avisos de partido programado, resultado confirmado, W.O. y sanción. Salen del outbox (§3.2), con preferencias por usuario y webhooks firmados por organización. **Parcialmente implementada en la spec 046 (2026-11-24):** bandeja en el Workspace y correo, con preferencias por miembro y tipo × canal (bandeja activada y correo desactivado por defecto); migración 067. **Webhooks firmados en la spec 047 (2026-11-25):** hasta 10 por organización con `MANAGE_WEBHOOKS`, HMAC-SHA256 con secreto mostrado una vez y cifrado con `WEBHOOK_SECRET_KEY`, comprobación de IP en cada intento, 6 intentos y historial de 50 entregas en 30 días; solo torneos públicos; migración 068. | Medio–alto | M | No |
| F7 | **Roles por torneo (delegación)** | R06; 006 retiró el scoping y dejó «roles por torneo» fuera | Asignar operadores o árbitros a un torneo concreto, sin dar acceso a toda la organización. `tournament_user_roles` ya existió. | Medio | M | No (cambia el modelo RBAC; documentarlo en README/AGENTS) |
| F8 | **Filtro del tiempo real por rol** | R32f, riesgo aceptado (008, 009, 010) | Salas por permiso o torneo en lugar de `organization:{id}`. Es requisito previo si F1 emite datos privados en vivo. | Medio (seguridad) | S–M | No |
| F9 | **Gestión de sanciones: apelación y anulación** | 018 (`appealed`/`cancelled` sin vía operativa) | Flujo administrativo auditado para recurrir o anular una sanción, con efecto hacia delante. | Medio | M | Probablemente sí (si altera efectos de actas cerradas) |
| F10 | **Exportaciones** | 018, 020 y 022 | CSV o PDF de clasificación, calendario, actas y estadísticas; plantillas solo en privado y sin documento ni fecha de nacimiento. **CSV implementado en la spec 048 (2026-11-25):** página «Exportaciones» del Workspace (clasificación, calendario, estadísticas de jugadores y de equipos, plantillas) y acta de partido cerrado, para cualquier miembro; UTF-8 con BOM, cabecera ES/EN, fórmulas neutralizadas y tope de 10.000 filas; solo las plantillas se auditan; sin migración ni dependencias. **PDF pendiente** en una spec aparte (acta y clasificación primero). | Medio | S–M | No |
| F11 | **Duplicados en calendarios generados / sorteo concurrente** | H7 de la spec 005; riesgo aceptado en 008 y 011 | Lock o unicidad por fase al sortear, y detección de emparejamientos duplicados también en fases generadas. **Implementada en la spec 042 (2026-11-23):** bloqueo fase → versión probado con concurrencia real, comprobación previa y migración 065; H7 retirado como riesgo aceptado. | Medio (integridad) | S | No |
| F12 | **Formaciones por modalidad (5v5/7v7/9v9)** | 012, 021 y 024 («spec independiente») | Catálogo de formaciones y planilla por `game_format`. **Implementada en la spec 044 (2026-11-24):** 13 formaciones (tres por modalidad reducida y las cuatro de 11v11) con 5/7/9/11 titulares, validación al guardar, publicar y cambiar de formato, selector y campo público por modalidad; migración 066 y `engine_version` sin cambios (2026.1). | Medio (fútbol amateur o base) | M | Cambia `docs/contrato-reglas.md` (`engine_version` sigue en 2026.1) |

### P3 — Superficie pública y crecimiento

| # | Función | Origen | Qué incluiría | Impacto | Esfuerzo | ¿Enmienda? |
|---|---|---|---|---|---|---|
| F13 | **Cronología pública del partido** | 020 y 022 | Línea de tiempo con goles y tarjetas en la vista pública (sin asistencias ni sanciones, según RF-016). Depende de F1. | Medio–alto | M | No (amplía la matriz 020) |
| F14 | **Compartir y SEO** | 020, 021 y 022 | Metadatos OpenGraph, imagen de resultado, sitemap de torneos públicos. **Implementada en la spec 043 (2026-11-23):** metadatos OpenGraph/X en el servidor, imágenes PNG de torneo y resultado, enlace de partido, sitemap, `robots.txt` y botón «Compartir»; sin migraciones ni campos públicos. | Medio | S | No |
| F15 | **API pública documentada para terceros** | 020, 021 y 022 | Versionado y documentación de las lecturas públicas existentes, con límites en el proxy. | Medio | S–M | No |
| F16 | **Fichas de jugador y estadísticas históricas** | 020 y 022 | Ficha entre torneos de la misma organización, comparativas y goleadores históricos. Choca con la política de proyección mínima. | Medio | M | Revisar §2.5 |
| F17 | **Estadísticas adicionales** | 022 | Minutos jugados, posiciones, penales atajados. Requiere registrar la posición de quien entra en una sustitución. | Bajo–medio | M | No |

### P4 — Cuenta, identidad y plataforma

| # | Función | Origen | Impacto | Esfuerzo |
|---|---|---|---|---|
| F18 | Segundo factor (TOTP) para administradores y plataforma | 013 | Medio | M |
| F19 | Borrado o exportación de datos personales (cuenta y jugador) y desvincular Google | 013 | Medio (cumplimiento) | M |
| F20 | Verificación del correo de cuentas locales | 013 | Medio | S |
| F21 | Varias organizaciones por usuario: crear otra y cambiar entre ellas (R32: «login devuelve solo la 1.ª org») | 013, R32 | Medio | S–M |
| F22 | Más proveedores (Microsoft/Apple) o dominio de Google Workspace restringido | 013 | Bajo | M |
| F23 | Tema y preferencias sincronizados con la cuenta | 032 | Bajo | S |

## 4. Deuda técnica que conviene programar junto a estas funciones

No son funciones nuevas, pero desbloquean o protegen las anteriores:

- **Rotación de `PLAYER_DATA_KEY`** y re-cifrado (002 fuera de alcance). Necesaria antes de operar en producción con datos reales.
- **Observabilidad**: métricas, alertas y monitorización del worker (004, 009, 011). Pasa a ser crítica con F1 y F6.
- **Escalado del tiempo real**: adaptador Redis para Socket.IO y prueba con proxy real y varios workers (004; límite declarado en la audit. 2026-11).
- **ESLint**: reactivar las 12 reglas desactivadas; **CSP con `script-src` por nonce** (`docs/seguridad-http-ci.md`).
- **Escudos y fotos**: miniaturas o variantes, cuotas por organización y limpieza de huérfanos (014).
- Seguir de cerca **deepmerge** (H6) y retirar los overrides de glob/minimatch cuando los padres declaren versiones corregidas.
- **Pruebas de carga** y E2E con proxy real (límite declarado en la audit. 2026-11).

## 5. Hoja de ruta sugerida

1. **Corto plazo (sin enmiendas):** F3 (contraseña), F5 (auditoría visible), F11 (sorteo concurrente), F14 (compartir/SEO). Valor rápido y riesgo bajo.
2. **Bloque «tiempo real de verdad»:** F8 → F1 → F13 (+ observabilidad). F8 va primero para no ampliar la exposición R32f.
3. **Bloque competición:** F2 (avance automático) y F12 (formaciones por modalidad).
4. **Bloque gobierno:** enmienda de la constitución → F4 (acta rectificativa) y F9 (apelaciones), junto con F6 (notificaciones).
5. **Bloque cuenta y cumplimiento:** F18–F21 y la rotación de claves.

## 6. Decisiones del propietario (2026-11-12)

### 6.1 Rectificación de actas (F4): enmendar §2.3

- **Enmienda constitucional propia, mayor (2.0.0).** §5.2 clasifica como mayor el cambio de un principio innegociable. La enmienda va en un PR aparte, sin cambios funcionales, con motivo, reglas afectadas e impacto, la fila correspondiente en §7 y su reflejo en `AGENTS.md` y el README.
- **Alcance acotado:** la enmienda permite **solo** el procedimiento de acta rectificativa. No es una autorización general para editar lo publicado. El acta original no se modifica ni se elimina.
- **Flujo:** solicitud de corrección (el organizador indica el motivo y aporta la evidencia) → revisión y aprobación por un usuario con un permiso específico → publicación del acta rectificativa. La versión nueva rige los resultados y la clasificación vigentes; la original sigue consultable como antecedente.
- **Requisitos:** motivo obligatorio y evidencia cuando corresponda; responsable y fecha; referencia al acta original; historial de versiones sin eliminación; recálculo de las clasificaciones y los avances afectados; registro de las notificaciones y los efectos.
- **Protección competitiva:** si la corrección afecta a fases posteriores con partidos ya disputados, esos encuentros **no se modifican automáticamente**. La rectificación queda bloqueada o señalada con un «impacto competitivo pendiente» que se resuelve con un procedimiento específico y auditado.
- **Implicación técnica:** el trigger `trg_protect_confirmed_match_result` (migración 016) no se relaja. El acta rectificativa vive en tablas propias, solo de inserción y con RLS, y el resultado vigente se resuelve como la última versión aprobada.

### 6.2 Sanciones (F9): spec independiente

| Proceso | Tratamiento |
|---|---|
| Apelación | Solicitud formal de revisión, con estado y resolución administrativa. No cambia la sanción por sí sola. |
| Anulación o modificación | Resolución auditada que fija el nuevo estado de la sanción. |
| Sanción que forma parte del contenido de un acta cerrada | Si corregirla altera lo confirmado, se hace mediante rectificación del acta (F4). |

- **Situación actual:** `player_suspensions.status` ya admite `appealed` y `cancelled` (init `01_schema.sql`), pero ningún flujo llega a esos estados (spec 018). No encontré ningún trigger que proteja `player_suspensions` como protege `matches` la migración 016.
- **Implicación:** F9 apela y resuelve sobre la sanción como entidad propia, con efecto hacia delante. Basta con la enmienda de F4 para el caso en que la sanción derive del contenido confirmado del acta. Conviene que F9 añada la inmutabilidad de las resoluciones: un historial solo de inserción, sin editar la fila anterior.
- **Orden:** enmienda → spec F4 → spec F9, que reutiliza la rectificación para el tercer caso.

### 6.3 Partido en vivo (F1)

| Momento | Público | Privado (responsables autorizados) |
|---|---|---|
| Durante el partido | Estado del encuentro, marcador en tiempo real y reloj del segmento cuando corresponda. | Eventos en borrador: goles, tarjetas, sustituciones y otras incidencias, sin publicación individual. |
| Tras el cierre | Resultado y eventos confirmados; cronología pública autorizada (F13). | Acta consolidada de forma atómica, como hoy. |

- **Implicación:** el borrador privado se emite por salas filtradas por permiso, de modo que **F8 pasa a ser requisito de F1**. Al público solo llegan los eventos de estado y marcador.

### 6.4 Traspasos entre equipos

- Siguen excluidos (§3.2 sin cambios).

### 6.5 Fichas de jugador e históricos públicos (F16)

- Se permiten como **proyección pública adicional, limitada y autorizada**, manteniendo la publicación mínima de §2.5: sin documento, fecha de nacimiento ni edad, y con foto solo bajo las reglas vigentes.
- **Encaje:** a primera vista no exige enmendar §2.5, pero sí una spec que amplíe la matriz de la spec 020 (RF-013–RF-018), con su lista cerrada de campos. Falta definir qué significa «autorizada»: si es una opción de la organización, del torneo o del jugador, o un consentimiento.

### 6.6 Orden revisado

1. Enmienda de §2.3 (PR propio, versión 2.0.0).
2. Spec F4: acta rectificativa.
3. Spec F9: apelaciones y resoluciones de sanciones.
4. F8 → F1 → F13 (tiempo real con borrador privado).
5. F16, con su spec de matriz pública.

## 7. Límites de este informe

Es una revisión documental y de código de solo lectura: no ejecuté pruebas ni la aplicación. Las estimaciones son orientativas. La existencia o ausencia de funciones se comprobó con búsquedas en el código (por ejemplo, no hay flujo de recuperación de contraseña y `core/email.py` ya existe). No es una validación de diseño: cada propuesta requiere su spec SDD (`specs/NNN-*`) conforme a la constitución.
