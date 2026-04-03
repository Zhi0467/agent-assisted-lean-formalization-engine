# Landscape

This project is not trying to be a full theorem-proving research stack on day one.
The main goal of the current scaffold is a clean agentic engine surface with persisted
artifacts and a Lean compile loop.

## Lean Interaction / Proving Infrastructure

### LeanDojo / LeanDojo-v2

- Repo: https://github.com/lean-dojo/LeanDojo
- Repo: https://github.com/lean-dojo/LeanDojo-v2
- Influence here:
  retrieval, tracing, and larger-scale Lean interaction patterns.
- Does not solve here:
  PDF/Markdown ingestion, explicit human checkpoints, or a small public-engine scaffold.

### LeanInteract

- Repo: https://github.com/augustepoiroux/LeanInteract
- Influence here:
  future shape of a richer Lean backend if the engine graduates from whole-file compile
  checks to command-level interaction.
- Does not solve here:
  theorem extraction, artifact persistence, or the human review loop.

### PyPantograph

- Repo: https://github.com/stanford-centaur/PyPantograph
- Influence here:
  another future backend option for programmatic Lean interaction from Python.
- Does not solve here:
  source ingestion, model orchestration, or review checkpoints.

## Natural Language To Formalization

### LeanAide

- Repo: https://github.com/siddhartha-gadgil/LeanAide
- Influence here:
  statement-first formalization. The engine should lock the intended theorem meaning
  before it starts proof generation.
- Does not solve here:
  the repo’s run-state machine, compile/repair loop, or artifact audit trail.

### DeepSeek-Prover

- Repo: https://github.com/deepseek-ai/DeepSeek-Prover-V1.5
- Influence here:
  model-side proof generation and repair intuition once a real provider is added.
- Does not solve here:
  turning PDFs/Markdown into approved theorem specs or handling human checkpoints.

## Agent-Style Theorem Workflows

### COPRA

- Repo: https://github.com/trishullab/copra
- Influence here:
  bounded retry against proof-environment feedback instead of a single shot.
- Does not solve here:
  source ingestion, repo-local artifacts, or a clean single-engine scaffold.

### LeanAgent

- Repo: https://github.com/lean-dojo/LeanAgent
- Influence here:
  long-horizon theorem-proving loops and agentic search ideas.
- Does not solve here:
  the current product surface, which is intentionally much smaller and more auditable.

## Working Conclusion

For this repo, the right v0 is smaller than the research systems above:

- one engine,
- one persisted run record,
- explicit checkpoints,
- whole-file Lean compile and repair,
- future-compatible interfaces for richer backends later.
