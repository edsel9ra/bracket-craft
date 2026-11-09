# Proxy y tiempo real en producción

## Corrección posterior del PR #25

El validador solo admite IP válidas o CIDR en modo estricto, como Uvicorn:
`192.0.2.10/24` se rechaza por tener bits de host; usar `192.0.2.0/24`.
Un CIDR inválido queda como literal en Uvicorn y no confía en la IP del proxy;
también se rechazan nombres y otros literales que no sean IP/CIDR.

`api.command` usa lista exec: por ejemplo, `FORWARDED_ALLOW_IPS='192.0.2.10, 198.51.100.7'`
se conserva como un solo argumento de Uvicorn, sin dividir la segunda IP por el espacio.
El validador rechaza `*` y cualquier red con prefijo cero, tanto `0.0.0.0/0` como
`::/0`, equivalentes con bits de host o máscara IPv4 cero. No son proxies de confianza acotados.

El gate Playwright ya interceptaba WebSocket, pero sus contadores y la búsqueda de
intentos previos solo contemplaban HTTP. Ahora contabiliza y espera ambos caminos:
en `abort` cierra el socket sin conectar al servidor; en `hold` no conecta ni cierra
hasta `releaseHeld`, que hace fallar el intento manual. El desbloqueo permite
conectar al servidor real. El canal queda aislado de la API HTTP y de la sesión;
no se vuelve a habilitar polling ni se rebajan las comprobaciones del escenario.

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
