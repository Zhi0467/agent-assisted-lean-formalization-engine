from __future__ import annotations

from typing import Protocol

from .models import AgentTurn, StageRequest


class FormalizationAgent(Protocol):
    name: str

    def run_stage(self, request: StageRequest) -> AgentTurn:
        ...
