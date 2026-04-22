#!/usr/bin/env python3
"""Validate Feast feature view definitions.

CI entry point. Parses each .py file under src/feast_repo/feature_views/
and enforces platform conventions:
  - FV name pattern
  - TTL minimum (reject < 5 min)
  - Required tags (owner must be set)
  - No duplicate feature names across FVs in the same repo

Usage: python scripts/validate_feature_views.py <feature_views_dir>
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

NAME_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
MIN_TTL_SECONDS = 5 * 60  # 5 minutes


def _extract_fv_metadata(path: Path) -> list[dict]:
    """Parse the Python file AST and pull out FeatureView constructor calls.

    Returns a list of dicts with keys: name, ttl_keyword, schema_keyword,
    tags_keyword, file. Values are the raw AST nodes -- caller inspects.
    """
    tree = ast.parse(path.read_text(), filename=str(path))
    feature_views: list[dict] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func_name = _callable_name(node.func)
        if func_name != "FeatureView":
            continue

        kwargs = {kw.arg: kw.value for kw in node.keywords if kw.arg}
        feature_views.append({
            "file": str(path),
            "name": _literal(kwargs.get("name")),
            "ttl": kwargs.get("ttl"),
            "schema": kwargs.get("schema"),
            "tags": kwargs.get("tags"),
            "online": _literal(kwargs.get("online")),
        })
    return feature_views


def _callable_name(node) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _literal(node):
    if node is None:
        return None
    if isinstance(node, ast.Constant):
        return node.value
    return None


def _ttl_seconds(ttl_node) -> int | None:
    """Recognize timedelta(...) and return total seconds, if possible."""
    if not isinstance(ttl_node, ast.Call):
        return None
    callable_name = _callable_name(ttl_node.func)
    if callable_name != "timedelta":
        return None

    seconds = 0
    for kw in ttl_node.keywords:
        if not kw.arg:
            continue
        value = _literal(kw.value)
        if not isinstance(value, (int, float)):
            return None
        multipliers = {
            "seconds": 1, "minutes": 60, "hours": 3600,
            "days": 86400, "weeks": 604800,
        }
        if kw.arg in multipliers:
            seconds += value * multipliers[kw.arg]
    return seconds if seconds > 0 else None


def _tag_value(tags_node, key: str):
    """Extract a string value from a dict literal AST."""
    if not isinstance(tags_node, ast.Dict):
        return None
    for k, v in zip(tags_node.keys, tags_node.values, strict=False):
        if isinstance(k, ast.Constant) and k.value == key:
            return _literal(v)
    return None


def _schema_field_names(schema_node) -> list[str]:
    """From a `schema=[Field(name='...'), ...]` list literal AST."""
    if not isinstance(schema_node, ast.List):
        return []
    names: list[str] = []
    for elt in schema_node.elts:
        if not isinstance(elt, ast.Call):
            continue
        if _callable_name(elt.func) != "Field":
            continue
        for kw in elt.keywords:
            if kw.arg == "name":
                value = _literal(kw.value)
                if value:
                    names.append(str(value))
    return names


def validate(fvs: list[dict]) -> list[str]:
    """Return a list of error messages. Empty list if all valid."""
    errors: list[str] = []
    seen_feature_names: dict[str, str] = {}  # feature_name -> fv_name

    for fv in fvs:
        file_short = Path(fv["file"]).name
        fv_name = fv["name"]
        prefix = f"[{file_short}] "

        if not fv_name:
            errors.append(f"{prefix}FeatureView missing 'name' keyword argument")
            continue

        if not NAME_PATTERN.match(fv_name):
            errors.append(
                f"{prefix}'{fv_name}' violates naming pattern {NAME_PATTERN.pattern}"
            )

        # TTL validation
        ttl_sec = _ttl_seconds(fv["ttl"])
        if ttl_sec is None:
            errors.append(f"{prefix}'{fv_name}' has no TTL or non-literal timedelta")
        elif ttl_sec < MIN_TTL_SECONDS:
            errors.append(
                f"{prefix}'{fv_name}' TTL {ttl_sec}s is below minimum {MIN_TTL_SECONDS}s"
            )

        # Tag validation -- owner is required
        owner = _tag_value(fv["tags"], "owner")
        if not owner:
            errors.append(
                f"{prefix}'{fv_name}' missing required tag 'owner'"
            )

        # Duplicate feature name check
        feature_names = _schema_field_names(fv["schema"])
        for fname in feature_names:
            if fname in seen_feature_names:
                errors.append(
                    f"{prefix}'{fv_name}' redefines feature '{fname}' "
                    f"(already defined in '{seen_feature_names[fname]}')"
                )
            else:
                seen_feature_names[fname] = fv_name

    return errors


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("Usage: validate_feature_views.py <feature_views_dir>")
        return 2

    root = Path(argv[1])
    if not root.is_dir():
        print(f"ERROR: {root} is not a directory")
        return 2

    files = [
        f for f in sorted(root.rglob("*.py"))
        if not f.name.startswith("_")
    ]

    if not files:
        print(f"No feature view files found under {root}")
        return 0

    print(f"Validating feature views in {len(files)} file(s)...\n")

    all_fvs: list[dict] = []
    for f in files:
        fvs = _extract_fv_metadata(f)
        all_fvs.extend(fvs)
        print(f"  {f.relative_to(root.parent)}: {len(fvs)} FV(s)")

    print(f"\nTotal feature views: {len(all_fvs)}\n")

    errors = validate(all_fvs)
    if errors:
        print(f"FAIL: {len(errors)} validation error(s)")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(f"OK: all {len(all_fvs)} feature views valid")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
