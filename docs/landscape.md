# External Systems Worth Borrowing From

These are the main adjacent systems relevant to this repo right now.

Athena's implementation advice matched the current scaffold: stay in Python for v0, keep the
state machine file-backed, make human checkpoints first-class, and borrow narrow subsystems
instead of adopting a full agent framework.

## Lean interaction and verification

### `lean-dojo/LeanDojo-v2`
URL: https://github.com/lean-dojo/LeanDojo-v2

Borrow:
- ideas about Lean-facing infrastructure, tracing, and evaluation surfaces

Do not borrow as-is:
- the repo is much broader than a lightweight scaffold and is not the right foundation for a small explicit engine

### `augustepoiroux/LeanInteract`
URL: https://github.com/augustepoiroux/LeanInteract

Borrow:
- the shape of a future Python-facing Lean backend if file-level compilation becomes too coarse

Do not borrow as-is:
- it does not solve theorem extraction, human review, or artifact persistence

### `stanford-centaur/PyPantograph`
URL: https://github.com/stanford-centaur/PyPantograph

Borrow:
- machine-to-machine Lean interaction patterns for a later richer backend

Do not borrow as-is:
- it is backend infrastructure, not a theorem-to-Lean workflow product

## Natural-language to formalization

### `siddhartha-gadgil/LeanAide`
URL: https://github.com/siddhartha-gadgil/LeanAide

Borrow:
- the statement-first mentality: stabilize the formal target before chasing proof search

Do not borrow as-is:
- it does not give this repo a persisted run schema or a human approval loop

### `deepseek-ai/DeepSeek-Prover-V1.5`
URL: https://github.com/deepseek-ai/DeepSeek-Prover-V1.5

Borrow:
- proof-generation priors and prompt ideas once the engine has a real provider adapter

Do not borrow as-is:
- it is a proving/model artifact, not an auditable theorem-ingestion engine

## Agent-style theorem workflows

### `trishullab/copra`
URL: https://github.com/trishullab/copra

Borrow:
- compile or proof-environment feedback loops with bounded retries

Do not borrow as-is:
- this repo also needs source ingestion, artifact persistence, and human checkpoints

### `lean-dojo/LeanAgent`
URL: https://github.com/lean-dojo/LeanAgent

Borrow:
- the idea that theorem proving can be treated as an agentic loop rather than a single generation pass

Do not borrow as-is:
- the current repo needs a clean single-run scaffold before it grows into a more elaborate agent system

## Landscape index

### `WoojinCho-Ryan/awesome-autoformalization`
URL: https://github.com/WoojinCho-Ryan/awesome-autoformalization

Use this as a survey pointer when the project expands beyond the current shortlist.
