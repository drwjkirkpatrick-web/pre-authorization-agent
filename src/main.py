"""
Pre-Authorization Agent — Main entry point.

Provides a command-line interface that ties together all modules:
  - Generate pre-submission checklists
  - Draft letters of medical necessity
  - Analyze denial letters (text, PDF, or image)
  - Log submissions and track follow-ups
  - View statistics and learning summaries

Can also be used as a Hermes skill — the functions are importable
and can be called from agent conversations via Telegram.

Usage (CLI):
    python -m src.main checklist --payer "BCBS" --procedure "Lumbar MRI"
    python -m src.main letter --payer "BCBS" --procedure "Lumbar MRI" --diagnosis "Lumbar radiculopathy"
    python -m src.main analyze --text "denial letter text..."
    python -m src.main analyze --file denial.pdf
    python -m src.main submit --payer "BCBS" --procedure "Lumbar MRI" --diagnosis "Lumbar radiculopathy"
    python -m main denial --submission-id 1 --text "denial letter text..."
    python -m src.main stats
    python -m src.main followup

Usage (as module):
    from src.main import PreAuthAgent
    agent = PreAuthAgent()
    checklist = agent.get_checklist("BCBS", "Lumbar MRI")
"""

import argparse
import json
import sys
import os
from pathlib import Path

# Ensure src is on the path when running as script
sys.path.insert(0, str(Path(__file__).parent))

from payer_knowledge_base import PayerKnowledgeBase
from checklist_generator import ChecklistGenerator
from letter_drafter import LetterDrafter
from denial_analyzer import DenialAnalyzer
from learning_loop import LearningLoop
from followup_tracker import FollowUpTracker


class PreAuthAgent:
    """
    Main agent class — ties together all pre-authorization modules.

    This class is designed to be used both from the CLI and from
    Hermes agent conversations. All methods return dicts that can
    be easily serialized for Telegram delivery.
    """

    def __init__(self, db_path: str = None):
        """Initialize the agent with all modules."""
        self.kb = PayerKnowledgeBase(db_path)
        self.checklist_gen = ChecklistGenerator(self.kb)
        self.letter_drafter = LetterDrafter(self.kb)
        self.denial_analyzer = DenialAnalyzer()
        self.learning_loop = LearningLoop(self.kb, self.denial_analyzer)
        self.followup_tracker = FollowUpTracker(self.kb)

    # ─── Checklist ────────────────────────────────────────────────────────

    def get_checklist(self, payer_name: str, procedure_name: str,
                      clinical_info: dict = None) -> dict:
        """Generate a pre-submission checklist."""
        checklist = self.checklist_gen.generate(payer_name, procedure_name, clinical_info)
        return checklist

    def get_checklist_text(self, payer_name: str, procedure_name: str,
                           clinical_info: dict = None) -> str:
        """Generate a pre-submission checklist as formatted text."""
        checklist = self.get_checklist(payer_name, procedure_name, clinical_info)
        return self.checklist_gen.format_checklist(checklist)

    # ─── Letter Drafting ──────────────────────────────────────────────────

    def draft_letter(self, payer_name: str, procedure_name: str,
                     clinical_info: dict = None, practice_info: dict = None,
                     patient_info: dict = None) -> dict:
        """Draft a letter of medical necessity."""
        return self.letter_drafter.draft_letter(
            payer_name, procedure_name, clinical_info, practice_info, patient_info
        )

    # ─── Denial Analysis ─────────────────────────────────────────────────

    def analyze_denial(self, text: str = None, file_path: str = None) -> dict:
        """Analyze a denial letter from text or file."""
        if file_path:
            return self.denial_analyzer.analyze_file(file_path)
        return self.denial_analyzer.analyze_text(text or "")

    def process_denial(self, submission_id: int, denial_text: str = None,
                       denial_file_path: str = None) -> dict:
        """Process a denial and update the knowledge base (learning loop)."""
        return self.learning_loop.process_denial(
            submission_id, denial_text, denial_file_path
        )

    def process_approval(self, submission_id: int,
                          auth_number: str = None) -> dict:
        """Process an approval and log it."""
        return self.learning_loop.process_approval(submission_id, auth_number)

    # ─── Submissions ──────────────────────────────────────────────────────

    def log_submission(self, payer_name: str, procedure_name: str,
                        diagnosis: str = None, icd10_code: str = None,
                        cpt_code: str = None, age_range: str = None,
                        sex: str = None, problem_summary: str = None,
                        included_items: list = None,
                        letter_text: str = None) -> dict:
        """Log a new pre-authorization submission."""
        payer_id = self.kb.find_or_create_payer(payer_name)
        procedure_id = self.kb.find_or_create_procedure(procedure_name)

        submission_id = self.kb.add_submission(
            payer_id=payer_id,
            procedure_id=procedure_id,
            diagnosis=diagnosis,
            icd10_code=icd10_code,
            cpt_code=cpt_code,
            age_range=age_range,
            sex=sex,
            problem_summary=problem_summary,
            included_items=included_items,
            letter_text=letter_text,
        )

        # Add follow-up tracking
        payer = self.kb.get_payer(payer_id)
        expected_days = payer.get("turnaround_days", 7) if payer else 7
        appeal_days = payer.get("appeal_deadline_days", 30) if payer else 30

        self.followup_tracker.add_followup(
            submission_id, expected_days=expected_days,
            appeal_deadline_days=appeal_days
        )

        return {
            "submission_id": submission_id,
            "payer": payer_name,
            "procedure": procedure_name,
            "message": f"Submission logged (ID: {submission_id}). "
                       f"Follow-up scheduled for {expected_days} days."
        }

    def list_submissions(self, payer_name: str = None,
                         status: str = None, limit: int = 20) -> list[dict]:
        """List submissions, optionally filtered."""
        payer_id = None
        if payer_name:
            payer = self.kb.get_payer_by_name(payer_name)
            payer_id = payer["id"] if payer else None

        return self.kb.list_submissions(payer_id=payer_id, status=status, limit=limit)

    # ─── Follow-up ───────────────────────────────────────────────────────

    def check_followups(self) -> list[dict]:
        """Check for overdue pre-auths and appeal deadlines."""
        return self.followup_tracker.check_for_overdue()

    def get_followup_alerts(self) -> str:
        """Get formatted follow-up alerts for delivery."""
        alerts = self.check_followups()
        return self.followup_tracker.format_alerts(alerts)

    def get_status_report(self) -> str:
        """Get a status report of all pre-auth activity."""
        return self.followup_tracker.get_status_report()

    # ─── Learning ─────────────────────────────────────────────────────────

    def get_learning_summary(self, payer_name: str = None,
                              procedure_name: str = None) -> dict:
        """Get a summary of what's been learned for a payer/procedure."""
        return self.learning_loop.get_learning_summary(payer_name, procedure_name)

    # ─── Statistics ───────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get summary statistics."""
        return self.kb.get_stats()

    def get_lessons(self, payer_name: str = None) -> list[dict]:
        """Get lessons learned."""
        payer_id = None
        if payer_name:
            payer = self.kb.get_payer_by_name(payer_name)
            payer_id = payer["id"] if payer else None
        return self.kb.get_lessons(payer_id=payer_id)


# ─── CLI ─────────────────────────────────────────────────────────────────

def cli_main():
    """Command-line interface for the pre-authorization agent."""
    parser = argparse.ArgumentParser(
        description="Pre-Authorization Agent — insurance pre-auth assistant"
    )
    subparsers = parser.add_subparsers(dest="command", help="Available commands")

    # Checklist command
    cl = subparsers.add_parser("checklist", help="Generate pre-submission checklist")
    cl.add_argument("--payer", required=True, help="Insurance company name")
    cl.add_argument("--procedure", required=True, help="Procedure name")
    cl.add_argument("--clinical", help="JSON file with clinical info")

    # Letter command
    lt = subparsers.add_parser("letter", help="Draft letter of medical necessity")
    lt.add_argument("--payer", required=True, help="Insurance company name")
    lt.add_argument("--procedure", required=True, help="Procedure name")
    lt.add_argument("--diagnosis", help="Working diagnosis")
    lt.add_argument("--icd10", help="ICD-10 code (only if confirmed)")
    lt.add_argument("--cpt", help="CPT code (only if confirmed)")
    lt.add_argument("--duration", help="Symptom duration")
    lt.add_argument("--clinical", help="JSON file with full clinical info")
    lt.add_argument("--practice", help="JSON file with practice info")
    lt.add_argument("--patient", help="JSON file with patient info")
    lt.add_argument("--output", help="Output file path (default: stdout)")

    # Analyze denial command
    an = subparsers.add_parser("analyze", help="Analyze a denial letter")
    an.add_argument("--text", help="Denial letter text (pasted)")
    an.add_argument("--file", help="Path to denial letter file (PDF/image/text)")

    # Log submission command
    sub = subparsers.add_parser("submit", help="Log a new pre-auth submission")
    sub.add_argument("--payer", required=True)
    sub.add_argument("--procedure", required=True)
    sub.add_argument("--diagnosis", help="Working diagnosis")
    sub.add_argument("--icd10", help="ICD-10 code")
    sub.add_argument("--cpt", help="CPT code")
    sub.add_argument("--age", help="Age range (e.g., '40-49')")
    sub.add_argument("--sex", help="Sex (M/F)")
    sub.add_argument("--summary", help="Problem summary")

    # Process denial (learning loop)
    den = subparsers.add_parser("denial", help="Process a denial and learn from it")
    den.add_argument("--submission-id", type=int, required=True,
                     help="Submission ID that was denied")
    den.add_argument("--text", help="Denial letter text")
    den.add_argument("--file", help="Path to denial letter file")

    # Process approval
    app = subparsers.add_parser("approval", help="Process an approval")
    app.add_argument("--submission-id", type=int, required=True)
    app.add_argument("--auth-number", help="Pre-auth authorization number")

    # Stats command
    subparsers.add_parser("stats", help="Show statistics")

    # Follow-up command
    subparsers.add_parser("followup", help="Check for overdue pre-auths and alerts")

    # Lessons command
    les = subparsers.add_parser("lessons", help="Show lessons learned")
    les.add_argument("--payer", help="Filter by payer")

    # Learning summary
    learn = subparsers.add_parser("learning", help="Show learning summary")
    learn.add_argument("--payer", help="Payer name")
    learn.add_argument("--procedure", help="Procedure name")

    # List submissions
    lst = subparsers.add_parser("list", help="List submissions")
    lst.add_argument("--payer", help="Filter by payer")
    lst.add_argument("--status", help="Filter by status")
    lst.add_argument("--limit", type=int, default=20)

    args = parser.parse_args()

    if not args.command:
        parser.print_help()
        return

    agent = PreAuthAgent()

    if args.command == "checklist":
        clinical_info = None
        if args.clinical:
            with open(args.clinical) as f:
                clinical_info = json.load(f)
        text = agent.get_checklist_text(args.payer, args.procedure, clinical_info)
        print(text)

    elif args.command == "letter":
        clinical_info = {}
        if args.clinical:
            with open(args.clinical) as f:
                clinical_info = json.load(f)
        else:
            if args.diagnosis:
                clinical_info["diagnosis"] = args.diagnosis
            if args.icd10:
                clinical_info["icd10_code"] = args.icd10
            if args.cpt:
                clinical_info["cpt_code"] = args.cpt
            if args.duration:
                clinical_info["symptom_duration"] = args.duration

        practice_info = None
        if args.practice:
            with open(args.practice) as f:
                practice_info = json.load(f)

        patient_info = None
        if args.patient:
            with open(args.patient) as f:
                patient_info = json.load(f)

        result = agent.draft_letter(
            args.payer, args.procedure, clinical_info, practice_info, patient_info
        )

        output_text = result["letter_text"]
        if result["missing_fields"]:
            output_text += "\n\n" + "=" * 50 + "\n"
            output_text += "⚠️  MISSING FIELDS (must be completed before submission):\n"
            output_text += "=" * 50 + "\n"
            for field in result["missing_fields"]:
                output_text += f"  • {field}\n"

        if result["warnings"]:
            output_text += "\n" + "=" * 50 + "\n"
            output_text += "⚠️  WARNINGS:\n"
            output_text += "=" * 50 + "\n"
            for w in result["warnings"]:
                output_text += f"  • {w}\n"

        if args.output:
            with open(args.output, "w") as f:
                f.write(output_text)
            print(f"Letter written to {args.output}")
        else:
            print(output_text)

    elif args.command == "analyze":
        if args.file:
            result = agent.analyze_denial(file_path=args.file)
        else:
            result = agent.analyze_denial(text=args.text)

        print("═══ DENIAL ANALYSIS ═══")
        print()
        print(f"Denial Code: {result.get('denial_code', 'N/A')}")
        if result.get('denial_code_desc'):
            print(f"  ({result['denial_code_desc']})")
        print(f"Category: {result.get('denial_category', 'N/A')}")
        print(f"Description: {result.get('category_description', 'N/A')}")
        print(f"Fixable: {result.get('is_fixable', 'Unknown')}")
        print(f"Appealable: {result.get('is_appealable', 'N/A')}")
        if result.get('appeal_deadline'):
            print(f"Appeal Deadline: {result['appeal_deadline']}")
        if result.get('policy_cited'):
            print(f"Policy Cited: {result['policy_cited']}")
        print()
        print(f"Denial Reason: {result.get('denial_reason', 'N/A')}")
        print()
        if result.get("missing_items"):
            print("MISSING ITEMS:")
            for item in result["missing_items"]:
                print(f"  • [{item['type']}] {item['description']}")
                if item.get('context'):
                    print(f"    Context: {item['context'][:200]}")
            print()

        if result.get("uncertainty_flags"):
            print("⚠️  UNCERTAINTY FLAGS:")
            for flag in result["uncertainty_flags"]:
                print(f"  • {flag}")

        # Show remediation checklist
        checklist = agent.denial_analyzer.generate_remediation_checklist(result)
        print()
        print("\n".join(checklist))

    elif args.command == "submit":
        result = agent.log_submission(
            payer_name=args.payer,
            procedure_name=args.procedure,
            diagnosis=args.diagnosis,
            icd10_code=args.icd10,
            cpt_code=args.cpt,
            age_range=args.age,
            sex=args.sex,
            problem_summary=args.summary,
        )
        print(f"✅ {result['message']}")

    elif args.command == "denial":
        result = agent.process_denial(
            submission_id=args.submission_id,
            denial_text=args.text,
            denial_file_path=args.file,
        )

        if "error" in result:
            print(f"❌ {result['error']}")
            return

        print("═══ DENIAL PROCESSED — LEARNING LOOP UPDATE ═══")
        print()
        print(f"Denial ID: {result.get('denial_id')}")
        print(f"Submission status updated: {result.get('submission_updated')}")
        print()

        if result.get("new_requirements"):
            print("NEW REQUIREMENTS ADDED TO KNOWLEDGE BASE:")
            for req in result["new_requirements"]:
                print(f"  + [{req['type']}] {req['description']}")
            print()

        if result.get("lesson"):
            print(f"LESSON LEARNED: {result['lesson']}")
            print()

        if result.get("remediation_checklist"):
            print("REMEDIATION CHECKLIST:")
            print("\n".join(result["remediation_checklist"]))

    elif args.command == "approval":
        result = agent.process_approval(args.submission_id, args.auth_number)
        if "error" in result:
            print(f"❌ {result['error']}")
            return
        print(f"✅ {result.get('message', 'Approved')}")

    elif args.command == "stats":
        stats = agent.get_stats()
        print("═══ PRE-AUTH STATISTICS ═══")
        print()
        for k, v in stats.items():
            label = k.replace("_", " ").title()
            print(f"  {label}: {v}")

    elif args.command == "followup":
        alerts = agent.check_followups()
        if alerts:
            print(agent.followup_tracker.format_alerts(alerts))
        else:
            print("✅ No overdue pre-auths or appeal deadlines.")

    elif args.command == "lessons":
        lessons = agent.get_lessons(args.payer) if args.payer else agent.get_lessons()
        if lessons:
            print("═══ LESSONS LEARNED ═══")
            for l in lessons:
                print(f"  💡 [{l['lesson_type']}] {l['lesson']}")
                print(f"     Frequency: {l['frequency']} | Last seen: {l['last_seen']}")
        else:
            print("No lessons learned yet. Process denials to build knowledge.")

    elif args.command == "learning":
        summary = agent.get_learning_summary(args.payer, args.procedure)
        print("═══ LEARNING SUMMARY ═══")
        print()
        print(f"Payer: {summary.get('payer', 'All')}")
        print(f"Procedure: {summary.get('procedure', 'All')}")
        print(f"Total requirements: {summary['total_requirements']}")
        print(f"  Learned from denials: {summary['learned_from_denials']}")
        print(f"Total submissions: {summary['total_submissions']}")
        print(f"Total denials: {summary['total_denials']}")
        print(f"Approval rate: {summary['approval_rate']}")
        if summary.get("top_denial_reasons"):
            print()
            print("Top denial reasons:")
            for reason in summary["top_denial_reasons"]:
                print(f"  • {reason}")
        if summary.get("lessons"):
            print()
            print("Lessons:")
            for lesson in summary["lessons"]:
                print(f"  💡 {lesson}")

    elif args.command == "list":
        submissions = agent.list_submissions(
            payer_name=args.payer, status=args.status, limit=args.limit
        )
        if submissions:
            print("═══ SUBMISSIONS ═══")
            for s in submissions:
                print(f"  [{s['id']}] {s['payer_name']} — {s['procedure_name']} "
                      f"| Status: {s['status']} | Submitted: {s.get('submitted_date', 'N/A')}")
        else:
            print("No submissions found.")


if __name__ == "__main__":
    cli_main()