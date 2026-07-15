"""
Tests for the LearningLoop module.

Tests cover:
  - Processing denials and extracting new requirements
  - Updating the knowledge base with learned requirements
  - Lesson creation from denial patterns
  - Processing approvals (positive learning)
  - Learning summary generation
"""

import pytest
from payer_knowledge_base import PayerKnowledgeBase
from denial_analyzer import DenialAnalyzer
from learning_loop import LearningLoop


@pytest.fixture
def loop(kb):
    analyzer = DenialAnalyzer()
    return LearningLoop(kb, analyzer)


class TestProcessDenial:
    """Test the core learning loop: process a denial and update KB."""

    def test_process_denial_text(self, loop, kb):
        """Process a denial from text and verify KB is updated."""
        # Set up submission
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Lumbar MRI")
        sub_id = kb.add_submission(
            payer_id=payer_id, procedure_id=proc_id,
            diagnosis="Lumbar radiculopathy",
        )

        denial_text = """
        We are denying your request for Lumbar MRI.
        Denial Code: CO-50
        Reason: Not medically necessary.
        The submitted information does not support medical necessity.
        Documentation of conservative treatment including physical therapy
        was not provided. Physical examination findings were not documented
        in the submitted records.
        You may appeal this decision within 30 days.
        """

        result = loop.process_denial(
            submission_id=sub_id,
            denial_text=denial_text,
        )

        assert result["submission_updated"] is True
        assert result["denial_id"] > 0
        assert len(result["new_requirements"]) > 0
        assert result["lesson"] is not None

        # Verify requirements were added to KB
        reqs = kb.get_requirements(payer_id, proc_id)
        learned = [r for r in reqs if r["learned_from_denial"]]
        assert len(learned) >= 1

    def test_process_denial_updates_submission_status(self, loop, kb):
        """Verify that submission status is updated to denied."""
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)

        loop.process_denial(
            submission_id=sub_id,
            denial_text="Denied. Not medically necessary. No conservative treatment documented.",
        )

        sub = kb.get_submission(sub_id)
        assert sub["status"] in ("denied", "denied_appealable")

    def test_process_denial_adds_lesson(self, loop, kb):
        """Verify a lesson is created and stored."""
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Lumbar MRI")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)

        result = loop.process_denial(
            submission_id=sub_id,
            denial_text="Denied. Conservative treatment not documented. Physical therapy required.",
        )

        lessons = kb.get_lessons(payer_id=payer_id, procedure_id=proc_id)
        assert len(lessons) >= 1
        assert "Test Payer" in result["lesson"]

    def test_process_denial_no_text_or_file(self, loop, kb):
        """Should return error if no denial text or file provided."""
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)

        result = loop.process_denial(submission_id=sub_id)
        assert "error" in result

    def test_process_denial_nonexistent_submission(self, loop):
        """Should handle nonexistent submission gracefully."""
        result = loop.process_denial(
            submission_id=99999,
            denial_text="Some denial text",
        )
        assert "error" in result

    def test_remediation_checklist_generated(self, loop, kb):
        """Verify a remediation checklist is generated."""
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)

        result = loop.process_denial(
            submission_id=sub_id,
            denial_text="Denied. Physical examination findings were not documented. "
                        "Conservative treatment was not documented.",
        )

        assert "remediation_checklist" in result
        assert len(result["remediation_checklist"]) > 0


class TestProcessApproval:
    """Test processing approvals (positive learning)."""

    def test_process_approval(self, loop, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)

        result = loop.process_approval(sub_id, auth_number="AUTH-12345")
        assert result["status"] == "approved"
        assert result["submission_updated"] is True

        sub = kb.get_submission(sub_id)
        assert sub["status"] == "approved"
        assert sub["auth_number"] == "AUTH-12345"

    def test_process_approval_nonexistent(self, loop):
        result = loop.process_approval(99999)
        assert "error" in result


class TestLearningSummary:
    """Test learning summary generation."""

    def test_learning_summary(self, loop, populated_kb):
        summary = loop.get_learning_summary("BCBS of Oregon", "Lumbar MRI")
        assert summary["payer"] == "BCBS of Oregon"
        assert summary["procedure"] == "Lumbar MRI"
        assert summary["total_requirements"] >= 3
        assert summary["learned_from_denials"] >= 1
        assert summary["total_submissions"] >= 1

    def test_learning_summary_nonexistent_payer(self, loop):
        summary = loop.get_learning_summary("Nonexistent Payer")
        assert summary["total_requirements"] == 0
        assert summary["total_submissions"] == 0