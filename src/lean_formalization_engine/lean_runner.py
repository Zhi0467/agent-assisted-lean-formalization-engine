from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import threading
from contextlib import contextmanager
from pathlib import Path

try:
    import tomllib
except ImportError:  # pragma: no cover - Python < 3.11 fallback
    tomllib = None
    TOMLDecodeError = ValueError
else:  # pragma: no cover - exercised on Python 3.11+
    TOMLDecodeError = tomllib.TOMLDecodeError

try:
    import fcntl
except ImportError:  # pragma: no cover - non-Unix fallback
    fcntl = None

try:
    import msvcrt
except ImportError:  # pragma: no cover - non-Windows fallback
    msvcrt = None

from .models import CompileAttempt
from .storage import RunStore

_THREAD_LOCKS: dict[str, threading.Lock] = {}
_THREAD_LOCKS_GUARD = threading.Lock()


class LeanRunner:
    def __init__(self, template_dir: Path, repo_root: Path | None = None, lake_path: str | None = None):
        self.template_dir = template_dir
        self.repo_root = repo_root or template_dir.parent
        self.lake_path = lake_path

    def compile_candidate(
        self,
        store: RunStore,
        candidate_relative_path: str,
        attempt: int,
    ) -> CompileAttempt:
        candidate_path = store.path(candidate_relative_path)
        content = candidate_path.read_text(encoding="utf-8")
        lake_path = self._resolve_lake()
        display_command = [
            self._display_lake(),
            "build",
            "FormalizationEngineWorkspace",
        ]
        if lake_path is None:
            return CompileAttempt(
                attempt=attempt,
                command=[" ".join(display_command)],
                stdout="",
                stderr="Lean toolchain is not available on PATH and ~/.elan/bin/lake was not found.",
                returncode=127,
                diagnostics=["Missing `lake` executable."],
                fast_check_passed=False,
                build_passed=False,
                contains_sorry="sorry" in content,
                missing_toolchain=True,
                quality_gate_passed=False,
                passed=False,
                status="toolchain_missing",
            )

        command_texts: list[str] = []
        stdout_sections: list[str] = []
        stderr_sections: list[str] = []
        workspace_fingerprint = self._workspace_fingerprint(lake_path)
        with self._workspace_lock():
            workspace, rebuilt_workspace = self._prepare_workspace(workspace_fingerprint)
            update_result = self._ensure_workspace_manifest(workspace, lake_path)
            if update_result is not None:
                update_command_text = " ".join([self._display_lake(), "update"])
                command_texts.append(update_command_text)
                stdout_sections.append(
                    self._format_process_output(
                        update_command_text,
                        update_result.stdout,
                        store,
                        workspace,
                        lake_path,
                        candidate_relative_path,
                    )
                )
                stderr_sections.append(
                    self._format_process_output(
                        update_command_text,
                        update_result.stderr,
                        store,
                        workspace,
                        lake_path,
                        candidate_relative_path,
                    )
                )
                if update_result.returncode != 0:
                    stdout = "".join(stdout_sections)
                    stderr = "".join(stderr_sections)
                    return CompileAttempt(
                        attempt=attempt,
                        command=command_texts,
                        stdout=stdout,
                        stderr=stderr,
                        returncode=update_result.returncode,
                        diagnostics=_extract_diagnostics(stderr),
                        fast_check_passed=False,
                        build_passed=False,
                        contains_sorry="sorry" in content,
                        missing_toolchain=False,
                        quality_gate_passed=False,
                        passed=False,
                        status="compile_failed",
                    )
            generated_path = workspace / "FormalizationEngineWorkspace" / "Generated.lean"
            generated_path.parent.mkdir(parents=True, exist_ok=True)
            generated_path.write_text(content, encoding="utf-8")
            self._clear_generated_build_outputs(workspace)

            build_command = [lake_path, "build", "FormalizationEngineWorkspace"]
            build_result = subprocess.run(
                build_command,
                cwd=workspace,
                capture_output=True,
                text=True,
                check=False,
            )

        contains_sorry = "sorry" in content
        fast_check_passed = build_result.returncode == 0
        build_passed = build_result.returncode == 0
        quality_gate_passed = not contains_sorry
        passed = fast_check_passed and build_passed and quality_gate_passed
        display_command_text = " ".join(display_command)
        command_texts.append(display_command_text)
        stdout_sections.append(
            self._format_process_output(
                display_command_text,
                build_result.stdout,
                store,
                workspace,
                lake_path,
                candidate_relative_path,
            )
        )
        stderr_sections.append(
            self._format_process_output(
                display_command_text,
                build_result.stderr,
                store,
                workspace,
                lake_path,
                candidate_relative_path,
            )
        )
        stdout = "".join(stdout_sections)
        stderr = "".join(stderr_sections)

        return CompileAttempt(
            attempt=attempt,
            command=command_texts,
            stdout=stdout,
            stderr=stderr,
            returncode=0 if passed else build_result.returncode,
            diagnostics=_extract_diagnostics(stderr),
            fast_check_passed=fast_check_passed,
            build_passed=build_passed,
            contains_sorry=contains_sorry,
            missing_toolchain=False,
            quality_gate_passed=quality_gate_passed,
            passed=passed,
            status="passed" if passed else "compile_failed",
        )

    def _prepare_workspace(self, fingerprint: dict[str, str]) -> tuple[Path, bool]:
        workspace = self._workspace_path()
        if workspace.exists() and self._workspace_ready(workspace) and self._read_workspace_metadata() == fingerprint:
            return workspace, False

        if workspace.exists():
            shutil.rmtree(workspace)
        workspace.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(
            self.template_dir,
            workspace,
            ignore=self._copy_template_ignore,
        )
        self._write_workspace_metadata(fingerprint)
        return workspace, True

    def _workspace_fingerprint(self, lake_executable: str) -> dict[str, str]:
        return {
            "lake_executable": lake_executable,
            "lake_signature": self._lake_signature(lake_executable),
            "template_dir": str(self.template_dir.resolve()),
            "template_hash": self._template_hash(),
        }

    def _workspace_path(self) -> Path:
        return self.repo_root / ".terry" / "lean_workspace"

    def _workspace_metadata_path(self) -> Path:
        return self.repo_root / ".terry" / "lean_workspace.json"

    def _workspace_lock_path(self) -> Path:
        return self.repo_root / ".terry" / "lean_workspace.lock"

    def _read_workspace_metadata(self) -> dict[str, str] | None:
        metadata_path = self._workspace_metadata_path()
        if not metadata_path.exists():
            return None
        lines = metadata_path.read_text(encoding="utf-8").splitlines()
        metadata: dict[str, str] = {}
        for line in lines:
            if not line or "=" not in line:
                continue
            key, value = line.split("=", 1)
            metadata[key] = value
        return metadata or None

    def _write_workspace_metadata(self, metadata: dict[str, str]) -> None:
        metadata_path = self._workspace_metadata_path()
        metadata_path.parent.mkdir(parents=True, exist_ok=True)
        metadata_path.write_text(
            "\n".join(f"{key}={value}" for key, value in sorted(metadata.items())) + "\n",
            encoding="utf-8",
        )

    def _template_hash(self) -> str:
        digest = hashlib.sha256()
        for root, dirnames, filenames in os.walk(self.template_dir):
            root_path = Path(root)
            root_relative = root_path.relative_to(self.template_dir)
            dirnames[:] = sorted(
                dirname
                for dirname in dirnames
                if not self._ignore_template_path(root_relative / dirname)
            )
            if root_relative == Path(".lake") / "packages":
                for package_dir in sorted(
                    child
                    for child in root_path.iterdir()
                    if child.is_dir() and not self._ignore_template_path(root_relative / child.name)
                ):
                    digest.update((root_relative / package_dir.name).as_posix().encode("utf-8"))
                    digest.update(b"\0")
                    digest.update(self._vendored_package_signature(package_dir).encode("utf-8"))
                    digest.update(b"\0")
                dirnames[:] = []
                continue
            for filename in sorted(filenames):
                relative_path = root_relative / filename
                if self._ignore_template_path(relative_path):
                    continue
                path = root_path / filename
                digest.update(relative_path.as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(path.read_bytes())
                digest.update(b"\0")
        return digest.hexdigest()

    def _ignore_template_path(self, relative_path: Path) -> bool:
        parts = relative_path.parts
        if ".git" in parts or ".terry" in parts:
            return True
        if relative_path.name == ".DS_Store":
            return True
        if parts and parts[0] == "build":
            return True
        if len(parts) >= 2 and parts[0] == ".lake" and parts[1] == "build":
            return True
        if len(parts) >= 4 and parts[0] == ".lake" and parts[1] == "packages" and parts[3] == "build":
            return True
        return any(part == ".lake" and parts[index + 1] == "build" for index, part in enumerate(parts[:-1]))

    def _copy_template_ignore(self, directory: str, names: list[str]) -> set[str]:
        relative_dir = Path(directory).relative_to(self.template_dir)
        return {
            name
            for name in names
            if self._ignore_template_path(relative_dir / name)
        }

    def _vendored_package_signature(self, package_dir: Path) -> str:
        git_dir = package_dir / ".git"
        if git_dir.exists():
            git_status = subprocess.run(
                ["git", "-C", str(package_dir), "status", "--porcelain=2", "--branch"],
                capture_output=True,
                text=True,
                check=False,
            )
            if git_status.returncode == 0:
                digest = hashlib.sha256()
                digest.update(git_status.stdout.encode("utf-8"))
                digest.update(git_status.stderr.encode("utf-8"))
                return digest.hexdigest()

        digest = hashlib.sha256()
        for root, dirnames, filenames in os.walk(package_dir):
            root_path = Path(root)
            root_relative = root_path.relative_to(package_dir)
            dirnames[:] = sorted(
                dirname
                for dirname in dirnames
                if not self._ignore_template_path(Path(".lake") / "packages" / package_dir.name / root_relative / dirname)
            )
            for filename in sorted(filenames):
                relative_path = root_relative / filename
                full_relative_path = Path(".lake") / "packages" / package_dir.name / relative_path
                if self._ignore_template_path(full_relative_path):
                    continue
                path = root_path / filename
                stat = path.stat()
                digest.update(relative_path.as_posix().encode("utf-8"))
                digest.update(b"\0")
                digest.update(str(stat.st_mtime_ns).encode("utf-8"))
                digest.update(b"\0")
                digest.update(str(stat.st_size).encode("utf-8"))
                digest.update(b"\0")
        return digest.hexdigest()

    def _lake_signature(self, lake_executable: str) -> str:
        signature_parts = [f"path={lake_executable}"]
        lake_path = Path(lake_executable)
        try:
            lake_stat = lake_path.stat()
        except OSError:
            lake_stat = None
        else:
            signature_parts.extend(
                [
                    f"mtime_ns={lake_stat.st_mtime_ns}",
                    f"size={lake_stat.st_size}",
                ]
            )
        try:
            resolved_path = lake_path.resolve(strict=True)
        except OSError:
            resolved_path = None
        if resolved_path is not None:
            signature_parts.append(f"resolved={resolved_path}")
            if resolved_path != lake_path:
                try:
                    resolved_stat = resolved_path.stat()
                except OSError:
                    resolved_stat = None
                else:
                    signature_parts.extend(
                        [
                            f"resolved_mtime_ns={resolved_stat.st_mtime_ns}",
                            f"resolved_size={resolved_stat.st_size}",
                        ]
                    )
        version_result = subprocess.run(
            [lake_executable, "--version"],
            capture_output=True,
            text=True,
            check=False,
        )
        signature_parts.append(f"version_returncode={version_result.returncode}")
        if version_result.stdout.strip():
            signature_parts.append(f"version_stdout={version_result.stdout.strip()}")
        if version_result.stderr.strip():
            signature_parts.append(f"version_stderr={version_result.stderr.strip()}")
        digest = hashlib.sha256()
        digest.update("\n".join(signature_parts).encode("utf-8"))
        return digest.hexdigest()

    def _workspace_ready(self, workspace: Path) -> bool:
        required_paths = [
            workspace / "FormalizationEngineWorkspace" / "Basic.lean",
            workspace / "FormalizationEngineWorkspace" / "Generated.lean",
        ]
        return all(path.exists() for path in required_paths)

    def _clear_generated_build_outputs(self, workspace: Path) -> None:
        build_roots = [
            workspace / ".lake" / "build",
            workspace / "build",
        ]
        for build_root in build_roots:
            for relative_dir in [
                Path("lib") / "FormalizationEngineWorkspace",
                Path("ir") / "FormalizationEngineWorkspace",
            ]:
                target_dir = build_root / relative_dir
                if not target_dir.exists():
                    continue
                for generated_output in target_dir.glob("Generated*"):
                    if generated_output.is_dir():
                        shutil.rmtree(generated_output, ignore_errors=True)
                    else:
                        generated_output.unlink(missing_ok=True)

    def _ensure_workspace_manifest(
        self,
        workspace: Path,
        lake_path: str,
    ) -> subprocess.CompletedProcess[str] | None:
        manifest_path = workspace / "lake-manifest.json"
        if manifest_path.exists() or self._vendored_packages_ready(workspace):
            return None
        return subprocess.run(
            [lake_path, "update"],
            cwd=workspace,
            capture_output=True,
            text=True,
            check=False,
        )

    def _vendored_packages_ready(self, workspace: Path) -> bool:
        vendored_packages_path = workspace / ".lake" / "packages"
        if not vendored_packages_path.exists():
            return False
        required_package_names = self._required_package_names(workspace)
        if required_package_names is None:
            return False
        pending = list(required_package_names)
        seen: set[str] = set()
        while pending:
            package_name = pending.pop()
            if package_name in seen:
                continue
            seen.add(package_name)
            package_dir = vendored_packages_path / package_name
            if not self._vendored_package_has_sources(package_dir):
                return False
            transitive_required = self._required_package_names(package_dir)
            if transitive_required is None:
                return False
            pending.extend(name for name in transitive_required if name not in seen)
        return True

    def _required_package_names(self, workspace: Path) -> set[str] | None:
        toml_lakefile_path = workspace / "lakefile.toml"
        if toml_lakefile_path.exists():
            try:
                lakefile_text = toml_lakefile_path.read_text(encoding="utf-8")
            except OSError:
                return None
            if tomllib is not None:
                try:
                    payload = tomllib.loads(lakefile_text)
                except (ValueError, TOMLDecodeError):
                    payload = None
                if isinstance(payload, dict):
                    require_entries = payload.get("require", [])
                    if isinstance(require_entries, list):
                        package_names = {
                            name
                            for entry in require_entries
                            if isinstance(entry, dict)
                            for name in [entry.get("name")]
                            if isinstance(name, str) and name
                        }
                        return package_names
            return self._parse_required_package_names_from_lakefile_toml(lakefile_text)

        lean_lakefile_path = workspace / "lakefile.lean"
        if lean_lakefile_path.exists():
            try:
                lakefile_text = lean_lakefile_path.read_text(encoding="utf-8")
            except OSError:
                return None
            return self._parse_required_package_names_from_lakefile_lean(lakefile_text)
        return None

    def _parse_required_package_names_from_lakefile_toml(self, lakefile_text: str) -> set[str]:
        package_names: set[str] = set()
        in_require_block = False
        for line in lakefile_text.splitlines():
            stripped = line.strip()
            if stripped.startswith("[[") and stripped.endswith("]]"):
                in_require_block = stripped == "[[require]]"
                continue
            if not in_require_block:
                continue
            match = re.match(r'^name\s*=\s*"([^"]+)"\s*$', stripped)
            if match:
                package_names.add(match.group(1))
        return package_names

    def _parse_required_package_names_from_lakefile_lean(self, lakefile_text: str) -> set[str]:
        package_names: set[str] = set()
        for line in lakefile_text.splitlines():
            match = re.match(r"^\s*require\s+([A-Za-z_][A-Za-z0-9_']*)\b", line)
            if match:
                package_names.add(match.group(1))
        return package_names

    def _vendored_package_has_sources(self, package_dir: Path) -> bool:
        if not package_dir.exists() or not package_dir.is_dir():
            return False
        for root, dirnames, filenames in os.walk(package_dir):
            root_path = Path(root)
            root_relative = root_path.relative_to(package_dir)
            dirnames[:] = sorted(
                dirname
                for dirname in dirnames
                if not self._ignore_template_path(Path(".lake") / "packages" / package_dir.name / root_relative / dirname)
            )
            for filename in filenames:
                full_relative_path = Path(".lake") / "packages" / package_dir.name / root_relative / filename
                if not self._ignore_template_path(full_relative_path):
                    return True
        return False

    @contextmanager
    def _workspace_lock(self):
        lock_path = self._workspace_lock_path()
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        thread_lock = _thread_lock_for(lock_path)
        with thread_lock:
            with lock_path.open("a+", encoding="utf-8") as handle:
                if fcntl is not None:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                elif msvcrt is not None:
                    handle.seek(0)
                    if handle.tell() == 0:
                        handle.write("0")
                        handle.flush()
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                try:
                    yield
                finally:
                    if fcntl is not None:
                        fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                    elif msvcrt is not None:
                        handle.seek(0)
                        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)

    def _resolve_lake(self) -> str | None:
        if self.lake_path:
            configured = shutil.which(self.lake_path)
            if configured:
                return configured

            configured_path = Path(self.lake_path).expanduser()
            if configured_path.exists() and os.access(configured_path, os.X_OK):
                return str(configured_path)
            return None

        candidate = shutil.which("lake")
        if candidate:
            return candidate

        elan_candidate = Path.home() / ".elan" / "bin" / "lake"
        if elan_candidate.exists():
            return str(elan_candidate)
        return None

    def _display_lake(self) -> str:
        if self.lake_path:
            configured = Path(self.lake_path).expanduser()
            if configured.is_absolute() or "/" in self.lake_path:
                return configured.name
            return self.lake_path
        return "lake"

    def _sanitize_output(
        self,
        content: str,
        store: RunStore,
        workspace: Path,
        lake_path: str,
        candidate_relative_path: str,
    ) -> str:
        run_root_display = f"artifacts/runs/{store.run_id}"
        generated_path = workspace / "FormalizationEngineWorkspace" / "Generated.lean"
        sanitized = content.replace(
            str(generated_path),
            f"{run_root_display}/{candidate_relative_path}",
        )
        sanitized = sanitized.replace(str(workspace), self._workspace_display_path(workspace))
        sanitized = sanitized.replace(str(store.run_root), run_root_display)
        sanitized = sanitized.replace(lake_path, self._display_lake())
        sanitized = sanitized.replace(str(Path.home()), "~")
        return sanitized

    def _format_process_output(
        self,
        command_text: str,
        content: str,
        store: RunStore,
        workspace: Path,
        lake_path: str,
        candidate_relative_path: str,
    ) -> str:
        return (
            f"$ {command_text}\n"
            f"{self._sanitize_output(content, store, workspace, lake_path, candidate_relative_path)}"
        )

    def _workspace_display_path(self, workspace: Path) -> str:
        try:
            return workspace.relative_to(self.repo_root).as_posix()
        except ValueError:
            return str(workspace)


def _extract_diagnostics(stderr: str) -> list[str]:
    return [line.strip() for line in stderr.splitlines() if line.strip()][-10:]


def _thread_lock_for(lock_path: Path) -> threading.Lock:
    key = str(lock_path.resolve())
    with _THREAD_LOCKS_GUARD:
        lock = _THREAD_LOCKS.get(key)
        if lock is None:
            lock = threading.Lock()
            _THREAD_LOCKS[key] = lock
        return lock
