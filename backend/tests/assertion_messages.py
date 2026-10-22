"""Mensajes de fallo de la suite sin volcar el cuerpo de la respuesta (RF-004).

La suite de invitaciones cerraba sus aserciones con ``assert ..., response.text``:
al fallar imprimía el cuerpo completo y con él ``invite_url``, que contiene el
token de la invitación. Este módulo es el único punto autorizado a mirar el
cuerpo y solo extrae una **lista blanca de una clave**: ``code``, y únicamente
cuando es una cadena no vacía.

El mensaje identifica la prueba (``label``) y el estado HTTP; el enlace, el token
y cualquier dato del cuerpo quedan fuera. El método y la ruta llegan dentro de la
respuesta, pero no se imprimen: la ruta de aceptación y de previsualización lleva
el token.
"""

import json

import httpx


def reason_code(payload: object) -> str | None:
    """Devuelve ``payload["code"]`` solo si es una cadena no vacía.

    La lista blanca es de una sola clave: cualquier otro dato del cuerpo
    (``detail``, ``invite_url``, tokens) no se lee.
    """

    if not isinstance(payload, dict):
        return None
    code = payload.get("code")
    if not isinstance(code, str) or not code.strip():
        return None
    return code


def describe_status(label: str, status: int, code: object = None) -> str:
    """Compone ``<label>: HTTP <status>[ (code=<code>)]`` sin cuerpo ni enlace."""

    message = f"{label}: HTTP {status}"
    if isinstance(code, str) and code.strip():
        message = f"{message} (code={code})"
    return message


def describe_response(label: str, response: httpx.Response) -> str:
    """Describe una respuesta con su estado y motivo, nunca con su cuerpo."""

    return describe_status(label, response.status_code, reason_code(_json_body(response)))


def _json_body(response: httpx.Response) -> object:
    try:
        return json.loads(response.content)
    except (ValueError, TypeError, httpx.ResponseNotRead):
        return None
