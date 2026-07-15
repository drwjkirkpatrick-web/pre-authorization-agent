"""
Tests for the FollowUpTracker module.

Tests cover:
  - Adding follow-up entries
  - Overdue submission detection
  - Appeal deadline tracking
  - Alert formatting
  - Status report generation
"""

import pytest
from datetime import date, timedelta
from payer_knowledge_base import PayerKnowledgeBase
from followup_tracker import FollowUpTracker


@pytest.fixture
def tracker(kb):
    return FollowUpTracker(kb)


class TestFollowUpTracking:
    """Test follow-up tracking."""

    def test_add_followup(self, tracker, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        f_id = tracker.add_followup(sub_id, expected_days=7)
        assert f_id > 0

    def test_check_no_overdue(self, tracker, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        # Set follow-up for 30 days from now (not overdue)
        tracker.add_followup(sub_id, expected_days=30)
        alerts = tracker.check_for_overdue()
        assert len(alerts) == 0

    def test_check_overdue(self, tracker, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        # Set follow-up for yesterday (overdue)
        tracker.add_followup(sub_id, expected_days=-1)
        alerts = tracker.check_for_overdue()
        assert len(alerts) >= 1
        assert alerts[0]["type"] == "overdue"
        assert alerts[0]["days_overdue"] >= 1

    def test_check_appeal_deadline(self, tracker, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        # Create a denied submission with an upcoming appeal deadline
        kb.update_submission_status(sub_id, "denied_appealable")
        tracker.add_followup(sub_id, expected_days=-1, appeal_deadline_days=7)
        alerts = tracker.check_for_overdue()
        appeal_alerts = [a for a in alerts if a["type"] == "appeal_deadline"]
        assert len(appeal_alerts) >= 1
        assert appeal_alerts[0]["days_remaining"] <= 7

    def test_format_alerts_empty(self, tracker):
        text = tracker.format_alerts([])
        assert text == ""

    def test_format_alerts_with_content(self, tracker, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        tracker.add_followup(sub_id, expected_days=-1)
        alerts = tracker.check_for_overdue()
        text = tracker.format_alerts(alerts)
        assert "PRE-AUTH FOLLOW-UP ALERTS" in text
        assert "Test Payer" in text
        assert "Test Procedure" in text

    def test_mark_alert_sent(self, tracker, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        tracker.add_followup(sub_id, expected_days=-1)
        alerts = tracker.check_for_overdue()
        assert len(alerts) >= 1
        tracker.mark_alert_sent(alerts[0]["followup_id"])
        # Should no longer appear in pending
        alerts_after = tracker.check_for_overdue()
        assert all(a["followup_id"] != alerts[0]["followup_id"]
                    for a in alerts_after)

    def test_status_report(self, tracker, kb):
        payer_id = kb.add_payer(name="Test Payer")
        proc_id = kb.add_procedure(name="Test Procedure")
        sub_id = kb.add_submission(payer_id=payer_id, procedure_id=proc_id)
        tracker.add_followup(sub_id, expected_days=7)
        report = tracker.get_status_report()
        assert "PRE-AUTH STATUS REPORT" in report
        assert "Total submissions" in report