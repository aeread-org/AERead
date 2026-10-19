"""Check a resolved registration file against both parent revisions (#178).

Run from a scratch worktree before committing a conflicted merge. This checks
structure, not scorer semantics; the scoring-contract tests remain required.
"""

from __future__ import annotations

import argparse
import ast
import collections
from pathlib import Path
import subprocess


SET_POLICIES = {
    "_NOT_YET_MIGRATED_TRUSTED_KEYS": "intersection",
    "_BRIDGE_GATED_ENROLLED_FAMILY_VERSIONS": "union",
}


def module_bindings(
    source: str, *, mutable: bool = True, allow_star_imports: bool = False
) -> dict[str, list[ast.stmt]]:
    bindings = collections.defaultdict(list)
    namespaces = collections.defaultdict(set)
    for node in ast.parse(source).body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            bindings[node.name].append(node)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                # import urllib.error + import urllib.request load siblings
                # into one namespace; they do not shadow different objects.
                if not alias.asname:
                    previous = namespaces[name]
                    if previous and alias.name not in previous:
                        previous.add(alias.name)
                        continue
                    previous.add(alias.name)
                bindings[name].append(node)
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "*":
                    if allow_star_imports:
                        continue
                    raise ValueError("star imports make bound-name checking ambiguous")
                bindings[alias.asname or alias.name].append(node)
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                for name in ast.walk(target):
                    if isinstance(name, ast.Name) and isinstance(name.ctx, ast.Store) and (mutable or name.id.isupper()
                            or (name.id.startswith("__") and name.id.endswith("__"))):
                        bindings[name.id].append(node)
    return dict(bindings)


def literal_set(source: str, name: str) -> set | None:
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.Assign, ast.AnnAssign)):
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        if not any(isinstance(target, ast.Name) and target.id == name for target in targets):
            continue
        value = node.value
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name) and value.func.id in {"frozenset", "set"}:
            if value.keywords or len(value.args) > 1:
                raise ValueError(f"{name} must be a literal set")
            value = value.args[0] if value.args else ast.Set(elts=[])
        result = ast.literal_eval(value)
        if not isinstance(result, (set, tuple, list)):
            raise ValueError(f"{name} must be a literal set")
        return set(result)
    return None


def exits(statements: list[ast.stmt]) -> set[str]:
    """Conservative exit paths, excluding returns in nested functions/classes."""
    paths = {"fallthrough"}
    for node in statements:
        if "fallthrough" not in paths:
            break
        branch = {"fallthrough"}
        if isinstance(node, ast.Return):
            branch = {"none" if node.value is None or (
                isinstance(node.value, ast.Constant) and node.value.value is None
            ) else "value"}
        elif isinstance(node, ast.Raise):
            branch = {"raise"}
        elif (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
              and ast.unparse(node.value.func) in {"pytest.skip", "pytest.fail", "pytest.exit", "sys.exit"}):
            branch = {"raise"}
        elif isinstance(node, ast.If):
            branch = exits(node.body) | exits(node.orelse)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            branch = exits(node.body)
        elif isinstance(node, ast.Try):
            branch = exits(node.body)
            if "fallthrough" in branch:
                branch = (branch - {"fallthrough"}) | exits(node.orelse)
            for handler in node.handlers:
                branch |= exits(handler.body)
            final = exits(node.finalbody)
            if "fallthrough" not in final:
                branch = final
            else:
                branch |= final - {"fallthrough"}
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            branch = exits(node.body) | exits(node.orelse) | {"fallthrough"}
        paths = (paths - {"fallthrough"}) | branch
    return paths


def missing_returns(source: str) -> list[str]:
    errors = []
    for node in ast.parse(source).body:
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) or node.returns is None:
            continue
        annotation = ast.unparse(node.returns)
        if any(word in annotation for word in ("None", "Optional", "Iterator", "Generator", "Iterable", "Never", "NoReturn")):
            continue
        if {"fallthrough", "none"} & exits(node.body):
            errors.append(f"{node.name}: annotated {annotation}, may return no value")
    return errors


def check_merge(resolved: str, ours: str, theirs: str) -> list[str]:
    actual = module_bindings(resolved)
    left, right = module_bindings(ours), module_bindings(theirs)
    errors = []
    missing = (left.keys() | right.keys()) - actual.keys()
    if missing:
        errors.append(f"dropped module bindings: {sorted(missing)}")
    for name, nodes in actual.items():
        allowance = max(len(left.get(name, [])), len(right.get(name, [])), 1)
        if len(nodes) > allowance:
            errors.append(f"new duplicate binding: {name} ({len(nodes)} occurrences)")
    for name, policy in SET_POLICIES.items():
        a, b, got = (literal_set(source, name) for source in (ours, theirs, resolved))
        if a is None and b is None:
            continue
        if a is None or b is None:
            expected = a if b is None else b
        else:
            expected = a & b if policy == "intersection" else a | b
        if got != expected:
            errors.append(f"{name}: expected {policy} {sorted(expected)}, got {sorted(got) if got is not None else None}")
    errors.extend(missing_returns(resolved))
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("file", type=Path)
    parser.add_argument("--ours", required=True)
    parser.add_argument("--theirs", required=True)
    args = parser.parse_args()
    root = Path(subprocess.check_output(["git", "rev-parse", "--show-toplevel"], text=True).strip())
    path = args.file.resolve().relative_to(root.resolve()).as_posix()
    parents = []
    for ref in (args.ours, args.theirs):
        sha = subprocess.check_output(["git", "rev-parse", "--verify", "--end-of-options", f"{ref}^{{commit}}"], text=True).strip()
        parents.append(subprocess.check_output(["git", "show", f"{sha}:{path}"], text=True))
    errors = check_merge(args.file.read_text(), *parents)
    for error in errors:
        print(f"{path}: {error}")
    if not errors:
        print(f"{path}: registration merge checks passed")
    return bool(errors)


if __name__ == "__main__":
    raise SystemExit(main())
