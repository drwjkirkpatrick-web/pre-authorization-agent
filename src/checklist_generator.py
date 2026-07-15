"""
Checklist Generator — Pre-submission requirements checklist.

Given a procedure + payer, generates a checklist of everything needed
before writing the pre-authorization letter. The checklist is built from:
  1. The knowledge base (learned requirements from past denials)
  2. General medical necessity criteria (fallback when KB is empty)
  3. Lessons learned (higher-level patterns)

If the knowledge base has no entries for this payer+procedure combination,
the agent falls back to general criteria and flags that the checklist
should be supplemented with payer-specific research.
"""

from typing import Optional
from payer_knowledge_base import PayerKnowledgeBase


# ─── General Medical Necessity Criteria ──────────────────────────────────
# Fallback requirements when no payer-specific data exists in the KB yet.
# These are GENERIC patterns common across most insurers for common procedures.
# As denials are processed, these get supplemented/augmented with payer-specific
# requirements in the knowledge base.

GENERAL_CRITERIA = {
    # ─── Imaging ─────────────────────────────────────────────────────────
    "MRI": {
        "history": [
            "Documented symptom duration (typically > 6 weeks)",
            "Failure of conservative treatment trial (PT, meds, activity modification)",
            "Specific neurological or musculoskeletal symptoms warranting imaging",
        ],
        "exam": [
            "Documented physical examination findings supporting imaging need",
            "Neurological deficit or radiculopathy if spinal",
            "Range of motion limitations with specific measurements",
        ],
        "imaging": [
            "Plain radiograph (X-ray) typically required before MRI",
        ],
        "prior_treatment": [
            "6-week conservative treatment trial documented (PT, NSAIDs, activity modification)",
        ],
        "labs": [
            "Relevant labs if indicated (e.g., CRP/ESR for infection, TSH for thyroid)",
        ],
        "documentation": [
            "Office/progress notes covering the treatment period",
            "Conservative treatment records (PT notes, medication history)",
        ],
    },
    "CT Scan": {
        "history": [
            "Clear clinical indication for CT vs alternative imaging",
            "Symptom duration and progression documented",
        ],
        "exam": [
            "Physical exam findings supporting CT need",
        ],
        "prior_treatment": [
            "Relevant prior treatments or imaging documented",
        ],
        "imaging": [
            "Plain radiograph typically required before CT",
        ],
        "labs": [
            "Relevant labs if infection, inflammation, or metabolic workup",
        ],
        "documentation": [
            "Clinical notes supporting the indication",
        ],
    },
    "Ultrasound": {
        "history": [
            "Clear clinical indication for ultrasound",
            "Symptom description and duration",
        ],
        "exam": [
            "Physical exam findings supporting ultrasound need",
        ],
        "documentation": [
            "Clinical notes supporting the indication",
        ],
    },
    # ─── Surgery ─────────────────────────────────────────────────────────
    "Surgery": {
        "history": [
            "Documented failure of conservative treatment (typically 6-12 weeks)",
            "Symptom duration and progression",
            "Impact on activities of daily living",
        ],
        "exam": [
            "Documented physical findings supporting surgical indication",
            "Specific measurements (ROM, strength, special tests)",
        ],
        "imaging": [
            "Appropriate imaging confirming structural pathology",
        ],
        "labs": [
            "Pre-operative labs if indicated",
            "Relevant diagnostic labs supporting the diagnosis",
        ],
        "prior_treatment": [
            "Conservative treatment trial documented (PT, injections, medications)",
            "Duration of conservative treatment (typically 6+ weeks for non-urgent)",
        ],
        "documentation": [
            "All treatment records (therapy notes, injection records, medication trials)",
            "Imaging reports",
            "Clinical progress notes",
        ],
    },
    # ─── Specialist Referral ─────────────────────────────────────────────
    "Specialist": {
        "history": [
            "Reason for referral clearly documented",
            "What question the specialist should answer",
            "Relevant history and prior workup",
        ],
        "exam": [
            "Physical exam findings supporting specialist referral",
        ],
        "prior_treatment": [
            "What has been tried in primary care before referral",
        ],
        "documentation": [
            "Primary care workup and findings",
            "Relevant labs and imaging already obtained",
        ],
    },
    # ─── Therapy / Physical Therapy ──────────────────────────────────────
    "Therapy": {
        "history": [
            "Condition being treated and expected benefit from therapy",
            "Symptom duration and functional impact",
        ],
        "exam": [
            "Physical exam findings supporting therapy need",
            "Functional limitations documented",
        ],
        "prior_treatment": [
            "Home exercise program trial (if applicable)",
            "Prior therapy episodes (if any) with outcomes",
        ],
        "documentation": [
            "Clinical notes with diagnosis and functional status",
            "Therapy prescription with specific goals",
        ],
    },
    # ─── DME / Durable Medical Equipment ──────────────────────────────────
    "DME": {
        "history": [
            "Condition requiring DME documented",
            "Expected duration of DME need",
        ],
        "exam": [
            "Physical exam supporting DME need",
        ],
        "documentation": [
            "Prescription with specific DME item",
            "Clinical justification for DME vs alternatives",
        ],
    },
    # ─── Default / Unknown ───────────────────────────────────────────────
    "Default": {
        "history": [
            "Clear clinical indication documented",
            "Symptom duration and progression",
            "Impact on daily activities",
        ],
        "exam": [
            "Relevant physical examination findings",
        ],
        "prior_treatment": [
            "Conservative treatments attempted and outcomes",
        ],
        "documentation": [
            "Clinical notes covering the treatment period",
            "Results of any prior diagnostic workup",
        ],
    },
}

# ─── Procedure Category Mapping ─────────────────────────────────────────
# Maps procedure names to their general category for fallback criteria.

def _categorize_procedure(procedure_name: str) -> str:
    """
    Categorize a procedure name into a general category for fallback criteria.
    """
    name_lower = procedure_name.lower()

    if "mri" in name_lower or "magnetic resonance" in name_lower:
        return "MRI"
    if "ct " in name_lower or "cat scan" in name_lower or "computed tomography" in name_lower:
        return "CT Scan"
    if "ultrasound" in name_lower or "sonogram" in name_lower or "doppler" in name_lower:
        return "Ultrasound"
    if any(x in name_lower for x in ["surger", "arthroscop", "fusion", "replacement",
                                      "arthroplasty", "laminectomy", "discectomy",
                                      "knee surgery", "hip surgery", "spine surgery"]):
        return "Surgery"
    if any(x in name_lower for x in ["physical therapy", "occupational therapy",
                                      "speech therapy", "PT ", "PT session"]):
        return "Therapy"
    if any(x in name_lower for x in ["referral", "consult", "specialist", "neurology",
                                      "cardiology", "orthopedic", "rheumatology",
                                      "endocrinology", "gastroenterology", "dermatology",
                                      "pulmonology", "nephrology", "hematology"]):
        return "Specialist"
    if any(x in name_lower for x in ["cpap", "wheelchair", "walker", "brace",
                                      "cpap", "oxygen", "nebulizer", "TENS",
                                      "durable medical", "DME", "splint", "orthotic"]):
        return "DME"

    return "Default"


# ─── Checklist Item Priority ─────────────────────────────────────────────

# Priority ordering for checklist display (most critical first)
TYPE_PRIORITY = {
    "prior_treatment": 1,   # Usually the #1 reason for denial
    "exam": 2,              # Physical exam findings are commonly missing
    "history": 3,           # History elements (duration, progression)
    "lab": 4,               # Lab values with thresholds
    "imaging": 5,           # Prior imaging requirements
    "diagnosis": 6,         # Diagnosis specificity
    "duration": 7,          # Timeframe requirements
    "documentation": 8,     # What to attach
    "threshold": 9,         # Specific value thresholds
    "authorization": 10,    # Auth process itself
}


class ChecklistGenerator:
    """
    Generate pre-submission checklists for pre-authorization requests.

    Usage:
        gen = ChecklistGenerator(kb)
        checklist = gen.generate("BCBS of Oregon", "Lumbar MRI")

    The checklist combines:
      1. Knowledge base requirements (learned from past denials)
      2. General medical necessity criteria (fallback)
      3. Lessons learned (patterns from this payer)
    """

    def __init__(self, knowledge_base: PayerKnowledgeBase):
        self.kb = knowledge_base

    def generate(self, payer_name: str, procedure_name: str,
                 clinical_info: dict = None) -> dict:
        """
        Generate a pre-submission checklist.

        Args:
            payer_name: Insurance company name
            procedure_name: Procedure being requested
            clinical_info: Optional dict of clinical info already available,
                           to check against requirements:
                             {
                               "history": [...],
                               "exam": [...],
                               "labs": {...},
                               "imaging": [...],
                               "prior_treatments": [...],
                               "duration": "6 weeks",
                               "diagnosis": "Lumbar radiculopathy",
                             }

        Returns:
            dict with:
              - payer: str
              - procedure: str
              - category: str (procedure category for fallback)
              - items: list[dict] each with:
                  - type: requirement type
                  - description: what's needed
                  - source: "knowledge_base", "general", "lesson_learned"
                  - status: "satisfied", "missing", "unknown", "check"
                  - mandatory: bool
                  - detail: dict or None (thresholds, specific values)
                  - learned_from_denial: bool
              - lessons: list[str] (applicable lessons)
              - using_fallback: bool (True if no KB data for this combo)
              - summary: str (human-readable summary)
        """
        clinical_info = clinical_info or {}

        # Find or create payer and procedure
        payer = self.kb.get_payer_by_name(payer_name)
        procedure = self.kb.get_procedure_by_name(procedure_name)

        # If payer doesn't exist, we can still generate a checklist
        # using general criteria
        payer_id = payer["id"] if payer else None
        procedure_id = procedure["id"] if procedure else None

        # Get KB requirements for this payer+procedure
        kb_requirements = []
        using_fallback = True

        if payer_id and procedure_id:
            kb_requirements = self.kb.get_requirements(payer_id, procedure_id)
            if kb_requirements:
                using_fallback = False

            # Also fetch general requirements (payer_id=0) that apply to all payers
            general_kb_reqs = self.kb.get_requirements(0, procedure_id)
            if general_kb_reqs:
                # Merge: payer-specific take priority, add general ones not already covered
                seen_descs = {r["requirement_desc"] for r in kb_requirements}
                for gr in general_kb_reqs:
                    if gr["requirement_desc"] not in seen_descs:
                        kb_requirements.append(gr)
                if kb_requirements:
                    using_fallback = False

        # Get lessons learned for this payer (and general lessons)
        lessons = []
        if payer_id:
            lessons = self.kb.get_lessons(payer_id=payer_id, procedure_id=procedure_id)

        # If no KB requirements at all, use hardcoded general criteria as fallback
        if not kb_requirements:
            category = _categorize_procedure(procedure_name)
            general = GENERAL_CRITERIA.get(category, GENERAL_CRITERIA["Default"])
            kb_requirements = self._general_to_requirements(general, category)

        # Merge: KB requirements take priority, but add any general ones
        # that aren't already covered
        all_items = self._merge_requirements(kb_requirements, procedure_name)

        # Check each item against provided clinical info
        items = self._check_against_clinical(all_items, clinical_info)

        # Sort by priority
        items.sort(key=lambda x: (
            TYPE_PRIORITY.get(x["type"], 99),
            0 if x["mandatory"] else 1,
            0 if x["status"] == "missing" else 1,
        ))

        # Build summary
        total = len(items)
        satisfied = sum(1 for i in items if i["status"] == "satisfied")
        missing = sum(1 for i in items if i["status"] == "missing")
        unknown = sum(1 for i in items if i["status"] == "unknown")

        if missing > 0:
            summary = (f"⚠️  {missing} of {total} requirements are MISSING. "
                       f"Collect these before submitting.")
        elif unknown > 0:
            summary = (f"📋  {total} requirements. {satisfied} satisfied, "
                       f"{unknown} need verification. Review checklist.")
        else:
            summary = f"✅  All {total} requirements appear satisfied. Ready to draft letter."

        return {
            "payer": payer_name,
            "procedure": procedure_name,
            "category": _categorize_procedure(procedure_name),
            "items": items,
            "lessons": [l["lesson"] for l in lessons],
            "using_fallback": using_fallback,
            "summary": summary,
            "stats": {
                "total": total,
                "satisfied": satisfied,
                "missing": missing,
                "unknown": unknown,
            },
        }

    def _general_to_requirements(self, general: dict, category: str) -> list[dict]:
        """Convert general criteria dict to requirement-like dicts."""
        requirements = []
        for req_type, descs in general.items():
            for desc in descs:
                requirements.append({
                    "requirement_type": req_type,
                    "requirement_desc": desc,
                    "detail": None,
                    "is_mandatory": True,
                    "learned_from_denial": False,
                    "source": "general",
                })
        return requirements

    def _merge_requirements(self, kb_reqs: list[dict],
                             procedure_name: str) -> list[dict]:
        """
        Merge KB requirements with general criteria.
        KB requirements take priority; general criteria supplement gaps.
        """
        # Start with KB requirements
        merged = []
        seen_types_descs = set()

        for req in kb_reqs:
            item = {
                "type": req.get("requirement_type", req.get("type", "")),
                "description": req.get("requirement_desc", req.get("description", "")),
                "detail": req.get("detail"),
                "mandatory": bool(req.get("is_mandatory", True)),
                "learned_from_denial": bool(req.get("learned_from_denial", False)),
                "source": req.get("source", "knowledge_base"),
            }
            merged.append(item)
            seen_types_descs.add((item["type"], item["description"]))

        # If using fallback (no KB data), don't double-add general criteria
        # because kb_reqs IS the general criteria already
        # Only add general criteria if KB had some data but not complete
        if not any(r.get("source") == "general" for r in kb_reqs):
            # KB had real data — supplement with any missing general criteria
            category = _categorize_procedure(procedure_name)
            general = GENERAL_CRITERIA.get(category, GENERAL_CRITERIA["Default"])
            general_reqs = self._general_to_requirements(general, category)

            for gen_req in general_reqs:
                key = (gen_req["requirement_type"], gen_req["requirement_desc"])
                if key not in seen_types_descs:
                    merged.append({
                        "type": gen_req["requirement_type"],
                        "description": gen_req["requirement_desc"],
                        "detail": None,
                        "mandatory": True,
                        "learned_from_denial": False,
                        "source": "general",
                    })

        return merged

    def _check_against_clinical(self, items: list[dict],
                                 clinical_info: dict) -> list[dict]:
        """
        Check each requirement against provided clinical information.

        Marks each item as:
          - "satisfied": Clinical info covers this requirement
          - "missing": Clinical info does NOT cover this requirement
          - "unknown": Cannot determine from available info
        """
        history = clinical_info.get("history", [])
        exam = clinical_info.get("exam", [])
        labs = clinical_info.get("labs", {})
        imaging = clinical_info.get("imaging", [])
        prior_treatments = clinical_info.get("prior_treatments", [])
        duration = clinical_info.get("duration", "")
        diagnosis = clinical_info.get("diagnosis", "")

        for item in items:
            status = "unknown"  # default
            item_type = item["type"]
            desc = item["description"].lower()

            if item_type == "history":
                # Check if any provided history element matches
                for h in history:
                    if any(word in h.lower() for word in desc.split()[:3]):
                        status = "satisfied"
                        break
                if status == "unknown" and history:
                    status = "check"  # some history provided, verify match

            elif item_type == "exam":
                for e in exam:
                    if any(word in e.lower() for word in desc.split()[:3]):
                        status = "satisfied"
                        break
                if status == "unknown" and exam:
                    status = "check"

            elif item_type == "lab":
                # Check if labs dict has entries
                if labs:
                    status = "check"  # labs provided, verify specific values
                else:
                    status = "missing"

            elif item_type == "imaging":
                if imaging:
                    for img in imaging:
                        if any(word in img.lower() for word in desc.split()[:3]):
                            status = "satisfied"
                            break
                    if status == "unknown":
                        status = "check"
                else:
                    status = "missing"

            elif item_type == "prior_treatment":
                if prior_treatments:
                    for pt in prior_treatments:
                        if any(word in pt.lower() for word in desc.split()[:3]):
                            status = "satisfied"
                            break
                    if status == "unknown":
                        status = "check"
                else:
                    status = "missing"

            elif item_type == "duration":
                if duration:
                    status = "satisfied"
                else:
                    status = "missing"

            elif item_type == "diagnosis":
                if diagnosis:
                    status = "satisfied"
                else:
                    status = "missing"

            elif item_type == "documentation":
                # Documentation is always needed; mark as check
                status = "check"

            item["status"] = status

        return items

    def format_checklist(self, checklist: dict) -> str:
        """
        Format the checklist dict as a human-readable string for display.
        """
        lines = []
        payer = checklist["payer"]
        procedure = checklist["procedure"]
        using_fallback = checklist["using_fallback"]

        lines.append(f"═══════════════════════════════════════════════")
        lines.append(f"  PRE-AUTHORIZATION CHECKLIST")
        lines.append(f"  Payer: {payer}")
        lines.append(f"  Procedure: {procedure}")
        lines.append(f"═══════════════════════════════════════════════")
        lines.append("")

        if using_fallback:
            lines.append("⚠️  No payer-specific data in knowledge base yet.")
            lines.append("   Using general medical necessity criteria.")
            lines.append("   After submission, log the result to build the KB.")
            lines.append("")

        # Group items by type
        current_type = None
        type_labels = {
            "history": "HISTORY",
            "exam": "PHYSICAL EXAMINATION",
            "lab": "LABORATORY VALUES",
            "imaging": "IMAGING",
            "prior_treatment": "PRIOR TREATMENT",
            "duration": "DURATION / TIMEFRAME",
            "diagnosis": "DIAGNOSIS",
            "documentation": "DOCUMENTATION TO ATTACH",
            "threshold": "THRESHOLD VALUES",
            "authorization": "AUTHORIZATION",
        }

        status_icons = {
            "satisfied": "✅",
            "missing": "❌",
            "unknown": "❓",
            "check": "🔎",
        }

        for item in checklist["items"]:
            item_type = item["type"]
            if item_type != current_type:
                current_type = item_type
                label = type_labels.get(item_type, item_type.upper())
                lines.append(f"── {label} ──")

            icon = status_icons.get(item["status"], "❓")
            mandatory = "*" if item["mandatory"] else " "
            learned = " [LEARNED FROM DENIAL]" if item["learned_from_denial"] else ""
            source_tag = ""
            if item["source"] == "general":
                source_tag = " (general criteria)"

            lines.append(f"  {icon} {mandatory} {item['description']}{learned}{source_tag}")

            if item.get("detail"):
                for k, v in item["detail"].items():
                    lines.append(f"       → {k}: {v}")

            if item["status"] == "missing":
                lines.append(f"       ⚠️  MISSING — collect this before submitting")
            elif item["status"] == "check":
                lines.append(f"       🔎  Verify this is documented in the chart")

        # Lessons learned
        if checklist.get("lessons"):
            lines.append("")
            lines.append("── LESSONS LEARNED ──")
            for lesson in checklist["lessons"]:
                lines.append(f"  💡 {lesson}")

        lines.append("")
        lines.append(f"━━━ SUMMARY ━━━")
        lines.append(f"  {checklist['summary']}")
        stats = checklist.get("stats", {})
        if stats:
            lines.append(f"  Total: {stats.get('total', 0)} | "
                        f"Satisfied: {stats.get('satisfied', 0)} | "
                        f"Missing: {stats.get('missing', 0)} | "
                        f"Unknown: {stats.get('unknown', 0)}")
        lines.append("")
        lines.append("* = mandatory for approval")
        lines.append("[LEARNED FROM DENIAL] = discovered from a past denial")

        return "\n".join(lines)