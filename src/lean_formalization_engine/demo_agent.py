from __future__ import annotations

from pathlib import Path

from .models import AgentTurn, BackendStage, StageRequest, to_jsonable


class DemoFormalizationAgent:
    """Deterministic backend used to exercise the Terry workflow end to end."""

    name = "demo_zero_add_agent"

    def run_stage(self, request: StageRequest) -> AgentTurn:
        repo_root = Path(request.repo_root)
        output_dir = repo_root / request.output_dir
        output_dir.mkdir(parents=True, exist_ok=True)

        source_text = self._read_input(repo_root, request, "normalized_source")
        theorem = self._select_demo_theorem(source_text)

        if request.stage == BackendStage.ENRICHMENT:
            handoff = "\n".join(
                [
                    "# Enrichment Handoff",
                    "",
                    theorem["enrichment_summary"],
                    "",
                    "Missing prerequisites: none.",
                    f"Recommended scope: {theorem['scope']}",
                    "",
                ]
            )
            (output_dir / "handoff.md").write_text(handoff, encoding="utf-8")
            return AgentTurn(
                request_payload=to_jsonable(request),
                prompt="Write an enrichment handoff that says whether the theorem is ready for planning.",
                raw_response=handoff,
            )

        if request.stage == BackendStage.PLAN:
            handoff = "\n".join(
                [
                    "# Plan Handoff",
                    "",
                    theorem["plan_summary"],
                    "",
                    f"Proposed theorem name: `{theorem['theorem_name']}`",
                    f"Target statement: `{theorem['target_statement']}`",
                    f"Imports: `{theorem['import_name']}`",
                    f"Proof route: use `{theorem['lemma']}`.",
                    "",
                ]
            )
            (output_dir / "handoff.md").write_text(handoff, encoding="utf-8")
            return AgentTurn(
                request_payload=to_jsonable(request),
                prompt="Write a plan handoff that locks the theorem statement and Lean proof route.",
                raw_response=handoff,
            )

        if request.stage != BackendStage.PROOF:
            raise ValueError(f"Unsupported demo stage `{request.stage.value}`.")

        candidate = "\n".join(
            [
                f"import {theorem['import_name']}",
                "",
                f"{theorem['target_statement']} := by",
                f"  simpa using {theorem['lemma_call']}",
                "",
            ]
        )
        (output_dir / "candidate.lean").write_text(candidate, encoding="utf-8")
        return AgentTurn(
            request_payload=to_jsonable(request),
            prompt=(
                "Write the Lean candidate for the approved plan. "
                f"Attempt: {request.attempt}/{request.max_attempts}"
            ),
            raw_response=candidate,
        )

    def _read_input(self, repo_root: Path, request: StageRequest, name: str) -> str:
        relative_path = request.input_paths.get(name)
        if relative_path is None:
            raise ValueError(f"Demo backend expected input `{name}` for `{request.stage.value}`.")
        return (repo_root / relative_path).read_text(encoding="utf-8")

    def _select_demo_theorem(self, normalized_source: str) -> dict[str, str]:
        lowered = normalized_source.lower()
        if "n + 0 = n" in normalized_source or "zero on the right" in lowered:
            return {
                "enrichment_summary": (
                    "The theorem is already self-contained for Lean over `Nat`. "
                    "The standard library lemma `Nat.add_zero` is enough."
                ),
                "scope": "Keep the theorem over `Nat` and reuse `Nat.add_zero`.",
                "plan_summary": (
                    "Keep the theorem over natural numbers and formalize it directly in the "
                    "local Terry workspace."
                ),
                "theorem_name": "right_add_zero_demo",
                "target_statement": "theorem right_add_zero_demo (n : Nat) : n + 0 = n",
                "lemma": "Nat.add_zero",
                "lemma_call": "Nat.add_zero n",
                "import_name": "FormalizationEngineWorkspace.Basic",
            }

        if "0 + n = n" in normalized_source or "zero on the left" in lowered:
            return {
                "enrichment_summary": (
                    "The theorem is already self-contained for Lean over `Nat`. "
                    "The standard library lemma `Nat.zero_add` is enough."
                ),
                "scope": "Keep the theorem over `Nat` and reuse `Nat.zero_add`.",
                "plan_summary": (
                    "Keep the theorem over natural numbers and formalize it directly in the "
                    "local Terry workspace."
                ),
                "theorem_name": "zero_add_demo",
                "target_statement": "theorem zero_add_demo (n : Nat) : 0 + n = n",
                "lemma": "Nat.zero_add",
                "lemma_call": "Nat.zero_add n",
                "import_name": "FormalizationEngineWorkspace.Basic",
            }

        raise ValueError(
            "The demo backend only supports the shipped natural-number zero-add examples. "
            "Use the Codex or command backend for broader theorem coverage."
        )
