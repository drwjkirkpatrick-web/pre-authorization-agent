# Architecture

## Overview

The Pre-Authorization Agent is a six-module Python application backed by a SQLite database. It runs as a CLI tool and is designed to integrate with Hermes Agent as a skill for Telegram-based interaction.

## Data Flow

```
Practitioner: "I need pre-auth for knee MRI for [de-identified patient]"
    ↓
ChecklistGenerator: "Need: 6wk conservative tx, weight-bearing X-ray, knee exam with effusion"
    ↓
Practitioner: collects missing info, provides it
    ↓
LetterDrafter: Drafts letter of medical necessity (DRAFT — Walker reviews)
    ↓
Practitioner: reviews, edits, signs, submits to insurance
    ↓
PreAuthAgent.log_submission(): Logs submission in KB, creates follow-up tracking
    ↓
FollowUpTracker: Tracks deadline, alerts via cron if overdue
    ↓
Insurance: approves or denies
    ↓
If denied:
    Practitioner: pastes/types/scans denial letter
    ↓
    DenialAnalyzer: Extracts denial code, category, missing items, appeal deadline
    ↓
    LearningLoop:
        1. Records denial in KB
        2. Extracts missing items → adds as new requirements (learned_from_denial=True)
        3. Creates lesson learned
        4. Generates remediation checklist
    ↓
    Next time same payer+procedure comes up:
        ChecklistGenerator automatically includes the new requirements
```

## Module Details

### PayerKnowledgeBase (`payer_knowledge_base.py`)

SQLite database with 7 tables:

- **payers**: Insurance companies with contact info, turnaround times, appeal deadline windows
- **procedures**: Medical procedures with optional CPT codes and categories
- **requirements**: Per payer+procedure: what's needed (history, labs, exams, imaging, prior treatment, documentation). Each requirement is tagged with its source: `general`, `policy`, `web_research`, or `denial`. The `learned_from_denial` flag marks requirements discovered from denial letters.
- **submissions**: De-identified log of every pre-auth submitted. Stores age range (not DOB), sex (if relevant), problem summary, what was included, and status.
- **denials**: Structured denial data: code, reason, category, missing items (JSON), appeal deadline, policy cited, raw text.
- **lessons_learned**: Higher-level patterns with frequency counters. Same lesson seen twice → frequency incremented.
- **followups**: Expected response dates and appeal deadlines for tracking.

Key design decision: requirements use a UNIQUE constraint on (payer_id, procedure_id, requirement_type, requirement_desc) to prevent duplicates. When the same requirement is added from a more authoritative source (e.g., a denial vs general knowledge), the source is upgraded.

### ChecklistGenerator (`checklist_generator.py`)

Two-tier checklist generation:

1. **KB-driven**: When the knowledge base has requirements for this payer+procedure, use them. Supplement with any general criteria not already covered.
2. **Fallback**: When no KB data exists, use GENERAL_CRITERIA — a hardcoded dict of common medical necessity requirements by procedure category (MRI, CT, Surgery, Specialist, Therapy, DME, Default).

Each checklist item is checked against provided clinical info and marked:
- ✅ satisfied — clinical info covers this
- ❌ missing — clinical info does NOT cover this
- ❓ unknown — cannot determine
- 🔎 check — some info provided, verify match

### DenialAnalyzer (`denial_analyzer.py`)

Multi-format input:
- Text paste → direct analysis
- Digital PDF → pdfplumber extraction
- Scanned PDF/image → pytesseract OCR, or Hermes vision tool

Analysis pipeline:
1. Extract denial code (CARC: CO-XX, PR-XX; RARC: N####, M####)
2. Classify category via keyword matching (missing_info, not_medically_necessary, not_covered, etc.)
3. Extract missing items via regex patterns (conservative treatment, labs, exam, imaging, etc.)
4. Extract appeal deadline (within X days, by [date], X days from date of letter)
5. Extract policy citation
6. Generate remediation checklist

### LearningLoop (`learning_loop.py`)

The core differentiator. After `process_denial()`:
1. Denial is recorded in the `denials` table
2. Each missing item becomes a new requirement in the `requirements` table, tagged `learned_from_denial=True, source='denial'`
3. A lesson learned is created (or frequency incremented if same lesson exists)
4. Submission status updated to `denied` or `denied_appealable`
5. Remediation checklist generated for the practitioner

After `process_approval()`:
1. Submission status updated to `approved`
2. If the submission included items that were learned from past denials, those requirements are validated (positive reinforcement)

### LetterDrafter (`letter_drafter.py`)

Builds a structured letter with sections:
- Header (practice info)
- Date
- Recipient (payer)
- RE: line (patient identifiers — filled by Walker)
- Opening paragraph (procedure, diagnosis, codes if provided)
- Clinical History
- Physical Examination
- Laboratory Results
- Imaging
- Prior Treatment / Conservative Care Trial
- Medical Necessity Justification
- Red Flags / Clinical Concerns (if provided)
- Request for Authorization
- Attachments list
- Closing

Safety rules:
- `[MISSING — TO BE COMPLETED]` for any absent clinical data
- ICD-10/CPT codes only included if explicitly provided
- Draft notice at top: "⚠️ DRAFT — DO NOT SUBMIT WITHOUT CLINICIAN REVIEW"
- No guideline claims unless Walker supplies them

### FollowUpTracker (`followup_tracker.py`)

Two alert types:
- **overdue**: Submission still pending past expected response date
- **appeal_deadline**: Denied submission with approaching appeal deadline (🚨 URGENT if ≤7 days, ⚠️ if ≤14 days)

Designed for Hermes cron: `check_for_overdue()` returns alerts, `format_alerts()` produces a Telegram-ready message.