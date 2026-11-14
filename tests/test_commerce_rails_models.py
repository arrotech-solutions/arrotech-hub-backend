"""Tests for commerce policy, returns, complaints, and refund attempt ORM models."""


def test_commerce_rails_model_tablenames():
    from src.models import (
        CommerceComplaint,
        CommercePolicy,
        CommerceRefundAttempt,
        CommerceReturn,
    )

    assert CommercePolicy.__tablename__ == "commerce_policies"
    assert CommerceReturn.__tablename__ == "commerce_returns"
    assert CommerceComplaint.__tablename__ == "commerce_complaints"
    assert CommerceRefundAttempt.__tablename__ == "commerce_refund_attempts"