from __future__ import annotations

from pathlib import Path


class CaseLoader:
    """Base helper for case-directory loader classes."""

    def __init__(self, case_path: str | Path) -> None:
        self.case_path = Path(case_path)
