# Test Coverage Plan

This document tracks which coverage gaps have been addressed and which remain open.

## Implemented (this PR)

| Test file | What it covers |
|-----------|----------------|
| `tests/test_models.py` | `utc_now` format/timezone, `to_jsonable` for all types (dataclass, enum, Path, dict, list, None), enum value assertions |
| `tests/test_ingest.py` | `detect_source_kind` for all extensions (case-insensitive), `_normalize_text` (trailing whitespace, blank-line collapsing, edge cases), `_display_path` (relative/absolute/None root), `ingest_source` for text/markdown/latex, PDF fallback RuntimeError when neither fitz nor pypdf is installed |
| `tests/test_storage.py` | `validate_run_id` (valid IDs, all invalid character classes), `ensure_new` (success + FileExistsError), `write/read_text`, `write/read_json` round-trip, `exists`, `append_log` (JSONL content, timeline.md content, stage suffix, accumulation) |
| `tests/test_prompt_loader.py` | All 9 templates exist and are non-empty, `FileNotFoundError` for missing template, `render_bullet_list` (empty → "- none", single, multiple, generator), `render_prompt_template` (substitution, missing key KeyError, missing template FileNotFoundError) |
| `tests/test_subprocess_agent.py` | Empty command ValueError, `_default_agent_name` for all forms (python -m, python -c, generic, path), `ProviderResponseError` attributes and defaults, `_invoke_provider` non-zero exit RuntimeError, FileNotFoundError for missing executable, invalid JSON ProviderResponseError, `run_stage` non-dict response, missing prompt, valid round-trip, missing raw_response fallback |

---

## Remaining High-Priority Gaps

### `workflow.py` — `_parse_review_file` with invalid decision

**Risk:** Users with a typo in `decision:` get a cryptic crash instead of a clear error.

**What to add:** A test that writes a review file with `decision: nonsense` and calls `workflow.resume()`; assert it raises a `ValueError` containing the bad value. The state machine should be at `AWAITING_ENRICHMENT_APPROVAL` (or any checkpoint stage) so the resume path reads the review file.

---

### `workflow.py` — legacy resume branches

**Risk:** Users with runs created before v0.5.0 cannot resume; the failure is silent or confusing.

**Stages to cover:** `LEGACY_AWAITING_ENRICHMENT_REVIEW`, `LEGACY_AWAITING_SPEC_REVIEW`, `LEGACY_AWAITING_PLAN_REVIEW`, `LEGACY_AWAITING_STALL_REVIEW`, `LEGACY_AWAITING_FINAL_REVIEW`.

**What to add:** For each legacy stage, write a manifest with that `current_stage` value, call `workflow.resume()` with the appropriate decision file, and assert either a clean transition or a descriptive error.

---

### `template_manager.py` — `_extract_mathlib_rev` / `_replace_mathlib_rev`

**Risk:** A regex regression silently produces a malformed lakefile; the workspace build fails with a confusing error far from the actual bug.

**What to add:** A `tests/test_template_manager.py` with direct unit tests:
- `_extract_mathlib_rev` with a valid lakefile containing `rev = "abc123"` → returns `"abc123"`
- `_extract_mathlib_rev` with no mathlib entry → returns `None`
- `_replace_mathlib_rev` with a known rev → produces expected output; verify round-trip

---

### `lean_runner.py` — `_extract_diagnostics`

**Risk:** Diagnostic parsing failures are invisible — the proof loop sees empty diagnostics, retries blindly, and hits the attempt cap without useful feedback.

**What to add:** A `tests/test_lean_runner.py` (or extend the existing workflow tests) with unit tests feeding known lake output strings to `_extract_diagnostics` and asserting the structured result. Cover: clean build (no errors), single error with file/line, multiple errors, sorry-containing output.

---

### `cli.py` — `_normalize_global_options`, `render_resume_command`, `render_retry_command`

**Risk:** Regressions in the guidance printed to the user after enrichment/plan/proof stages would go undetected.

**What to add:**
- Direct calls to `render_resume_command(manifest, ...)` asserting the output contains the correct run ID, subcommand, and `--workdir` flag.
- Direct calls to `render_retry_command(manifest, ...)` with a lake path set and without.
- `_normalize_global_options` with `--workdir` placed after the subcommand (the case it's meant to reorder).

---

### `demo_agent.py` — unmatched theorem and REVIEW with notes

**Risk:** The `ValueError` in `_select_demo_theorem` and the reviewer-notes branch in REVIEW stage are dead code from the test perspective; a refactor that breaks them goes undetected.

**What to add:**
- A workflow test that passes source text matching neither demo theorem pattern and asserts a `ValueError` is raised at the PROOF/ENRICHMENT stage.
- A REVIEW-stage test that sets `review_notes_path` to a file with content and asserts the notes are read and incorporated.

---

### `subprocess_agent.py` — `working_directory` propagation

**Risk:** The `working_directory` argument is stored but its propagation into `subprocess.run(cwd=...)` is never verified.

**What to add:** A mock test that captures the `cwd` argument passed to `subprocess.run` and asserts it equals the configured `working_directory`.

---

### `ingest.py` — PDF extraction with fitz / pypdf present

**Risk:** The happy paths of `_extract_pdf_text` (fitz and pypdf branches) are untested. A version bump in either library that changes the API would not be caught.

**What to add:** Tests using `unittest.mock.patch` to inject a fake `fitz` module (mock `fitz.open` returning pages with `get_text`) and a fake `pypdf` module (mock `PdfReader`). Assert the correct extraction method string is returned alongside the text.

---

## Lower-Priority Gaps (backlog)

- `storage.py` — concurrent `append_log` writes (requires a threading/multiprocessing test harness)
- `lean_runner.py` — `_read_git_reference` when `.git` is a file (worktree)
- `lean_runner.py` — `_parse_required_packages_from_lakefile_toml` and `_parse_required_packages_from_lakefile_lean` separately
- `cli.py` — `_validate_prove_request` with missing source file or conflicting run IDs
- `cli.py` — `_legacy_json_output` / `_render_legacy_manifest_payload` format
- `workflow.py` — `retry()` called when not in a blocked stage (expected `ValueError`)
- `workflow.py` — `_write_fallback_attempt_review` with `compile_passed=True` vs `False`
