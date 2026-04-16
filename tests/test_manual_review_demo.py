from __future__ import annotations

import unittest

from examples.run_codex_manual_review_demo import (
    validate_enrichment_report,
    validate_final_candidate,
    validate_formalization_plan,
)


class ManualReviewDemoValidationTest(unittest.TestCase):
    def test_validate_enrichment_report_accepts_self_contained_case(self) -> None:
        validate_enrichment_report(
            {
                "self_contained": True,
                "missing_prerequisites": [],
            }
        )

    def test_validate_formalization_plan_rejects_wrong_target(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "target statement"):
            validate_formalization_plan(
                {
                    "theorem_name": "right_add_zero_nat",
                    "imports": ["FormalizationEngineWorkspace.Basic"],
                    "proof_sketch": ["Use Nat.add_zero."],
                    "assumptions": ["n : Nat"],
                    "target_statement": "theorem wrong (n : Nat) : n = n",
                }
            )

    def test_validate_final_candidate_rejects_missing_nat_add_zero(self) -> None:
        with self.assertRaisesRegex(RuntimeError, "Nat.add_zero"):
            validate_final_candidate(
                "import FormalizationEngineWorkspace.Basic\n\n"
                "theorem right_add_zero_nat (n : Nat) : n + 0 = n := by\n"
                "  rfl\n"
            )
