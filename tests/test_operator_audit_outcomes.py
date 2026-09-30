from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.operator_audit import OperatorActionContext, append_operator_event


def test_operator_outcomes_are_correlated_and_redacted():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    actor = models.User(username="operator", email="op@test", hashed_password="x", is_admin=1)
    target = models.User(username="target", email="target@test", hashed_password="x")
    db.add_all([actor, target]); db.flush()
    context = OperatorActionContext.create(
        actor_user_id=actor.id, target_user_id=target.id, purpose="incident investigation",
        case_id="CASE-123", action="export-summary",
    )
    append_operator_event(db, context, outcome="authorized")
    append_operator_event(db, context, outcome="started")
    append_operator_event(
        db, context, outcome="partial", external_confirmation="unconfirmed",
        resource_references={"token": "Bearer abc.def.ghi", "user_id": target.id},
    )
    db.commit()
    rows = db.query(models.SecurityAuditEvent).all()
    assert [row.outcome for row in rows] == ["authorized", "started", "partial"]
    assert len({row.event_metadata["correlation_id"] for row in rows}) == 1
    assert "abc.def.ghi" not in str(rows[-1].event_metadata)
    assert rows[-1].event_metadata["external_confirmation"] == "unconfirmed"
