"""Pruebas del filtro determinista de la auditoría del frontend (spec 003).

Carga ``infra/scripts/audit_frontend.py`` con ``importlib`` como las pruebas de
los otros scripts de infraestructura. Todas las entradas son fixtures JSON en
memoria o temporales: no se ejecuta pnpm, no se usa red ni base de datos.
"""

from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT_PATH = REPO_ROOT / "infra" / "scripts" / "audit_frontend.py"

MISSING = object()

KNOWN_SEVERITIES = ("info", "low", "moderate", "high", "critical")
COUNTED_SEVERITIES = ("low", "moderate", "high", "critical")


def _load_module() -> Any:
    spec = importlib.util.spec_from_file_location("audit_frontend", SCRIPT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("audit_frontend", module)
    spec.loader.exec_module(module)
    return module


audit = _load_module()


def _advisory(
    severity: str = "high",
    *,
    ghsa: str = "GHSA-aaaa-bbbb-cccc",
    module_name: str = "paquete",
    vulnerable: str = "<1.0.0",
    patched: Any = ">=1.0.1",
    unpublished: Any = MISSING,
    **extra: Any,
) -> dict[str, Any]:
    advisory: dict[str, Any] = {
        "github_advisory_id": ghsa,
        "module_name": module_name,
        "severity": severity,
        "vulnerable_versions": vulnerable,
    }
    if patched is not MISSING:
        advisory["patched_versions"] = patched
    if unpublished is not MISSING:
        advisory["patched_versions_unpublished"] = unpublished
    advisory.update(extra)
    return advisory


def _metadata_for(
    advisories: dict[str, Any],
    *,
    info: int = 0,
    dependencies: Any = MISSING,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    counts = {severity: 0 for severity in COUNTED_SEVERITIES}
    for advisory in advisories.values():
        if not isinstance(advisory, dict):
            continue
        severity = advisory.get("severity")
        if severity in counts:
            counts[severity] += 1
    vulnerabilities: dict[str, Any] = {**counts, "info": info}
    if overrides:
        vulnerabilities.update(overrides)
    metadata: dict[str, Any] = {"vulnerabilities": vulnerabilities}
    if dependencies is not MISSING:
        metadata["dependencies"] = dependencies
    return metadata


def _report(
    advisories: dict[str, Any],
    *,
    metadata: Any = MISSING,
    info: int = 0,
    dependencies: Any = MISSING,
    overrides: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if metadata is MISSING:
        metadata = _metadata_for(
            advisories,
            info=info,
            dependencies=dependencies,
            overrides=overrides,
        )
    return {"advisories": advisories, "metadata": metadata}


# ---------------------------------------------------------------------------
# Funciones puras
# ---------------------------------------------------------------------------


def test_parse_report_accepts_a_json_object():
    report = audit.parse_report('{"advisories": {}, "metadata": {}}')
    assert isinstance(report, dict)
    assert report["advisories"] == {}


@pytest.mark.parametrize("raw", ["", "{", "null", "[]", '"texto"', "0"])
def test_parse_report_rejects_invalid_json_or_non_object_roots(raw):
    with pytest.raises(ValueError):
        audit.parse_report(raw)


@pytest.mark.parametrize(
    "advisory",
    [
        _advisory("high", patched=MISSING),
        _advisory("high", patched=None),
        _advisory("high", patched=""),
        _advisory("high", patched=">=2.0.0", unpublished=True),
    ],
)
def test_published_fix_false_for_the_four_forms_without_correction(advisory):
    assert audit.published_fix(advisory) is False


@pytest.mark.parametrize(
    "advisory",
    [
        _advisory("high", patched=">=1.0.1"),
        _advisory("high", patched=">=2.0.0", unpublished=False),
    ],
)
def test_published_fix_true_when_a_version_is_published(advisory):
    assert audit.published_fix(advisory) is True


def test_is_actionable_requires_high_and_a_published_fix():
    assert audit.is_actionable(_advisory("critical", patched=">=1.0.1")) is True
    assert audit.is_actionable(_advisory("high", patched=">=1.0.1")) is True
    assert audit.is_actionable(_advisory("high", patched=None)) is False
    assert audit.is_actionable(_advisory("moderate", patched=">=1.0.1")) is False
    assert audit.is_actionable(_advisory("low", patched=">=1.0.1")) is False


def test_count_by_severity_counts_every_known_severity():
    advisories = {
        "1": _advisory("critical"),
        "2": _advisory("high"),
        "3": _advisory("high"),
        "4": _advisory("moderate"),
        "5": _advisory("low"),
        "6": _advisory("info"),
    }
    assert audit.count_by_severity(advisories) == {
        "info": 1,
        "low": 1,
        "moderate": 1,
        "high": 2,
        "critical": 1,
    }


# ---------------------------------------------------------------------------
# Juicio: accionables, visibles e informativos
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("severity", "patched"),
    [("critical", ">=2.0.0"), ("high", ">=4.0.1")],
)
def test_critical_and_high_actionables_fail_and_are_listed(severity, patched):
    advisories = {"1": _advisory(severity, patched=patched)}

    decision = audit.decide(_report(advisories), 1)

    assert decision.exit_code == 1
    assert len(decision.actionables) == 1
    text = audit.render_decision(decision)
    assert "GHSA-aaaa-bbbb-cccc" in text
    assert "paquete" in text
    assert severity in text
    assert patched in text


@pytest.mark.parametrize(
    "advisory",
    [
        _advisory("high", patched=MISSING),
        _advisory("high", patched=None),
        _advisory("high", patched=""),
        _advisory("high", patched=">=2.0.0", unpublished=True),
    ],
)
def test_high_without_published_fix_does_not_block_and_stays_visible(advisory):
    advisories = {"1": advisory}

    decision = audit.decide(_report(advisories), 1)

    assert decision.exit_code == 0
    assert decision.actionables == ()
    assert len(decision.visible) == 1
    text = audit.render_decision(decision)
    assert "GHSA-aaaa-bbbb-cccc" in text
    assert "paquete" in text
    assert "sin corrección" in text


@pytest.mark.parametrize("severity", ["moderate", "low"])
def test_moderate_and_low_are_visible_and_do_not_block(severity):
    advisories = {"1": _advisory(severity, patched=">=1.0.1")}

    decision = audit.decide(_report(advisories), 1)

    assert decision.exit_code == 0
    assert decision.actionables == ()
    assert len(decision.visible) == 1
    text = audit.render_decision(decision)
    assert "GHSA-aaaa-bbbb-cccc" in text
    assert "paquete" in text
    assert severity in text


def test_info_only_in_metadata_is_counted_and_not_listed():
    report = _report({}, info=2)

    decision = audit.decide(report, 1)

    assert decision.exit_code == 0
    assert decision.info_count == 2
    assert decision.visible == ()
    text = audit.render_decision(decision)
    assert "2" in text
    assert "GHSA" not in text


def test_info_in_advisories_is_accepted_but_not_listed():
    report = _report({"1": _advisory("info", patched=">=1.0.1")})

    decision = audit.decide(report, 1)

    assert decision.exit_code == 0
    assert decision.visible == ()
    assert "GHSA" not in audit.render_decision(decision)


def test_info_is_also_counted_when_an_actionable_fails_the_run():
    advisories = {"1": _advisory("high", patched=">=2.0.0")}
    report = _report(advisories, info=3)

    decision = audit.decide(report, 1)

    assert decision.exit_code == 1
    assert decision.info_count == 3
    assert "3" in audit.render_decision(decision)


def test_empty_advisories_is_no_findings():
    decision = audit.decide(_report({}), 1)

    assert decision.exit_code == 0
    assert decision.actionables == ()
    assert decision.visible == ()
    assert decision.info_count == 0


# ---------------------------------------------------------------------------
# Fallo cerrado: esquema, coherencia y estado de pnpm
# ---------------------------------------------------------------------------


def test_missing_advisories_fails_closed_even_with_zero_metadata():
    report = {
        "metadata": {"vulnerabilities": {**{s: 0 for s in COUNTED_SEVERITIES}, "info": 0}}
    }

    decision = audit.decide(report, 0)

    assert decision.exit_code == 2
    assert decision.actionables == ()


@pytest.mark.parametrize(
    "metadata",
    [
        MISSING,
        None,
        [],
        "texto",
    ],
)
def test_metadata_must_be_present_and_an_object(metadata):
    report = {"advisories": {}}
    if metadata is not MISSING:
        report["metadata"] = metadata

    assert audit.decide(report, 0).exit_code == 2


@pytest.mark.parametrize(
    "report",
    [
        {"advisories": None, "metadata": {"vulnerabilities": {}}},
        {"advisories": [], "metadata": {"vulnerabilities": {}}},
        {"advisories": "texto", "metadata": {"vulnerabilities": {}}},
        _report({"1": "no es un objeto"}),
        _report({"1": _advisory("severe")}),
        _report({"1": _advisory("high", patched=123)}),
        _report({"1": _advisory("high", patched=[])}),
        _report({}, metadata={"dependencies": 1}),
        _report({}, metadata={"vulnerabilities": []}),
        _report(
            {},
            metadata={"vulnerabilities": {"high": "1"}},
        ),
        _report({}, metadata={"vulnerabilities": {}, "dependencies": "0"}),
    ],
)
def test_invalid_schema_fails_closed(report):
    decision = audit.decide(report, 0)

    assert decision.exit_code == 2
    assert decision.errors


def test_advisories_metadata_mismatch_fails_closed():
    advisories = {"1": _advisory("high", patched=">=2.0.0")}
    report = {
        "advisories": advisories,
        "metadata": _metadata_for({}),
    }

    decision = audit.decide(report, 1)

    assert decision.exit_code == 2
    assert any("desajuste" in error for error in decision.errors)


def test_hidden_entries_filtered_by_audit_level_are_detected():
    # pnpm --audit-level high recorta advisories pero no metadata.
    advisories = {"1": _advisory("critical", patched=">=2.0.0")}
    metadata = _metadata_for(advisories, overrides={"moderate": 1})
    report = {"advisories": advisories, "metadata": metadata}

    decision = audit.decide(report, 1)

    assert decision.exit_code == 2
    assert any("desajuste" in error for error in decision.errors)


def test_zero_dependencies_with_advisories_is_invalid():
    advisories = {"1": _advisory("high", patched=None)}

    decision = audit.decide(_report(advisories, dependencies=0), 1)

    assert decision.exit_code == 2
    assert any("dependencies" in error for error in decision.errors)


def test_zero_dependencies_without_advisories_is_valid():
    decision = audit.decide(_report({}, dependencies=0), 1)

    assert decision.exit_code == 0


@pytest.mark.parametrize("status", [None, -1, 2, 3, "0", "1", True, False])
def test_invalid_pnpm_status_fails_closed(status):
    decision = audit.decide(_report({}), status)

    assert decision.exit_code == 2


def test_pnpm_status_1_without_actionables_is_valid():
    assert audit.decide(_report({}), 1).exit_code == 0


def test_pnpm_status_0_with_actionables_still_fails():
    advisories = {"1": _advisory("critical", patched=">=2.0.0")}

    assert audit.decide(_report(advisories), 0).exit_code == 1


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _run_cli(
    args: list[str],
    *,
    cwd: Path,
    stdin: str | None = None,
) -> subprocess.CompletedProcess[str]:
    environment = dict(os.environ)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    return subprocess.run(
        [sys.executable, str(SCRIPT_PATH), *args],
        input=stdin,
        text=True,
        capture_output=True,
        cwd=cwd,
        env=environment,
        check=False,
    )


def test_cli_reads_input_file_and_does_not_write_files(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    audit_path = tmp_path / "audit.json"
    audit_path.write_text(
        json.dumps(_report({"1": _advisory("critical", patched=">=2.0.0")})),
        encoding="utf-8",
    )

    result = _run_cli(
        ["--input", str(audit_path), "--pnpm-status", "1"],
        cwd=work,
    )

    assert result.returncode == 1
    assert "GHSA-aaaa-bbbb-cccc" in result.stdout
    assert list(work.iterdir()) == []


def test_cli_reads_stdin_and_does_not_write_files(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    payload = json.dumps(_report({"1": _advisory("high", patched=None)}))

    result = _run_cli(
        ["--input", "-", "--pnpm-status", "1"],
        cwd=work,
        stdin=payload,
    )

    assert result.returncode == 0
    assert "GHSA-aaaa-bbbb-cccc" in result.stdout
    assert "sin corrección" in result.stdout
    assert list(work.iterdir()) == []


def test_cli_invalid_json_exits_2(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    audit_path = tmp_path / "audit.json"
    audit_path.write_text("{", encoding="utf-8")

    result = _run_cli(
        ["--input", str(audit_path), "--pnpm-status", "1"],
        cwd=work,
    )

    assert result.returncode == 2
    assert list(work.iterdir()) == []


def test_cli_missing_file_exits_2(tmp_path):
    work = tmp_path / "work"
    work.mkdir()

    result = _run_cli(
        ["--input", str(tmp_path / "no-existe.json"), "--pnpm-status", "1"],
        cwd=work,
    )

    assert result.returncode == 2
    assert list(work.iterdir()) == []


def test_cli_requires_pnpm_status(tmp_path):
    work = tmp_path / "work"
    work.mkdir()

    result = _run_cli(["--input", "-"], cwd=work, stdin="{}")

    assert result.returncode == 2


def test_cli_rejects_a_non_integer_pnpm_status(tmp_path):
    work = tmp_path / "work"
    work.mkdir()

    result = _run_cli(
        ["--input", "-", "--pnpm-status", "abc"],
        cwd=work,
        stdin="{}",
    )

    assert result.returncode == 2


def test_cli_missing_advisories_exits_2(tmp_path):
    work = tmp_path / "work"
    work.mkdir()
    payload = json.dumps(
        {"metadata": {"vulnerabilities": {**{s: 0 for s in COUNTED_SEVERITIES}, "info": 0}}}
    )

    result = _run_cli(
        ["--input", "-", "--pnpm-status", "0"],
        cwd=work,
        stdin=payload,
    )

    assert result.returncode == 2
    assert list(work.iterdir()) == []
