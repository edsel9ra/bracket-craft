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

## Límite de la API pública (spec 051)

Las 9 lecturas de la API pública (`docs/api-publica.md`) y su documento
`/api/v1/public/openapi.json` se limitan por IP en el proxy, no en la API (DA-4).
El SSR del sitio no pasa por aquí: Nuxt llama a la API por la red interna con
`NUXT_API_INTERNAL_BASE` (por ejemplo `http://api:8000/api/v1`), así que el límite
no agrupa a todos los visitantes bajo la IP del frontend. Las peticiones que el
navegador de un visitante hace desde el sitio sí pasan por el proxy y cuentan para
su propia IP, igual que las de un tercero; las cifras dejan margen para ese uso.

Ejemplo para Nginx. `limit_req_zone` va en el bloque `http`; las dos `location`, en
el `server` que ya enruta `/api/v1` y `/socket.io/` hacia `api:8000`:

```nginx
limit_req_zone $binary_remote_addr zone=public_api:10m rate=120r/m;

# Los mismos orígenes que CORS_ALLOWED_ORIGINS conservan su CORS con credenciales.
map $http_origin $public_api_429_origin {
    default "*";
    "https://torneos.example.com" $http_origin;
}
map $http_origin $public_api_429_credentials {
    default "";
    "https://torneos.example.com" "true";
}

server {
    # … location /api/v1/ y /socket.io/ existentes …

    location ~ "^/api/v1/(public/openapi\.json|tournaments/public(/(?!.*share-image).*)?)$" {
        limit_req zone=public_api burst=60 nodelay;
        limit_req_status 429;
        error_page 429 = @public_api_429;
        proxy_pass http://api:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    location @public_api_429 {
        default_type application/json;
        add_header Retry-After 10 always;
        add_header Access-Control-Allow-Origin $public_api_429_origin always;
        add_header Access-Control-Allow-Credentials $public_api_429_credentials always;
        add_header Access-Control-Expose-Headers Retry-After always;
        add_header Vary Origin always;
        return 429 '{"detail":"Demasiadas peticiones"}';
    }
}
```

- **Cifras:** 120 peticiones por minuto por IP, con ráfagas de 60. La guía de la API
  publica estas cifras; si se cambian aquí, hay que cambiarlas también allí.
- **Todo `/api/v1/tournaments/public…` salvo las imágenes:** la expresión cubre las 9
  lecturas y el documento con cualquier forma del UUID que acepte la API (mayúsculas,
  sin guiones, entre llaves o `urn:uuid:`), para que no se pueda saltar el límite, y
  también rutas inexistentes bajo ese prefijo. Las imágenes `…/share-image`, el
  Workspace y la autenticación siguen por la `location /api/v1/` existente, con su
  comportamiento actual.
- **Precedencia:** Nginx evalúa las `location ~` antes de usar un prefijo normal. No
  declares la `location` de `/api/v1/` con `^~`, porque entonces esta expresión no se
  evalúa nunca.
- **`Retry-After` y CORS en el 429:** la respuesta del límite lleva `Retry-After`,
  expuesto con `Access-Control-Expose-Headers`, y `Access-Control-Allow-Origin: *`
  para que un navegador de otro origen pueda leer el error y la espera. Los orígenes
  de `CORS_ALLOWED_ORIGINS` (el sitio, si llama a la API desde otro origen con
  credenciales) se repiten en los dos `map` y reciben su propio origen con
  `Access-Control-Allow-Credentials: true`, como en el resto de respuestas.
- **IP del cliente:** `X-Forwarded-For` se sobrescribe con `$remote_addr`; mantiene el
  saneado de la sección anterior y el valor de `FORWARDED_ALLOW_IPS`.

`backend/tests/test_public_api_docs.py` comprueba que la expresión acepta las 9 rutas
y el documento, también con otras formas del UUID, y rechaza las imágenes y el
Workspace.
