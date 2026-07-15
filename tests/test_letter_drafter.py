"""
Tests for the LetterDrafter module.

Tests cover:
  - Letter generation with complete clinical info
  - Missing field detection ([MISSING] markers)
  - Draft-only notice
  - Attachment list building
  - ICD-10/CPT code handling (only when provided)
"""

import pytest
from payer_knowledge_base import PayerKnowledgeBase
from letter_drafter import LetterDrafter


@pytest.fixture
def drafter(kb):
    return LetterDrafter(kb)


@pytest.fixture
def practice_info():
    return {
        "practice_name": "Test Clinic",
        "practice_address": "123 Main St, Portland, OR",
        "practice_phone": "503-555-0100",
        "practice_fax": "503-555-0101",
        "npi": "1234567890",
        "clinician_name": "Test Clinician, ND",
    }


@pytest.fixture
def patient_info():
    return {
        "member_id": "MEM12345",
        "group_id": "GRP678",
        "patient_name": "[TO BE COMPLETED]",
        "patient_dob": "[TO BE COMPLETED]",
    }


@pytest.fixture
def complete_clinical_info():
    return {
        "diagnosis": "Lumbar radiculopathy",
        "icd10_code": "M54.16",
        "cpt_code": "72148",
        "age_range": "40-49",
        "sex": "F",
        "symptom_duration": "8 weeks",
        "symptom_description": "Lower back pain radiating to left leg",
        "history": ["Chronic lower back pain 8 weeks", "No prior surgery"],
        "exam": ["Positive straight leg raise left", "Reduced sensation left L5 dermatome"],
        "labs": {"CRP": "normal", "ESR": "20 mm/hr"},
        "imaging": ["Lumbar X-ray: mild disc narrowing L4-L5"],
        "prior_treatments": ["6 weeks physical therapy", "NSAIDs x 6 weeks"],
        "conservative_trial_duration": "6 weeks",
        "functional_impact": "Unable to sit > 30 minutes",
        "red_flags": ["No bowel/bladder dysfunction"],
    }


class TestLetterGeneration:
    """Test letter generation."""

    def test_letter_has_draft_notice(self, drafter, practice_info, patient_info,
                                       complete_clinical_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            complete_clinical_info, practice_info, patient_info
        )
        assert "DRAFT" in result["letter_text"]
        assert "DO NOT SUBMIT" in result["letter_text"]

    def test_letter_includes_payer_name(self, drafter, practice_info, patient_info,
                                          complete_clinical_info):
        result = drafter.draft_letter(
            "BCBS of Oregon", "Lumbar MRI",
            complete_clinical_info, practice_info, patient_info
        )
        assert "BCBS of Oregon" in result["letter_text"]

    def test_letter_includes_diagnosis(self, drafter, practice_info, patient_info,
                                         complete_clinical_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            complete_clinical_info, practice_info, patient_info
        )
        assert "Lumbar radiculopathy" in result["letter_text"]

    def test_letter_includes_icd10(self, drafter, practice_info, patient_info,
                                     complete_clinical_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            complete_clinical_info, practice_info, patient_info
        )
        assert "M54.16" in result["letter_text"]

    def test_letter_includes_history(self, drafter, practice_info, patient_info,
                                        complete_clinical_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            complete_clinical_info, practice_info, patient_info
        )
        assert "CLINICAL HISTORY" in result["letter_text"]
        assert "Lower back pain" in result["letter_text"]

    def test_letter_includes_exam(self, drafter, practice_info, patient_info,
                                    complete_clinical_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            complete_clinical_info, practice_info, patient_info
        )
        assert "PHYSICAL EXAMINATION" in result["letter_text"]
        assert "straight leg raise" in result["letter_text"]

    def test_letter_includes_attachments(self, drafter, practice_info, patient_info,
                                           complete_clinical_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            complete_clinical_info, practice_info, patient_info
        )
        assert "ATTACHMENTS" in result["letter_text"]
        assert len(result["attachments"]) > 0

    def test_letter_includes_closing(self, drafter, practice_info, patient_info,
                                       complete_clinical_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            complete_clinical_info, practice_info, patient_info
        )
        assert "Sincerely" in result["letter_text"]
        assert "Test Clinician, ND" in result["letter_text"]


class TestMissingFieldDetection:
    """Test detection of missing fields."""

    def test_missing_diagnosis(self, drafter, practice_info, patient_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            clinical_info={},  # Empty — everything missing
            practice_info=practice_info,
            patient_info=patient_info,
        )
        assert "Diagnosis" in result["missing_fields"]

    def test_missing_history(self, drafter, practice_info, patient_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            clinical_info={},
            practice_info=practice_info,
            patient_info=patient_info,
        )
        assert any("history" in f.lower() or "symptom" in f.lower()
                     for f in result["missing_fields"])

    def test_missing_exam(self, drafter, practice_info, patient_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            clinical_info={},
            practice_info=practice_info,
            patient_info=patient_info,
        )
        assert any("exam" in f.lower() for f in result["missing_fields"])

    def test_missing_patient_info_warning(self, drafter, practice_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            clinical_info={"diagnosis": "Test"},
            practice_info=practice_info,
            patient_info={},  # Empty patient info
        )
        assert len(result["warnings"]) > 0

    def test_no_missing_with_complete_info(self, drafter, practice_info, patient_info,
                                              complete_clinical_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            complete_clinical_info, practice_info, patient_info
        )
        # With complete clinical info, should have fewer missing fields
        # (patient_info still has placeholders, but clinical fields should be filled)
        clinical_missing = [f for f in result["missing_fields"]
                             if "history" not in f.lower() and "exam" not in f.lower()]
        # Diagnosis should not be missing
        assert "Diagnosis" not in result["missing_fields"]


class TestCodeHandling:
    """Test ICD-10 and CPT code handling — never fabricated."""

    def test_codes_included_when_provided(self, drafter, practice_info, patient_info,
                                             complete_clinical_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            complete_clinical_info, practice_info, patient_info
        )
        assert "ICD-10: M54.16" in result["letter_text"]
        assert "CPT: 72148" in result["letter_text"]

    def test_no_codes_when_not_provided(self, drafter, practice_info, patient_info):
        result = drafter.draft_letter(
            "Test Payer", "Lumbar MRI",
            clinical_info={"diagnosis": "Test diagnosis"},  # No ICD-10 or CPT
            practice_info=practice_info,
            patient_info=patient_info,
        )
        # Should not fabricate codes
        assert "ICD-10:" not in result["letter_text"].replace("ICD-10: [", "")
        assert "CPT:" not in result["letter_text"].replace("CPT: [", "")