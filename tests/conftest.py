"""Shared fixtures: deterministic remittance files and dry-run agents."""
import os
from pathlib import Path

import pytest

# CLI-output assertions must not depend on the host terminal's capabilities
# (COLORTERM/TERM leak into Rich under the Click test runner; NO_COLOR alone
# still leaves bold/highlight escapes that split numbers mid-string).
os.environ["NO_COLOR"] = "1"
os.environ["TERM"] = "dumb"

SAMPLE_CSV = """\
claim_id,payer,carc_code,rarc_codes,denial_reason_text,billed_amount,service_date,denial_date,appeal_deadline
CLM-001,Synthetic Payer A,CO-50,N115,These are non-covered services because this is not deemed a medical necessity by the payer.,12500.00,2026-04-10,2026-05-01,2026-06-30
CLM-002,Synthetic Payer B,CO-29,N30,The time limit for filing has expired.,430.25,2026-03-02,2026-04-15,2026-07-15
CLM-003,Synthetic Payer A,CO-97,M15,The benefit for this service is included in the payment for another service already adjudicated.,8300.00,2026-05-20,2026-06-10,
"""

# With --as-of 2026-07-05: CLM-001 is overdue (-5d), CLM-002 has 10 days,
# CLM-003 has no deadline and must sort last.
AS_OF = "2026-07-05"


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    path = tmp_path / "denials.csv"
    path.write_text(SAMPLE_CSV, encoding="utf-8")
    return path
