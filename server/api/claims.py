from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from server.api.deps import scoped_claim
from server.models import Claim, utcnow
from server.payloads import claim_entry, letter_markdown

router = APIRouter(prefix="/claims", tags=["claims"])


class ClaimPatch(BaseModel):
    letter: str | None = None
    status: str | None = None


@router.get("/{claim_id}")
def get_claim(claim: Claim = Depends(scoped_claim)) -> dict:
    return claim_entry(claim, date.today())


@router.patch("/{claim_id}")
def patch_claim(patch: ClaimPatch, claim: Claim = Depends(scoped_claim)) -> dict:
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
