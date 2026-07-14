"""Debt status labels and share token helpers."""

from app.models.enums import DEBT_STATUS_LABELS, OPEN_DEBT_STATUSES, DebtStatus
from app.repositories.debts import DebtRepository


def test_open_debt_statuses_include_review() -> None:
    values = {s.value for s in OPEN_DEBT_STATUSES}
    assert DebtStatus.ACTIVE.value in values
    assert DebtStatus.NEEDS_REVIEW.value in values
    assert DebtStatus.PAID.value not in values


def test_debt_status_labels_ux() -> None:
    assert "Ожидает" in DEBT_STATUS_LABELS[DebtStatus.ACTIVE]
    assert "проверить" in DEBT_STATUS_LABELS[DebtStatus.NEEDS_REVIEW].lower()
    assert "Оплачено" in DEBT_STATUS_LABELS[DebtStatus.PAID]


def test_share_token_generated() -> None:
    token = DebtRepository.new_share_token()
    assert len(token) >= 8
    assert token != DebtRepository.new_share_token()
