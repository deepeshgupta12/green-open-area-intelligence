"""Test-wide settings.

The QA agents call Gemini when credentials are configured; the suite runs
them only where a test enables them explicitly with stubbed agents.
"""

import os

os.environ.setdefault("QA_AGENTS_ENABLED", "false")
os.environ.setdefault("QA_TEACHER_ENABLED", "false")
