"""
Tests for the PayerKnowledgeBase SQLite module.

Tests cover:
  - Schema initialization
  - Payer CRUD operations
  - Procedure CRUD operations
  - Requirement management (including deduplication and source ranking)
  - Submission logging
  - Denial recording
  - Lessons learned (including frequency incrementing)
  - Follow-up tracking
  - Statistics
"""

import pytest
from payer_knowledge_base import PayerKnowledgeBase


class TestSchema:
    """Test schema initialization."""

    def test_init_creates_tables(self, kb):
        """All tables should be created on init."""
        import sqlite3
        conn = sqlite3.connect(kb.db_path)
        tables = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        ).fetchall()
        table_names = {t[0] for t in tables}
        expected = {"payers", "procedures", "requirements", "submissions",
                    "denials", "lessons_learned", "followups"}
        assert expected.issubset(table_names)
        conn.close()

    def test_init_is_idempotent(self, kb):
        """Calling init again should not error."""
        kb._init_schema()  # Should not raise
        kb._init_schema()  # Still fine


class TestPayers:
    """Test payer CRUD operations."""

    def test_add_payer(self, kb):
        pid = kb.add_payer(name="Test Insurance", phone="555-1234")
        assert pid > 0

    def test_get_payer_by_name(self, kb):
        kb.add_payer(name="Test Insurance")
        payer = kb.get_payer_by_name("Test Insurance")
        assert payer is not None
        assert payer["name"] == "Test Insurance"

    def test_get_payer_by_name_case_insensitive(self, kb):
        kb.add_payer(name="Aetna")
        payer = kb.get_payer_by_name("aetna")
        assert payer is not None
        assert payer["name"] == "Aetna"

    def test_add_payer_updates_existing(self, kb):
        pid1 = kb.add_payer(name="Cigna", phone="111-1111")
        pid2 = kb.add_payer(name="Cigna", phone="222-2222")
        assert pid1 == pid2  # Same ID, not duplicated
        payer = kb.get_payer(pid1)
        assert payer["phone"] == "222-2222"  # Updated

    def test_list_payers(self, kb):
        kb.add_payer(name="Aetna")
        kb.add_payer(name="BCBS")
        payers = kb.list_payers()
        assert len(payers) == 2

    def test_find_or_create_payer(self, kb):
        pid1 = kb.find_or_create_payer("New Payer")
        pid2 = kb.find_or_create_payer("New Payer")
        assert pid1 == pid2


class TestProcedures:
    """Test procedure CRUD operations."""

    def test_add_procedure(self, kb):
        pid = kb.add_procedure(name="Lumbar MRI", category="imaging")
        assert pid > 0

    def test_add_procedure_dedup(self, kb):
        pid1 = kb.add_procedure(name="Knee X-ray")
        pid2 = kb.add_procedure(name="Knee X-ray")
        assert pid1 == pid2

    def test_get_procedure_by_name(self, kb):
        kb.add_procedure(name="Shoulder MRI")
        proc = kb.get_procedure_by_name("shoulder mri")
        assert proc is not None
        assert proc["name"] == "Shoulder MRI"

    def test_list_procedures(self, kb):
        kb.add_procedure(name="CT Head")
        kb.add_procedure(name="MRI Spine")
        procs = kb.list_procedures()
        assert len(procs) == 2


class TestRequirements:
    """Test requirement management — the learning engine core."""

    def test_add_requirement(self, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        req_id = kb.add_requirement(
            payer_id=payer_id, procedure_id=proc_id,
            requirement_type="lab",
            requirement_desc="CBC required",
        )
        assert req_id > 0

    def test_add_requirement_dedup(self, kb):
        """Adding the same requirement twice should not duplicate."""
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        kb.add_requirement(
            payer_id=payer_id, procedure_id=proc_id,
            requirement_type="exam",
            requirement_desc="Neurological exam",
        )
        kb.add_requirement(
            payer_id=payer_id, procedure_id=proc_id,
            requirement_type="exam",
            requirement_desc="Neurological exam",
        )
        reqs = kb.get_requirements(payer_id, proc_id)
        assert len(reqs) == 1

    def test_requirement_source_upgrade(self, kb):
        """A requirement from 'denial' should upgrade one from 'general'."""
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        kb.add_requirement(
            payer_id=payer_id, procedure_id=proc_id,
            requirement_type="lab",
            requirement_desc="CRP required",
            source="general",
        )
        kb.add_requirement(
            payer_id=payer_id, procedure_id=proc_id,
            requirement_type="lab",
            requirement_desc="CRP required",
            source="denial",
            learned_from_denial=True,
        )
        reqs = kb.get_requirements(payer_id, proc_id)
        assert len(reqs) == 1
        assert reqs[0]["source"] == "denial"
        assert reqs[0]["learned_from_denial"] is True

    def test_get_requirements(self, populated_kb):
        reqs = populated_kb.get_requirements(
            populated_kb.get_payer_by_name("BCBS of Oregon")["id"],
            populated_kb.get_procedure_by_name("Lumbar MRI")["id"],
        )
        assert len(reqs) >= 3  # At least 3 requirements in fixture
        # Verify mandatory ones come first
        assert reqs[0]["is_mandatory"] is True

    def test_requirement_detail_json(self, kb):
        """Test that detail dict is properly stored and retrieved as JSON."""
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        kb.add_requirement(
            payer_id=payer_id, procedure_id=proc_id,
            requirement_type="threshold",
            requirement_desc="ESR > 30 mm/hr",
            detail={"value": 30, "unit": "mm/hr", "test": "ESR"},
        )
        reqs = kb.get_requirements(payer_id, proc_id)
        assert reqs[0]["detail"] is not None
        assert reqs[0]["detail"]["value"] == 30
        assert reqs[0]["detail"]["test"] == "ESR"


class TestSubmissions:
    """Test submission logging."""

    def test_add_submission(self, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(
            payer_id=payer_id, procedure_id=proc_id,
            diagnosis="Test diagnosis",
            age_range="30-39",
            sex="M",
        )
        assert sub_id > 0

    def test_get_submission(self, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(
            payer_id=payer_id, procedure_id=proc_id,
            diagnosis="Test diagnosis",
            included_items=["notes", "labs"],
        )
        sub = kb.get_submission(sub_id)
        assert sub is not None
        assert sub["diagnosis"] == "Test diagnosis"
        assert sub["included_items"] == ["notes", "labs"]
        assert sub["status"] == "submitted"

    def test_update_submission_status(self, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        kb.update_submission_status(sub_id, "approved", auth_number="AUTH123")
        sub = kb.get_submission(sub_id)
        assert sub["status"] == "approved"
        assert sub["auth_number"] == "AUTH123"

    def test_list_submissions(self, populated_kb):
        subs = populated_kb.list_submissions()
        assert len(subs) >= 1


class TestDenials:
    """Test denial recording."""

    def test_add_denial(self, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)

        denial_id = kb.add_denial(
            submission_id=sub_id,
            denial_reason="Not medically necessary",
            denial_code="CO-50",
            missing_items=["conservative_treatment", "exam_findings"],
        )
        assert denial_id > 0

    def test_get_denial(self, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        denial_id = kb.add_denial(
            submission_id=sub_id,
            denial_reason="Missing info",
            missing_items=["labs"],
        )
        denial = kb.get_denial(denial_id)
        assert denial is not None
        assert denial["missing_items"] == ["labs"]
        assert denial["is_appealable"] is True


class TestLessonsLearned:
    """Test lessons learned — frequency incrementing."""

    def test_add_lesson(self, kb):
        lid = kb.add_lesson(lesson="Test lesson", lesson_type="requirement")
        assert lid > 0

    def test_lesson_frequency_increment(self, kb):
        """Adding the same lesson twice should increment frequency."""
        lid1 = kb.add_lesson(lesson="Same lesson")
        lid2 = kb.add_lesson(lesson="Same lesson")
        assert lid1 == lid2
        lessons = kb.get_lessons()
        assert len(lessons) == 1
        assert lessons[0]["frequency"] == 2

    def test_get_lessons_by_payer(self, populated_kb):
        bcbs_id = populated_kb.get_payer_by_name("BCBS of Oregon")["id"]
        lessons = populated_kb.get_lessons(payer_id=bcbs_id)
        assert len(lessons) >= 1


class TestFollowups:
    """Test follow-up tracking."""

    def test_add_followup(self, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        f_id = kb.add_followup(sub_id, expected_date="2025-07-20")
        assert f_id > 0

    def test_get_pending_followups(self, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        # Set expected date to yesterday (overdue)
        from datetime import date, timedelta
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        kb.add_followup(sub_id, expected_date=yesterday)
        pending = kb.get_pending_followups()
        assert len(pending) >= 1

    def test_mark_alert_sent(self, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        f_id = kb.add_followup(sub_id, expected_date="2025-07-20")
        kb.mark_alert_sent(f_id)
        pending = kb.get_pending_followups()
        # Should not include the one we just marked
        assert all(f["id"] != f_id for f in pending)


class TestStats:
    """Test statistics."""

    def test_get_stats(self, populated_kb):
        stats = populated_kb.get_stats()
        assert stats["total_payers"] >= 2
        assert stats["total_procedures"] >= 3
        assert stats["total_submissions"] >= 1
        assert stats["total_denials"] >= 1
        assert stats["total_requirements"] >= 4