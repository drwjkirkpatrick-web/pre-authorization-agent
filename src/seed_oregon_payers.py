"""
Oregon Insurance Payer Seeder — Populate the knowledge base with Oregon insurers.

This script seeds the pre-authorization agent's knowledge base with:
  1. Major commercial health insurers operating in Oregon
  2. Oregon Health Plan (OHP) Coordinated Care Organizations (CCOs)
  3. Medicare Advantage plans active in Oregon
  4. Common pre-authorization requirements for each

Data sources:
  - Publicly available payer websites and provider manuals
  - Oregon Health Authority OHP CCO contact lists
  - CMS Medicare Advantage plan directories
  - Standard CARC denial codes and common pre-auth requirements

CRITICAL: This is publicly available administrative information only.
No patient data. No proprietary payer policies. Requirements listed
are GENERAL medical necessity patterns, not payer-specific policy quotes.
The learning loop will supplement these with payer-specific requirements
as denials are processed.

Usage:
    cd ~/projects/pre-authorization-agent
    python -m src.seed_oregon_payers
    # or
    python src/seed_oregon_payers.py
"""

import sys
from pathlib import Path

# Ensure src is on the path
sys.path.insert(0, str(Path(__file__).parent if __file__ else Path(__file__).parent))

from payer_knowledge_base import PayerKnowledgeBase


# ─── Oregon Commercial Health Insurers ───────────────────────────────────
# These are the major commercial payers a small Oregon practice will encounter.

OREGON_COMMERCIAL_PAYERS = [
    {
        "name": "Regence BlueCross BlueShield of Oregon",
        "portal_url": "https://www.availity.com",
        "phone": "888-218-7525",          # Provider pre-auth line
        "fax": "888-843-6281",            # Pre-auth fax
        "turnaround_days": 5,            # Typical: 5 business days
        "appeal_deadline_days": 180,     # Regence allows 180 days for appeals
        "notes": "Largest commercial insurer in Oregon. Part of Cambia Health Solutions. "
                 "Pre-auth via Availity portal. Uses Regence medical necessity policies. "
                 "Common requirement: conservative treatment trial before imaging/surgery. "
                 "BCBS prefix varies by plan (OR1, OR2, etc.).",
    },
    {
        "name": "Moda Health Plan",
        "portal_url": "https://www.modahealth.com/provider",
        "phone": "800-852-2814",         # Provider services
        "fax": "877-684-0263",
        "turnaround_days": 5,
        "appeal_deadline_days": 180,
        "notes": "Portland-based. Formerly ODS Health Plan. "
                 "Common in Oregon group/employer plans. "
                 "Pre-auth via Moda provider portal or fax. "
                 "Known for requiring documented conservative treatment before MRI/surgery.",
    },
    {
        "name": "PacificSource Health Plans",
        "portal_url": "https://www.pacificsource.com/provider",
        "phone": "800-624-0756",
        "fax": "541-687-1014",
        "turnaround_days": 5,
        "appeal_deadline_days": 180,
        "notes": "Springfield, OR-based. Strong presence in Lane County and Central Oregon. "
                 "Also operates PacificSource Community Solutions (CCO for OHP in several counties). "
                 "Pre-auth via provider portal or fax.",
    },
    {
        "name": "Providence Health Plan",
        "portal_url": "https://www.providencehealthplan.com/provider",
        "phone": "800-678-7803",         # Provider services
        "fax": "503-582-8450",
        "turnaround_days": 3,            # Often faster than others
        "appeal_deadline_days": 180,
        "notes": "Portland-based. Part of Providence Health System. "
                 "Common in Portland metro and NW Oregon. "
                 "Pre-auth via Providence provider portal. "
                 "Generally responsive — 3-5 business day turnaround.",
    },
    {
        "name": "Kaiser Permanente Northwest",
        "portal_url": "https://kp.org/provider",
        "phone": "800-813-2000",         # Provider line
        "fax": "866-369-7733",
        "turnaround_days": 5,
        "appeal_deadline_days": 180,
        "notes": "HMO model — pre-auth typically through KP's own system. "
                 "Referrals to outside specialists require KP authorization. "
                 "Common in Portland metro area. "
                 "Notable: KP often requires their own specialist to review before approving outside referral.",
    },
    {
        "name": "Aetna",
        "portal_url": "https://www.availity.com",
        "phone": "800-624-0756",         # Aetna provider services
        "fax": "866-622-5578",
        "turnaround_days": 7,
        "appeal_deadline_days": 180,
        "notes": "National payer active in Oregon. Pre-auth via Availity or Aetna portal. "
                 "Uses Aetna Clinical Policy Bulletins (CPBs) for medical necessity. "
                 "Common requirement: documented conservative treatment trial.",
    },
    {
        "name": "Cigna",
        "portal_url": "https://www.cignaforhcp.cigna.com",
        "phone": "800-881-2659",         # Provider pre-auth
        "fax": "866-597-7999",
        "turnaround_days": 7,
        "appeal_deadline_days": 180,
        "notes": "National payer. Pre-auth via CignaforHCP portal. "
                 "Uses Cigna Medical Coverage Policies. "
                 "Common: conservative treatment trial, imaging before advanced imaging.",
    },
    {
        "name": "UnitedHealthcare",
        "portal_url": "https://www.uhcprovider.com",
        "phone": "877-842-3210",         # UHC provider pre-auth
        "fax": "877-299-5681",
        "turnaround_days": 7,
        "appeal_deadline_days": 180,
        "notes": "National payer. Pre-auth via UHC Provider portal. "
                 "Uses Optum clinical guidelines. "
                 "Common: conservative treatment, imaging step-up protocol. "
                 "UHC often requires notification (not full pre-auth) for many services.",
    },
    {
        "name": "Samaritan Health Plans",
        "portal_url": "https://www.samaritanhealthplans.com",
        "phone": "800-880-8813",
        "fax": "541-768-4639",
        "turnaround_days": 5,
        "appeal_deadline_days": 180,
        "notes": "Benton/Linn County area. Part of Samaritan Health Services. "
                 "Common in mid-Willamette Valley. Pre-auth via Samaritan provider portal.",
    },
    {
        "name": "Trillium Community Health Plan (Commercial)",
        "portal_url": "https://www.trilliumchp.com",
        "phone": "800-554-4493",
        "fax": "541-687-1014",
        "turnaround_days": 5,
        "appeal_deadline_days": 180,
        "notes": "Lane County area. Trillium also operates as an OHP CCO. "
                 "Commercial plans separate from OHP plans.",
    },
]

# ─── Oregon Health Plan (OHP) CCOs ──────────────────────────────────────
# Oregon's Medicaid program is delivered through Coordinated Care Organizations.
# Each CCO covers specific geographic regions. Pre-auth for OHP follows the
# Oregon Prioritized List of Health Services (OAR 410-141-0480).

OREGON_OHP_CCOS = [
    {
        "name": "Health Share of Oregon",
        "portal_url": "https://www.healthshareoregon.org",
        "phone": "503-416-8090",
        "fax": "503-416-8088",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,      # OHP appeals typically shorter
        "notes": "Largest CCO. Serves Multnomah, Clackamas, Washington, "
                 "and parts of Marion counties. Portland metro area. "
                 "OHP follows Oregon Prioritized List. "
                 "Pre-auth required for services not on the prioritized list "
                 "or above the funding line.",
    },
    {
        "name": "Trillium Community Health Plan (OHP)",
        "portal_url": "https://www.trilliumchp.com",
        "phone": "800-554-4493",
        "fax": "541-687-1014",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "Serves Lane County (Eugene/Springfield area). "
                 "OHP plan. Uses Oregon Prioritized List. "
                 "Also covers parts of Multnomah County.",
    },
    {
        "name": "PacificSource Community Solutions (OHP)",
        "portal_url": "https://www.pacificsource.com",
        "phone": "800-624-0756",
        "fax": "541-687-1014",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "OHP CCO for Central Oregon (Deschutes, Crook, Jefferson), "
                 "Columbia Gorge (Hood River, Wasco), and Springfield area. "
                 "Uses Oregon Prioritized List.",
    },
    {
        "name": "Jackson Care Connect",
        "portal_url": "https://www.jacksoncareconnect.org",
        "phone": "541-858-2925",
        "fax": "541-858-2926",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "Jackson County (Medford/Ashland area). OHP CCO. "
                 "Uses Oregon Prioritized List.",
    },
    {
        "name": "AllCare Health (OHP)",
        "portal_url": "https://www.allcarehealth.org",
        "phone": "800-870-1296",
        "fax": "541-471-6657",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "Josephine, Curry, Douglas counties (Southern Oregon). OHP CCO. "
                 "Uses Oregon Prioritized List.",
    },
    {
        "name": "Umpqua Health Alliance",
        "portal_url": "https://www.umpquahealth.com",
        "phone": "541-229-4842",
        "fax": "541-673-1710",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "Douglas County (Roseburg area). OHP CCO. "
                 "Uses Oregon Prioritized List.",
    },
    {
        "name": "Western Oregon Advanced Health (OHP)",
        "portal_url": "https://www.woah.org",
        "phone": "541-269-1980",
        "fax": "541-269-1985",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "Coos, Curry, Western Douglas counties (South Coast). OHP CCO. "
                 "Uses Oregon Prioritized List.",
    },
    {
        "name": "Columbia Pacific CCO",
        "portal_url": "https://www.colpahealth.org",
        "phone": "503-421-4380",
        "fax": "503-397-6515",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "Columbia, Clatsop, Tillamook counties (NW Oregon coast). OHP CCO. "
                 "Uses Oregon Prioritized List.",
    },
    {
        "name": "Yamhill Community Care (OHP)",
        "portal_url": "https://www.yamhillcco.org",
        "phone": "855-822-9369",
        "fax": "503-376-6480",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "Yamhill County (McMinnville area). OHP CCO. "
                 "Uses Oregon Prioritized List.",
    },
    {
        "name": "Cascade Health Alliance",
        "portal_url": "https://www.cascadehealthalliance.org",
        "phone": "541-884-2888",
        "fax": "541-885-2900",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "Klamath and Lake counties (South Central Oregon). OHP CCO. "
                 "Uses Oregon Prioritized List.",
    },
    {
        "name": "Eastern Oregon CCO (EOCCO)",
        "portal_url": "https://www.eoccco.org",
        "phone": "541-278-0160",
        "fax": "541-278-0165",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "Baker, Gilliam, Grant, Harney, Malheur, Morrow, Sherman, "
                 "Umatilla, Union, Wallowa, Wheeler counties. "
                 "OHP CCO. Uses Oregon Prioritized List.",
    },
    {
        "name": "North Central Regional Health (OHP)",
        "portal_url": "https://www.ncrh.co",
        "phone": "541-296-7260",
        "fax": "541-298-5290",
        "turnaround_days": 5,
        "appeal_deadline_days": 45,
        "notes": "Wasco, Sherman, Hood River counties (Columbia Gorge area). "
                 "OHP CCO. Uses Oregon Prioritized List.",
    },
]

# ─── Medicare Advantage Plans in Oregon ──────────────────────────────────
# Medicare Advantage (Part C) plans replace Original Medicare for enrolled
# beneficiaries. Pre-auth rules differ from Original Medicare.

OREGON_MEDICARE_ADVANTAGE = [
    {
        "name": "Regence Medicare Advantage",
        "portal_url": "https://www.availity.com",
        "phone": "888-218-7525",
        "fax": "888-843-6281",
        "turnaround_days": 5,
        "appeal_deadline_days": 60,      # MA plans: 60 days for standard appeals
        "notes": "Regence's Medicare Advantage product. "
                 "Pre-auth rules may differ from commercial Regence plans. "
                 "Follows CMS MA requirements. Appeals follow CMS timeline.",
    },
    {
        "name": "Kaiser Medicare Advantage",
        "portal_url": "https://kp.org/provider",
        "phone": "800-813-2000",
        "fax": "866-369-7733",
        "turnaround_days": 5,
        "appeal_deadline_days": 60,
        "notes": "Kaiser's MA product in Oregon. HMO model. "
                 "All referrals through KP system.",
    },
    {
        "name": "Providence Medicare Advantage",
        "portal_url": "https://www.providencehealthplan.com/provider",
        "phone": "800-678-7803",
        "fax": "503-582-8450",
        "turnaround_days": 3,
        "appeal_deadline_days": 60,
        "notes": "Providence's MA product. Portland/metro focused. "
                 "Generally responsive. Follows CMS MA requirements.",
    },
    {
        "name": "UnitedHealthcare Medicare Advantage",
        "portal_url": "https://www.uhcprovider.com",
        "phone": "877-842-3210",
        "fax": "877-299-5681",
        "turnaround_days": 7,
        "appeal_deadline_days": 60,
        "notes": "UHC's MA product (AARP-branded in many cases). "
                 "Pre-auth via UHC portal. Follows CMS MA requirements.",
    },
    {
        "name": "Aetna Medicare Advantage",
        "portal_url": "https://www.availity.com",
        "phone": "800-624-0756",
        "fax": "866-622-5578",
        "turnaround_days": 7,
        "appeal_deadline_days": 60,
        "notes": "Aetna's MA product in Oregon. "
                 "Uses Aetna CPBs modified for MA compliance.",
    },
    {
        "name": "Moda Medicare Advantage",
        "portal_url": "https://www.modahealth.com/provider",
        "phone": "800-852-2814",
        "fax": "877-684-0263",
        "turnaround_days": 5,
        "appeal_deadline_days": 60,
        "notes": "Moda's MA product. Oregon-focused.",
    },
]

# ─── Other Oregon Payers ─────────────────────────────────────────────────

OREGON_OTHER_PAYERS = [
    {
        "name": "Original Medicare (Part B)",
        "portal_url": "https://www.cms.gov",
        "phone": "855-224-4520",         # Noridian (Oregon MAC)
        "fax": "855-224-4517",
        "turnaround_days": 7,
        "appeal_deadline_days": 120,     # Medicare: 120 days for redetermination
        "notes": "Original Medicare Part B. Oregon MAC is Noridian Healthcare Solutions. "
                 "Many services DON'T require pre-auth under Original Medicare. "
                 "MRI/CT/imaging: pre-auth NOT required (but may require ABN if not "
                 "reasonable and necessary). "
                 "Notable: Medicare does NOT require pre-auth for most imaging — "
                 "the issue is medical necessity at claim adjudication, not pre-auth. "
                 "DME and some procedures do require pre-auth.",
    },
    {
        "name": "Workers' Compensation (SAIF Corporation)",
        "portal_url": "https://www.saif.com",
        "phone": "800-628-7915",
        "fax": "503-373-8000",
        "turnaround_days": 5,
        "appeal_deadline_days": 60,
        "notes": "Oregon's largest workers' comp insurer (state-owned). "
                 "Pre-auth for medical services in WC claims. "
                 "Different rules than health insurance — focused on work-related injury/illness. "
                 "Use WC-specific documentation (work status, causation, etc.).",
    },
    {
        "name": "VA Community Care Network (Oregon)",
        "portal_url": "https://www.va.gov/COMMUNITYCARE",
        "phone": "877-881-7618",        # CCN provider line
        "fax": "888-622-7739",
        "turnaround_days": 7,
        "appeal_deadline_days": 90,
        "notes": "Veterans receiving community care via VA CCN. "
                 "Pre-auth required through Optum (CCN administrator for Region 9). "
                 "Referral originates from VA. Provider bills Optum/CCN, not VA directly.",
    },
]

# ─── Common Procedures with General Pre-Auth Requirements ────────────────
# These are the procedures most commonly referred out by a small clinic.
# Requirements listed are GENERAL patterns, not payer-specific policy quotes.

COMMON_PROCEDURES = [
    {"name": "Lumbar MRI", "cpt_code": "72148", "category": "imaging",
     "notes": "Without contrast. Most commonly denied imaging pre-auth."},
    {"name": "Cervical MRI", "cpt_code": "72141", "category": "imaging",
     "notes": "Without contrast."},
    {"name": "Brain MRI", "cpt_code": "70551", "category": "imaging",
     "notes": "Without contrast."},
    {"name": "Knee MRI", "cpt_code": "73721", "category": "imaging",
     "notes": "Without contrast. Common sports medicine referral."},
    {"name": "Shoulder MRI", "cpt_code": "73221", "category": "imaging",
     "notes": "Without contrast."},
    {"name": "CT Head/Brain", "cpt_code": "70450", "category": "imaging",
     "notes": "Without contrast."},
    {"name": "CT Abdomen/Pelvis", "cpt_code": "74177", "category": "imaging",
     "notes": "With contrast. Common for abdominal workup."},
    {"name": "CT Lumbar Spine", "cpt_code": "72133", "category": "imaging",
     "notes": "With contrast."},
    {"name": "Diagnostic Ultrasound", "cpt_code": "76700", "category": "imaging",
     "notes": "Abdominal complete. Often doesn't require pre-auth."},
    {"name": "Echocardiogram", "cpt_code": "93306", "category": "imaging",
     "notes": "Transthoracic echo. Sometimes requires pre-auth depending on payer."},
    {"name": "Mammogram (Diagnostic)", "cpt_code": "76641", "category": "imaging",
     "notes": "Diagnostic mammogram (screening usually doesn't need pre-auth)."},
    {"name": "Knee Arthroscopy", "cpt_code": "29881", "category": "surgery",
     "notes": "Meniscectomy. Common surgery referral."},
    {"name": "Carpal Tunnel Release", "cpt_code": "64721", "category": "surgery",
     "notes": "Median nerve decompression."},
    {"name": "Cataract Surgery", "cpt_code": "66984", "category": "surgery",
     "notes": "Common ophthalmology referral. Usually low pre-auth barrier."},
    {"name": "Physical Therapy (Initial Evaluation)", "cpt_code": "97161", "category": "therapy",
     "notes": "PT eval. Some payers require pre-auth for ongoing PT sessions."},
    {"name": "Physical Therapy (Therapeutic Exercise)", "cpt_code": "97110", "category": "therapy",
     "notes": "Common ongoing PT code. Many payers limit sessions without pre-auth."},
    {"name": "Occupational Therapy Evaluation", "cpt_code": "97165", "category": "therapy",
     "notes": "OT initial eval."},
    {"name": "Nerve Conduction Study", "cpt_code": "95860", "category": "imaging",
     "notes": "EMG/NCS. Often referred for suspected neuropathy/radiculopathy."},
    {"name": "Sleep Study (Polysomnography)", "cpt_code": "95810", "category": "imaging",
     "notes": "In-lab sleep study. Home sleep test (95800) often preferred first."},
    {"name": "Colonoscopy (Screening)", "cpt_code": "45378", "category": "surgery",
     "notes": "Screening colonoscopy. Usually covered under preventive care without pre-auth."},
    {"name": "EGD (Upper Endoscopy)", "cpt_code": "43239", "category": "surgery",
     "notes": "Upper GI endoscopy with biopsy. Often requires pre-auth."},
    {"name": "Cardiology Consult", "cpt_code": "99244", "category": "specialist",
     "notes": "Consultative visit. Pre-auth sometimes required for out-of-network specialist."},
    {"name": "Orthopedic Consult", "cpt_code": "99244", "category": "specialist",
     "notes": "Ortho referral consult."},
    {"name": "Neurology Consult", "cpt_code": "99244", "category": "specialist",
     "notes": "Neurology referral consult."},
    {"name": "Dermatology Consult", "cpt_code": "99244", "category": "specialist",
     "notes": "Derm referral consult."},
    {"name": "CPAP Device", "cpt_code": "E0601", "category": "DME",
     "notes": "CPAP for OSA. Requires sleep study documentation."},
    {"name": "Knee Brace (Off-the-shelf)", "cpt_code": "E1831", "category": "DME",
     "notes": "DME. Often requires exam and imaging documentation."},
    {"name": "TENS Unit", "cpt_code": "E0730", "category": "DME",
     "notes": "TENS for chronic pain. Often requires trial period documentation."},
]


# ─── General Pre-Auth Requirements by Procedure Category ──────────────────
# These are common requirements that apply across most payers.
# The learning loop will supplement these with payer-specific requirements.

GENERAL_PROCEDURE_REQUIREMENTS = [
    # ─── MRI (all body regions) ─────────────────────────────────────────
    {
        "procedure_name": "Lumbar MRI",
        "requirements": [
            ("history", "Documented symptom duration > 6 weeks"),
            ("prior_treatment", "6-week conservative treatment trial (PT, NSAIDs, activity modification)"),
            ("exam", "Neurological exam documenting radiculopathy or motor deficit"),
            ("exam", "Range of motion with specific measurements"),
            ("imaging", "Plain radiograph (X-ray) before MRI"),
            ("lab", "ESR and CRP if infection suspected"),
            ("documentation", "Office/progress notes covering treatment period"),
            ("documentation", "Conservative treatment records (PT notes, medication log)"),
        ],
    },
    {
        "procedure_name": "Cervical MRI",
        "requirements": [
            ("history", "Documented symptom duration > 6 weeks"),
            ("prior_treatment", "6-week conservative treatment trial"),
            ("exam", "Neurological exam documenting cervical radiculopathy"),
            ("exam", "Cervical range of motion with specific measurements"),
            ("imaging", "Cervical X-ray before MRI"),
            ("documentation", "Office/progress notes covering treatment period"),
            ("documentation", "Conservative treatment records"),
        ],
    },
    {
        "procedure_name": "Brain MRI",
        "requirements": [
            ("history", "Documented neurological symptoms (headache, dizziness, focal deficits)"),
            ("exam", "Neurological examination findings"),
            ("history", "Duration and progression of symptoms"),
            ("imaging", "CT head considered or completed first (some payers)"),
            ("documentation", "Clinical notes documenting indication"),
        ],
    },
    {
        "procedure_name": "Knee MRI",
        "requirements": [
            ("history", "Documented knee pain duration and mechanism of injury"),
            ("prior_treatment", "Conservative treatment trial (rest, NSAIDs, PT) typically 4-6 weeks"),
            ("exam", "Knee exam: range of motion, stability (Lachman, McMurray), effusion"),
            ("imaging", "Knee X-ray (weight-bearing if possible) before MRI"),
            ("documentation", "Clinical notes documenting exam findings and treatment"),
        ],
    },
    {
        "procedure_name": "Shoulder MRI",
        "requirements": [
            ("history", "Documented shoulder pain, duration, mechanism"),
            ("prior_treatment", "Conservative treatment trial (rest, NSAIDs, PT) 4-6 weeks"),
            ("exam", "Shoulder exam: ROM, special tests (Hawkins-Kennedy, Neer, Jobe)"),
            ("imaging", "Shoulder X-ray before MRI"),
            ("documentation", "Clinical notes and conservative treatment records"),
        ],
    },
    # ─── CT Scans ────────────────────────────────────────────────────────
    {
        "procedure_name": "CT Head/Brain",
        "requirements": [
            ("history", "Clear clinical indication (headache, trauma, focal deficit, etc.)"),
            ("exam", "Relevant neurological examination"),
            ("documentation", "Clinical notes supporting CT indication"),
        ],
    },
    {
        "procedure_name": "CT Abdomen/Pelvis",
        "requirements": [
            ("history", "Clear clinical indication (abdominal pain, mass, etc.)"),
            ("exam", "Abdominal examination findings"),
            ("lab", "Relevant labs (CBC, metabolic panel, liver function, lipase)"),
            ("imaging", "Abdominal X-ray or ultrasound considered first (some payers)"),
            ("documentation", "Clinical notes supporting CT indication"),
        ],
    },
    {
        "procedure_name": "CT Lumbar Spine",
        "requirements": [
            ("history", "Documented back pain duration and characteristics"),
            ("prior_treatment", "Conservative treatment trial"),
            ("exam", "Neurological and musculoskeletal exam"),
            ("imaging", "Lumbar X-ray before CT"),
            ("documentation", "Clinical notes"),
        ],
    },
    # ─── Surgery ────────────────────────────────────────────────────────
    {
        "procedure_name": "Knee Arthroscopy",
        "requirements": [
            ("history", "Documented knee symptoms and functional impact"),
            ("prior_treatment", "Conservative treatment trial 6-12 weeks (PT, NSAIDs, injections)"),
            ("exam", "Knee exam: instability, meniscal signs, effusion"),
            ("imaging", "Knee MRI confirming structural pathology"),
            ("imaging", "Knee X-ray (weight-bearing)"),
            ("documentation", "All conservative treatment records"),
            ("documentation", "MRI report"),
        ],
    },
    {
        "procedure_name": "Carpal Tunnel Release",
        "requirements": [
            ("history", "Documented CTS symptoms (numbness, tingling, nocturnal symptoms)"),
            ("prior_treatment", "Conservative treatment: splinting, NSAIDs, possibly injection"),
            ("exam", "Positive Phalen, Tinel, or median nerve compression test"),
            ("lab", "Nerve conduction study confirming CTS"),
            ("documentation", "NCS results, conservative treatment records"),
        ],
    },
    {
        "procedure_name": "Cataract Surgery",
        "requirements": [
            ("history", "Documented visual impairment impacting daily activities"),
            ("exam", "Visual acuity testing (Snellen) documenting impairment"),
            ("exam", "Slit lamp exam documenting cataract"),
            ("documentation", "Ophthalmology exam findings"),
            ("documentation", "Impact on activities of daily living"),
        ],
    },
    # ─── Therapy ─────────────────────────────────────────────────────────
    {
        "procedure_name": "Physical Therapy (Initial Evaluation)",
        "requirements": [
            ("history", "Condition being treated and functional goals"),
            ("exam", "Physical exam findings supporting PT need"),
            ("documentation", "Therapy prescription with specific diagnosis and goals"),
        ],
    },
    {
        "procedure_name": "Physical Therapy (Therapeutic Exercise)",
        "requirements": [
            ("history", "Ongoing condition and progress"),
            ("prior_treatment", "Initial PT eval completed"),
            ("documentation", "Therapy progress notes showing improvement"),
            ("documentation", "Plan of care with measurable goals"),
        ],
    },
    # ─── Nerve Conduction Study ─────────────────────────────────────────
    {
        "procedure_name": "Nerve Conduction Study",
        "requirements": [
            ("history", "Documented neurological symptoms (numbness, tingling, weakness)"),
            ("exam", "Neurological exam with specific deficit documentation"),
            ("prior_treatment", "Conservative treatment trial if applicable"),
            ("documentation", "Clinical notes supporting NCS indication"),
        ],
    },
    # ─── Sleep Study ─────────────────────────────────────────────────────
    {
        "procedure_name": "Sleep Study (Polysomnography)",
        "requirements": [
            ("history", "Documented sleep symptoms (snoring, witnessed apnea, daytime sleepiness)"),
            ("exam", "BMI, neck circumference, airway assessment"),
            ("prior_treatment", "Home sleep test attempted first (some payers require)"),
            ("documentation", "STOP-BANG or Epworth Sleepiness Scale"),
            ("documentation", "Clinical notes supporting sleep study indication"),
        ],
    },
    # ─── EGD ────────────────────────────────────────────────────────────
    {
        "procedure_name": "EGD (Upper Endoscopy)",
        "requirements": [
            ("history", "Documented GI symptoms (dyspepsia, reflux, dysphagia, bleeding)"),
            ("prior_treatment", "Trial of PPI or H2 blocker (if dyspepsia/reflux)"),
            ("exam", "Abdominal examination"),
            ("lab", "CBC if anemia/bleeding suspected"),
            ("documentation", "Clinical notes and medication trial documentation"),
        ],
    },
    # ─── DME ─────────────────────────────────────────────────────────────
    {
        "procedure_name": "CPAP Device",
        "requirements": [
            ("history", "Documented OSA diagnosis"),
            ("imaging", "Sleep study (PSG or home sleep test) confirming OSA"),
            ("documentation", "Sleep study report with AHI"),
            ("documentation", "CPAP prescription with pressure settings"),
        ],
    },
    {
        "procedure_name": "TENS Unit",
        "requirements": [
            ("history", "Documented chronic pain condition"),
            ("prior_treatment", "Trial period (rental TENS for 30 days)"),
            ("documentation", "Documentation of trial showing benefit"),
            ("documentation", "Prescription with diagnosis"),
        ],
    },
]


def seed_oregon_payers(db_path: str = None):
    """
    Seed the knowledge base with all Oregon medical insurance payers.

    Adds:
      1. Commercial insurers (10 payers)
      2. OHP CCOs (12 payers)
      3. Medicare Advantage plans (6 payers)
      4. Other payers (Medicare, WC, VA) (3 payers)
      5. Common procedures (28 procedures)
      6. General pre-auth requirements per procedure

    Total: 31 payers, 28 procedures, ~150 general requirements
    """
    kb = PayerKnowledgeBase(db_path)

    payer_count = 0
    procedure_count = 0
    requirement_count = 0

    # ─── Add all payers ────────────────────────────────────────────────
    all_payers = (
        OREGON_COMMERCIAL_PAYERS +
        OREGON_OHP_CCOS +
        OREGON_MEDICARE_ADVANTAGE +
        OREGON_OTHER_PAYERS
    )

    print("═══════════════════════════════════════════════")
    print("  SEEDING OREGON INSURANCE PAYERS")
    print("═══════════════════════════════════════════════")
    print()

    # ─── Commercial Payers ────────────────────────────────────────────
    print("── Commercial Health Insurers ──")
    for payer in OREGON_COMMERCIAL_PAYERS:
        pid = kb.add_payer(**payer)
        print(f"  ✅ {payer['name']}")
        payer_count += 1

    # ─── OHP CCOs ─────────────────────────────────────────────────────
    print()
    print("── Oregon Health Plan (OHP) CCOs ──")
    for payer in OREGON_OHP_CCOS:
        pid = kb.add_payer(**payer)
        print(f"  ✅ {payer['name']}")
        payer_count += 1

    # ─── Medicare Advantage ──────────────────────────────────────────
    print()
    print("── Medicare Advantage Plans ──")
    for payer in OREGON_MEDICARE_ADVANTAGE:
        pid = kb.add_payer(**payer)
        print(f"  ✅ {payer['name']}")
        payer_count += 1

    # ─── Other Payers ────────────────────────────────────────────────
    print()
    print("── Other Payers (Medicare, WC, VA) ──")
    for payer in OREGON_OTHER_PAYERS:
        pid = kb.add_payer(**payer)
        print(f"  ✅ {payer['name']}")
        payer_count += 1

    # ─── Add all procedures ───────────────────────────────────────────
    print()
    print("── Common Procedures ──")
    for proc in COMMON_PROCEDURES:
        pid = kb.add_procedure(**proc)
        print(f"  ✅ {proc['name']} ({proc.get('cpt_code', 'no CPT')})")
        procedure_count += 1

    # ─── Add general requirements for each procedure ──────────────────
    print()
    print("── General Pre-Auth Requirements ──")
    for proc_req in GENERAL_PROCEDURE_REQUIREMENTS:
        proc_name = proc_req["procedure_name"]
        proc = kb.get_procedure_by_name(proc_name)
        if not proc:
            print(f"  ⚠️  Procedure '{proc_name}' not found — skipping")
            continue

        for req_type, req_desc in proc_req["requirements"]:
            kb.add_requirement(
                payer_id=0,  # 0 = general (applies to all payers)
                procedure_id=proc["id"],
                requirement_type=req_type,
                requirement_desc=req_desc,
                is_mandatory=True,
                learned_from_denial=False,
                source="general",
            )
            requirement_count += 1
        print(f"  ✅ {proc_name}: {len(proc_req['requirements'])} requirements")

    # ─── Summary ─────────────────────────────────────────────────────
    print()
    print("═══════════════════════════════════════════════")
    print("  SEEDING COMPLETE")
    print("═══════════════════════════════════════════════")
    print(f"  Payers added:       {payer_count}")
    print(f"  Procedures added:  {procedure_count}")
    print(f"  Requirements added: {requirement_count}")
    print()

    # Verify with stats
    stats = kb.get_stats()
    print("  KNOWLEDGE BASE STATS:")
    print(f"    Total payers:       {stats['total_payers']}")
    print(f"    Total procedures:   {stats['total_procedures']}")
    print(f"    Total requirements: {stats['total_requirements']}")
    print(f"    Learned from denials: {stats['learned_requirements']}")
    print()

    # List all payers
    print("  ALL PAYERS IN KNOWLEDGE BASE:")
    payers = kb.list_payers()
    for p in payers:
        print(f"    [{p['id']:2d}] {p['name']}")

    return {
        "payers_added": payer_count,
        "procedures_added": procedure_count,
        "requirements_added": requirement_count,
    }


if __name__ == "__main__":
    seed_oregon_payers()