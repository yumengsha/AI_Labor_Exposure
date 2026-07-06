"""
schema.py
=========
The structured-output contract for a single task's AI-exposure score.

Claude is constrained to return exactly this shape (via messages.parse / Pydantic),
so every row is valid and range-checked before it ever reaches a CSV or Snowflake.
The three scores are independent (see rubric.md) — none is derived from the others.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class TaskScore(BaseModel):
    """One task's three independent AI scores + confidence + rationale."""

    ai_exposure_score: float = Field(
        ge=0.0, le=1.0,
        description="Overall degree the task is affected by current AI (0-1).",
    )
    automation_score: float = Field(
        ge=0.0, le=1.0,
        description="Likelihood AI performs the task in place of the human (0-1).",
    )
    augmentation_score: float = Field(
        ge=0.0, le=1.0,
        description="Likelihood AI assists a human doing the task, human in loop (0-1).",
    )
    confidence: float = Field(
        ge=0.0, le=1.0,
        description="Confidence in these scores given the task/occupation info (0-1).",
    )
    rationale: str = Field(
        max_length=240,
        description="One sentence naming the deciding factor. No numbers.",
    )
