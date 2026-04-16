from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass
class TemplateResolution:
    template_dir: Path
    origin: str
    command: list[str] | None = None


def resolve_workspace_template(
    search_root: Path,
    package_template_dir: Path,
    *,
    lake_path: str | None = None,
    init_timeout_seconds: int = 20 * 60,
) -> TemplateResolution:
    discovered = _find_eligible_template(search_root)
    if discovered is not None:
        return TemplateResolution(template_dir=discovered, origin="discovered")

    target_dir = search_root / "lean_workspace_template"
    command = _initialize_workspace_template(
        search_root=search_root,
        target_dir=target_dir,
        package_template_dir=package_template_dir,
        lake_path=lake_path,
        timeout_seconds=init_timeout_seconds,
    )
    return TemplateResolution(
        template_dir=target_dir,
        origin="initialized",
        command=command,
    )


def discover_workspace_template(search_root: Path) -> Path | None:
    return _find_eligible_template(search_root)


def _find_eligible_template(search_root: Path) -> Path | None:
    candidates: list[Path] = [search_root / "lean_workspace_template"]
    for child in sorted(search_root.iterdir()):
        if not child.is_dir():
            continue
        candidates.append(child / "lean_workspace_template")

    for candidate in candidates:
        if _is_eligible_template(candidate):
            return candidate.resolve()
    return None


def _is_eligible_template(candidate: Path) -> bool:
    if not candidate.exists() or not candidate.is_dir():
        return False

    generated_module = candidate / "FormalizationEngineWorkspace" / "Generated.lean"
    basic_module = candidate / "FormalizationEngineWorkspace" / "Basic.lean"
    if not generated_module.exists() or not basic_module.exists():
        return False

    lakefile_toml = candidate / "lakefile.toml"
    lakefile_lean = candidate / "lakefile.lean"
    lake_text = ""
    if lakefile_toml.exists():
        lake_text = lakefile_toml.read_text(encoding="utf-8")
    elif lakefile_lean.exists():
        lake_text = lakefile_lean.read_text(encoding="utf-8")
    else:
        return False
    return "mathlib" in lake_text.lower()


def _initialize_workspace_template(
    *,
    search_root: Path,
    target_dir: Path,
    package_template_dir: Path,
    lake_path: str | None,
    timeout_seconds: int,
) -> list[str]:
    search_root.mkdir(parents=True, exist_ok=True)
    command: list[str] = []
    if target_dir.exists():
        if _is_eligible_template(target_dir):
            return []
        if not target_dir.is_dir():
            raise RuntimeError(f"`{target_dir}` exists but is not a directory.")
        raise RuntimeError(
            f"`{target_dir}` already exists but is not an eligible Terry template. "
            "Fix or move that directory before running Terry so local template content is not overwritten."
        )
    else:
        lake_executable = _resolve_lake(lake_path)
        if lake_executable is None:
            raise RuntimeError(
                "Could not initialize `lean_workspace_template`: `lake` is not available on PATH."
            )

        command = [lake_executable, "new", target_dir.name, "math"]
        try:
            subprocess.run(
                command,
                cwd=search_root,
                capture_output=True,
                text=True,
                check=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Timed out while running `lake new ... math` for `lean_workspace_template`."
            ) from exc
        except subprocess.CalledProcessError as exc:
            details = "\n".join(part for part in [exc.stdout, exc.stderr] if part).strip()
            raise RuntimeError(
                "Failed to initialize `lean_workspace_template` with `lake new ... math`."
                + (f"\n{details}" if details else "")
            ) from exc

    shutil.copytree(
        package_template_dir,
        target_dir,
        ignore=shutil.ignore_patterns(".git", ".lake", "build", "lake-manifest.json"),
        dirs_exist_ok=True,
    )
    return command


def _resolve_lake(configured_lake: str | None) -> str | None:
    if configured_lake:
        candidate = shutil.which(configured_lake)
        if candidate:
            return candidate

        configured_path = Path(configured_lake).expanduser()
        if configured_path.exists() and os.access(configured_path, os.X_OK):
            return str(configured_path)
        return None

    candidate = shutil.which("lake")
    if candidate:
        return candidate

    elan_candidate = Path.home() / ".elan" / "bin" / "lake"
    if elan_candidate.exists() and os.access(elan_candidate, os.X_OK):
        return str(elan_candidate)
    return None
