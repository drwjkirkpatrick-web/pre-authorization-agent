"""
Payer Knowledge Base — SQLite-backed learning engine for pre-authorization.

This module manages all persistent data for the pre-authorization agent:
  - Payers (insurance companies)
  - Procedures (what the clinic requests pre-auth for)
  - Requirements (what each payer needs for each procedure)
  - Submissions (log of every pre-auth submitted and its outcome)
  - Denials (structured denial data for learning)
  - Lessons learned (extracted actionable rules)

CRITICAL: This database stores PATTERNS and REQUIREMENTS, never patient PHI.
Patient-specific data lives only in de-identified submission logs (age range,
sex, problem list — per clinic-workflows de-identification rules).
"""

import sqlite3
import json
import os
from datetime import datetime, date
from pathlib import Path
from typing import Optional


# ─── Schema ──────────────────────────────────────────────────────────────
# The schema is designed to be self-documenting. Each table has a clear
# purpose in the learning loop: requirements ← denials ← lessons_learned.

SCHEMA_SQL = """
-- Insurance companies / payers
CREATE TABLE IF NOT EXISTS payers (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL UNIQUE,         -- "BCBS of Oregon", "Aetna", "Cigna"
    portal_url  TEXT,                          -- online pre-auth portal
    phone       TEXT,                          -- pre-auth phone line
    fax         TEXT,                          -- fax for submissions
    turnaround_days INTEGER DEFAULT 7,         -- typical response time
    appeal_deadline_days INTEGER DEFAULT 30,   -- deadline to file appeal
    notes       TEXT,                          -- free-text payer quirks
    created_at  TEXT DEFAULT (datetime('now')),
    updated_at  TEXT DEFAULT (datetime('now'))
);

-- Procedures / services that need pre-auth
CREATE TABLE IF NOT EXISTS procedures (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    name        TEXT NOT NULL,                -- "Lumbar MRI", "Knee Arthroscopy"
    cpt_code    TEXT,                         -- CPT code if known (not fabricated)
    category    TEXT,                         -- "imaging", "surgery", "specialist", "therapy"
    notes       TEXT,
    created_at  TEXT DEFAULT (datetime('now'))
);

-- Requirements: what each payer needs for each procedure
-- This is the table that GROWS from learning. Each denial adds rows here.
CREATE TABLE IF NOT EXISTS requirements (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    payer_id        INTEGER NOT NULL REFERENCES payers(id),
    procedure_id    INTEGER NOT NULL REFERENCES procedures(id),
    requirement_type TEXT NOT NULL,            -- "history", "lab", "exam", "imaging",
                                               -- "prior_treatment", "documentation",
                                               -- "duration", "threshold"
    requirement_desc TEXT NOT NULL,            -- "Documented 6-week conservative treatment trial"
    detail          TEXT,                      -- JSON: thresholds, specific values, etc.
    is_mandatory    INTEGER DEFAULT 1,         -- 1=required for approval, 0=helpful but optional
    learned_from_denial INTEGER DEFAULT 0,    -- 1=this requirement was learned from a denial
    source          TEXT DEFAULT 'general',   -- "general", "denial", "policy", "web_research"
    created_at      TEXT DEFAULT (datetime('now')),
    updated_at      TEXT DEFAULT (datetime('now')),
    UNIQUE(payer_id, procedure_id, requirement_type, requirement_desc)
);

-- Submissions: log of every pre-auth submitted
-- De-identified: no patient names, DOBs, MRNs. Only age range, sex, problem.
CREATE TABLE IF NOT EXISTS submissions (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    payer_id        INTEGER NOT NULL REFERENCES payers(id),
    procedure_id    INTEGER NOT NULL REFERENCES procedures(id),
    diagnosis       TEXT,                      -- working diagnosis (text, not code unless confirmed)
    icd10_code      TEXT,                      -- only if Walker confirmed it
    cpt_code        TEXT,                      -- only if Walker confirmed it
    age_range       TEXT,                      -- "30-39", "60-69" — NOT exact age
    sex             TEXT,                      -- "M", "F", or NULL if not relevant
    problem_summary TEXT,                      -- brief de-identified clinical summary
    included_items  TEXT,                      -- JSON list of what was submitted
    letter_text     TEXT,                      -- the drafted letter (stored for reference)
    status          TEXT DEFAULT 'submitted',  -- "submitted", "approved", "denied",
                                               -- "denied_appealable", "expired", "withdrawn"
    submitted_date  TEXT,                      -- ISO date
    response_date   TEXT,                      -- when payer responded (NULL if pending)
    auth_number     TEXT,                      -- pre-auth number if approved
    created_at     TEXT DEFAULT (datetime('now'))
);

-- Denials: structured data from denial letters / EOBs
CREATE TABLE IF NOT EXISTS denials (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id       INTEGER NOT NULL REFERENCES submissions(id),
    denial_code         TEXT,                  -- payer's denial reason code
    denial_reason       TEXT NOT NULL,          -- narrative: "insufficient conservative treatment"
    denial_category     TEXT,                  -- "missing_info", "not_medically_necessary",
                                                -- "not_covered", "prior_auth_required",
                                                -- "out_of_network", "other"
    missing_items        TEXT,                   -- JSON list of what was missing
    is_appealable       INTEGER DEFAULT 1,
    appeal_deadline     TEXT,                   -- ISO date
    policy_cited        TEXT,                   -- payer policy referenced in denial
    raw_text            TEXT,                   -- full denial text for reference
    analyzed_at         TEXT DEFAULT (datetime('now')),
    created_at          TEXT DEFAULT (datetime('now'))
);

-- Lessons learned: extracted actionable rules from patterns
-- These are higher-level insights, e.g. "BCBS always requires 6wk conservative tx before MRI"
CREATE TABLE IF NOT EXISTS lessons_learned (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    payer_id        INTEGER REFERENCES payers(id),    -- NULL = applies to all payers
    procedure_id    INTEGER REFERENCES procedures(id), -- NULL = applies to all procedures
    lesson          TEXT NOT NULL,                    -- "Always document 6wk conservative treatment"
    lesson_type     TEXT,                             -- "requirement", "timing", "format", "common_pitfall"
    frequency       INTEGER DEFAULT 1,                -- how many times this pattern seen
    first_seen      TEXT DEFAULT (datetime('now')),
    last_seen       TEXT DEFAULT (datetime('now'))
);

-- Follow-up tracking: deadlines for submitted pre-auths
CREATE TABLE IF NOT EXISTS followups (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    submission_id   INTEGER NOT NULL REFERENCES submissions(id),
    expected_date   TEXT NOT NULL,             -- when response is expected
    appeal_deadline TEXT,                      -- if denied, appeal deadline
    alert_sent      INTEGER DEFAULT 0,         -- 1 if alert already sent
    notes           TEXT,
    created_at      TEXT DEFAULT (datetime('now'))
);
"""


class PayerKnowledgeBase:
    """
    SQLite-backed knowledge base for pre-authorization requirements and learning.

    All methods are designed to be safe for a clinical setting:
      - No patient identifiers stored
      - Requirements are tagged with their source (general, denial, policy)
      - Every denial can feed back into requirements (the learning loop)
    """

    def __init__(self, db_path: str = None):
        """
        Initialize the knowledge base.

        Args:
            db_path: Path to the SQLite database file.
                     Defaults to data/preauth.db relative to this module.
        """
        if db_path is None:
            # Default path: data/preauth.db in the project directory
            project_root = Path(__file__).parent.parent
            db_path = project_root / "data" / "preauth.db"

        self.db_path = str(db_path)
        os.makedirs(os.path.dirname(self.db_path), exist_ok=True)
        self._init_schema()

    def _init_schema(self):
        """Create tables if they don't exist. Safe to call multiple times."""
        with sqlite3.connect(self.db_path) as conn:
            conn.executescript(SCHEMA_SQL)
            conn.commit()

    def _get_conn(self) -> sqlite3.Connection:
        """Get a SQLite connection with row factory for dict-like access."""
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        return conn

    # ─── Payers ──────────────────────────────────────────────────────────

    def add_payer(self, name: str, portal_url: str = None, phone: str = None,
                  fax: str = None, turnaround_days: int = 7,
                  appeal_deadline_days: int = 30, notes: str = None) -> int:
        """
        Add or update an insurance payer.

        Returns the payer ID. If the payer already exists (by name), updates it.
        """
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM payers WHERE name = ?", (name,)
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE payers SET portal_url=?, phone=?, fax=?,
                       turnaround_days=?, appeal_deadline_days=?, notes=?,
                       updated_at=datetime('now') WHERE id=?""",
                    (portal_url, phone, fax, turnaround_days,
                     appeal_deadline_days, notes, existing['id'])
                )
                conn.commit()
                return existing['id']

            cursor = conn.execute(
                """INSERT INTO payers (name, portal_url, phone, fax,
                   turnaround_days, appeal_deadline_days, notes)
                   VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (name, portal_url, phone, fax, turnaround_days,
                 appeal_deadline_days, notes)
            )
            conn.commit()
            return cursor.lastrowid

    def get_payer(self, payer_id: int) -> Optional[dict]:
        """Get a payer by ID. Returns dict or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM payers WHERE id = ?", (payer_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_payer_by_name(self, name: str) -> Optional[dict]:
        """Get a payer by name (case-insensitive). Returns dict or None."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM payers WHERE LOWER(name) = LOWER(?)", (name,)
            ).fetchone()
            return dict(row) if row else None

    def list_payers(self) -> list[dict]:
        """List all payers."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM payers ORDER BY name"
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Procedures ──────────────────────────────────────────────────────

    def add_procedure(self, name: str, cpt_code: str = None,
                      category: str = None, notes: str = None) -> int:
        """
        Add a procedure. If one with the same name exists, return its ID.
        Never fabricate CPT codes — only store if provided.
        """
        with self._get_conn() as conn:
            existing = conn.execute(
                "SELECT id FROM procedures WHERE name = ?", (name,)
            ).fetchone()

            if existing:
                return existing['id']

            cursor = conn.execute(
                """INSERT INTO procedures (name, cpt_code, category, notes)
                   VALUES (?, ?, ?, ?)""",
                (name, cpt_code, category, notes)
            )
            conn.commit()
            return cursor.lastrowid

    def get_procedure(self, procedure_id: int) -> Optional[dict]:
        """Get a procedure by ID."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM procedures WHERE id = ?", (procedure_id,)
            ).fetchone()
            return dict(row) if row else None

    def get_procedure_by_name(self, name: str) -> Optional[dict]:
        """Get a procedure by name (case-insensitive)."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM procedures WHERE LOWER(name) = LOWER(?)", (name,)
            ).fetchone()
            return dict(row) if row else None

    def list_procedures(self) -> list[dict]:
        """List all procedures."""
        with self._get_conn() as conn:
            rows = conn.execute(
                "SELECT * FROM procedures ORDER BY name"
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Requirements ─────────────────────────────────────────────────────
    # This is the heart of the learning engine.
    # Requirements grow over time as denials reveal what payers need.

    def add_requirement(self, payer_id: int, procedure_id: int,
                        requirement_type: str, requirement_desc: str,
                        detail: dict = None, is_mandatory: bool = True,
                        learned_from_denial: bool = False,
                        source: str = "general") -> int:
        """
        Add a requirement for a payer+procedure combination.

        If the same requirement already exists, it is NOT duplicated
        (UNIQUE constraint on payer_id, procedure_id, requirement_type, requirement_desc).

        Args:
            payer_id: Which insurance company
            procedure_id: Which procedure
            requirement_type: One of: history, lab, exam, imaging,
                             prior_treatment, documentation, duration, threshold
            requirement_desc: Human-readable description of what's needed
            detail: Optional dict with specifics (thresholds, values, etc.)
            is_mandatory: True if required for approval, False if helpful
            learned_from_denial: True if this was discovered from a denial
            source: Where this requirement came from:
                    "general" - standard medical knowledge
                    "denial" - learned from a specific denial
                    "policy" - from payer policy document
                    "web_research" - from online research
        """
        detail_json = json.dumps(detail) if detail else None

        with self._get_conn() as conn:
            try:
                cursor = conn.execute(
                    """INSERT INTO requirements
                       (payer_id, procedure_id, requirement_type,
                        requirement_desc, detail, is_mandatory,
                        learned_from_denial, source)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (payer_id, procedure_id, requirement_type,
                     requirement_desc, detail_json,
                     1 if is_mandatory else 0,
                     1 if learned_from_denial else 0,
                     source)
                )
                conn.commit()
                return cursor.lastrowid
            except sqlite3.IntegrityError:
                # Already exists — update the source if this one has more authority
                # (denial > policy > web_research > general)
                source_rank = {"general": 0, "web_research": 1,
                               "policy": 2, "denial": 3}
                existing = conn.execute(
                    """SELECT id, source FROM requirements
                       WHERE payer_id=? AND procedure_id=?
                       AND requirement_type=? AND requirement_desc=?""",
                    (payer_id, procedure_id, requirement_type, requirement_desc)
                ).fetchone()

                if existing and source_rank.get(source, 0) > source_rank.get(existing['source'], 0):
                    conn.execute(
                        """UPDATE requirements SET source=?,
                           learned_from_denial=?, updated_at=datetime('now')
                           WHERE id=?""",
                        (source, 1 if learned_from_denial else 0, existing['id'])
                    )
                    conn.commit()
                return existing['id'] if existing else None

    def get_requirements(self, payer_id: int, procedure_id: int) -> list[dict]:
        """
        Get all requirements for a specific payer+procedure combination.

        Returns list of requirement dicts, mandatory ones first.
        Each dict includes a parsed 'detail' field (dict or None).
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT * FROM requirements
                   WHERE payer_id = ? AND procedure_id = ?
                   ORDER BY is_mandatory DESC, requirement_type""",
                (payer_id, procedure_id)
            ).fetchall()

            results = []
            for row in rows:
                d = dict(row)
                d['detail'] = json.loads(d['detail']) if d['detail'] else None
                d['is_mandatory'] = bool(d['is_mandatory'])
                d['learned_from_denial'] = bool(d['learned_from_denial'])
                results.append(d)
            return results

    def get_all_requirements_for_payer(self, payer_id: int) -> list[dict]:
        """Get all requirements for a payer across all procedures."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT r.*, p.name as procedure_name
                   FROM requirements r
                   JOIN procedures p ON r.procedure_id = p.id
                   WHERE r.payer_id = ?
                   ORDER BY p.name, r.is_mandatory DESC""",
                (payer_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Submissions ─────────────────────────────────────────────────────

    def add_submission(self, payer_id: int, procedure_id: int,
                       diagnosis: str = None, icd10_code: str = None,
                       cpt_code: str = None, age_range: str = None,
                       sex: str = None, problem_summary: str = None,
                       included_items: list = None, letter_text: str = None,
                       submitted_date: str = None) -> int:
        """
        Log a new pre-authorization submission.

        All patient data is DE-IDENTIFIED:
          - age_range: "30-39", NOT exact age
          - sex: "M"/"F"/None
          - problem_summary: brief clinical description, no names
          - icd10_code / cpt_code: ONLY if Walker confirmed them
        """
        if submitted_date is None:
            submitted_date = date.today().isoformat()

        included_json = json.dumps(included_items) if included_items else None

        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO submissions
                   (payer_id, procedure_id, diagnosis, icd10_code, cpt_code,
                    age_range, sex, problem_summary, included_items,
                    letter_text, status, submitted_date)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'submitted', ?)""",
                (payer_id, procedure_id, diagnosis, icd10_code, cpt_code,
                 age_range, sex, problem_summary, included_json,
                 letter_text, submitted_date)
            )
            conn.commit()
            return cursor.lastrowid

    def update_submission_status(self, submission_id: int, status: str,
                                  response_date: str = None,
                                  auth_number: str = None):
        """
        Update a submission's status.

        status: "approved", "denied", "denied_appealable", "expired", "withdrawn"
        """
        if response_date is None and status in ("approved", "denied", "denied_appealable"):
            response_date = date.today().isoformat()

        with self._get_conn() as conn:
            conn.execute(
                """UPDATE submissions SET status=?, response_date=?,
                   auth_number=? WHERE id=?""",
                (status, response_date, auth_number, submission_id)
            )
            conn.commit()

    def get_submission(self, submission_id: int) -> Optional[dict]:
        """Get a submission by ID with all fields."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM submissions WHERE id = ?", (submission_id,)
            ).fetchone()
            if row:
                d = dict(row)
                d['included_items'] = json.loads(d['included_items']) if d['included_items'] else []
                return d
            return None

    def list_submissions(self, payer_id: int = None,
                         status: str = None, limit: int = 50) -> list[dict]:
        """
        List submissions, optionally filtered by payer or status.
        """
        query = """SELECT s.*, p.name as payer_name, pr.name as procedure_name
                   FROM submissions s
                   JOIN payers p ON s.payer_id = p.id
                   JOIN procedures pr ON s.procedure_id = pr.id"""
        params = []
        clauses = []

        if payer_id:
            clauses.append("s.payer_id = ?")
            params.append(payer_id)
        if status:
            clauses.append("s.status = ?")
            params.append(status)

        if clauses:
            query += " WHERE " + " AND ".join(clauses)

        query += " ORDER BY s.submitted_date DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ─── Denials ─────────────────────────────────────────────────────────

    def add_denial(self, submission_id: int, denial_reason: str,
                   denial_code: str = None, denial_category: str = None,
                   missing_items: list = None, is_appealable: bool = True,
                   appeal_deadline: str = None, policy_cited: str = None,
                   raw_text: str = None) -> int:
        """
        Record a denial. This is the input to the learning loop.

        Args:
            submission_id: Which submission was denied
            denial_reason: Narrative reason from the denial letter
            denial_code: Payer's code (e.g., "PR-1", "CO-50")
            denial_category: Categorized type of denial
            missing_items: JSON list of what was missing
            is_appealable: Whether appeal is an option
            appeal_deadline: ISO date for appeal deadline
            policy_cited: Medical necessity policy referenced
            raw_text: Full denial text for reference
        """
        missing_json = json.dumps(missing_items) if missing_items else None

        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO denials
                   (submission_id, denial_code, denial_reason, denial_category,
                    missing_items, is_appealable, appeal_deadline,
                    policy_cited, raw_text)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (submission_id, denial_code, denial_reason, denial_category,
                 missing_json, 1 if is_appealable else 0,
                 appeal_deadline, policy_cited, raw_text)
            )
            conn.commit()
            return cursor.lastrowid

    def get_denial(self, denial_id: int) -> Optional[dict]:
        """Get a denial by ID with parsed fields."""
        with self._get_conn() as conn:
            row = conn.execute(
                "SELECT * FROM denials WHERE id = ?", (denial_id,)
            ).fetchone()
            if row:
                d = dict(row)
                d['missing_items'] = json.loads(d['missing_items']) if d['missing_items'] else []
                d['is_appealable'] = bool(d['is_appealable'])
                return d
            return None

    def get_denials_by_payer(self, payer_id: int) -> list[dict]:
        """Get all denials for a specific payer (for pattern analysis)."""
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT d.*, s.payer_id, s.procedure_id
                   FROM denials d
                   JOIN submissions s ON d.submission_id = s.id
                   WHERE s.payer_id = ?
                   ORDER BY d.created_at DESC""",
                (payer_id,)
            ).fetchall()
            return [dict(r) for r in rows]

    def get_denials_by_payer_procedure(self, payer_id: int,
                                        procedure_id: int) -> list[dict]:
        """
        Get all denials for a specific payer+procedure combination.
        This is used by the learning loop to find recurring patterns.
        """
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT d.* FROM denials d
                   JOIN submissions s ON d.submission_id = s.id
                   WHERE s.payer_id = ? AND s.procedure_id = ?
                   ORDER BY d.created_at DESC""",
                (payer_id, procedure_id)
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Lessons Learned ─────────────────────────────────────────────────

    def add_lesson(self, lesson: str, payer_id: int = None,
                   procedure_id: int = None, lesson_type: str = "requirement",
                   frequency: int = 1) -> int:
        """
        Add or update a lesson learned.

        If the same lesson already exists for the same payer+procedure,
        increment its frequency counter instead of duplicating.
        """
        with self._get_conn() as conn:
            existing = conn.execute(
                """SELECT id, frequency FROM lessons_learned
                   WHERE lesson = ? AND
                   COALESCE(payer_id, -1) = COALESCE(?, -1) AND
                   COALESCE(procedure_id, -1) = COALESCE(?, -1)""",
                (lesson, payer_id, procedure_id)
            ).fetchone()

            if existing:
                conn.execute(
                    """UPDATE lessons_learned SET frequency=?,
                       last_seen=datetime('now') WHERE id=?""",
                    (existing['frequency'] + 1, existing['id'])
                )
                conn.commit()
                return existing['id']

            cursor = conn.execute(
                """INSERT INTO lessons_learned
                   (payer_id, procedure_id, lesson, lesson_type, frequency)
                   VALUES (?, ?, ?, ?, ?)""",
                (payer_id, procedure_id, lesson, lesson_type, frequency)
            )
            conn.commit()
            return cursor.lastrowid

    def get_lessons(self, payer_id: int = None,
                    procedure_id: int = None) -> list[dict]:
        """Get lessons, optionally filtered by payer or procedure."""
        with self._get_conn() as conn:
            query = "SELECT * FROM lessons_learned"
            params = []
            clauses = []

            if payer_id:
                clauses.append("(payer_id = ? OR payer_id IS NULL)")
                params.append(payer_id)
            if procedure_id:
                clauses.append("(procedure_id = ? OR procedure_id IS NULL)")
                params.append(procedure_id)

            if clauses:
                query += " WHERE " + " AND ".join(clauses)

            query += " ORDER BY frequency DESC, last_seen DESC"

            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    # ─── Follow-ups ──────────────────────────────────────────────────────

    def add_followup(self, submission_id: int, expected_date: str,
                     appeal_deadline: str = None, notes: str = None) -> int:
        """Add a follow-up tracking entry for a submitted pre-auth."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """INSERT INTO followups
                   (submission_id, expected_date, appeal_deadline, notes)
                   VALUES (?, ?, ?, ?)""",
                (submission_id, expected_date, appeal_deadline, notes)
            )
            conn.commit()
            return cursor.lastrowid

    def get_pending_followups(self) -> list[dict]:
        """
        Get all follow-ups that haven't been alerted yet and may be overdue.

        Returns entries where alert_sent=0 and expected_date <= today.
        """
        today = date.today().isoformat()
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT f.*, s.payer_id, s.procedure_id, s.status,
                          p.name as payer_name, pr.name as procedure_name
                   FROM followups f
                   JOIN submissions s ON f.submission_id = s.id
                   JOIN payers p ON s.payer_id = p.id
                   JOIN procedures pr ON s.procedure_id = pr.id
                   WHERE f.alert_sent = 0
                   AND f.expected_date <= ?
                   AND s.status = 'submitted'
                   ORDER BY f.expected_date ASC""",
                (today,)
            ).fetchall()
            return [dict(r) for r in rows]

    def mark_alert_sent(self, followup_id: int):
        """Mark a follow-up alert as sent (prevents duplicate alerts)."""
        with self._get_conn() as conn:
            conn.execute(
                "UPDATE followups SET alert_sent = 1 WHERE id = ?",
                (followup_id,)
            )
            conn.commit()

    def get_overdue_appeals(self) -> list[dict]:
        """Get denied submissions with upcoming appeal deadlines."""
        today = date.today().isoformat()
        with self._get_conn() as conn:
            rows = conn.execute(
                """SELECT f.*, s.payer_id, s.procedure_id, s.status,
                          p.name as payer_name, pr.name as procedure_name
                   FROM followups f
                   JOIN submissions s ON f.submission_id = s.id
                   JOIN payers p ON s.payer_id = p.id
                   JOIN procedures pr ON s.procedure_id = pr.id
                   WHERE f.appeal_deadline IS NOT NULL
                   AND f.appeal_deadline >= ?
                   AND s.status IN ('denied', 'denied_appealable')
                   ORDER BY f.appeal_deadline ASC""",
                (today,)
            ).fetchall()
            return [dict(r) for r in rows]

    # ─── Statistics ──────────────────────────────────────────────────────

    def get_stats(self) -> dict:
        """Get summary statistics for the dashboard."""
        with self._get_conn() as conn:
            stats = {}
            stats['total_payers'] = conn.execute(
                "SELECT COUNT(*) as c FROM payers"
            ).fetchone()['c']
            stats['total_procedures'] = conn.execute(
                "SELECT COUNT(*) as c FROM procedures"
            ).fetchone()['c']
            stats['total_submissions'] = conn.execute(
                "SELECT COUNT(*) as c FROM submissions"
            ).fetchone()['c']

            # Approval rate
            decided = conn.execute(
                "SELECT COUNT(*) as c FROM submissions WHERE status IN ('approved', 'denied', 'denied_appealable')"
            ).fetchone()['c']
            approved = conn.execute(
                "SELECT COUNT(*) as c FROM submissions WHERE status = 'approved'"
            ).fetchone()['c']
            stats['approval_rate'] = f"{approved}/{decided}" if decided > 0 else "N/A"
            stats['approval_pct'] = round(approved / decided * 100, 1) if decided > 0 else 0

            stats['total_denials'] = conn.execute(
                "SELECT COUNT(*) as c FROM denials"
            ).fetchone()['c']
            stats['total_requirements'] = conn.execute(
                "SELECT COUNT(*) as c FROM requirements"
            ).fetchone()['c']
            stats['learned_requirements'] = conn.execute(
                "SELECT COUNT(*) as c FROM requirements WHERE learned_from_denial = 1"
            ).fetchone()['c']
            stats['total_lessons'] = conn.execute(
                "SELECT COUNT(*) as c FROM lessons_learned"
            ).fetchone()['c']
            stats['pending_followups'] = conn.execute(
                "SELECT COUNT(*) as c FROM followups WHERE alert_sent = 0"
            ).fetchone()['c']

            return stats

    # ─── Utility ─────────────────────────────────────────────────────────

    def find_or_create_payer(self, name: str) -> int:
        """Convenience: get payer ID by name, creating if needed."""
        payer = self.get_payer_by_name(name)
        if payer:
            return payer['id']
        return self.add_payer(name)

    def find_or_create_procedure(self, name: str) -> int:
        """Convenience: get procedure ID by name, creating if needed."""
        proc = self.get_procedure_by_name(name)
        if proc:
            return proc['id']
        return self.add_procedure(name)