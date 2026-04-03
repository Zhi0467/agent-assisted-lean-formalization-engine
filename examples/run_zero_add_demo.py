from __future__ import annotations

import subprocess
from pathlib import Path


def main() -> None:
    repo_root = Path(__file__).resolve().parents[1]
    command = [
        "python3",
        "-m",
        "lean_formalization_engine",
        "--input",
        str(repo_root / "examples" / "inputs" / "zero_add.md"),
        "--kind",
        "markdown",
        "--run-id",
        "zero_add_demo",
        "--auto-approve-spec",
        "--auto-approve-plan",
        "--auto-finalize",
    ]
    subprocess.run(command, cwd=repo_root, check=True)


if __name__ == "__main__":
    main()
