"""
Test fixtures and configuration for the pre-authorization agent test suite.

All tests use an in-memory or temporary SQLite database to avoid
touching real data.
"""

import pytest
import tempfile
import os
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from payer_knowledge_base import PayerKnowledgeBase


@pytest.fixture
def temp_db_path():
    """Provide a temporary database path that's cleaned up after the test."""
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    yield path
    if os.path.exists(path):
        os.remove(path)


@pytest.fixture
def kb(temp_db_path):
    """Provide a fresh knowledge base with a temporary database."""
    return PayerKnowledgeBase(db_path=temp_db_path)


@pytest.fixture
def populated_kb(kb):
    """Provide a knowledge base pre-populated with test data."""
    # Add payers
    bcbs_id = kb.add_payer(
        name="BCBS of Oregon",
        portal_url="https://port.bcbs.com",
        phone="800-555-0100",
        fax="800-555-0101",
        turnaround_days=5,
        appeal_deadline_days=30,
    )
    aetna_id = kb.add_payer(
        name="Aetna",
        phone="800-555-0200",
        turnaround_days=7,
        appeal_deadline_days=45,
    )

    # Add procedures
    mri_id = kb.add_procedure(name="Lumbar MRI", cpt_code="72148", category="imaging")
    knee_id = kb.add_procedure(name="Knee Arthroscopy", category="surgery")
    pt_id = kb.add_procedure(name="Physical Therapy", category="therapy")

    # Add requirements (some from general knowledge, some learned from denials)
    kb.add_requirement(
        payer_id=bcbs_id, procedure_id=mri_id,
        requirement_type="prior_treatment",
        requirement_desc="6-week conservative treatment trial documented",
        is_mandatory=True, source="general",
    )
    kb.add_requirement(
        payer_id=bcbs_id, procedure_id=mri_id,
        requirement_type="imaging",
        requirement_desc="Plain radiograph before MRI",
        is_mandatory=True, source="general",
    )
    kb.add_requirement(
        payer_id=bcbs_id, procedure_id=mri_id,
        requirement_type="exam",
        requirement_desc="Neurological exam with documented deficit",
        is_mandatory=True, source="general",
    )
    # A learned requirement (from a past denial)
    kb.add_requirement(
        payer_id=bcbs_id, procedure_id=mri_id,
        requirement_type="lab",
        requirement_desc="ESR and CRP to rule out infection",
        is_mandatory=True, learned_from_denial=True, source="denial",
    )

    # Add a submission
    sub_id = kb.add_submission(
        payer_id=bcbs_id, procedure_id=mri_id,
        diagnosis="Lumbar radiculopathy",
        icd10_code="M54.16",
        age_range="40-49",
        sex="F",
        problem_summary="Lower back pain radiating to left leg, 8 weeks duration",
        included_items=["clinical_notes", "xray_report", "PT_notes"],
    )

    # Add a denial for that submission
    kb.add_denial(
        submission_id=sub_id,
        denial_code="CO-50",
        denial_reason="Not medically necessary - insufficient conservative treatment documentation",
        denial_category="not_medically_necessary",
        missing_items=["conservative treatment trial documentation"],
        is_appealable=True,
        appeal_deadline="2025-08-15",
        policy_cited="Medical Policy MRI-001",
    )

    # Add a lesson learned
    kb.add_lesson(
        lesson="BCBS requires documented 6-week conservative treatment before lumbar MRI",
        payer_id=bcbs_id,
        procedure_id=mri_id,
        lesson_type="requirement",
        frequency=2,
    )

    return kb