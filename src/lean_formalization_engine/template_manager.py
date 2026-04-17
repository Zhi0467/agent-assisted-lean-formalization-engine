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
    warning: str | None = None


@dataclass
class TemplateVersionPins:
    lean_toolchain: str | None = None
    mathlib_rev: str | None = None


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
    if not target_dir.exists() and _resolve_lake(lake_path) is None:
        return TemplateResolution(template_dir=package_template_dir.resolve(), origin="packaged", command=[])
    return _initialize_workspace_template(
        search_root=search_root,
        target_dir=target_dir,
        package_template_dir=package_template_dir,
        lake_path=lake_path,
        timeout_seconds=init_timeout_seconds,
    )


def discover_workspace_template(search_root: Path) -> Path | None:
    return _find_eligible_template(search_root)


def _find_eligible_template(search_root: Path) -> Path | None:
    if not search_root.exists() or not search_root.is_dir():
        return None
    candidates: list[Path] = [search_root / "lean_workspace_template"]
    for child in sorted(search_root.iterdir()):
        if not child.is_dir():
            continue
        candidates.append(child / "lean_workspace_template")

    eligible = [candidate.resolve() for candidate in candidates if _is_eligible_template(candidate)]
    if not eligible:
        return None
    if len(eligible) > 1:
        listed = ", ".join(str(path) for path in eligible)
        raise RuntimeError(
            "Found multiple eligible `lean_workspace_template` directories at depth 1. "
            f"Keep only one Terry template in this repo before continuing: {listed}"
        )
    return eligible[0]


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
) -> TemplateResolution:
    search_root.mkdir(parents=True, exist_ok=True)
    command: list[str] = []
    generated_pins: TemplateVersionPins | None = None
    if target_dir.exists():
        if _is_eligible_template(target_dir):
            return TemplateResolution(template_dir=target_dir.resolve(), origin="discovered", command=[])
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
            generated_pins = _capture_initialized_version_pins(target_dir)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(
                "Timed out while running `lake new ... math` for `lean_workspace_template`."
            ) from exc
        except subprocess.CalledProcessError as exc:
            details = "\n".join(part for part in [exc.stdout, exc.stderr] if part).strip()
            if not _is_packaged_template_fallback_error(details):
                shutil.rmtree(target_dir, ignore_errors=True)
                raise RuntimeError(
                    "Failed to initialize `lean_workspace_template` with `lake new ... math`."
                    + (f"\n{details}" if details else "")
                ) from exc
            shutil.rmtree(target_dir, ignore_errors=True)
            _copy_packaged_template(package_template_dir, target_dir)
            warning = (
                "`lake new ... math` failed, so Terry copied the packaged workspace template "
                "into `lean_workspace_template` instead."
            )
            if details:
                warning = f"{warning}\n{details}"
            return TemplateResolution(
                template_dir=target_dir.resolve(),
                origin="packaged-fallback",
                command=command,
                warning=warning,
            )

    _copy_packaged_template(package_template_dir, target_dir)
    if generated_pins is not None:
        _restore_initialized_version_pins(target_dir, generated_pins)
    return TemplateResolution(
        template_dir=target_dir.resolve(),
        origin="initialized",
        command=command,
    )


def _copy_packaged_template(package_template_dir: Path, target_dir: Path) -> None:
    shutil.copytree(
        package_template_dir,
        target_dir,
        ignore=shutil.ignore_patterns(".git", ".lake", "build", "lake-manifest.json"),
        dirs_exist_ok=True,
    )


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


def _is_packaged_template_fallback_error(details: str) -> bool:
    normalized = details.lower()
    return "mathlib" in normalized and "revision not found" in normalized


def _capture_initialized_version_pins(target_dir: Path) -> TemplateVersionPins:
    toolchain_path = target_dir / "lean-toolchain"
    lakefile_path = target_dir / "lakefile.toml"
    return TemplateVersionPins(
        lean_toolchain=toolchain_path.read_text(encoding="utf-8") if toolchain_path.exists() else None,
        mathlib_rev=_extract_mathlib_rev(lakefile_path.read_text(encoding="utf-8")) if lakefile_path.exists() else None,
    )


def _restore_initialized_version_pins(target_dir: Path, pins: TemplateVersionPins) -> None:
    if pins.lean_toolchain is not None:
        (target_dir / "lean-toolchain").write_text(pins.lean_toolchain, encoding="utf-8")
    if pins.mathlib_rev is None:
        return

    lakefile_path = target_dir / "lakefile.toml"
    if not lakefile_path.exists():
        return
    lakefile_path.write_text(
        _replace_mathlib_rev(lakefile_path.read_text(encoding="utf-8"), pins.mathlib_rev),
        encoding="utf-8",
    )


def _extract_mathlib_rev(lakefile_text: str) -> str | None:
    blocks = lakefile_text.split("[[require]]")
    for block in blocks[1:]:
        if 'name = "mathlib"' not in block:
            continue
        for raw_line in block.splitlines():
            line = raw_line.strip()
            if line.startswith("rev = "):
                return line.split("=", 1)[1].strip().strip('"')
    return None


def _replace_mathlib_rev(lakefile_text: str, revision: str) -> str:
    blocks = lakefile_text.split("[[require]]")
    rebuilt: list[str] = [blocks[0]]
    replaced = False
    for block in blocks[1:]:
        block_text = "[[require]]" + block
        if not replaced and 'name = "mathlib"' in block_text:
            lines = block_text.splitlines()
            for index, raw_line in enumerate(lines):
                if raw_line.strip().startswith("rev = "):
                    prefix = raw_line.split("rev", 1)[0]
                    lines[index] = f'{prefix}rev = "{revision}"'
                    replaced = True
                    break
            block_text = "\n".join(lines)
        rebuilt.append(block_text)
    return "".join(rebuilt)
