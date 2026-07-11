import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.api.deps import get_session, scoped_claim
from server.models import Claim, utcnow
from server.payloads import claim_entry, letter_markdown

router = APIRouter(prefix="/claims", tags=["claims"])

DISMISS_REASONS = frozenset({"payer_correct", "too_small", "deadline_passed", "other"})


class ClaimPatch(BaseModel):
    letter: str | None = None
    status: str | None = None
    dismissReason: str | None = None


def _audit(session: Session, run_id: uuid.UUID, event_type: str, details: dict) -> None:
    from server.models import AuditEvent

    session.add(AuditEvent(run_id=run_id, ts=utcnow(),
                           event_type=event_type, details=details))


@router.get("/{claim_id}")
def get_claim(claim: Claim = Depends(scoped_claim)) -> dict:
    return claim_entry(claim, date.today())


@router.patch("/{claim_id}")
def patch_claim(
    patch: ClaimPatch,
    claim: Claim = Depends(scoped_claim),
    session: Session = Depends(get_session),
) -> dict:
    if claim.run.is_demo:
        raise HTTPException(409, detail="demo run is read-only")

    if patch.status == "dismissed":
        if claim.status not in ("draft_ready", "failed"):
            raise HTTPException(409, detail=f"cannot dismiss a {claim.status} claim")
        if patch.dismissReason is not None and patch.dismissReason not in DISMISS_REASONS:
            raise HTTPException(422, detail="unknown dismissal reason")
        claim.status = "dismissed"
        claim.dismiss_reason = patch.dismissReason
        _audit(session, claim.run_id, "claim_dismissed",
               {"claim_id": claim.claim_id, "reason": patch.dismissReason})
    elif patch.status == "restored":
        if claim.status != "dismissed":
            raise HTTPException(409, detail="only dismissed claims can be restored")
        restored_to = "draft_ready" if claim.letter else "failed"
        claim.status = restored_to
        claim.dismiss_reason = None
        _audit(session, claim.run_id, "claim_restored",
               {"claim_id": claim.claim_id, "restored_to": restored_to})
    elif patch.status == "submitted":
        if claim.status not in ("draft_ready", "submitted"):
            raise HTTPException(409, detail=f"claim is {claim.status}; not editable yet")
        claim.status = "submitted"
    elif patch.status is not None:
        raise HTTPException(422, detail="status may be 'submitted', 'dismissed', or 'restored'")

    if "letter" in patch.model_fields_set:
        if claim.status not in ("draft_ready", "submitted"):
            raise HTTPException(409, detail=f"claim is {claim.status}; letter not editable")
        claim.letter = claim.letter_original if patch.letter is None else patch.letter
    claim.updated_at = utcnow()
    return claim_entry(claim, date.today())


@router.get("/{claim_id}/letter.md")
def claim_letter(claim: Claim = Depends(scoped_claim)) -> Response:
    if not claim.letter:
        raise HTTPException(404, detail="no letter drafted for this claim")
    return Response(
        letter_markdown(claim),
        media_type="text/markdown",
        headers={
            "Content-Disposition":
                f'attachment; filename="{claim.claim_id}-appeal.md"'
        },
    )
