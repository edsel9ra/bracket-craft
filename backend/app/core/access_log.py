"""Línea de acceso saneada (RNF-5, D-11).

Uvicorn arranca con ``--no-access-log``: su log por defecto escribe la petición
completa, incluida ``?code=…&state=…``. En su lugar, el middleware de
``app/main.py`` emite una línea por petición con **solo** método, ruta sin
consulta ni fragmento y estado; nunca cabeceras, cookies, cuerpo, ``Referer`` ni
parámetros.

El formateador es puro: no lee reloj, entorno ni red, y no puede filtrar datos
que no recibe.
"""

from __future__ import annotations


def access_log_record(method: str, path: str, status: int) -> str:
    """Devuelve la línea estable ``access method=… path=… status=…``.

    ``path`` se recorta en la primera ``?`` y en el primer ``#``: la consulta y
    el fragmento no se registran nunca. El método se normaliza a mayúsculas y el
    estado se conserva tal cual para que la línea sea grep-able.
    """

    clean_path = path.split("?", 1)[0].split("#", 1)[0]
    return f"access method={method.upper()} path={clean_path} status={status}"
