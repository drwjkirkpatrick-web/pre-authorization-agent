"""
Learning Loop — Update the knowledge base from denial outcomes.

This is the core differentiator of the pre-authorization agent.
After each denial:
  1. Extract what was missing from the denial analysis
  2. Add those missing items as NEW requirements for that payer+procedure
  3. Tag them as "learned_from_denial" so they appear in future checklists
  4. Add a lesson learned (higher-level pattern)
  5. Update the submission status

The next time the same payer+procedure combination comes up,
the pre-submission checklist will AUTOMATICALLY include the
previously-missing items.

CRITICAL: This module never fabricates requirements. It extracts
genuine gaps from real denial letters and records them so the
practitioner can address them in future submissions.
"""

from typing import Optional
from payer_knowledge_base import PayerKnowledgeBase
from denial_analyzer import DenialAnalyzer


class LearningLoop:
    """
    Update the knowledge base from denial outcomes.

    Usage:
        loop = LearningLoop(kb, analyzer)
        result = loop.process_denial(
            submission_id=42,
            denial_text="...denial letter text..."
        )
        # KB is now updated with new requirements
    """

    def __init__(self, knowledge_base: PayerKnowledgeBase,
                 analyzer: DenialAnalyzer = None):
        self.kb = knowledge_base
        self.analyzer = analyzer or DenialAnalyzer()

    def process_denial(self, submission_id: int,
                       denial_text: str = None,
                       denial_file_path: str = None,
                       analysis: dict = None) -> dict:
        """
        Process a denial for a submission and update the knowledge base.

        Args:
            submission_id: The ID of the denied submission
            denial_text: Denial letter text (if pasted/extracted)
            denial_file_path: Path to denial letter file (PDF/image)
            analysis: Pre-computed analysis dict (skip extraction)

        Returns:
            dict with:
              - analysis: the denial analysis
              - new_requirements: list of new requirements added to KB
              - lesson: the lesson learned (str)
              - submission_updated: bool
              - remediation_checklist: list[str]
        """
        # Get the submission to find payer and procedure
        submission = self.kb.get_submission(submission_id)
        if not submission:
            return {
                "error": f"Submission {submission_id} not found",
                "new_requirements": [],
                "lesson": None,
            }

        payer_id = submission["payer_id"]
        procedure_id = submission["procedure_id"]

        # Analyze the denial (if not already analyzed)
        if analysis is None:
            if denial_text:
                analysis = self.analyzer.analyze_text(denial_text)
            elif denial_file_path:
                analysis = self.analyzer.analyze_file(denial_file_path)
            else:
                return {
                    "error": "No denial text or file provided for analysis",
                    "new_requirements": [],
                    "lesson": None,
                }

        # Record the denial in the database
        missing_items_list = [
            {"type": item["type"], "description": item["description"]}
            for item in analysis.get("missing_items", [])
        ]

        denial_id = self.kb.add_denial(
            submission_id=submission_id,
            denial_code=analysis.get("denial_code"),
            denial_reason=analysis.get("denial_reason", "Unknown"),
            denial_category=analysis.get("denial_category"),
            missing_items=missing_items_list,
            is_appealable=analysis.get("is_appealable", True),
            appeal_deadline=analysis.get("appeal_deadline"),
            policy_cited=analysis.get("policy_cited"),
            raw_text=analysis.get("raw_text"),
        )

        # Update submission status
        if analysis.get("is_appealable"):
            self.kb.update_submission_status(submission_id, "denied_appealable")
        else:
            self.kb.update_submission_status(submission_id, "denied")

        # Extract new requirements from missing items
        new_requirements = self._extract_new_requirements(
            analysis, payer_id, procedure_id
        )

        # Add a lesson learned
        lesson = self._create_lesson(analysis, submission)
        if lesson:
            self.kb.add_lesson(
                lesson=lesson,
                payer_id=payer_id,
                procedure_id=procedure_id,
                lesson_type="requirement",
            )

        # Generate remediation checklist
        remediation_checklist = self.analyzer.generate_remediation_checklist(analysis)

        return {
            "analysis": analysis,
            "denial_id": denial_id,
            "new_requirements": new_requirements,
            "lesson": lesson,
            "submission_updated": True,
            "remediation_checklist": remediation_checklist,
        }

    def _extract_new_requirements(self, analysis: dict,
                                   payer_id: int,
                                   procedure_id: int) -> list[dict]:
        """
        Extract new requirements from the denial analysis and add them to KB.

        Each missing item becomes a new requirement, tagged as
        "learned_from_denial" so it appears in future checklists.
        """
        new_reqs = []
        missing_items = analysis.get("missing_items", [])

        for item in missing_items:
            req_type = item["type"]
            desc = item["description"]
            context = item.get("context", "")

            # Build a detailed description that includes context
            # This helps the practitioner understand exactly what's needed
            detailed_desc = desc
            if context:
                # Keep it concise — just the key part of the context
                detailed_desc = f"{desc} (payer stated: {context[:150]})"

            req_id = self.kb.add_requirement(
                payer_id=payer_id,
                procedure_id=procedure_id,
                requirement_type=req_type,
                requirement_desc=detailed_desc,
                is_mandatory=True,
                learned_from_denial=True,
                source="denial",
            )

            if req_id:
                new_reqs.append({
                    "requirement_id": req_id,
                    "type": req_type,
                    "description": detailed_desc,
                    "is_new": True,
                })

        # Also check for denial category patterns
        # e.g., "not_medically_necessary" often means the submission
        # didn't meet specific criteria — add a general requirement
        category = analysis.get("denial_category")
        if category == "not_medically_necessary" and not missing_items:
            # No specific items detected but it was a medical necessity denial
            req_id = self.kb.add_requirement(
                payer_id=payer_id,
                procedure_id=procedure_id,
                requirement_type="documentation",
                requirement_desc="Payer denied for medical necessity — "
                                "ensure all clinical justification is documented. "
                                "Review payer's specific medical necessity policy.",
                is_mandatory=True,
                learned_from_denial=True,
                source="denial",
            )
            if req_id:
                new_reqs.append({
                    "requirement_id": req_id,
                    "type": "documentation",
                    "description": "Medical necessity documentation (non-specific)",
                    "is_new": True,
                })

        return new_reqs

    def _create_lesson(self, analysis: dict, submission: dict) -> Optional[str]:
        """
        Create a high-level lesson learned from this denial.

        The lesson is a concise, actionable statement that summarizes
        the pattern, e.g.:
        "BCBS requires documented 6-week conservative treatment trial
         before approving lumbar MRI"
        """
        category = analysis.get("denial_category", "")
        missing_items = analysis.get("missing_items", [])

        # Get payer and procedure names
        payer = self.kb.get_payer(submission["payer_id"])
        procedure = self.kb.get_procedure(submission["procedure_id"])
        payer_name = payer["name"] if payer else "Unknown payer"
        procedure_name = procedure["name"] if procedure else "Unknown procedure"

        if missing_items:
            # Build lesson from the primary missing item
            primary = missing_items[0]
            desc = primary["description"]
            lesson = f"{payer_name} denied {procedure_name}: {desc.lower()}. " \
                     f"Ensure this is documented before submitting."
        elif category == "not_medically_necessary":
            lesson = f"{payer_name} denied {procedure_name} for medical necessity. " \
                     f"Review payer's specific medical necessity criteria " \
                     f"and ensure all elements are documented."
        elif category == "not_covered":
            lesson = f"{payer_name} does not cover {procedure_name} " \
                     f"under patient's plan. Verify coverage before submitting."
        elif category == "prior_auth_required":
            lesson = f"{payer_name} requires prior authorization for {procedure_name}. " \
                     f"Obtain pre-auth before providing service."
        elif category == "out_of_network":
            lesson = f"{payer_name} denied {procedure_name}: out-of-network provider. " \
                     f"Refer to in-network or request exception."
        else:
            lesson = f"{payer_name} denied {procedure_name}: {analysis.get('denial_reason', 'Unknown reason')}"

        return lesson

    def process_approval(self, submission_id: int,
                          auth_number: str = None) -> dict:
        """
        Process an approval — update submission status and optionally
        record what worked (for positive learning).

        Args:
            submission_id: The approved submission
            auth_number: Pre-authorization number from payer

        Returns:
            dict with status info
        """
        submission = self.kb.get_submission(submission_id)
        if not submission:
            return {"error": f"Submission {submission_id} not found"}

        self.kb.update_submission_status(
            submission_id, "approved", auth_number=auth_number
        )

        # Positive learning: if this submission included items that were
        # learned from past denials, the lesson is reinforced.
        # The included_items field records what was submitted.
        included = submission.get("included_items", [])
        if isinstance(included, str):
            import json
            included = json.loads(included) if included else []

        # Check if any included items match learned requirements
        requirements = self.kb.get_requirements(
            submission["payer_id"], submission["procedure_id"]
        )
        learned_reqs = [r for r in requirements if r.get("learned_from_denial")]

        reinforced = []
        for req in learned_reqs:
            for item in included:
                if isinstance(item, str) and req["requirement_desc"][:20] in item:
                    reinforced.append(req["requirement_desc"])
                    break

        return {
            "status": "approved",
            "submission_updated": True,
            "auth_number": auth_number,
            "reinforced_requirements": reinforced,
            "message": "Submission approved and logged. " +
                       (f"{len(reinforced)} learned requirements were validated."
                        if reinforced else ""),
        }

    def get_learning_summary(self, payer_name: str = None,
                               procedure_name: str = None) -> dict:
        """
        Get a summary of what has been learned so far.

        Useful for the practitioner to see accumulated knowledge:
        "What do we know about BCBS + Lumbar MRI?"
        """
        payer = self.kb.get_payer_by_name(payer_name) if payer_name else None
        procedure = self.kb.get_procedure_by_name(procedure_name) if procedure_name else None

        summary = {
            "payer": payer_name,
            "procedure": procedure_name,
            "total_requirements": 0,
            "learned_from_denials": 0,
            "total_submissions": 0,
            "total_denials": 0,
            "approval_rate": "N/A",
            "lessons": [],
            "top_denial_reasons": [],
        }

        if not payer:
            return summary

        payer_id = payer["id"]
        procedure_id = procedure["id"] if procedure else None

        # Requirements
        if procedure_id:
            reqs = self.kb.get_requirements(payer_id, procedure_id)
            summary["total_requirements"] = len(reqs)
            summary["learned_from_denials"] = sum(
                1 for r in reqs if r.get("learned_from_denial")
            )

        # Submissions
        submissions = self.kb.list_submissions(payer_id=payer_id, limit=100)
        summary["total_submissions"] = len(submissions)
        decided = [s for s in submissions
                   if s["status"] in ("approved", "denied", "denied_appealable")]
        approved = [s for s in submissions if s["status"] == "approved"]
        if decided:
            summary["approval_rate"] = f"{len(approved)}/{len(decided)} ({round(len(approved)/len(decided)*100)}%)"

        # Denials
        denials = self.kb.get_denials_by_payer(payer_id)
        summary["total_denials"] = len(denials)

        # Top denial reasons (by category)
        from collections import Counter
        if procedure_id:
            proc_denials = self.kb.get_denials_by_payer_procedure(payer_id, procedure_id)
            categories = Counter()
            for d in proc_denials:
                categories[d.get("denial_category", "unknown")] += 1
            summary["top_denial_reasons"] = [
                f"{cat}: {count} times" for cat, count in categories.most_common(5)
            ]

        # Lessons
        lessons = self.kb.get_lessons(payer_id=payer_id, procedure_id=procedure_id)
        summary["lessons"] = [l["lesson"] for l in lessons[:10]]

        return summary