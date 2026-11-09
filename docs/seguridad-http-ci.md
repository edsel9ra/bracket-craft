# Endurecimiento HTTP y cadena de suministro

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
