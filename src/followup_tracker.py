"""
Follow-Up Tracker — Monitor pre-authorization deadlines and send alerts.

Tracks:
  - Expected response dates for submitted pre-auths
  - Appeal deadlines for denied pre-auths
  - Overdue submissions (no response by expected date)
  - Approaching appeal deadlines

Designed to work with Hermes cron jobs for automated monitoring.
The check_for_overdue() method returns alerts that can be delivered
via Telegram or other messaging platforms.
"""

from datetime import date, timedelta
from typing import Optional
from payer_knowledge_base import PayerKnowledgeBase


class FollowUpTracker:
    """
    Track pre-authorization deadlines and generate alerts.

    Usage:
        tracker = FollowUpTracker(kb)
        alerts = tracker.check_for_overdue()
        for alert in alerts:
            print(alert['message'])

    With Hermes cron:
        tracker = FollowUpTracker(kb)
        alerts = tracker.check_for_overdue()
        if alerts:
            # Format alerts for Telegram delivery
            message = tracker.format_alerts(alerts)
            # cron delivers message to practitioner
    """

    def __init__(self, knowledge_base: PayerKnowledgeBase):
        self.kb = knowledge_base

    def add_followup(self, submission_id: int, expected_days: int = 7,
                     appeal_deadline_days: int = None,
                     notes: str = None) -> int:
        """
        Add a follow-up entry for a newly submitted pre-auth.

        Args:
            submission_id: The submission to track
            expected_days: Expected response time in business days
            appeal_deadline_days: Appeal deadline in days (if denied)
            notes: Optional notes about this follow-up
        """
        expected_date = date.today() + timedelta(days=expected_days)
        appeal_date = None
        if appeal_deadline_days:
            appeal_date = date.today() + timedelta(days=appeal_deadline_days)

        return self.kb.add_followup(
            submission_id=submission_id,
            expected_date=expected_date.isoformat(),
            appeal_deadline=appeal_date.isoformat() if appeal_date else None,
            notes=notes,
        )

    def check_for_overdue(self) -> list[dict]:
        """
        Check for overdue pre-authorizations and approaching appeal deadlines.

        Returns a list of alert dicts, each with:
            - type: "overdue", "appeal_deadline", "overdue_appeal"
            - submission_id: int
            - payer: str
            - procedure: str
            - message: str (human-readable alert)
            - followup_id: int
            - days_overdue: int (for overdue)
            - days_remaining: int (for appeal deadlines)
        """
        alerts = []

        # 1. Overdue submissions (no response by expected date, still pending)
        overdue = self.kb.get_pending_followups()
        for item in overdue:
            expected = date.fromisoformat(item["expected_date"])
            days_overdue = (date.today() - expected).days

            alert = {
                "type": "overdue",
                "submission_id": item["submission_id"],
                "payer": item["payer_name"],
                "procedure": item["procedure_name"],
                "followup_id": item["id"],
                "days_overdue": days_overdue,
                "message": (
                    f"⏰ OVERDUE: {item['payer_name']} pre-auth for "
                    f"{item['procedure_name']} is {days_overdue} days overdue. "
                    f"Expected response by {item['expected_date']}. "
                    f"Follow up with payer."
                ),
            }
            alerts.append(alert)

        # 2. Approaching appeal deadlines
        appeals = self.kb.get_overdue_appeals()
        for item in appeals:
            if not item.get("appeal_deadline"):
                continue
            deadline = date.fromisoformat(item["appeal_deadline"])
            days_remaining = (deadline - date.today()).days

            urgency = ""
            if days_remaining <= 7:
                urgency = "🚨 URGENT — "
            elif days_remaining <= 14:
                urgency = "⚠️  "

            alert = {
                "type": "appeal_deadline",
                "submission_id": item["submission_id"],
                "payer": item["payer_name"],
                "procedure": item["procedure_name"],
                "followup_id": item["id"],
                "days_remaining": days_remaining,
                "message": (
                    f"{urgency}APPEAL DEADLINE: {item['payer_name']} denied "
                    f"{item['procedure_name']}. Appeal deadline in "
                    f"{days_remaining} days ({item['appeal_deadline']})."
                ),
            }
            alerts.append(alert)

        return alerts

    def mark_alert_sent(self, followup_id: int):
        """Mark a follow-up alert as sent (prevents duplicate alerts)."""
        self.kb.mark_alert_sent(followup_id)

    def format_alerts(self, alerts: list[dict]) -> str:
        """
        Format alerts into a single message for delivery via Telegram/email.

        Returns a formatted string, or empty string if no alerts.
        """
        if not alerts:
            return ""

        lines = ["🔔 PRE-AUTH FOLLOW-UP ALERTS", "=" * 45]

        # Separate by type
        overdue_alerts = [a for a in alerts if a["type"] == "overdue"]
        appeal_alerts = [a for a in alerts if a["type"] == "appeal_deadline"]

        if overdue_alerts:
            lines.append("")
            lines.append("⏰ OVERDUE PRE-AUTHS")
            for a in overdue_alerts:
                lines.append(f"  • {a['message']}")

        if appeal_alerts:
            lines.append("")
            lines.append("⚖️  APPEAL DEADLINES")
            for a in appeal_alerts:
                lines.append(f"  • {a['message']}")

        lines.append("")
        lines.append(f"Total alerts: {len(alerts)}")

        return "\n".join(lines)

    def get_status_report(self) -> str:
        """
        Generate a status report of all active pre-auths.

        Useful for a daily/weekly summary cron job.
        """
        stats = self.kb.get_stats()
        pending = self.kb.list_submissions(status="submitted")
        alerts = self.check_for_overdue()

        lines = ["📊 PRE-AUTH STATUS REPORT", "=" * 45]
        lines.append("")

        lines.append("OVERVIEW")
        lines.append(f"  Total submissions: {stats['total_submissions']}")
        lines.append(f"  Approval rate: {stats['approval_rate']} "
                      f"({stats.get('approval_pct', 0)}%)")
        lines.append(f"  Total denials: {stats['total_denials']}")
        lines.append(f"  Pending follow-ups: {stats['pending_followups']}")
        lines.append(f"  Requirements in KB: {stats['total_requirements']} "
                      f"({stats['learned_requirements']} learned from denials)")
        lines.append("")

        if pending:
            lines.append("PENDING PRE-AUTHS")
            for s in pending:
                lines.append(f"  • {s['payer_name']} — {s['procedure_name']} "
                              f"(submitted {s.get('submitted_date', 'N/A')})")
            lines.append("")

        if alerts:
            lines.append(f"ALERTS: {len(alerts)}")
            for a in alerts:
                lines.append(f"  • {a['message']}")
        else:
            lines.append("ALERTS: None ✅")

        return "\n".join(lines)