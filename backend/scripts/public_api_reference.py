"""Copia de referencia del contrato público v1 (spec 051, RF-006, RF-007).

``--check`` compara el documento OpenAPI público con la copia guardada en
``docs/api-publica/openapi-v1.json`` y falla ante un cambio incompatible o una
diferencia sin registrar. ``--update`` reescribe la copia, pero se niega si el
cambio es incompatible: un cambio así no cabe en v1.

Uso: ``cd backend && python -m scripts.public_api_reference --check|--update``.
Códigos de salida: ``0`` correcto, ``1`` incompatible o desactualizado.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from app.modules.public_api.compat import incompatibilities

DEFAULT_REFERENCE = Path(__file__).resolve().parents[2] / "docs" / "api-publica" / "openapi-v1.json"


def render(document: dict[str, Any]) -> str:
    return json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def current_document() -> dict[str, Any]:
    from app.main import api
    from app.modules.public_api.openapi import build_public_openapi

    return build_public_openapi(api)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--update", action="store_true")
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    args = parser.parse_args(argv)

    current = current_document()
    if not args.reference.exists():
        if args.check:
            print(f"No existe la copia de referencia {args.reference}", file=sys.stderr)
            return 1
        args.reference.parent.mkdir(parents=True, exist_ok=True)
        args.reference.write_text(render(current), encoding="utf-8")
        return 0

    reference = json.loads(args.reference.read_text(encoding="utf-8"))
    problems = incompatibilities(reference, current)
    if problems:
        print("Cambio incompatible con el contrato público v1:", file=sys.stderr)
        for problem in problems:
            print(f"- {problem}", file=sys.stderr)
        return 1
    if current == reference:
        return 0
    if args.check:
        print(
            "El contrato cambió de forma compatible: ejecuta "
            "`python -m scripts.public_api_reference --update` y anota el cambio "
            "en el historial de docs/api-publica.md y docs/api-publica.en.md.",
            file=sys.stderr,
        )
        return 1
    args.reference.write_text(render(current), encoding="utf-8")
    print("Copia de referencia actualizada; anota el cambio en el historial de la guía.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
