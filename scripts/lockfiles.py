#!/usr/bin/env python3
"""Generate or verify all pip-compile lockfiles from package metadata.

Root ``pyproject.toml`` is the only dependency manifest. Each generated lock
is mirrored inside ``ultron-v6/`` as a regular file so both repository-level
scanners and package-local tooling consume the same pinned dependency set.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PACKAGE = ROOT / "ultron-v6"
PYPROJECT = ROOT / "pyproject.toml"
# Resolution evaluates environment markers. Use one declared baseline so all
# five candidates remain byte-reproducible; it also matches the newest Python
# supported by the vulnerability-constrained Chroma dependency set.
LOCK_PYTHON = (3, 11)


@dataclass(frozen=True)
class LockSpec:
    """A lockfile and the optional-dependency groups it includes."""

    filename: str
    extras: tuple[str, ...] = ()
    build_only: bool = False


LOCKS = (
    LockSpec("requirements-build.lock", build_only=True),
    LockSpec("requirements.lock"),
    LockSpec("requirements-dev.lock", ("dev",)),
    LockSpec("requirements-chroma.lock", ("chroma",)),
    LockSpec("requirements-all.lock", ("all",)),
)


def _compile(spec: LockSpec, destination: Path, *, upgrade: bool) -> None:
    """Compile one deterministic candidate, seeding existing pins by default."""
    source = PACKAGE / spec.filename
    if source.exists() and not upgrade:
        shutil.copyfile(source, destination)

    command = [
        sys.executable,
        "-m",
        "piptools",
        "compile",
        "--quiet",
        "--no-header",
        "--strip-extras",
        "--generate-hashes",
        "--reuse-hashes",
        "--allow-unsafe",
        "--no-emit-index-url",
        "--no-emit-trusted-host",
        "--resolver=backtracking",
        f"--output-file={destination}",
    ]
    if upgrade:
        command.append("--upgrade")
    if spec.build_only:
        command.extend(("--all-build-deps", "--only-build-deps"))
    command.extend(f"--extra={extra}" for extra in spec.extras)
    command.append(PYPROJECT.name)
    try:
        subprocess.run(command, cwd=ROOT, check=True)  # noqa: S603
    except subprocess.CalledProcessError as exc:
        raise SystemExit(
            f"pip-compile failed for {spec.filename} (exit {exc.returncode}); "
            "install requirements-dev.lock and review the output above"
        ) from None


def _write(upgrade: bool) -> int:
    with tempfile.TemporaryDirectory(prefix="ultron-locks-") as temp:
        temporary = Path(temp)
        for spec in LOCKS:
            candidate = temporary / spec.filename
            _compile(spec, candidate, upgrade=upgrade)
            package_lock = PACKAGE / spec.filename
            root_lock = ROOT / spec.filename
            shutil.copyfile(candidate, package_lock)
            if root_lock.is_symlink():
                root_lock.unlink()
            shutil.copyfile(candidate, root_lock)
            print(f"wrote {package_lock.relative_to(ROOT)} and {spec.filename}")
    return 0


def _check() -> int:
    failures: list[str] = []
    with tempfile.TemporaryDirectory(prefix="ultron-lock-check-") as temp:
        temporary = Path(temp)
        for spec in LOCKS:
            package_lock = PACKAGE / spec.filename
            root_lock = ROOT / spec.filename
            if not package_lock.is_file():
                failures.append(f"missing {package_lock.relative_to(ROOT)}")
                continue
            if root_lock.is_symlink() or not root_lock.is_file():
                failures.append(f"{spec.filename} must be a regular root-level mirror")
            elif root_lock.read_bytes() != package_lock.read_bytes():
                failures.append(f"{spec.filename} differs from its package mirror")

            candidate = temporary / spec.filename
            _compile(spec, candidate, upgrade=False)
            if candidate.read_bytes() != package_lock.read_bytes():
                failures.append(
                    f"{package_lock.relative_to(ROOT)} is out of sync with "
                    "pyproject.toml"
                )

    if failures:
        print("Lockfile verification failed:", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)
        print("Run 'make lockfiles' and commit every changed lock.", file=sys.stderr)
        return 1
    print(f"Verified {len(LOCKS)} lockfiles and their root-level mirrors.")
    return 0


def _validate_manifest() -> None:
    """Keep the cross-version ``all`` extra equal to its component groups."""
    import tomllib  # noqa: PLC0415 (the script enforces Python 3.11 first)

    with PYPROJECT.open("rb") as stream:
        groups = tomllib.load(stream)["project"]["optional-dependencies"]
    expected = [*groups["secrets"], *groups["observability"]]
    if sorted(groups["all"]) != sorted(expected):
        raise SystemExit(
            "pyproject.toml extra 'all' must equal the union of 'secrets' and "
            "'observability'"
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--check", action="store_true", help="fail on lock drift")
    mode.add_argument("--write", action="store_true", help="regenerate locks")
    parser.add_argument(
        "--upgrade",
        action="store_true",
        help="resolve newest compatible versions (only valid with --write)",
    )
    args = parser.parse_args(argv)
    if args.upgrade and not args.write:
        parser.error("--upgrade requires --write")
    running_python = sys.version_info[:2]
    if running_python != LOCK_PYTHON:
        parser.error(
            "lock generation and verification require Python "
            f"{LOCK_PYTHON[0]}.{LOCK_PYTHON[1]} (running "
            f"{running_python[0]}.{running_python[1]}) so environment markers "
            "resolve reproducibly"
        )
    _validate_manifest()
    return _write(upgrade=args.upgrade) if args.write else _check()


if __name__ == "__main__":
    raise SystemExit(main())
