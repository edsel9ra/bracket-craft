# Mantenimiento de la auditoría

## ESLint gradual

`frontend` usa `@nuxt/eslint` y ESLint flat. `pnpm run lint` prepara Nuxt antes
de cargar `.nuxt/eslint.config.mjs`; CI lo ejecuta después del install congelado.
Se conserva pnpm 12.12.1. No se reescriben las plantillas ni el arnés E2E.

La primera revisión encontró 169 avisos/errores preexistentes. Se desactivan
explícitamente en `eslint.config.mjs` estas reglas, sin desactivar el resto:

- `@typescript-eslint/no-explicit-any`, `no-unused-vars`: tipado y símbolos heredados.
- `@typescript-eslint/no-dynamic-delete`: eliminación deliberada de claves reactivas.
- `@typescript-eslint/no-import-type-side-effects`, `import/no-duplicates`,
  `prefer-const`, `no-useless-assignment`: normalización de imports/declaraciones.
- `no-control-regex`: expresiones que rechazan caracteres de control deliberadamente.
- `vue/html-self-closing`, `vue/attributes-order`, `vue/attribute-hyphenation`: estilo.
- `vue/require-toggle-inside-transition`: transiciones con contenido dinámico por clave.

Las reglas pueden reactivarse en cambios acotados; no se aplica `eslint --fix`
masivo. Se excluyen solo reportes generados, además de los ignores de Nuxt.

## Bandit y secretos

Bandit 1.9.4 se fija en `backend/requirements-dev.txt`, nunca en la imagen productiva.
Comando desde `backend`: `bandit -r app -ll -c pyproject.toml`.
Se revisaron los nueve B608: la interpolación usa exclusivamente columnas binarias
del avance, sufijo de bloqueo constante, precedencia de roles con columna literal
y expresión HMAC constante; los datos de la petición siguen ligados por parámetros.
Cada lugar tiene `nosec B608` y justificación local. B108 se limita al fichero de
latido sin secretos de un contenedor dedicado; no se desactiva la regla globalmente.
Los hallazgos de severidad baja siguen visibles en las métricas, fuera del umbral `-ll`.

Gitleaks 8.30.1 se ejecuta mediante imagen fijada por digest. No se incorpora una
acción nueva ni se cambian los tags de las acciones existentes. CI exporta únicamente
`git archive HEAD` y ejecuta `dir /repo --config /repo/.gitleaks.toml --redact`.
Así no escanea historial, `.git`, `.env`, node_modules ni artefactos no versionados.
La configuración extiende todas las reglas por defecto y solo permite las tres claves
dummy literales públicas de los ejemplos CI (`JWT_SECRET`, `PLAYER_DATA_KEY` e `INVITATION_TOKEN_KEY`).
No permite claves por nombre de variable ni excluye workflows, documentación o tests.
Las contraseñas demo/prueba que no coinciden con reglas no requieren excepciones.
El escaneo histórico de la auditoría anterior queda fuera del alcance de este gate.

## Redis y revalidación

Rate limit y `/health/ready` reutilizan un cliente/pool Redis por proceso, creado
perezosamente. El lifespan lo cierra después de cancelar las tareas. No se cierra
al terminar cada petición, tampoco tras un fallo: el pool puede reconectar.
Se mantienen 429 con Retry-After y 503 si Redis falla; disponibilidad sigue 503
si falla PostgreSQL o Redis. El relay tiene ciclo de reconexión y cliente propios.

Aplicar **032_socket_session_revalidation.sql** antes de desplegar la API nueva.
El ciclo de 30 segundos manda una instantánea de sockets en una sola consulta SQL.
La función `SECURITY INVOKER` itera en PostgreSQL, conservando RLS y contexto
usuario/organización por entrada; restaura el contexto del llamante al terminar.
No usa privilegios de administrador ni convierte las tablas tenant en lecturas globales.
El trabajo dentro de PostgreSQL sigue siendo lineal; se eliminan los viajes secuenciales
API–BD por socket, no el coste de comprobar cada sesión.

Se mantienen visibilidad pública, usuario activo, sesión vigente/no revocada,
pertenencia activa (incluida organización activa) y huella exacta de roles/permisos.
Un fallo de validación desconecta; un error de BD no expulsa por indisponibilidad.
Una entrada malformada no impide validar las demás. Sin sockets no hay consulta.

## Memoria y evidencia

La memoria raíz distingue entregas confirmadas en git de verificaciones históricas.
Los commits 890b280, 0977a26 y e5df755 materializan las specs 025–028; 4eba00b
modifica el arnés E2E y 0977a26 lo adapta de nuevo. Eso no demuestra por sí solo
una ejecución E2E satisfactoria: no se declara verde sin resultado de ejecución.
