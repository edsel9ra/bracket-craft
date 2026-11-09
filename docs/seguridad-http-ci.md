# Endurecimiento HTTP y cadena de suministro

## Cambio posterior H4 — acciones y dependencias (2026-11-09)

Todos los `uses:` de los workflows apuntan a commits SHA completos. El
comentario conserva el tag exacto que resolvía la referencia anterior; no se
actualiza de major ni se cambia Trivy v0.36.0. Los SHA se obtuvieron con
`git ls-remote --tags`, desreferenciando los tags anotados mediante `^{}`:

| Acción | Tag resuelto | Commit |
|---|---|---|
| actions/checkout | v4.4.0 | `11d5960a326750d5838078e36cf38b85af677262` |
| actions/setup-python | v5.6.0 | `a26af69be951a213d495a4c3e4e4022e16d87065` |
| actions/setup-node | v4.4.0 | `49933ea5288caeca8642d1e84afbd3f7d6820020` |
| pnpm/action-setup | v4.3.0 | `b906affcce14559ad1aafd4ab0e942779e9f58b1` |
| actions/upload-artifact | v4.6.2 | `ea165f8d65b6e75b540449e92b4886f43607fa02` |
| aquasecurity/trivy-action | v0.36.0 | `ed142fd0673e97e23eac54620cfb913e5ce36c25` |

La referencia móvil `pnpm/action-setup@v4` resolvía v4.3.0, no v4.4.0:
se conserva el commit realmente usado, no se selecciona otro por ser mayor.
Dependabot abre propuestas semanales para github-actions (`/`), pip
(`/backend`) y npm (`/frontend`), agrupando minor/patch y dejando majors
separados. Nada se fusiona automáticamente ni se suprimen vulnerabilidades.

## Cambio posterior H3 — cabeceras (2026-11-09)

API y SSR envían `X-Content-Type-Options: nosniff`, `X-Frame-Options: DENY`
y `Referrer-Policy: strict-origin-when-cross-origin`. El retorno OAuth conserva
`no-referrer` para no filtrar parámetros del proveedor.

La API usa la lista existente `DEVELOPMENT_ENVS` (`development`, `dev`,
`local`, sin distinguir mayúsculas/espacios). Fuera de ella envía
`Strict-Transport-Security: max-age=31536000; includeSubDomains`. Nuxt activa
HSTS solo al construir en producción (`NODE_ENV=production`). Antes de
desplegar, HTTPS debe funcionar también para los subdominios.

El middleware ASGI exterior añade cabeceras incluso a errores y respuestas
HTTP de Engine.IO, sin tocar cuerpos, WebSocket ni lifespan. No aplica CSP
a Swagger. Nitro aplica a todas las rutas la CSP conservadora
`frame-ancestors 'none'; object-src 'none'; base-uri 'self'`: no bloquea los
scripts inline de Nuxt ni conexiones HTTP/WebSocket. No es una CSP completa
contra XSS; endurecer `script-src` exige un diseño de nonce independiente.
