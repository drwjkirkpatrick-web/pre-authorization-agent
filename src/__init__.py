"""
Pre-Authorization Agent
=======================
A Hermes-powered assistant for small medical practices to manage
insurance pre-authorization workflows.

Core principle: NEVER falsify information. The agent identifies what
genuine information is needed, helps collect it, and drafts accurate
paperwork. Missing information is flagged as MISSING — not invented.

Modules:
  - payer_knowledge_base: SQLite DB of payer requirements and denial patterns
  - checklist_generator: Pre-submission requirements checklist
  - letter_drafter: Letter of medical necessity drafts
  - denial_analyzer: Parse denials from text/PDF/image, extract gaps
  - learning_loop: Update knowledge base from denial outcomes
  - followup_tracker: Deadline monitoring and alerts
"""

__version__ = "0.1.0"
__license__ = "MIT"