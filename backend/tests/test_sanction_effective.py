from dataclasses import replace

import pytest

from app.modules.sanction_appeals.effective import EffectiveResolution, project_duration


@pytest.mark.parametrize("status", ["active", "served", "appealed", "cancelled"])
def test_duration_original_without_resolution(status):
    result = project_duration(3, 1, status=status)
    assert result.original_duration == result.effective_duration == 3
    assert result.served_count == 1
    assert result.status == status
    assert result.remaining == (0 if status == "cancelled" else 2)
    assert not result.pending_effect
    assert result.blocking == (status == "active")


@pytest.mark.parametrize("served", [0, 1, 2, 4])
def test_duration_reduction_preserves_serves_and_no_credit(served):
    result = project_duration(3, served, resolution=EffectiveResolution("reduce", 2, applied=True))
    assert result.original_duration == 3
    assert result.effective_duration == 2
    assert result.served_count == served
    assert result.remaining == max(0, 2 - served)
    assert result.status == ("active" if served < 2 else "served")


def test_duration_pending_annulment_declaration_and_legacy():
    pending = EffectiveResolution("reduce", 1)
    assert project_duration(3, 0, resolution=pending).effective_duration == 3
    assert project_duration(3, 0, resolution=pending).pending_effect
    excluded = replace(pending, excluded=True)
    assert not project_duration(3, 0, resolution=excluded).pending_effect
    annulled = project_duration(3, 2, resolution=EffectiveResolution("annul", applied=True))
    assert (annulled.effective_duration, annulled.remaining, annulled.status) == (0, 0, "cancelled")
    declared = project_duration(3, 3, status="served", resolution=EffectiveResolution("reduce", 1, declarative=True))
    assert (declared.effective_duration, declared.served_count, declared.remaining, declared.status) == (1, 3, 0, "served")
    assert not declared.pending_effect
    assert project_duration(3, 0, status="appealed").status == "appealed"
    assert not project_duration(3, 0, status="appealed").blocking
    zero = project_duration(3, 0, resolution=EffectiveResolution("reduce", 0, applied=True))
    assert (zero.remaining, zero.status) == (0, "served")


@pytest.mark.parametrize("original,served,resolution", [
    (0, 0, None), (True, 0, None), (3, -1, None), (3, False, None),
    (3, 0, EffectiveResolution("reduce", 3)), (3, 0, EffectiveResolution("reduce", -1)),
    (3, 0, EffectiveResolution("reduce")), (3, 0, EffectiveResolution("annul", 1)),
    (3, 0, EffectiveResolution("increase", 4)),
])
def test_duration_invalid_facts_rejected(original, served, resolution):
    with pytest.raises(ValueError):
        project_duration(original, served, resolution=resolution)
