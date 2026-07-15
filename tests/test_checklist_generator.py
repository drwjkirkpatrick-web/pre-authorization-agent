"""
Tests for the ChecklistGenerator module.

Tests cover:
  - General criteria fallback (when KB is empty for a payer+procedure)
  - KB-driven checklists (when requirements exist)
  - Merging general + learned requirements
  - Clinical info checking (satisfied/missing/unknown)
  - Checklist formatting
"""

import pytest
from payer_knowledge_base import PayerKnowledgeBase
from checklist_generator import ChecklistGenerator


@pytest.fixture
def generator(kb):
    return ChecklistGenerator(kb)


class TestGeneralCriteriaFallback:
    """Test fallback to general criteria when KB is empty."""

    def test_mri_fallback(self, generator):
        checklist = generator.generate("Unknown Payer", "Lumbar MRI")
        assert checklist["using_fallback"] is True
        assert checklist["category"] == "MRI"
        assert len(checklist["items"]) > 0
        # Should have history requirements
        types = [i["type"] for i in checklist["items"]]
        assert "history" in types
        assert "exam" in types

    def test_surgery_fallback(self, generator):
        checklist = generator.generate("Unknown Payer", "Knee Arthroscopy")
        assert checklist["using_fallback"] is True
        assert checklist["category"] == "Surgery"

    def test_therapy_fallback(self, generator):
        checklist = generator.generate("Unknown Payer", "Physical Therapy")
        assert checklist["category"] == "Therapy"

    def test_specialist_fallback(self, generator):
        checklist = generator.generate("Unknown Payer", "Cardiology Consult")
        assert checklist["category"] == "Specialist"

    def test_unknown_procedure_default(self, generator):
        checklist = generator.generate("Unknown Payer", "Some Unknown Procedure")
        assert checklist["category"] == "Default"
        assert len(checklist["items"]) > 0


class TestKBDrivenChecklist:
    """Test checklists driven by knowledge base data."""

    def test_kb_checklist(self, populated_kb):
        gen = ChecklistGenerator(populated_kb)
        checklist = gen.generate("BCBS of Oregon", "Lumbar MRI")
        assert checklist["using_fallback"] is False
        assert len(checklist["items"]) >= 3
        # Should include the learned requirement (ESR/CRP)
        descs = [i["description"] for i in checklist["items"]]
        assert any("ESR" in d or "CRP" in d for d in descs)

    def test_kb_includes_learned_from_denial(self, populated_kb):
        gen = ChecklistGenerator(populated_kb)
        checklist = gen.generate("BCBS of Oregon", "Lumbar MRI")
        learned = [i for i in checklist["items"] if i["learned_from_denial"]]
        assert len(learned) >= 1

    def test_kb_includes_lessons(self, populated_kb):
        gen = ChecklistGenerator(populated_kb)
        checklist = gen.generate("BCBS of Oregon", "Lumbar MRI")
        assert len(checklist["lessons"]) >= 1


class TestClinicalInfoChecking:
    """Test checking items against provided clinical info."""

    def test_satisfied_history(self, generator):
        clinical_info = {
            "history": ["Chronic lower back pain x 8 weeks"],
            "duration": "8 weeks",
        }
        checklist = generator.generate("Test Payer", "Lumbar MRI", clinical_info)
        # Duration should be satisfied
        duration_items = [i for i in checklist["items"] if i["type"] == "duration"]
        for item in duration_items:
            assert item["status"] == "satisfied"

    def test_missing_prior_treatment(self, generator):
        clinical_info = {}  # No prior treatments provided
        checklist = generator.generate("Test Payer", "Lumbar MRI", clinical_info)
        pt_items = [i for i in checklist["items"] if i["type"] == "prior_treatment"]
        for item in pt_items:
            assert item["status"] == "missing"

    def test_provided_prior_treatment(self, generator):
        clinical_info = {
            "prior_treatments": ["6 weeks physical therapy", "NSAIDs x 6 weeks"],
        }
        checklist = generator.generate("Test Payer", "Lumbar MRI", clinical_info)
        pt_items = [i for i in checklist["items"] if i["type"] == "prior_treatment"]
        for item in pt_items:
            assert item["status"] in ("satisfied", "check")

    def test_missing_labs(self, generator):
        clinical_info = {}
        checklist = generator.generate("Test Payer", "Lumbar MRI", clinical_info)
        lab_items = [i for i in checklist["items"] if i["type"] == "lab"]
        for item in lab_items:
            assert item["status"] == "missing"

    def test_provided_labs(self, generator):
        clinical_info = {"labs": {"CRP": "5 mg/L", "ESR": "20 mm/hr"}}
        checklist = generator.generate("Test Payer", "Lumbar MRI", clinical_info)
        lab_items = [i for i in checklist["items"] if i["type"] == "lab"]
        for item in lab_items:
            assert item["status"] == "check"  # labs provided, verify specifics


class TestChecklistFormatting:
    """Test checklist formatting for display."""

    def test_format_checklist_output(self, generator):
        checklist = generator.generate("Test Payer", "Lumbar MRI")
        text = generator.format_checklist(checklist)
        assert "PRE-AUTHORIZATION CHECKLIST" in text
        assert "Test Payer" in text
        assert "Lumbar MRI" in text

    def test_format_with_fallback_warning(self, generator):
        checklist = generator.generate("Unknown Payer", "Lumbar MRI")
        text = generator.format_checklist(checklist)
        assert "general medical necessity" in text.lower()

    def test_format_shows_status_icons(self, generator):
        clinical_info = {}  # All missing
        checklist = generator.generate("Test Payer", "Lumbar MRI", clinical_info)
        text = generator.format_checklist(checklist)
        # Should contain at least one missing icon
        assert "❌" in text or "MISSING" in text

    def test_format_includes_summary(self, generator):
        checklist = generator.generate("Test Payer", "Lumbar MRI")
        text = generator.format_checklist(checklist)
        assert "SUMMARY" in text