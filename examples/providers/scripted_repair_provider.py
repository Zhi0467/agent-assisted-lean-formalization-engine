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
            "An existing natural-language proof is available directly from the theorem input plus `Nat.zero_add`.",
            "No prerequisites are missing, and the plan can stay focused on the theorem itself.",
            "",
            "Recommended scope: keep the theorem over `Nat` and reuse the existing core lemma.",
            "",
        ]
    )
    natural_language_proof = "\n".join(
        [
            "# Natural-Language Proof",
            "",
            "The claim follows from the library fact `Nat.zero_add`: for every natural number `n`, `0 + n = n`.",
            "",
        ]
    )
    natural_language_statement = "\n".join(
        [
            "# Natural-Language Statement",
            "",
            "For every natural number `n`, prove that `0 + n = n`.",
            "",
        ]
    )
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "handoff.md").write_text(handoff, encoding="utf-8")
    (output_dir / "natural_language_statement.md").write_text(natural_language_statement, encoding="utf-8")
    (output_dir / "natural_language_proof.md").write_text(natural_language_proof, encoding="utf-8")
    (output_dir / "proof_status.json").write_text(
        json.dumps(
            {
                "obtained": True,
                "source": "input",
                "notes": "The provider is formalizing a theorem with an explicit known proof route.",
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return "\n\n".join([handoff, natural_language_statement, natural_language_proof])


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


def _write_attempt_review(request: dict[str, object]) -> str:
    output_dir = _resolve(request, str(request["output_dir"]))
    compile_path = _resolve(request, str(request["latest_compile_result_path"]))
    compile_payload = json.loads(compile_path.read_text(encoding="utf-8"))
    candidate_path = _resolve(request, str(request["input_paths"]["attempt_candidate"]))
    candidate_text = candidate_path.read_text(encoding="utf-8")
    output_dir.mkdir(parents=True, exist_ok=True)
    walkthrough = "\n".join(
        [
            "# Attempt Walkthrough",
            "",
            "This attempt imports the Terry workspace and proves the theorem directly from `Nat.zero_add`.",
            "The Lean body is a single `simpa` step, so the code matches the natural-language proof exactly.",
            "",
        ]
    )
    readable_candidate = "\n".join(
        [
            "-- Human-readable rewrite of the Terry proof attempt.",
            candidate_text.strip(),
            "",
        ]
    )
    error_report = "\n".join(
        [
            "# Error Report",
            "",
            (
                "This attempt compiled cleanly; there is no Lean error to repair."
                if compile_payload.get("passed")
                else f"Terry saw `{compile_payload.get('status', 'unknown')}` on this attempt."
            ),
            "",
        ]
    )
    (output_dir / "walkthrough.md").write_text(walkthrough, encoding="utf-8")
    (output_dir / "readable_candidate.lean").write_text(readable_candidate, encoding="utf-8")
    (output_dir / "error.md").write_text(error_report, encoding="utf-8")
    return "\n\n".join([walkthrough, error_report])


def main() -> int:
    request = json.load(sys.stdin)
    stage = request.get("stage")

    if stage == "enrichment":
        raw_response = _write_enrichment(request)
        prompt = (
            "Write the enrichment handoff, natural-language proof, and proof-status files "
            "under the requested output directory."
        )
    elif stage == "plan":
        raw_response = _write_plan(request)
        prompt = "Write the plan handoff under the requested output directory."
    elif stage == "proof":
        raw_response = _write_candidate(request)
        prompt = "Write the Lean candidate under the requested proof-attempt directory."
    elif stage == "review":
        raw_response = _write_attempt_review(request)
        prompt = "Write the Terry review artifacts under the requested proof-attempt directory."
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
