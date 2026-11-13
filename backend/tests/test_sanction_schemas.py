from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.modules.sanction_appeals.schemas import (
    AppealRequest, CaseFilters, DecisionRequest, ProposalRequest, WithdrawalRequest,
)


def test_appeal_evidence_optional_and_representation_explicit():
    dto = AppealRequest(suspension_id=uuid4(), represented_player_id=uuid4(), reason=" Review ")
    assert dto.reason == "Review" and dto.evidence_text is None and dto.evidence_links == []


@pytest.mark.parametrize("extra", [{"reason": " "}, {"attachments": []}, {"scope_type": "new"},
    {"represented_player_id": None}, {"represented_team_id": str(uuid4())}, {"suspension_id": "bad"}])
def test_appeal_rejects_invalid_contract(extra):
    with pytest.raises(ValidationError):
        AppealRequest.model_validate({"suspension_id": str(uuid4()), "represented_player_id": str(uuid4()),
            "reason": "Review", **extra})


@pytest.mark.parametrize("action,duration,valid", [("annul", None, True), ("reduce", 0, True),
    ("reduce", None, False), ("reduce", -1, False), ("annul", 1, False), ("increase", 3, False)])
def test_proposal_measure(action, duration, valid):
    body = {"suspension_id": uuid4(), "reason": "Review", "proposed_action": action, "proposed_duration": duration}
    if valid:
        assert ProposalRequest(**body).proposed_action == action
    else:
        with pytest.raises(ValidationError):
            ProposalRequest(**body)


@pytest.mark.parametrize("model,body", [(WithdrawalRequest, {"reason": ""}),
    (DecisionRequest, {"reason": "Review", "decision": "reduce", "expected_base_duration": 3}),
    (DecisionRequest, {"reason": "Review", "decision": "reduce", "expected_base_duration": 3, "after_duration": 3}),
    (CaseFilters, {"limit": 101}), (CaseFilters, {"offset": -1}), (CaseFilters, {"status": "open"})])
def test_invalid_decision_withdrawal_and_pagination(model, body):
    with pytest.raises(ValidationError):
        model(**body)


def test_decision_and_filters():
    assert DecisionRequest(reason="Reviewed", decision="reduce", expected_base_duration=3, after_duration=1).after_duration == 1
    assert CaseFilters().limit == 50
