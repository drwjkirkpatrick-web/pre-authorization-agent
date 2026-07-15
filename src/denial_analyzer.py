"""
Denial Analyzer — Parse insurance denial letters and extract structured data.

Handles three input formats:
  1. Text pasted from insurance portal or email
  2. Digital PDF (pdfplumber extracts text)
  3. Scanned image / scanned PDF (OCR via pytesseract, or Hermes vision)

The analyzer extracts:
  - Denial reason code (e.g., PR-1, CO-50, CO-97)
  - Denial reason narrative
  - Category (missing_info, not_medically_necessary, not_covered, etc.)
  - What was missing (structured list)
  - Whether appealable
  - Appeal deadline
  - Policy cited
  - Raw text for reference

CRITICAL: This module analyzes only. It does not fabricate information.
If the denial text is ambiguous, it flags uncertainty rather than guessing.
"""

import re
import json
import os
from pathlib import Path
from typing import Optional
from datetime import date, timedelta


# ─── Denial Reason Code Patterns ─────────────────────────────────────────
# Standard Claim Adjustment Reason Codes (CARC) used by most US insurers.
# Reference: https://x12.org/codes/claim-adjustment-reason-codes
# These are the most common ones a small practice will encounter.

CARC_CODES = {
    "CO-16": "Claim/service lacks information needed for adjudication",
    "CO-18": "Exact duplicate claim/service",
    "CO-19": "This is a work-related injury/illness",
    "CO-22": "This care may be covered by another payer per coordination of benefits",
    "CO-24": "Charges are covered under a capitation agreement",
    "CO-27": "Expenses incurred after coverage terminated",
    "CO-29": "The time limit for filing has expired",
    "CO-45": "Charge exceeds fee schedule/maximum allowable",
    "CO-50": "Non-covered services: not deemed medically necessary",
    "CO-55": "Service not covered by primary payer",
    "CO-96": "Non-covered charges",
    "CO-97": "Payment is included in the allowance for another service/procedure",
    "CO-109": "Claim not covered by this payer; submit to other payer",
    "CO-151": "Payment adjusted because payer deems service not medically necessary",
    "CO-167": "Diagnosis not covered",
    "CO-204": "Service not covered under patient's current benefit plan",
    "PR-1": "Deductible amount",
    "PR-2": "Coinsurance amount",
    "PR-49": "Routine examination not covered",
    "PR-119": "Benefit maximum for this time period reached",
}

# ─── Denial Category Classification ──────────────────────────────────────
# Maps denial patterns to categories that determine next steps.

DENIAL_CATEGORIES = {
    "missing_info": {
        "keywords": ["lacks information", "additional information", "missing",
                      "incomplete", "documentation required", "not provided",
                      "insufficient documentation", "need additional",
                      "submitted information does not support", "does not support",
                      "no documentation", "not documented"],
        "description": "The submission was missing required information. "
                       "This is fixable — gather the missing items and resubmit.",
        "is_fixable": True,
    },
    "not_medically_necessary": {
        "keywords": ["not medically necessary", "medical necessity not established",
                      "not medically necessary", "no medical necessity",
                      "does not meet medical necessity", "not supported",
                      "insufficient to support", "not sufficient to establish",
                      "criteria not met", "guideline not met",
                      "does not meet criteria", "failed to meet"],
        "description": "The payer determined the procedure is not medically necessary "
                       "based on what was submitted. May need more documentation, "
                       "different diagnosis support, or appeal.",
        "is_fixable": True,  # Often fixable with better documentation
    },
    "not_covered": {
        "keywords": ["not covered", "not a covered benefit", "excluded",
                      "non-covered service", "benefit plan does not cover",
                      "not covered under", "exclusion", "not a covered service"],
        "description": "The procedure is not covered under the patient's plan. "
                       "This is a plan/benefit issue, not a documentation issue. "
                       "May need appeal or alternative procedure.",
        "is_fixable": False,
    },
    "prior_auth_required": {
        "keywords": ["prior authorization required", "preauthorization required",
                      "pre-auth required", "no authorization on file",
                      "authorization required", "obtain prior authorization",
                      "pre-authorization was not obtained"],
        "description": "Prior authorization was required but not obtained. "
                       "This is a process issue — need to obtain pre-auth before service.",
        "is_fixable": True,
    },
    "out_of_network": {
        "keywords": ["out of network", "out-of-network", "non-participating",
                      "not in network", "out of network provider"],
        "description": "The provider/facility is out of network. "
                       "May need to refer to in-network provider or get exception.",
        "is_fixable": False,
    },
    "duplicate": {
        "keywords": ["duplicate", "already paid", "previously submitted",
                      "exact duplicate"],
        "description": "Claim was submitted as a duplicate. "
                       "Check if original was already processed.",
        "is_fixable": False,
    },
    "timely_filing": {
        "keywords": ["timely filing", "time limit", "filing deadline",
                      "not filed timely", "filing limit expired"],
        "description": "Claim was not filed within the timely filing window. "
                       "Difficult to appeal unless extenuating circumstances.",
        "is_fixable": False,
    },
    "other": {
        "keywords": [],
        "description": "Uncategorized denial. Manual review needed.",
        "is_fixable": None,
    },
}

# ─── Missing Item Extraction Patterns ────────────────────────────────────
# These patterns help identify WHAT was specifically missing from the submission.
# The agent uses these to build a remediation checklist.

MISSING_ITEM_PATTERNS = [
    # History / clinical documentation
    {
        "pattern": r"(?i)(history|clinical records|office notes|progress notes|chart notes|medical records)\b.*?(not provided|missing|incomplete|insufficient|not submitted|lacking)",
        "type": "documentation",
        "description": "Clinical documentation / history",
    },
    # Conservative treatment trial
    {
        "pattern": r"(?i)(conservative treatment|conservative therapy|conservative care|physical therapy|PT)\b.*?(not documented|not provided|insufficient|inadequate|not completed|missing|trial.*?not)",
        "type": "prior_treatment",
        "description": "Documented conservative treatment trial",
    },
    # Duration / timeframe
    {
        "pattern": r"(?i)(duration|weeks?|days?|months?|timeframe|timeline)\b.*?(not documented|insufficient|inadequate|not provided|missing)",
        "type": "duration",
        "description": "Duration of symptoms / condition",
    },
    # Lab values
    {
        "pattern": r"(?i)(lab|laboratory|blood work|blood test|TSH|CBC|CRP|ESR|HbA1c|vitamin|metabolic panel|lab values|laboratory results)\b.*?(not provided|missing|not submitted|insufficient|not documented|absent)",
        "type": "lab",
        "description": "Laboratory values/results",
    },
    # Imaging
    {
        "pattern": r"(?i)(imaging|radiograph|x-ray|MRI|CT scan|ultrasound|imaging study|radiology|prior imaging)\b.*?(not provided|missing|not submitted|insufficient|not documented|absent)",
        "type": "imaging",
        "description": "Imaging studies",
    },
    # Physical exam
    {
        "pattern": r"(?i)(physical exam|examination|PE findings|neurological exam|musculoskeletal exam|range of motion|ROM|strength|reflexes)\b.*?(not documented|not provided|insufficient|inadequate|missing|absent)",
        "type": "exam",
        "description": "Physical examination findings",
    },
    # Prior treatments tried
    {
        "pattern": r"(?i)(prior treatment|previous treatment|failed conservative|medication trial|injection|previous therapy|treatment history)\b.*?(not documented|not provided|insufficient|missing|not tried)",
        "type": "prior_treatment",
        "description": "Prior treatments attempted",
    },
    # Diagnosis specificity
    {
        "pattern": r"(?i)(diagnosis|ICD|diagnostic|indication)\b.*?(not specific|insufficient|inadequate|not documented|lacks specificity|not supported)",
        "type": "diagnosis",
        "description": "Diagnosis specificity / ICD coding",
    },
    # Authorization number
    {
        "pattern": r"(?i)(authorization|pre-?auth|pre-?authorization|prior auth)\b.*?(not obtained|required|missing|not on file|not found)",
        "type": "authorization",
        "description": "Prior authorization",
    },
]


class DenialAnalyzer:
    """
    Parse insurance denial letters and extract structured data.

    Usage:
        analyzer = DenialAnalyzer()
        result = analyzer.analyze_text(denial_letter_text)

    The result dict can be passed directly to:
        knowledge_base.add_denial(...)
        learning_loop.update_from_denial(...)
    """

    def __init__(self):
        self.carc_codes = CARC_CODES
        self.categories = DENIAL_CATEGORIES
        self.missing_patterns = MISSING_ITEM_PATTERNS

    # ─── Text Extraction ─────────────────────────────────────────────────

    def extract_text(self, source: str) -> str:
        """
        Extract text from various input formats.

        Args:
            source: One of:
                    - Raw text (pasted from portal/email)
                    - File path to a PDF
                    - File path to an image (PNG, JPG, etc.)

        Returns:
            Extracted text string.

        If the source is already text (no file exists at the path),
            it's returned as-is.
        """
        # If source is a path to an existing file, extract from it
        if os.path.isfile(source):
            ext = Path(source).suffix.lower()

            if ext == ".pdf":
                return self._extract_from_pdf(source)
            elif ext in (".png", ".jpg", ".jpeg", ".tiff", ".bmp", ".webp"):
                return self._extract_from_image(source)
            elif ext == ".txt":
                with open(source, "r", encoding="utf-8") as f:
                    return f.read()
            else:
                # Try PDF first, then OCR
                text = self._extract_from_pdf(source)
                if text.strip():
                    return text
                return self._extract_from_image(source)

        # Otherwise, treat source as raw text
        return source

    def _extract_from_pdf(self, pdf_path: str) -> str:
        """
        Extract text from a digital PDF using pdfplumber.
        Returns empty string if extraction fails or PDF is scanned (image-only).
        """
        try:
            import pdfplumber
            text_parts = []
            with pdfplumber.open(pdf_path) as pdf:
                for page in pdf.pages:
                    page_text = page.extract_text()
                    if page_text:
                        text_parts.append(page_text)
            return "\n\n".join(text_parts)
        except ImportError:
            raise RuntimeError(
                "pdfplumber not installed. Run: pip install pdfplumber"
            )
        except Exception as e:
            # If pdfplumber fails, the PDF might be scanned (image-only).
            # Fall back to OCR if available.
            print(f"  [pdfplumber extraction failed: {e}; trying OCR fallback]")
            return self._extract_from_image(pdf_path)

    def _extract_from_image(self, image_path: str) -> str:
        """
        Extract text from an image or scanned PDF using OCR (pytesseract).

        For higher-quality extraction from scanned denial letters,
        Hermes's vision tool can be used instead — pass the image to
        the vision tool and ask it to transcribe the denial letter.
        """
        try:
            import pytesseract
            from PIL import Image

            # If it's a PDF, convert first page to image for OCR
            if image_path.lower().endswith(".pdf"):
                try:
                    import pdf2image
                    pages = pdf2image.convert_from_path(image_path, dpi=300)
                    text_parts = []
                    for page in pages:
                        text_parts.append(pytesseract.image_to_string(page))
                    return "\n\n".join(text_parts)
                except ImportError:
                    raise RuntimeError(
                        "For scanned PDFs, install pdf2image: pip install pdf2image\n"
                        "Also requires poppler: sudo apt install poppler-utils"
                    )

            # It's an image file — OCR directly
            image = Image.open(image_path)
            return pytesseract.image_to_string(image)
        except ImportError:
            raise RuntimeError(
                "pytesseract not installed for OCR. Options:\n"
                "1. pip install pytesseract Pillow  (requires tesseract binary)\n"
                "2. Use Hermes vision tool: pass the image to the agent\n"
                "   and ask it to transcribe the denial letter."
            )

    # ─── Denial Code Extraction ──────────────────────────────────────────

    def extract_denial_code(self, text: str) -> Optional[str]:
        """
        Extract the denial reason code from the denial letter text.

        Looks for standard CARC codes (CO-XX, PR-XX) and Remittance Advice
        Remark Codes (RARC, N#### or M#### patterns).
        """
        # CARC codes: CO-16, PR-1, CO-50, etc.
        carc_match = re.search(r"\b(CO|PR|OA|PI)-(\d{1,4})\b", text, re.IGNORECASE)
        if carc_match:
            code = f"{carc_match.group(1).upper()}-{carc_match.group(2)}"
            return code

        # RARC codes: N1234, M4567 (4-digit remark codes)
        rarc_match = re.search(r"\b([NM]\d{4})\b", text)
        if rarc_match:
            return rarc_match.group(1)

        # Some payers use "Reason Code" followed by a number
        reason_match = re.search(r"(?i)reason\s*code[:\s]*(\d+)", text)
        if reason_match:
            return f"RC-{reason_match.group(1)}"

        # Some payers use "Denial Code" explicitly
        denial_match = re.search(r"(?i)denial\s*code[:\s]*(\w+)", text)
        if denial_match:
            return denial_match.group(1)

        return None

    def get_code_description(self, code: str) -> Optional[str]:
        """Get the standard description for a CARC code, if known."""
        return self.carc_codes.get(code)

    # ─── Category Classification ─────────────────────────────────────────

    def classify_denial(self, text: str) -> tuple[str, dict]:
        """
        Classify the denial into a category based on keywords in the text.

        Returns:
            (category_name, category_info_dict)

        The category_info includes:
            - description: Human-readable explanation
            - is_fixable: Whether this can be fixed by resubmission
            - keywords_matched: Which keywords triggered the classification
        """
        text_lower = text.lower()
        best_category = "other"
        best_score = 0
        matched_keywords = []

        for category_name, info in self.categories.items():
            if category_name == "other":
                continue

            score = 0
            cat_matches = []
            for kw in info["keywords"]:
                if kw in text_lower:
                    score += 1
                    cat_matches.append(kw)

            if score > best_score:
                best_score = score
                best_category = category_name
                matched_keywords = cat_matches

        result_info = self.categories[best_category].copy()
        result_info["keywords_matched"] = matched_keywords
        return best_category, result_info

    # ─── Missing Items Extraction ────────────────────────────────────────

    def extract_missing_items(self, text: str) -> list[dict]:
        """
        Extract what was specifically missing from the submission.

        Returns a list of dicts, each with:
            - type: "documentation", "lab", "exam", "imaging", etc.
            - description: Human-readable description of what's needed
            - context: The matching text snippet (for Walker's review)
        """
        missing_items = []
        seen_types = set()  # Avoid too many duplicates of the same type

        for pattern_info in self.missing_patterns:
            matches = re.finditer(pattern_info["pattern"], text,
                                  re.IGNORECASE | re.DOTALL)
            for match in matches:
                # Extract surrounding context (±100 chars)
                start = max(0, match.start() - 50)
                end = min(len(text), match.end() + 50)
                context = text[start:end].replace("\n", " ").strip()

                item = {
                    "type": pattern_info["type"],
                    "description": pattern_info["description"],
                    "context": context,
                }

                # Deduplicate by type+description (keep first match per type)
                key = (item["type"], item["description"])
                if key not in seen_types:
                    missing_items.append(item)
                    seen_types.add(key)

        return missing_items

    # ─── Appeal Deadline Extraction ──────────────────────────────────────

    def extract_appeal_deadline(self, text: str) -> Optional[str]:
        """
        Extract the appeal deadline from the denial letter.

        Returns ISO date string (YYYY-MM-DD) or None.
        """
        # Pattern 1: "appeal within X days"
        days_match = re.search(
            r"(?i)(appeal|appeal.*?must be filed|file.*?appeal).*?"
            r"within\s+(\d+)\s+(?:calendar\s+)?days?",
            text
        )
        if days_match:
            days = int(days_match.group(2))
            deadline = date.today() + timedelta(days=days)
            return deadline.isoformat()

        # Pattern 2: "appeal by [date]"
        date_match = re.search(
            r"(?i)(appeal.*?by|appeal.*?no later than|appeal.*?deadline)"
            r"\s*[:\-]?\s*(\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4})",
            text
        )
        if date_match:
            date_str = date_match.group(2)
            return self._parse_date(date_str)

        # Pattern 3: "X days from the date of this letter/notice"
        days_from_match = re.search(
            r"(?i)(\d+)\s+(?:calendar\s+)?days?\s+from.*?(?:date of|this letter|this notice|date of this)",
            text
        )
        if days_from_match:
            days = int(days_from_match.group(1))
            deadline = date.today() + timedelta(days=days)
            return deadline.isoformat()

        return None

    def _parse_date(self, date_str: str) -> Optional[str]:
        """Parse a date string into ISO format. Handles common US formats."""
        for fmt in ("%m/%d/%Y", "%m-%d-%Y", "%m/%d/%y", "%m-%d-%y",
                     "%B %d, %Y", "%b %d, %Y"):
            try:
                from datetime import datetime as dt
                parsed = dt.strptime(date_str.strip(), fmt)
                return parsed.date().isoformat()
            except ValueError:
                continue
        return None

    # ─── Policy Citation Extraction ──────────────────────────────────────

    def extract_policy_citation(self, text: str) -> Optional[str]:
        """
        Extract the medical necessity policy cited in the denial.

        Looks for patterns like:
            - "Medical Policy #X-1234"
            - "Policy XYZ-001"
            - "per policy document XYZ"
            - "based on medical necessity criteria"
        """
        patterns = [
            r"(?i)(medical\s+(?:necessity\s+)?policy|policy\s+(?:number|#|code))\s*[:#]?\s*([A-Z0-9\-]+)",
            r"(?i)(policy\s+document|policy\s+guideline)\s*[:#]?\s*([A-Z0-9\-]+)",
            r"(?i)(clinical\s+(?:policy|guideline))\s*[:#]?\s*([A-Z0-9\-]+)",
            r"(?i)(per|according to|based on)\s+(?:our\s+)?(?:medical\s+)?policy\s*[:#]?\s*([A-Z0-9\-]+)",
            r"(?i)(medical necessity (?:criteria|guideline|policy))",
        ]

        for pattern in patterns:
            match = re.search(pattern, text)
            if match:
                # Return full match (policy label + code if present)
                return match.group(0).strip()

        return None

    # ─── Full Analysis ────────────────────────────────────────────────────

    def analyze_text(self, text: str) -> dict:
        """
        Fully analyze a denial letter text and return structured data.

        This is the main entry point. Pass in denial letter text (pasted,
        extracted from PDF, or OCR'd from an image).

        Returns dict with:
            - denial_code: str or None
            - denial_code_desc: str or None (standard CARC description)
            - denial_reason: str (best-effort narrative extracted from text)
            - denial_category: str (categorized type)
            - category_description: str (what this category means)
            - is_fixable: bool or None (can this be fixed by resubmission?)
            - missing_items: list[dict] (what was specifically missing)
            - is_appealable: bool (based on text analysis)
            - appeal_deadline: str (ISO date) or None
            - policy_cited: str or None
            - raw_text: str (full text for reference)
            - uncertainty_flags: list[str] (things that need Walker's review)
        """
        uncertainty_flags = []

        # Extract denial code
        denial_code = self.extract_denial_code(text)
        denial_code_desc = self.get_code_description(denial_code) if denial_code else None

        # Classify denial category
        category, cat_info = self.classify_denial(text)
        is_fixable = cat_info.get("is_fixable")

        # If no category keywords matched, flag for manual review
        if category == "other":
            uncertainty_flags.append(
                "Could not automatically categorize this denial. "
                "Manual review recommended."
            )

        # Extract missing items
        missing_items = self.extract_missing_items(text)
        if not missing_items and is_fixable:
            uncertainty_flags.append(
                "No specific missing items detected, but denial appears fixable. "
                "Manual review needed to identify what's missing."
            )

        # Extract appeal deadline
        appeal_deadline = self.extract_appeal_deadline(text)
        is_appealable = appeal_deadline is not None or is_fixable is not False

        # If "not covered" or "out of network", likely not appealable via resubmission
        if category in ("not_covered", "out_of_network"):
            is_appealable = False

        # Extract policy citation
        policy_cited = self.extract_policy_citation(text)

        # Extract denial reason narrative
        # Look for the main denial statement in the text
        denial_reason = self._extract_denial_reason(text)
        if not denial_reason:
            uncertainty_flags.append(
                "Could not extract a clear denial reason statement. "
                "Full text has been preserved for manual review."
            )

        return {
            "denial_code": denial_code,
            "denial_code_desc": denial_code_desc,
            "denial_reason": denial_reason,
            "denial_category": category,
            "category_description": cat_info.get("description", ""),
            "is_fixable": is_fixable,
            "missing_items": missing_items,
            "is_appealable": is_appealable,
            "appeal_deadline": appeal_deadline,
            "policy_cited": policy_cited,
            "raw_text": text,
            "uncertainty_flags": uncertainty_flags,
        }

    def _extract_denial_reason(self, text: str) -> Optional[str]:
        """
        Extract the main denial reason statement from the letter.

        Looks for common patterns:
            - "We are denying... because..."
            - "This request is denied..."
            - "After review, we have determined..."
            - "The service is not medically necessary..."
            - "Coverage is denied..."
        """
        patterns = [
            # Direct denial statement
            r"(?i)((?:we|this|the|your)\s+(?:are\s+)?(?:denying|denied|is\s+denied|has\s+been\s+denied)[^.]*\.)",
            # Medical necessity determination
            r"(?i)((?:after|upon)\s+review[,.]?\s+[^.]*?(?:not\s+medically\s+necessary|not\s+meet|does\s+not\s+meet)[^.]*\.)",
            # Coverage determination
            r"(?i)(coverage\s+(?:is\s+)?denied[^.]*\.)",
            # Not covered / not authorized
            r"(?i)((?:this|the)\s+(?:service|procedure|request)[^.]*?(?:not\s+(?:covered|authorized|medically\s+necessary))[^.]*\.)",
            # Generic determination
            r"(?i)((?:we|the)\s+(?:have\s+)?(?:determined|concluded)[^.]*?(?:not|denied|not\s+covered)[^.]*\.)",
        ]

        for pattern in patterns:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                reason = match.group(1).strip()
                # Clean up whitespace
                reason = re.sub(r"\s+", " ", reason)
                # Limit to reasonable length
                if len(reason) > 500:
                    reason = reason[:497] + "..."
                return reason

        # If no pattern matched, try to find the paragraph with "denied" in it
        paragraphs = text.split("\n\n")
        for para in paragraphs:
            if "denied" in para.lower() and len(para) > 20:
                reason = re.sub(r"\s+", " ", para.strip())
                if len(reason) > 500:
                    reason = reason[:497] + "..."
                return reason

        return None

    def analyze_file(self, file_path: str) -> dict:
        """
        Analyze a denial letter from a file (PDF, image, or text file).

        Extracts text from the file, then runs the full analysis.
        """
        text = self.extract_text(file_path)
        if not text.strip():
            return {
                "error": f"No text could be extracted from {file_path}",
                "raw_text": "",
                "uncertainty_flags": ["Text extraction failed. Manual review needed."],
            }
        return self.analyze_text(text)

    # ─── Remediation Checklist ───────────────────────────────────────────

    def generate_remediation_checklist(self, analysis: dict) -> list[str]:
        """
        Generate a remediation checklist from the denial analysis.

        Returns a list of actionable steps the practitioner should take
        before resubmitting. Each step is specific and actionable.

        CRITICAL: These are steps to COLLECT GENUINE information, not
        fabricate it. If a test wasn't done, the step is "order/perform this test",
        not "document that this test was done."
        """
        checklist = []

        category = analysis.get("denial_category", "")
        missing_items = analysis.get("missing_items", [])
        is_fixable = analysis.get("is_fixable")

        if is_fixable is False:
            if category == "not_covered":
                checklist.append("☐ This procedure may not be covered under the patient's plan.")
                checklist.append("  → Verify patient's specific benefit plan coverage.")
                checklist.append("  → Consider alternative covered procedures.")
                checklist.append("  → If patient wants to proceed, discuss self-pay options.")
            elif category == "out_of_network":
                checklist.append("☐ Provider/facility is out of network.")
                checklist.append("  → Refer to in-network provider if available.")
                checklist.append("  → Request network exception if clinically necessary.")
            elif category == "timely_filing":
                checklist.append("☐ Claim filed outside timely filing window.")
                checklist.append("  → Gather documentation of extenuating circumstances.")
                checklist.append("  → File appeal with justification for late submission.")
            else:
                checklist.append("☐ This denial may not be fixable by resubmission.")
                checklist.append("  → Review denial carefully.")
                checklist.append("  → Consider formal appeal if appropriate.")
            return checklist

        # Fixable denial — build checklist from missing items
        if missing_items:
            checklist.append("═══ REMEDIATION CHECKLIST ═══")
            checklist.append("")
            checklist.append("Before resubmitting, collect the following:")
            checklist.append("")

            for item in missing_items:
                item_type = item["type"]
                desc = item["description"]
                context = item.get("context", "")

                if item_type == "documentation":
                    checklist.append(f"☐ {desc}:")
                    checklist.append(f"  → Ensure clinical notes document: {context.strip()}")
                    checklist.append("  → Include relevant office/progress notes with resubmission.")
                elif item_type == "lab":
                    checklist.append(f"☐ {desc}:")
                    checklist.append(f"  → Order or obtain the missing laboratory tests.")
                    checklist.append(f"  → Include results with resubmission: {context.strip()}")
                    checklist.append("  → Ensure values meet medical necessity thresholds.")
                elif item_type == "exam":
                    checklist.append(f"☐ {desc}:")
                    checklist.append(f"  → Perform and document the required examination.")
                    checklist.append(f"  → Include exam findings in resubmission: {context.strip()}")
                elif item_type == "imaging":
                    checklist.append(f"☐ {desc}:")
                    checklist.append(f"  → Obtain or order the required imaging studies.")
                    checklist.append(f"  → Include imaging reports with resubmission: {context.strip()}")
                elif item_type == "prior_treatment":
                    checklist.append(f"☐ {desc}:")
                    checklist.append(f"  → Document conservative treatments tried and their outcomes.")
                    checklist.append(f"  → Include therapy records if available: {context.strip()}")
                    checklist.append("  → If no trial was done, initiate one before resubmitting.")
                elif item_type == "duration":
                    checklist.append(f"☐ {desc}:")
                    checklist.append(f"  → Document symptom duration in clinical notes.")
                    checklist.append(f"  → Ensure timeframe meets payer criteria: {context.strip()}")
                elif item_type == "diagnosis":
                    checklist.append(f"☐ {desc}:")
                    checklist.append("  → Verify ICD-10 code specificity.")
                    checklist.append(f"  → Ensure diagnosis supports medical necessity: {context.strip()}")
                elif item_type == "authorization":
                    checklist.append(f"☐ {desc}:")
                    checklist.append("  → Obtain prior authorization BEFORE providing service.")
                else:
                    checklist.append(f"☐ {desc}:")
                    checklist.append(f"  → Review and address: {context.strip()}")

            checklist.append("")
            checklist.append("═══ AFTER COLLECTING ═══")
            checklist.append("")
            checklist.append("☐ Re-run the pre-submission checklist to verify all items are present.")
            checklist.append("☐ Draft updated letter of medical necessity.")
            checklist.append("☐ Attach all supporting documentation.")
            checklist.append("☐ Submit to payer with reference to original denial.")
            checklist.append("☐ Log the resubmission in the knowledge base.")
        else:
            # Fixable but no specific missing items detected
            checklist.append("═══ REMEDIATION CHECKLIST ═══")
            checklist.append("")
            checklist.append("The denial appears fixable, but specific missing items")
            checklist.append("could not be automatically identified.")
            checklist.append("")
            checklist.append("Recommended steps:")
            checklist.append("☐ Review the full denial text carefully.")
            checklist.append("☐ Call the payer's pre-auth line for specifics.")
            checklist.append("☐ Cross-check with payer's medical necessity policy.")
            if analysis.get("policy_cited"):
                checklist.append(f"  → Policy cited: {analysis['policy_cited']}")
            checklist.append("☐ Identify what additional documentation is needed.")
            checklist.append("☐ Resubmit with additional information.")

        return checklist