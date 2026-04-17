from __future__ import annotations

import unittest

from examples.run_codex_manual_review_demo import (
    validate_enrichment_handoff,
    validate_final_candidate,
    validate_plan_handoff,
)


class ManualReviewDemoValidationTest(unittest.TestCase):
    def test_validate_enrichment_handoff_accepts_self_contained_case(self) -> None:
        validate_enrichment_handoff(
            "# Enrichment Handoff\n\nThe theorem is self-contained over Nat.\nMissing prerequisites: none.\n"
        )

    def test_validate_plan_handoff_rejects_wrong_target(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "right-add-zero target"):
            validate_plan_handoff(
                "\n".join(
                    [
                        "# Plan Handoff",
                        "",
                        "Proposed theorem name: `right_add_zero_nat`",
                        "Target statement: `theorem wrong (n : Nat) : n = n`",
                        "Imports: `FormalizationEngineWorkspace.Basic`",
                        "Proof route: use `Nat.add_zero`.",
                    ]
                )
            )

    def test_validate_final_candidate_rejects_missing_target(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "right-add-zero"):
            validate_final_candidate(
                "theorem right_add_zero_nat (n : Nat) : n = n := by\n"
                "  rfl\n"
            )
