# Proxy y tiempo real en producción

## Cambio posterior — auditoría H1/H2 (2026-11-09)

El proxy debe enrutar `/api/v1` y `/socket.io/` a `api:8000` y permitir el
upgrade de WebSocket. El cliente usa exclusivamente WebSocket: no necesita
afinidad entre workers ni manager compartido, porque cada proceso relaya el
stream de Redis a sus clientes. No hay fallback a long-polling. El servidor
conserva sus transportes para no romper otros clientes ni desarrollo.

Antes de renderizar o desplegar el overlay de producción, asigna
`FORWARDED_ALLOW_IPS` a la IP o lista de IP/CIDR del proxy tal como los ve la
API, separados por comas. No hay default; el valor vacío de `.env.example`
no sirve para producción. No uses `*` ni redes que incluyan clientes no
confiables. Si cambia la IP del proxy, actualiza la lista y recrea la API.

Uvicorn usa `--proxy-headers --forwarded-allow-ips=…`. El proxy debe sanear
`X-Forwarded-For` y `X-Forwarded-Proto`; solo se confía en cabeceras recibidas
desde los pares configurados. Así `request.client.host`, usado por el límite
de autenticación, representa al cliente y no agrupa a todos bajo el proxy.
La confianza no sustituye al aislamiento de red ni al límite por cuenta.

Verifica el merge antes de desplegar:

```sh
docker compose -f docker-compose.yml -f docker-compose.production.yml config -q
docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json \
  | python3 infra/scripts/assert_production_compose.py -
docker compose -f docker-compose.yml -f docker-compose.production.yml config --format json \
  | python3 infra/scripts/check_env_contract.py -
```

Desarrollo no consume esta variable y conserva su comando Uvicorn.
