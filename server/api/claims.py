import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session

from server.api.deps import get_session
from server.models import Claim, utcnow
from server.payloads import claim_entry, letter_markdown
from server.security import require_user

router = APIRouter(prefix="/claims", tags=["claims"])


class ClaimPatch(BaseModel):
    letter: str | None = None
    status: str | None = None


def get_claim_or_404(session: Session, claim_id: uuid.UUID) -> Claim:
    claim = session.get(Claim, claim_id)
    if claim is None:
        raise HTTPException(status_code=404, detail="claim not found")
    return claim


@router.get("/{claim_id}")
def get_claim(
    claim_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> dict:
    return claim_entry(get_claim_or_404(session, claim_id), date.today())


@router.patch("/{claim_id}")
def patch_claim(
    claim_id: uuid.UUID,
    patch: ClaimPatch,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> dict:
    claim = get_claim_or_404(session, claim_id)
    if claim.run.is_demo:
        raise HTTPException(409, detail="demo run is read-only")
    if claim.status not in ("draft_ready", "submitted"):
        raise HTTPException(409, detail=f"claim is {claim.status}; not editable yet")

    if patch.status is not None:
        if patch.status != "submitted":
            raise HTTPException(422, detail="status may only be set to 'submitted'")
        claim.status = "submitted"
    if "letter" in patch.model_fields_set:
        claim.letter = claim.letter_original if patch.letter is None else patch.letter
    claim.updated_at = utcnow()
    return claim_entry(claim, date.today())


@router.get("/{claim_id}/letter.md")
def claim_letter(
    claim_id: uuid.UUID,
    session: Session = Depends(get_session),
    _user: str = Depends(require_user),
) -> Response:
    claim = get_claim_or_404(session, claim_id)
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
