from datetime import date

from server.models import AuditEvent, Claim, Run, utcnow


def make_run(**over):
    defaults = dict(filename="remit.csv", total_records=1, total_billed=100.5)
    defaults.update(over)
    return Run(**defaults)


def make_claim(run, **over):
    defaults = dict(
        run_id=run.id, claim_id="CLM-1", payer="P", carc_code="CO-50",
        rarc_codes=["N115"], billed_amount=100.5,
        service_date=date(2026, 5, 1), denial_date=date(2026, 6, 1),
        appeal_deadline=date(2026, 8, 1), denial_reason_text="text",
    )
    defaults.update(over)
    return Claim(**defaults)


def test_run_defaults_and_roundtrip(session_factory):
    with session_factory() as s:
        run = make_run()
        s.add(run)
        s.commit()
        assert run.status == "queued"
        assert run.dry_run is False and run.is_demo is False
        assert run.drafted == 0 and run.failed_records == 0
        assert run.created_at is not None and run.started_at is None


def test_claim_defaults_and_cascade_delete(session_factory):
    with session_factory() as s:
        run = make_run()
        s.add(run)
        s.flush()
        s.add(make_claim(run))
        s.commit()
        claim = s.query(Claim).one()
        assert claim.status == "queued"
        assert claim.rarc_codes == ["N115"]
        assert claim.letter is None and claim.letter_original is None
        s.delete(run)
        s.commit()
        assert s.query(Claim).count() == 0


def test_org_user_membership_invite_roundtrip(session_factory):
    import uuid
    from datetime import timedelta

    from server.models import Invite, Membership, Org, User

    with session_factory() as s:
        org = Org(name="Acme RCM")
        user = User(email="a@b.c", password_hash="h")
        s.add_all([org, user])
        s.flush()
        s.add(Membership(user_id=user.id, org_id=org.id, role="admin"))
        s.add(Invite(
            token="tok123", org_id=org.id, role="member",
            created_by=user.id, expires_at=utcnow() + timedelta(days=7),
        ))
        s.commit()
        assert org.status == "active"
        assert org.anthropic_key_encrypted is None
        assert user.is_platform_admin is False
        inv = s.query(Invite).one()
        assert inv.used_at is None and inv.used_by is None


def test_run_carries_org_id(session_factory):
    from server.models import Org

    with session_factory() as s:
        org = Org(name="O2")
        s.add(org)
        s.flush()
        run = make_run(org_id=org.id)
        s.add(run)
        s.commit()
        assert s.query(Run).one().org_id == org.id


def test_audit_event_jsonb_details(session_factory):
    with session_factory() as s:
        run = make_run()
        s.add(run)
        s.flush()
        s.add(AuditEvent(run_id=run.id, ts=utcnow(), event_type="phi_redacted",
                         details={"count": 2, "types": ["NAME"]}))
        s.commit()
        ev = s.query(AuditEvent).one()
        assert ev.details["count"] == 2
        assert ev.agent is None


def test_ci_gate_negative_check_scratch(session_factory):
    assert False, "deliberate failure - CI gate negative test, will be reverted"
