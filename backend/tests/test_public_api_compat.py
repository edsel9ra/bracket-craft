"""Compatibilidad del contrato público v1 (spec 051, RF-006, RF-007)."""

import copy
import json
from pathlib import Path

import pytest

from app.main import api
from app.modules.public_api.compat import incompatibilities
from app.modules.public_api.openapi import build_public_openapi
from scripts import public_api_reference

REFERENCE = Path(__file__).resolve().parents[2] / "docs" / "api-publica" / "openapi-v1.json"
PATH = "/api/v1/tournaments/public/{tournament_id}/standings"


def _base():
    return {
        "openapi": "3.1.0",
        "info": {"title": "t", "version": "v1"},
        "paths": {
            PATH: {
                "get": {
                    "parameters": [
                        {"name": "tournament_id", "in": "path", "required": True,
                         "schema": {"type": "string", "format": "uuid"}},
                        {"name": "limit", "in": "query", "required": False,
                         "schema": {"type": "integer", "maximum": 500, "minimum": 1, "default": 200}},
                        {"name": "lang", "in": "query", "required": False,
                         "schema": {"enum": ["es", "en"], "type": "string"}},
                    ],
                    "responses": {
                        "200": {"content": {"application/json": {"schema": {
                            "type": "array", "items": {"$ref": "#/components/schemas/Row"}}}}},
                        "404": {"content": {"application/json": {"schema": {
                            "$ref": "#/components/schemas/PublicError"}}}},
                    },
                }
            }
        },
        "components": {"schemas": {
            "Row": {
                "title": "Row",
                "type": "object",
                "properties": {
                    "team_id": {"type": "string", "format": "uuid"},
                    "points": {"type": "integer"},
                    "crest_url": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                    "status": {"type": "string", "enum": ["live", "finished"]},
                    "match": {"oneOf": [
                        {"$ref": "#/components/schemas/A"}, {"$ref": "#/components/schemas/B"}]},
                },
                "required": ["team_id", "points", "status"],
            },
            "A": {"title": "A", "type": "object", "properties": {"kind": {"const": "a"}}, "required": ["kind"]},
            "B": {"title": "B", "type": "object", "properties": {"kind": {"const": "b"}}, "required": ["kind"]},
            "PublicError": {"title": "PublicError", "type": "object",
                            "properties": {"detail": {"type": "string"}}, "required": ["detail"]},
        }},
    }


def _op(doc):
    return doc["paths"][PATH]["get"]


def _param(doc, name):
    return next(p for p in _op(doc)["parameters"] if p["name"] == name)


def _row(doc):
    return doc["components"]["schemas"]["Row"]


def test_identical_documents_are_compatible():
    assert incompatibilities(_base(), _base()) == []


def _compatible_add_path(doc):
    doc["paths"]["/api/v1/tournaments/public/new"] = copy.deepcopy(doc["paths"][PATH])


def _compatible_new_optional_param(doc):
    _op(doc)["parameters"].append(
        {"name": "group_id", "in": "query", "required": False, "schema": {"type": "string"}})


def _compatible_new_param_enum_value(doc):
    _param(doc, "lang")["schema"]["enum"].append("fr")


def _compatible_new_optional_property(doc):
    _row(doc)["properties"]["extra"] = {"type": "integer"}


def _compatible_wider_param_limit(doc):
    _param(doc, "limit")["schema"]["maximum"] = 1000


def _compatible_response_no_longer_nullable(doc):
    _row(doc)["properties"]["crest_url"] = {"type": "string"}


@pytest.mark.parametrize("change", [
    _compatible_add_path,
    _compatible_new_optional_param,
    _compatible_new_param_enum_value,
    _compatible_new_optional_property,
    _compatible_wider_param_limit,
    _compatible_response_no_longer_nullable,
])
def test_compatible_changes(change):
    current = _base()
    change(current)
    assert incompatibilities(_base(), current) == []


def _remove_path(doc):
    del doc["paths"][PATH]


def _remove_param(doc):
    _op(doc)["parameters"] = [p for p in _op(doc)["parameters"] if p["name"] != "lang"]


def _param_becomes_required(doc):
    _param(doc, "limit")["required"] = True


def _new_required_param(doc):
    _op(doc)["parameters"].append(
        {"name": "season", "in": "query", "required": True, "schema": {"type": "string"}})


def _param_type_change(doc):
    _param(doc, "limit")["schema"]["type"] = "string"


def _param_enum_value_removed(doc):
    _param(doc, "lang")["schema"]["enum"] = ["es"]


def _param_limit_narrowed(doc):
    _param(doc, "limit")["schema"]["maximum"] = 100


def _param_default_changed(doc):
    _param(doc, "limit")["schema"]["default"] = 100


def _param_default_removed(doc):
    del _param(doc, "limit")["schema"]["default"]


def _response_code_removed(doc):
    del _op(doc)["responses"]["404"]


def _property_removed(doc):
    del _row(doc)["properties"]["points"]


def _property_no_longer_required(doc):
    _row(doc)["required"].remove("points")


def _property_type_change(doc):
    _row(doc)["properties"]["points"] = {"type": "string"}


def _property_format_change(doc):
    _row(doc)["properties"]["team_id"] = {"type": "string"}


def _property_becomes_nullable(doc):
    _row(doc)["properties"]["points"] = {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def _new_required_property(doc):
    _row(doc)["properties"]["extra"] = {"type": "integer"}
    _row(doc)["required"].append("extra")


def _response_enum_value_added(doc):
    _row(doc)["properties"]["status"]["enum"].append("suspended")


def _new_union_variant(doc):
    doc["components"]["schemas"]["C"] = {
        "title": "C", "type": "object", "properties": {"kind": {"const": "c"}}, "required": ["kind"]}
    _row(doc)["properties"]["match"]["oneOf"].append({"$ref": "#/components/schemas/C"})


def _nested_change_behind_ref(doc):
    doc["components"]["schemas"]["A"]["properties"]["kind"] = {"const": "z"}


def _error_schema_changed(doc):
    del doc["components"]["schemas"]["PublicError"]["properties"]["detail"]


@pytest.mark.parametrize("change", [
    _remove_path,
    _remove_param,
    _param_becomes_required,
    _new_required_param,
    _param_type_change,
    _param_enum_value_removed,
    _param_limit_narrowed,
    _param_default_changed,
    _param_default_removed,
    _response_code_removed,
    _property_removed,
    _property_no_longer_required,
    _property_type_change,
    _property_format_change,
    _property_becomes_nullable,
    _new_required_property,
    _response_enum_value_added,
    _new_union_variant,
    _nested_change_behind_ref,
    _error_schema_changed,
])
def test_incompatible_changes(change):
    current = _base()
    change(current)
    problems = incompatibilities(_base(), current)
    assert problems, change.__name__
    assert all(isinstance(problem, str) and problem for problem in problems)


def test_current_document_matches_committed_reference():
    reference = json.loads(REFERENCE.read_text(encoding="utf-8"))
    current = build_public_openapi(api)
    assert incompatibilities(reference, current) == []
    assert current == reference, (
        "El contrato cambió de forma compatible: ejecuta "
        "`cd backend && python -m scripts.public_api_reference --update`"
    )


def test_script_check_passes_on_committed_reference():
    assert public_api_reference.main(["--check"]) == 0


def test_script_check_fails_when_reference_differs(tmp_path):
    reference = copy.deepcopy(build_public_openapi(api))
    del reference["paths"]["/api/v1/tournaments/public/players/{player_id}"]
    path = tmp_path / "ref.json"
    path.write_text(json.dumps(reference), encoding="utf-8")
    assert public_api_reference.main(["--check", "--reference", str(path)]) == 1


def test_script_update_writes_compatible_change(tmp_path):
    reference = copy.deepcopy(build_public_openapi(api))
    del reference["paths"]["/api/v1/tournaments/public/players/{player_id}"]
    path = tmp_path / "ref.json"
    path.write_text(json.dumps(reference), encoding="utf-8")
    assert public_api_reference.main(["--update", "--reference", str(path)]) == 0
    assert json.loads(path.read_text(encoding="utf-8")) == build_public_openapi(api)
    assert public_api_reference.main(["--check", "--reference", str(path)]) == 0


def test_script_update_refuses_incompatible_change(tmp_path):
    reference = copy.deepcopy(build_public_openapi(api))
    reference["paths"]["/api/v1/tournaments/public/removed"] = copy.deepcopy(
        reference["paths"]["/api/v1/tournaments/public"])
    path = tmp_path / "ref.json"
    original = json.dumps(reference)
    path.write_text(original, encoding="utf-8")
    assert public_api_reference.main(["--update", "--reference", str(path)]) == 1
    assert path.read_text(encoding="utf-8") == original
