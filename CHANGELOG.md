# Changelog

Todas las versiones y cambios notables del proyecto Bracket Craft.

El formato sigue [Keep a Changelog](https://keepachangelog.com/es-ES/1.1.0/) y este proyecto adhiere a [Semantic Versioning](https://semver.org/lang/es/).

## [Unreleased]

### Añadido
- **Spec 020 — Consulta pública: navegación y acceso.** Navegación por fases y grupos en portada y detalle; un torneo no visible responde el mismo `404` indistinguible; lista cerrada de campos públicos verificada automáticamente; sin escrituras, cookies ni dependencia de sesión. Matriz de acceso público documentada en `README.md`.
- **Spec 021 — Formaciones gráficas.** `segment_number` (entero, nullable) aditivo en `PublicTeamLineupResponse` para etiquetar la formación con su segmento.
- **Spec 022 — Estadísticas públicas de jugadores y equipos y porterías imbatidas.**
  - Dos lecturas públicas nuevas: `GET /tournaments/public/{id}/player-stats` y `GET /tournaments/public/{id}/team-stats`, sin sesión, con filtros por fase/grupo y paginación (tope 500).
  - Columnas de jugador (nombre, equipo, goles, amarillas, rojas, porterías imbatidas) y de equipo (escudo, GF, GC, porterías imbatidas, fair play).
  - Definición única de portería imbatida: equipo = partido disputado con cero goles recibidos (prórroga incluida, tanda excluida; walkover y resolución administrativa no cuentan); portero = identificable por `GK` en una formación táctica **publicada**, titular del primer segmento o entrante acreditado por sustitución, con al menos 60 minutos y sin goles recibidos; nunca se infiere un portero.
  - Foto solo con inscripción vigente + consentimiento + foto cargada; un jugador retirado lógicamente nunca publica foto (iniciales); iniciales de reserva si la imagen falla.
  - Ámbito por defecto: torneo completo, con filtro por fase explícito y reversible.
  - Columna de posición (`rank`) en ambas tablas: las filas empatadas en todos los criterios visibles comparten posición (patrón 1, 2, 2, 4); estable al paginar.
  - `response_model` declarado en los dos endpoints; lista cerrada de campos públicos veraz.
  - Definiciones visibles en español e inglés (goles, goles a favor, goles en contra, fair play, portería imbatida, exclusiones).
  - Aislamiento entre organizaciones con datos reales.
- **Migraciones 028–031** (aditivas, sin rollback, *forward-fix*): `segment_number` en la vista de alineaciones; `organization_id` en `v_public_tournaments`; vistas de eventos/segmentos/plantillas; proyección interna con todas las formaciones publicadas.
- **Auditoría de dependencias:** override de `serialize-javascript >=7.1.3` y `node-forge >=1.4.1`; solo queda un hallazgo bajo (`deepmerge`).

### Cambiado
- La publicación de nombres de jugadores que participaron en partidos confirmados aunque no figuren en una alineación publicada es un cambio no aditivo declarado (RF-033), sin publicar plantilla inscrita, asistencias, sanciones ni suspensiones.
- `engine_version` sigue en **2026.1**; el contrato interno de reglas no cambia. Todos los cambios de respuesta son aditivos salvo RF-033.

### Notas de despliegue
- Aplicar las migraciones en orden: **026 → 027 → 028 → 029 → 030 → 031** antes de la imagen nueva.
- Sin *backfill* ni rollback; cualquier defecto se corrige con una migración nueva (*forward-fix*).
