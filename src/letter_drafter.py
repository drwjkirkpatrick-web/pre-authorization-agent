"""
Letter Drafter — Generate letters of medical necessity for pre-authorization.

Takes the completed checklist + clinical information and drafts a properly
formatted letter of medical necessity that addresses each required element.

CRITICAL SAFETY RULES:
  - DRAFT ONLY: Walker must review and sign before submission.
  - NO FABRICATION: If a clinical finding isn't provided, it's marked as
    [MISSING — TO BE COMPLETED] in the letter, never invented.
  - NO CODE FABRICATION: ICD-10 and CPT codes are only included if
    Walker provided them. Otherwise, placeholders are used.
  - NO GUIDELINE CLAIMS: The agent does not claim "per ASRA guidelines..."
    unless Walker supplies the specific reference.
"""

import os
from datetime import date
from typing import Optional
from payer_knowledge_base import PayerKnowledgeBase
from checklist_generator import ChecklistGenerator


class LetterDrafter:
    """
    Draft letters of medical necessity for pre-authorization submissions.

    Usage:
        drafter = LetterDrafter(kb)
        letter = drafter.draft_letter(
            payer_name="BCBS of Oregon",
            procedure_name="Lumbar MRI",
            clinical_info={...},
            practice_info={...},
        )

    The letter is a DRAFT. Walker must review, edit, and sign.
    """

    def __init__(self, knowledge_base: PayerKnowledgeBase):
        self.kb = knowledge_base
        self.checklist_gen = ChecklistGenerator(knowledge_base)

    def draft_letter(self, payer_name: str, procedure_name: str,
                     clinical_info: dict = None,
                     practice_info: dict = None,
                     patient_info: dict = None) -> dict:
        """
        Draft a letter of medical necessity.

        Args:
            payer_name: Insurance company name
            procedure_name: Procedure being requested
            clinical_info: dict with clinical details:
                {
                    "diagnosis": "Lumbar radiculopathy",
                    "icd10_code": "M54.16",  # only if Walker confirmed
                    "cpt_code": "72148",      # only if Walker confirmed
                    "age_range": "40-49",
                    "sex": "F",
                    "symptom_duration": "8 weeks",
                    "symptom_description": "Lower back pain radiating to left leg",
                    "history": ["Chronic lower back pain x 8 weeks", ...],
                    "exam": ["Positive straight leg raise left side", ...],
                    "labs": {"CRP": "normal", "ESR": "normal"},
                    "imaging": ["Lumbar X-ray: mild disc space narrowing L4-L5"],
                    "prior_treatments": ["6 weeks PT", "NSAIDs x 6 weeks", ...],
                    "conservative_trial_duration": "6 weeks",
                    "functional_impact": "Unable to sit > 30 min, difficulty walking",
                    "red_flags": ["No bowel/bladder dysfunction", ...],
                }
            practice_info: dict with practice details:
                {
                    "practice_name": "Dr. Walker Clinic",
                    "practice_address": "123 Main St, Portland, OR 97201",
                    "practice_phone": "503-555-0100",
                    "practice_fax": "503-555-0101",
                    "npi": "1234567890",
                    "clinician_name": "Walker Kirkpatrick, ND",
                }
            patient_info: dict with DE-IDENTIFIED patient details:
                {
                    "member_id": "MEM123456",  # from insurance card
                    "group_id": "GRP789",
                    "patient_name": "[TO BE COMPLETED WITH PATIENT INFO]",
                    "patient_dob": "[TO BE COMPLETED]",
                }
                NOTE: Patient identifiers are NOT stored in the knowledge base.
                They are only used in the letter template and must be filled
                in by Walker before submission.

        Returns:
            dict with:
              - letter_text: str (the drafted letter)
              - checklist: dict (the checklist used to build the letter)
              - missing_fields: list[str] (fields marked [MISSING])
              - attachments: list[str] (recommended attachments)
              - warnings: list[str] (items needing Walker's attention)
        """
        clinical_info = clinical_info or {}
        practice_info = practice_info or {}
        patient_info = patient_info or {}

        # Generate the checklist to ensure all requirements are addressed
        checklist = self.checklist_gen.generate(
            payer_name, procedure_name, clinical_info
        )

        # Build the letter
        letter_parts = []
        missing_fields = []
        warnings = []
        attachments = []

        # ─── Header ────────────────────────────────────────────────────
        practice_name = practice_info.get("practice_name", "[PRACTICE NAME]")
        practice_addr = practice_info.get("practice_address", "[PRACTICE ADDRESS]")
        practice_phone = practice_info.get("practice_phone", "[PRACTICE PHONE]")
        practice_fax = practice_info.get("practice_fax", "[PRACTICE FAX]")
        clinician = practice_info.get("clinician_name", "[CLINICIAN NAME]")
        npi = practice_info.get("npi", "[NPI]")

        letter_parts.append(self._header(
            practice_name, practice_addr, practice_phone, practice_fax,
            clinician, npi
        ))

        # ─── Date ─────────────────────────────────────────────────────
        letter_parts.append(date.today().strftime("%B %d, %Y"))

        # ─── Recipient (Payer) ─────────────────────────────────────────
        letter_parts.append(self._recipient(payer_name))

        # ─── Re: line with patient and procedure info ──────────────────
        member_id = patient_info.get("member_id", "[MEMBER ID]")
        group_id = patient_info.get("group_id", "[GROUP ID]")
        patient_name = patient_info.get("patient_name", "[PATIENT NAME — TO BE COMPLETED]")
        patient_dob = patient_info.get("patient_dob", "[PATIENT DOB — TO BE COMPLETED]")

        if "[TO BE COMPLETED" in patient_name or "[MEMBER" in member_id:
            missing_fields.append("Patient identifying information (name, DOB, member ID)")
            warnings.append("Patient identifiers must be filled in by Walker before submission.")

        letter_parts.append(self._re_line(
            patient_name, patient_dob, member_id, group_id, procedure_name
        ))

        # ─── Salutation ────────────────────────────────────────────────
        letter_parts.append("Dear Pre-Authorization Review:")

        # ─── Opening paragraph ─────────────────────────────────────────
        diagnosis = clinical_info.get("diagnosis", "[DIAGNOSIS — TO BE COMPLETED]")
        icd10 = clinical_info.get("icd10_code")
        cpt = clinical_info.get("cpt_code")

        if "[" in diagnosis:
            missing_fields.append("Diagnosis")

        letter_parts.append(self._opening(
            procedure_name, diagnosis, icd10, cpt, patient_name
        ))

        # ─── Clinical History section ──────────────────────────────────
        history_items = clinical_info.get("history", [])
        duration = clinical_info.get("symptom_duration", "")
        symptom_desc = clinical_info.get("symptom_description", "")

        history_section, hist_missing = self._history_section(
            history_items, duration, symptom_desc
        )
        letter_parts.append(history_section)
        missing_fields.extend(hist_missing)

        # ─── Physical Examination section ───────────────────────────────
        exam_items = clinical_info.get("exam", [])
        exam_section, exam_missing = self._exam_section(exam_items)
        letter_parts.append(exam_section)
        missing_fields.extend(exam_missing)

        # ─── Laboratory Results section ────────────────────────────────
        labs = clinical_info.get("labs", {})
        if labs:
            letter_parts.append(self._labs_section(labs))
        else:
            # Check if labs are required
            lab_reqs = [i for i in checklist["items"] if i["type"] == "lab"
                        and i["status"] == "missing"]
            if lab_reqs:
                missing_fields.append("Laboratory values (required by payer)")
                letter_parts.append(self._labs_missing_section(lab_reqs))

        # ─── Imaging section ───────────────────────────────────────────
        imaging = clinical_info.get("imaging", [])
        letter_parts.append(self._imaging_section(imaging))

        # ─── Prior Treatment / Conservative Trial ──────────────────────
        prior_tx = clinical_info.get("prior_treatments", [])
        trial_duration = clinical_info.get("conservative_trial_duration", "")
        functional_impact = clinical_info.get("functional_impact", "")

        tx_section, tx_missing = self._prior_treatment_section(
            prior_tx, trial_duration, functional_impact
        )
        letter_parts.append(tx_section)
        missing_fields.extend(tx_missing)

        # ─── Medical Necessity Justification ───────────────────────────
        letter_parts.append(self._medical_necessity_section(
            procedure_name, diagnosis, checklist, clinical_info
        ))

        # ─── Red flags / urgency ────────────────────────────────────────
        red_flags = clinical_info.get("red_flags", [])
        if red_flags:
            letter_parts.append(self._red_flags_section(red_flags))

        # ─── Request for Authorization ──────────────────────────────────
        letter_parts.append(self._request_section(procedure_name))

        # ─── Attachments list ───────────────────────────────────────────
        attachments = self._build_attachments_list(checklist, clinical_info)
        letter_parts.append(self._attachments_section(attachments))

        # ─── Closing ────────────────────────────────────────────────────
        letter_parts.append(self._closing(clinician))

        # ─── Compile letter ─────────────────────────────────────────────
        letter_text = "\n\n".join(letter_parts)

        # Add draft watermark at top
        draft_notice = (
            "═══════════════════════════════════════════════════════════\n"
            "  ⚠️  DRAFT — DO NOT SUBMIT WITHOUT CLINICIAN REVIEW  ⚠️\n"
            "  This letter was generated by the Pre-Authorization Agent.\n"
            "  Walker must review, edit, fill in [MISSING] fields, and sign.\n"
            "═══════════════════════════════════════════════════════════\n\n"
        )
        letter_text = draft_notice + letter_text

        # Deduplicate missing fields
        missing_fields = list(dict.fromkeys(missing_fields))

        return {
            "letter_text": letter_text,
            "checklist": checklist,
            "missing_fields": missing_fields,
            "attachments": attachments,
            "warnings": warnings,
        }

    # ─── Letter Section Builders ──────────────────────────────────────────

    def _header(self, practice, addr, phone, fax, clinician, npi) -> str:
        return f"""{practice}
{addr}
Phone: {phone} | Fax: {fax}
NPI: {npi}
Clinician: {clinician}"""

    def _recipient(self, payer_name) -> str:
        payer = self.kb.get_payer_by_name(payer_name)
        portal = payer.get("portal_url", "") if payer else ""
        fax = payer.get("fax", "") if payer else ""

        lines = [f"{payer_name}", "Pre-Authorization Department"]
        if fax:
            lines.append(f"Fax: {fax}")
        if portal:
            lines.append(f"Portal: {portal}")
        return "\n".join(lines)

    def _re_line(self, name, dob, member_id, group_id, procedure) -> str:
        return f"""RE: Request for Pre-Authorization — {procedure}

Patient Name: {name}
Date of Birth: {dob}
Member ID: {member_id}
Group ID: {group_id}"""

    def _opening(self, procedure, diagnosis, icd10, cpt, patient_name) -> str:
        code_str = ""
        if icd10 or cpt:
            parts = []
            if icd10:
                parts.append(f"ICD-10: {icd10}")
            if cpt:
                parts.append(f"CPT: {cpt}")
            code_str = f" ({', '.join(parts)})"

        return (f"I am requesting pre-authorization for {procedure} for the "
                f"above-named patient. The patient has been evaluated in our "
                f"clinic, and based on clinical findings, this procedure is "
                f"medically necessary for the following diagnosis: {diagnosis}"
                f"{code_str}.")

    def _history_section(self, history_items, duration, symptom_desc) -> tuple[str, list]:
        missing = []
        lines = ["CLINICAL HISTORY"]

        if symptom_desc:
            lines.append(f"The patient presents with {symptom_desc}.")
        else:
            lines.append("[SYMPTOM DESCRIPTION — TO BE COMPLETED]")
            missing.append("Symptom description")

        if duration:
            lines.append(f"Symptom duration: {duration}.")
        else:
            lines.append("[SYMPTOM DURATION — TO BE COMPLETED]")
            missing.append("Symptom duration")

        if history_items:
            lines.append("Relevant history:")
            for h in history_items:
                lines.append(f"  • {h}")
        else:
            lines.append("[DETAILED HISTORY — TO BE COMPLETED]")
            missing.append("Detailed clinical history")

        return "\n".join(lines), missing

    def _exam_section(self, exam_items) -> tuple[str, list]:
        missing = []
        lines = ["PHYSICAL EXAMINATION"]

        if exam_items:
            lines.append("Examination findings supporting medical necessity:")
            for e in exam_items:
                lines.append(f"  • {e}")
        else:
            lines.append("[PHYSICAL EXAMINATION FINDINGS — TO BE COMPLETED]")
            missing.append("Physical examination findings")

        return "\n".join(lines), missing

    def _labs_section(self, labs) -> str:
        lines = ["LABORATORY RESULTS"]
        lines.append("Relevant laboratory values:")
        for test, value in labs.items():
            lines.append(f"  • {test}: {value}")
        return "\n".join(lines)

    def _labs_missing_section(self, lab_reqs) -> str:
        lines = ["LABORATORY RESULTS"]
        lines.append("⚠️  The following laboratory values are required by the payer:")
        for req in lab_reqs:
            lines.append(f"  • {req['description']}")
        lines.append("")
        lines.append("[LAB VALUES — TO BE ORDERED AND INCLUDED BEFORE SUBMISSION]")
        return "\n".join(lines)

    def _imaging_section(self, imaging_items) -> str:
        lines = ["IMAGING"]
        if imaging_items:
            lines.append("Prior imaging studies:")
            for img in imaging_items:
                lines.append(f"  • {img}")
        else:
            lines.append("No prior imaging on file, or [PRIOR IMAGING — TO BE COMPLETED]")
        return "\n".join(lines)

    def _prior_treatment_section(self, prior_tx, trial_duration,
                                   functional_impact) -> tuple[str, list]:
        missing = []
        lines = ["PRIOR TREATMENT / CONSERVATIVE CARE TRIAL"]

        if trial_duration:
            lines.append(f"Conservative treatment trial: {trial_duration}")
        else:
            lines.append("[CONSERVATIVE TREATMENT DURATION — TO BE COMPLETED]")
            missing.append("Conservative treatment trial duration")

        if prior_tx:
            lines.append("Treatments attempted:")
            for tx in prior_tx:
                lines.append(f"  • {tx}")
        else:
            lines.append("[PRIOR TREATMENTS DOCUMENTATION — TO BE COMPLETED]")
            missing.append("Prior treatment documentation")

        if functional_impact:
            lines.append(f"Functional impact: {functional_impact}")

        return "\n".join(lines), missing

    def _medical_necessity_section(self, procedure, diagnosis,
                                    checklist, clinical_info) -> str:
        lines = ["MEDICAL NECESSITY JUSTIFICATION"]

        lines.append(
            f"The requested {procedure} is medically necessary for this "
            f"patient based on the following:"
        )

        # Address each mandatory checklist item that is satisfied
        satisfied_items = [
            i for i in checklist["items"]
            if i["mandatory"] and i["status"] in ("satisfied", "check")
        ]

        for item in satisfied_items:
            lines.append(f"  • {item['description']}")

        # Note any items learned from denials
        learned_items = [
            i for i in checklist["items"] if i.get("learned_from_denial")
        ]
        if learned_items:
            lines.append("")
            lines.append("The following items are specifically addressed based on "
                        "payer requirements:")
            for item in learned_items:
                lines.append(f"  • {item['description']}")

        return "\n".join(lines)

    def _red_flags_section(self, red_flags) -> str:
        lines = ["CLINICAL CONCERNS / RED FLAGS"]
        for flag in red_flags:
            lines.append(f"  • {flag}")
        return "\n".join(lines)

    def _request_section(self, procedure) -> str:
        return (f"Based on the above clinical findings, I am requesting "
                f"pre-authorization for {procedure}. This procedure is "
                f"medically necessary to guide treatment decisions for this "
                f"patient. I attest that the information provided in this "
                f"letter is accurate and complete to the best of my knowledge.")

    def _build_attachments_list(self, checklist, clinical_info) -> list:
        """Build a list of recommended attachments based on the checklist."""
        attachments = []

        # Standard attachments
        attachments.append("Clinical office/progress notes")
        attachments.append("This letter of medical necessity")

        # Conditional attachments based on what's in the checklist
        for item in checklist["items"]:
            if item["type"] == "imaging" and item["status"] in ("satisfied", "check"):
                attachments.append("Imaging reports")
            elif item["type"] == "lab" and item["status"] in ("satisfied", "check"):
                attachments.append("Laboratory results")
            elif item["type"] == "prior_treatment" and item["status"] in ("satisfied", "check"):
                attachments.append("Conservative treatment records (PT notes, medication history)")
            elif item["type"] == "documentation" and "conservative" in item["description"].lower():
                attachments.append("Therapy/conservative treatment records")

        # Deduplicate
        return list(dict.fromkeys(attachments))

    def _attachments_section(self, attachments) -> str:
        lines = ["ATTACHMENTS"]
        lines.append("The following documentation is enclosed with this request:")
        for i, att in enumerate(attachments, 1):
            lines.append(f"  {i}. {att}")
        return "\n".join(lines)

    def _closing(self, clinician) -> str:
        return (f"I am available to provide additional information if needed. "
                f"Please contact our office with any questions or to discuss "
                f"this request. Thank you for your prompt review.\n\n"
                f"Sincerely,\n\n"
                f"_______________________________\n"
                f"{clinician}")