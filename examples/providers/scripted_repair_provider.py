from __future__ import annotations

import json
import sys
from pathlib import Path


def _resolve(request: dict[str, object], relative_path: str) -> Path:
    return Path(str(request["repo_root"])) / relative_path


def _write_enrichment(request: dict[str, object]) -> str:
    output_dir = _resolve(request, str(request["output_dir"]))
    handoff = "\n".join(
        [
            "# Enrichment Handoff",
            "",
            "The theorem is already self-contained for Lean over `Nat`.",
            "No prerequisites are missing, and the plan can stay focused on the theorem itself.",
            "",
            "Recommended scope: keep the theorem over `Nat` and reuse the existing core lemma.",
            "",
        ]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "handoff.md").write_text(handoff, encoding="utf-8")
    return handoff


def _write_plan(request: dict[str, object]) -> str:
    output_dir = _resolve(request, str(request["output_dir"]))
    handoff = "\n".join(
        [
            "# Plan Handoff",
            "",
            "Keep the theorem over natural numbers and formalize it directly in the local Terry workspace.",
            "",
            "Proposed theorem name: `zero_add_provider_demo`",
            "Target statement: `theorem zero_add_provider_demo (n : Nat) : 0 + n = n`",
            "Imports: `FormalizationEngineWorkspace.Basic`",
            "Proof route: use `Nat.zero_add`.",
            "",
        ]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "handoff.md").write_text(handoff, encoding="utf-8")
    return handoff


def _write_candidate(request: dict[str, object]) -> str:
    output_dir = _resolve(request, str(request["output_dir"]))
    output_dir.mkdir(parents=True, exist_ok=True)
    previous_compile = request.get("latest_compile_result_path")

    if previous_compile is None:
        content = "\n".join(
            [
                "import FormalizationEngineWorkspace.Basic",
                "",
                "theorem zero_add_provider_demo (n : Nat) : 0 + n = n := by",
                "  sorry",
                "",
            ]
        )
    else:
        compile_payload = json.loads(_resolve(request, str(previous_compile)).read_text(encoding="utf-8"))
        if not compile_payload.get("contains_sorry"):
            raise RuntimeError("The scripted repair provider expected the first failure to come from `sorry`.")
        content = "\n".join(
            [
                "import FormalizationEngineWorkspace.Basic",
                "",
                "theorem zero_add_provider_demo (n : Nat) : 0 + n = n := by",
                "  simpa using Nat.zero_add n",
                "",
            ]
        )

    (output_dir / "candidate.lean").write_text(content, encoding="utf-8")
    return content


def main() -> int:
    request = json.load(sys.stdin)
    stage = request.get("stage")

    if stage == "enrichment":
        raw_response = _write_enrichment(request)
        prompt = "Write the enrichment handoff under the requested output directory."
    elif stage == "plan":
        raw_response = _write_plan(request)
        prompt = "Write the plan handoff under the requested output directory."
    elif stage == "proof":
        raw_response = _write_candidate(request)
        prompt = "Write the Lean candidate under the requested proof-attempt directory."
    else:
        raise RuntimeError(f"Unsupported stage: {stage}")

    json.dump(
        {
            "prompt": prompt,
            "raw_response": raw_response,
        },
        sys.stdout,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
