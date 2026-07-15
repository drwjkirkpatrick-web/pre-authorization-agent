"""
Tests for the DenialAnalyzer module.

Tests cover:
  - Denial code extraction (CARC codes, RARC codes, custom formats)
  - Category classification (missing_info, not_medically_necessary, etc.)
  - Missing item extraction (specific gaps in the submission)
  - Appeal deadline extraction
  - Policy citation extraction
  - Full analysis pipeline
  - Remediation checklist generation
"""

import pytest
from denial_analyzer import DenialAnalyzer


@pytest.fixture
def analyzer():
    return DenialAnalyzer()


class TestDenialCodeExtraction:
    """Test denial code extraction from various formats."""

    def test_carc_code(self, analyzer):
        text = "Your claim has been denied. Reason Code: CO-50"
        code = analyzer.extract_denial_code(text)
        assert code == "CO-50"

    def test_pr_code(self, analyzer):
        text = "Denial reason: PR-1 - Deductible amount"
        code = analyzer.extract_denial_code(text)
        assert code == "PR-1"

    def test_rarc_code(self, analyzer):
        text = "Remark Code: N1234 indicates additional information needed"
        code = analyzer.extract_denial_code(text)
        assert code == "N1234"

    def test_reason_code_numeric(self, analyzer):
        text = "Reason Code: 42 - Not covered"
        code = analyzer.extract_denial_code(text)
        assert code == "RC-42"

    def test_no_code_found(self, analyzer):
        text = "This service is not covered under your plan."
        code = analyzer.extract_denial_code(text)
        assert code is None

    def test_get_code_description(self, analyzer):
        desc = analyzer.get_code_description("CO-50")
        assert "medically necessary" in desc.lower()


class TestCategoryClassification:
    """Test denial category classification."""

    def test_missing_info_category(self, analyzer):
        text = ("We are denying this request because the submitted information "
                "does not support medical necessity. Additional documentation "
                "is required including insufficient documentation of "
                "conservative treatment.")
        category, info = analyzer.classify_denial(text)
        assert category == "missing_info"
        assert info["is_fixable"] is True

    def test_not_medically_necessary(self, analyzer):
        text = ("After review, we have determined that this service is "
                "not medically necessary. The criteria for medical necessity "
                "have not been met.")
        category, info = analyzer.classify_denial(text)
        assert category == "not_medically_necessary"

    def test_not_covered(self, analyzer):
        text = "This service is not covered under the patient's current benefit plan."
        category, info = analyzer.classify_denial(text)
        assert category == "not_covered"
        assert info["is_fixable"] is False

    def test_out_of_network(self, analyzer):
        text = "Service denied: provider is out of network."
        category, info = analyzer.classify_denial(text)
        assert category == "out_of_network"

    def test_prior_auth_required(self, analyzer):
        text = "Prior authorization required but was not obtained."
        category, info = analyzer.classify_denial(text)
        assert category == "prior_auth_required"

    def test_timely_filing(self, analyzer):
        text = "Claim denied: time limit for filing has expired."
        category, info = analyzer.classify_denial(text)
        assert category == "timely_filing"

    def test_duplicate(self, analyzer):
        text = "This claim is an exact duplicate of a previously submitted claim."
        category, info = analyzer.classify_denial(text)
        assert category == "duplicate"


class TestMissingItemExtraction:
    """Test extraction of specific missing items from denial text."""

    def test_extract_conservative_treatment(self, analyzer):
        text = ("The denial is due to insufficient documentation of "
                "conservative treatment. Physical therapy was not documented "
                "as required.")
        items = analyzer.extract_missing_items(text)
        assert len(items) > 0
        types = [i["type"] for i in items]
        assert "prior_treatment" in types

    def test_extract_missing_labs(self, analyzer):
        text = ("Laboratory results including CRP and ESR were not provided. "
                "These lab values are required for medical necessity review.")
        items = analyzer.extract_missing_items(text)
        assert len(items) > 0
        types = [i["type"] for i in items]
        assert "lab" in types

    def test_extract_missing_exam(self, analyzer):
        text = ("Physical examination findings including range of motion "
                "and neurological exam were not documented in the submitted "
                "records.")
        items = analyzer.extract_missing_items(text)
        assert len(items) > 0
        types = [i["type"] for i in items]
        assert "exam" in types

    def test_extract_missing_imaging(self, analyzer):
        text = "Prior imaging including X-ray was not provided before MRI request."
        items = analyzer.extract_missing_items(text)
        assert len(items) > 0

    def test_no_missing_items_detected(self, analyzer):
        text = "This service is not a covered benefit under this plan."
        items = analyzer.extract_missing_items(text)
        assert len(items) == 0


class TestAppealDeadline:
    """Test appeal deadline extraction."""

    def test_appeal_within_days(self, analyzer):
        text = "You may appeal this decision within 30 days of receipt of this letter."
        deadline = analyzer.extract_appeal_deadline(text)
        assert deadline is not None
        # Should be approximately 30 days from today

    def test_appeal_by_date(self, analyzer):
        text = "Appeals must be filed by 08/15/2025."
        deadline = analyzer.extract_appeal_deadline(text)
        assert deadline is not None

    def test_no_appeal_deadline(self, analyzer):
        text = "This service is not covered."
        deadline = analyzer.extract_appeal_deadline(text)
        assert deadline is None


class TestPolicyCitation:
    """Test medical necessity policy citation extraction."""

    def test_policy_number(self, analyzer):
        text = "This denial is based on Medical Policy #MRI-2024-001."
        policy = analyzer.extract_policy_citation(text)
        assert policy is not None
        assert "MRI-2024-001" in policy or "Medical Policy" in policy

    def test_no_policy_cited(self, analyzer):
        text = "This service is not covered."
        policy = analyzer.extract_policy_citation(text)
        assert policy is None


class TestFullAnalysis:
    """Test the full analysis pipeline."""

    def test_analyze_text_complete(self, analyzer):
        text = """
        Dear Provider,

        We are denying your request for pre-authorization of Lumbar MRI.

        Denial Code: CO-50
        Reason: Non-covered services: not deemed medically necessary.

        After review, we have determined that the submitted information does
        not support medical necessity. Specifically, documentation of
        conservative treatment including physical therapy was not provided.
        Additionally, physical examination findings were not documented
        in the submitted records.

        You may appeal this decision within 30 days.
        Per Medical Policy #MRI-001.
        """
        result = analyzer.analyze_text(text)

        assert result["denial_code"] == "CO-50"
        assert result["denial_category"] is not None
        assert result["missing_items"] is not None
        assert result["appeal_deadline"] is not None
        assert result["raw_text"] == text

    def test_analyze_text_empty(self, analyzer):
        result = analyzer.analyze_text("")
        assert result["denial_code"] is None
        assert "uncertainty_flags" in result

    def test_analyze_uncertain_text(self, analyzer):
        """Test that ambiguous denials get uncertainty flags."""
        text = "We could not process your request at this time."
        result = analyzer.analyze_text(text)
        assert len(result["uncertainty_flags"]) > 0


class TestRemediationChecklist:
    """Test remediation checklist generation."""

    def test_fixable_denial_checklist(self, analyzer):
        analysis = {
            "denial_category": "missing_info",
            "is_fixable": True,
            "missing_items": [
                {"type": "prior_treatment", "description": "Conservative treatment trial",
                 "context": "Physical therapy was not documented"},
                {"type": "exam", "description": "Physical examination findings",
                 "context": "Exam findings were not documented"},
            ],
        }
        checklist = analyzer.generate_remediation_checklist(analysis)
        assert any("CONSERVATIVE" in c.upper() for c in checklist)
        assert any("EXAMINATION" in c.upper() for c in checklist)

    def test_not_covered_checklist(self, analyzer):
        analysis = {
            "denial_category": "not_covered",
            "is_fixable": False,
            "missing_items": [],
        }
        checklist = analyzer.generate_remediation_checklist(analysis)
        assert any("covered" in c.lower() for c in checklist)

    def test_fixable_no_items_checklist(self, analyzer):
        analysis = {
            "denial_category": "not_medically_necessary",
            "is_fixable": True,
            "missing_items": [],
        }
        checklist = analyzer.generate_remediation_checklist(analysis)
        assert any("review" in c.lower() for c in checklist)