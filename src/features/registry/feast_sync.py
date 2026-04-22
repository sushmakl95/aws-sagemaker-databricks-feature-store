"""Feast registry sync helpers.

The `feast apply` command reads from `feast_repo/` and updates the registry.
These helpers wrap that for CI/CD usage and programmatic access.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from features.utils.logging_config import get_logger

log = get_logger(__name__, component="registry.feast")


def apply_registry(
    repo_path: str = "src/feast_repo",
    dry_run: bool = False,
) -> dict:
    """Run `feast apply` to sync the registry.

    In dry_run mode, runs `feast plan` instead to preview changes.
    """
    cmd = ["feast"]
    if dry_run:
        cmd.extend(["plan", "--chdir", repo_path])
    else:
        cmd.extend(["apply", "--chdir", repo_path])

    log.info("feast_registry_sync", cmd=" ".join(cmd), dry_run=dry_run)

    # cmd is a fixed list; repo_path is internal input (not user-controlled)
    result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    return {
        "returncode": result.returncode,
        "stdout": result.stdout,
        "stderr": result.stderr,
    }


def validate_repo(repo_path: str = "src/feast_repo") -> bool:
    """Verify the Feast repo structure is valid.

    Checks: feature_store.yaml exists, Python files import cleanly.
    """
    repo = Path(repo_path)
    fs_yaml = repo / "feature_store.yaml"
    if not fs_yaml.exists():
        log.error("feast_repo_missing_config", path=str(fs_yaml))
        return False

    for subdir in ("entities", "data_sources", "feature_views"):
        if not (repo / subdir).is_dir():
            log.error("feast_repo_missing_subdir", subdir=subdir)
            return False

    return True


def list_feature_views(repo_path: str = "src/feast_repo") -> list[str]:
    """Return list of feature view names defined in the repo."""
    fv_dir = Path(repo_path) / "feature_views"
    if not fv_dir.is_dir():
        return []
    return [f.stem for f in fv_dir.glob("*.py") if not f.name.startswith("_")]
