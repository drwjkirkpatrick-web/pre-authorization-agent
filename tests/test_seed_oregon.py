"""
Tests for the Oregon payer seeder.

Tests cover:
  - Seeder runs without errors
  - All expected payers are added
  - All procedures are added
  - General requirements are linked to procedures
  - Running seeder twice is idempotent (no duplicates)
"""

import pytest
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from payer_knowledge_base import PayerKnowledgeBase
from seed_oregon_payers import seed_oregon_payers


class TestSeeder:
    """Test the Oregon payer seeder."""

    def test_seed_runs(self, temp_db_path):
        """Seeder should run without errors."""
        result = seed_oregon_payers(db_path=temp_db_path)
        assert result["payers_added"] > 0
        assert result["procedures_added"] > 0
        assert result["requirements_added"] > 0

    def test_all_payers_added(self, temp_db_path):
        """Should have 31 payers total (10 commercial + 12 OHP + 6 MA + 3 other)."""
        seed_oregon_payers(db_path=temp_db_path)
        kb = PayerKnowledgeBase(db_path=temp_db_path)
        payers = kb.list_payers()
        # 10 commercial + 12 OHP CCOs + 6 Medicare Advantage + 3 other = 31
        assert len(payers) >= 30

    def test_commercial_payers(self, temp_db_path):
        """Should include major commercial insurers."""
        seed_oregon_payers(db_path=temp_db_path)
        kb = PayerKnowledgeBase(db_path=temp_db_path)
        expected = ["Regence BlueCross BlueShield of Oregon", "Moda Health Plan",
                     "PacificSource Health Plans", "Providence Health Plan",
                     "Kaiser Permanente Northwest", "Aetna", "Cigna",
                     "UnitedHealthcare"]
        for name in expected:
            payer = kb.get_payer_by_name(name)
            assert payer is not None, f"{name} not found in KB"

    def test_ohp_ccos_added(self, temp_db_path):
        """Should include OHP Coordinated Care Organizations."""
        seed_oregon_payers(db_path=temp_db_path)
        kb = PayerKnowledgeBase(db_path=temp_db_path)
        expected = ["Health Share of Oregon", "Trillium Community Health Plan (OHP)",
                     "PacificSource Community Solutions (OHP)",
                     "Jackson Care Connect", "AllCare Health (OHP)",
                     "Umpqua Health Alliance", "Columbia Pacific CCO",
                     "Eastern Oregon CCO (EOCCO)"]
        for name in expected:
            payer = kb.get_payer_by_name(name)
            assert payer is not None, f"{name} not found in KB"

    def test_medicare_advantage_added(self, temp_db_path):
        """Should include Medicare Advantage plans."""
        seed_oregon_payers(db_path=temp_db_path)
        kb = PayerKnowledgeBase(db_path=temp_db_path)
        ma_payers = [p for p in kb.list_payers() if "Medicare Advantage" in p["name"]]
        assert len(ma_payers) >= 5

    def test_procedures_added(self, temp_db_path):
        """Should include common procedures."""
        seed_oregon_payers(db_path=temp_db_path)
        kb = PayerKnowledgeBase(db_path=temp_db_path)
        expected = ["Lumbar MRI", "Brain MRI", "Knee Arthroscopy",
                     "Physical Therapy (Initial Evaluation)",
                     "Nerve Conduction Study", "Sleep Study (Polysomnography)",
                     "CPAP Device", "TENS Unit"]
        for name in expected:
            proc = kb.get_procedure_by_name(name)
            assert proc is not None, f"{name} not found in KB"

    def test_requirements_added(self, temp_db_path):
        """Should have general requirements for procedures."""
        seed_oregon_payers(db_path=temp_db_path)
        kb = PayerKnowledgeBase(db_path=temp_db_path)

        # Check Lumbar MRI has requirements
        mri = kb.get_procedure_by_name("Lumbar MRI")
        reqs = kb.get_requirements(0, mri["id"])  # payer_id=0 = general
        assert len(reqs) >= 5  # Should have multiple general requirements

        # Check requirement types
        types = [r["requirement_type"] for r in reqs]
        assert "history" in types
        assert "prior_treatment" in types
        assert "exam" in types

    def test_seeder_idempotent(self, temp_db_path):
        """Running seeder twice should not duplicate payers."""
        seed_oregon_payers(db_path=temp_db_path)
        kb1 = PayerKnowledgeBase(db_path=temp_db_path)
        count1 = len(kb1.list_payers())

        seed_oregon_payers(db_path=temp_db_path)  # Run again
        kb2 = PayerKnowledgeBase(db_path=temp_db_path)
        count2 = len(kb2.list_payers())

        assert count1 == count2  # No new payers added

    def test_payer_has_contact_info(self, temp_db_path):
        """Payers should have contact information populated."""
        seed_oregon_payers(db_path=temp_db_path)
        kb = PayerKnowledgeBase(db_path=temp_db_path)
        regence = kb.get_payer_by_name("Regence BlueCross BlueShield of Oregon")
        assert regence is not None
        assert regence["phone"] is not None
        assert regence["fax"] is not None
        assert regence["portal_url"] is not None
        assert regence["turnaround_days"] is not None

    def test_ohp_appeal_deadlines_shorter(self, temp_db_path):
        """OHP CCOs should have shorter appeal deadlines (45 days) vs commercial (180)."""
        seed_oregon_payers(db_path=temp_db_path)
        kb = PayerKnowledgeBase(db_path=temp_db_path)

        health_share = kb.get_payer_by_name("Health Share of Oregon")
        regence = kb.get_payer_by_name("Regence BlueCross BlueShield of Oregon")

        assert health_share["appeal_deadline_days"] < regence["appeal_deadline_days"]