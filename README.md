# Pre-Authorization Agent

A Hermes-powered assistant for small medical practices to manage insurance pre-authorization workflows. Built for the one-room clinic that refers out for procedures when needed.

## What It Does

The agent helps the practitioner:
1. **Know what's needed before submitting** — generates a pre-submission checklist for each payer + procedure combination
2. **Draft letters of medical necessity** — properly formatted, addressing each required element
3. **Analyze denials** — parses denial letters (text, PDF, or scanned image) to extract the specific reason and what was missing
4. **Learn from every denial** — updates its knowledge base so the next submission for the same payer + procedure includes the previously-missing information
5. **Track deadlines** — monitors expected response dates and appeal deadlines with alerts

## Core Principle

**Never falsify information.** The agent identifies what *genuine* information is needed, helps the practitioner collect it, and drafts accurate paperwork. If a lab value or exam finding isn't documented, the agent flags it as **MISSING** — it never invents data to get a claim approved.

## The Learning Loop

This is the key differentiator. Every denial teaches the agent something:

```
Submit lumbar MRI pre-auth to BCBS
    → Denied: "insufficient conservative treatment trial"
    → Agent updates knowledge base: BCBS + lumbar MRI requires 6-week conservative tx
    → Next lumbar MRI pre-auth for BCBS
    → Checklist now includes "document PT or home exercise program × 6 weeks"
    → Approved ✅
```

Over time, the agent accumulates payer-specific requirements so denials become rare.

## Architecture

```
┌─────────────────────────────────────────────────────┐
│                    Main CLI /                        │
│                  Hermes Skill Entry                  │
└──────┬──────────────────────────────────────────────┘
       │
  ┌────┴────┐    ┌─────────────┐    ┌──────────────┐
  │Checklist │    │   Letter    │    │   Denial     │
  │Generator │    │  Drafter   │    │  Analyzer    │
  └────┬────┘    └──────┬─────┘    └──────┬───────┘
       │                │                  │
       └────────────────┼──────────────────┘
                        │
                ┌───────┴───────┐
                │  Learning     │    ┌──────────────┐
                │  Loop         │───→│  Follow-Up   │
                └───────┬───────┘    │  Tracker     │
                        │            └──────────────┘
                ┌───────┴───────┐
                │  Payer        │
                │  Knowledge    │
                │  Base (SQLite)│
                └───────────────┘
```

## Modules

### `payer_knowledge_base.py` — SQLite Learning Engine
Stores payer requirements, procedure data, submission logs, denials, lessons learned, and follow-up deadlines. All patient data is **de-identified** (age range, not DOB; sex only if clinically relevant).

### `checklist_generator.py` — Pre-Submission Requirements
Given a payer + procedure, returns a checklist of everything needed before writing the letter. Uses KB requirements first, falls back to general medical necessity criteria when no payer-specific data exists yet.

### `letter_drafter.py` — Medical Necessity Letters
Drafts a formatted letter addressing each required element. Missing clinical information is marked `[MISSING — TO BE COMPLETED]`, never fabricated. ICD-10/CPT codes included only when the practitioner provides them.

### `denial_analyzer.py` — Denial Letter Parser
Extracts structured data from denial letters in three formats:
- Text pasted from insurance portal/email
- Digital PDF (via pdfplumber)
- Scanned image/scanned PDF (via OCR, or Hermes vision tool)

Extracts: denial codes (CARC/RARC), category classification, missing items, appeal deadlines, policy citations.

### `learning_loop.py` — The Feedback Engine
Processes denials, extracts what was missing, adds those as new requirements to the KB (tagged `learned_from_denial`), and creates lessons learned. The next checklist for the same payer + procedure automatically includes the new requirements.

### `followup_tracker.py` — Deadline Monitoring
Tracks expected response dates and appeal deadlines. Designed to work with Hermes cron jobs for automated alerts via Telegram.

## Installation

```bash
# Clone
git clone https://github.com/drwjkirkpatrick-web/pre-authorization-agent.git
cd pre-authorization-agent

# Install dependencies
pip install -r requirements.txt

# For OCR (scanned denial letters):
# Requires tesseract binary: sudo apt install tesseract-ocr
# For scanned PDFs: sudo apt install poppler-utils
```

## Usage

### CLI

```bash
# Generate a pre-submission checklist
python -m src.main checklist --payer "BCBS of Oregon" --procedure "Lumbar MRI"

# Draft a letter of medical necessity
python -m src.main letter --payer "BCBS of Oregon" --procedure "Lumbar MRI" \
    --diagnosis "Lumbar radiculopathy" --icd10 "M54.16" --cpt "72148" \
    --duration "8 weeks"

# Analyze a denial letter (pasted text)
python -m src.main analyze --text "We are denying your request..."

# Analyze a denial letter (PDF or image file)
python -m src.main analyze --file denial_letter.pdf

# Log a submission
python -m src.main submit --payer "BCBS of Oregon" --procedure "Lumbar MRI" \
    --diagnosis "Lumbar radiculopathy" --age "40-49" --sex "F"

# Process a denial (runs the learning loop)
python -m src.main denial --submission-id 1 --text "Denial letter text..."

# Process an approval
python -m src.main approval --submission-id 1 --auth-number "AUTH-12345"

# Check for overdue pre-auths
python -m src.main followup

# View statistics
python -m src.main stats

# View lessons learned
python -m src.main lessons --payer "BCBS of Oregon"

# View learning summary for a payer + procedure
python -m src.main learning --payer "BCBS of Oregon" --procedure "Lumbar MRI"
```

### As a Python Module

```python
from src.main import PreAuthAgent

agent = PreAuthAgent()

# Get a checklist
checklist = agent.get_checklist("BCBS of Oregon", "Lumbar MRI")
print(agent.checklist_gen.format_checklist(checklist))

# Draft a letter
result = agent.draft_letter(
    "BCBS of Oregon", "Lumbar MRI",
    clinical_info={
        "diagnosis": "Lumbar radiculopathy",
        "icd10_code": "M54.16",
        "symptom_duration": "8 weeks",
        "prior_treatments": ["6 weeks PT", "NSAIDs x 6 weeks"],
        "exam": ["Positive straight leg raise left"],
    },
    practice_info={
        "practice_name": "Dr. Walker Clinic",
        "clinician_name": "Walker Kirkpatrick, ND",
        # ...
    },
)
print(result["letter_text"])

# Process a denial (learning loop)
result = agent.process_denial(
    submission_id=1,
    denial_text="Denied. Conservative treatment not documented...",
)
# KB is now updated with new requirements
```

## Hermes Integration

This agent is designed to work as a Hermes skill. Key integrations:

| Hermes Feature | Usage |
|---|---|
| **Telegram Gateway** | Practitioner sends denial letter via Telegram; agent analyzes and responds |
| **Vision** | Scanned denial letters / EOBs analyzed via Hermes vision tool |
| **Cron Jobs** | Automated follow-up deadline monitoring with alerts |
| **Session Search** | Find past similar cases ("last time we submitted X to Y, what happened?") |
| **Persistent Memory** | Payer-specific quirks remembered across sessions |
| **Skills** | The entire agent can be loaded as a Hermes skill |

### Setting Up Cron Monitoring

```python
# Hermes cron job: check for overdue pre-auths daily
# Schedule: every 8h
# Prompt: "Check for overdue pre-authorizations and alert if any"
```

## Safety Guardrails

- **Draft-only**: The agent never submits anything. The practitioner reviews, edits, and signs every letter.
- **No fabrication**: Missing information is flagged as `[MISSING]`, never invented.
- **De-identification**: Patient data in the KB is de-identified (age range, not DOB).
- **No external PII transmission**: The knowledge base stores *patterns* ("BCBS requires X for MRI"), never patient data.
- **Clinician approval required**: Per clinic-workflows skill, Walker must approve any output before it's used.

## Database Schema

The SQLite knowledge base (`data/preauth.db`) contains:

| Table | Purpose |
|---|---|
| `payers` | Insurance companies with contact info and turnaround times |
| `procedures` | Procedures/services with optional CPT codes |
| `requirements` | What each payer needs for each procedure (grows from denials) |
| `submissions` | Log of every pre-auth submitted (de-identified) |
| `denials` | Structured denial data for learning |
| `lessons_learned` | Higher-level actionable patterns |
| `followups` | Deadline tracking for submitted pre-auths |

## Testing

```bash
# Run all tests
python -m pytest tests/ -o 'addopts=' -q

# Run specific module tests
python -m pytest tests/test_denial_analyzer.py -o 'addopts=' -q
```

109 tests covering all modules.

## Project Structure

```
pre-authorization-agent/
├── src/
│   ├── __init__.py
│   ├── payer_knowledge_base.py    # SQLite learning engine
│   ├── checklist_generator.py      # Pre-submission checklists
│   ├── letter_drafter.py           # Medical necessity letter drafts
│   ├── denial_analyzer.py          # Parse denials (text/PDF/image)
│   ├── learning_loop.py            # Update KB from denial outcomes
│   ├── followup_tracker.py         # Deadline monitoring
│   └── main.py                     # CLI + PreAuthAgent class
├── tests/
│   ├── conftest.py                 # Fixtures with test data
│   ├── test_knowledge_base.py      # 38 tests
│   ├── test_denial_analyzer.py     # 28 tests
│   ├── test_checklist_generator.py # 19 tests
│   ├── test_learning_loop.py       # 12 tests
│   ├── test_letter_drafter.py      # 15 tests
│   └── test_followup_tracker.py    # 8 tests
├── data/
│   └── templates/                  # Letter templates
├── docs/
│   └── architecture.md
├── README.md
├── requirements.txt
└── LICENSE
```

## License

MIT

## Author

Walker Kirkpatrick, ND