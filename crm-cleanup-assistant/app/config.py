"""App settings, read from environment variables."""
import os

# Postgres in production, e.g. postgresql+psycopg2://user:pass@host:5432/crm
# Falls back to a local SQLite file so the app runs with zero setup.
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./crm.db")

# If set, lead categorization and summaries use Claude. If not, a simple
# rules-based fallback runs instead, so the demo still works offline.
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CLAUDE_MODEL = os.getenv("CLAUDE_MODEL", "claude-haiku-5-5")

# Pairs scoring at or above this (0-100) are flagged as likely duplicates.
DUPLICATE_THRESHOLD = int(os.getenv("DUPLICATE_THRESHOLD", "85"))

LEAD_CATEGORIES = ["Hot", "Warm", "Cold", "Existing customer", "Not a fit"]
