"""Static extraction of every family's PhaseSpec graph from the plugin source."""
import ast, json, sys
from pathlib import Path
ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2])
FAM = ROOT / "src/aeread_families"

def src(node, text):
    return ast.get_source_segment(text, node) or "<expr>"

def resolve(node, consts, text):
    """Literal value, or {'variants': [...]} for IfExp, or {'dynamic': src} otherwise."""
    if isinstance(node, ast.Constant):
        return node.value
    if isinstance(node, (ast.Tuple, ast.List)):
        items = [resolve(e, consts, text) for e in node.elts]
        if any(isinstance(i, dict) and ("dynamic" in i or "variants" in i) for i in items):
            return {"dynamic": src(node, text), "items": items}
        return items
    if isinstance(node, ast.Dict):
        out = {}
        for k, v in zip(node.keys, node.values):
            kk = resolve(k, consts, text) if k is not None else "**"
            out[str(kk)] = resolve(v, consts, text)
        return out
    if isinstance(node, ast.Name) and node.id in consts:
        return resolve(consts[node.id], consts, text)
    if isinstance(node, ast.IfExp):
        return {"variants": [
            {"when": src(node.test, text), "value": resolve(node.body, consts, text)},
            {"when": "not (" + src(node.test, text) + ")", "value": resolve(node.orelse, consts, text)},
        ]}
    if isinstance(node, ast.Attribute) or isinstance(node, ast.Call) or isinstance(node, ast.Subscript) or isinstance(node, ast.BinOp) or isinstance(node, ast.Name) or isinstance(node, ast.JoinedStr) or isinstance(node, ast.Starred):
        return {"dynamic": src(node, text)}
    return {"dynamic": src(node, text)}

def enclosing(node, parents):
    chain = []
    n = node
    while n in parents:
        n = parents[n]
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            chain.append(n.name)
    return "::".join(reversed(chain))

def conditional_depth(node, parents, stop):
    d = []
    n = node
    while n in parents and n is not stop:
        n = parents[n]
        if isinstance(n, ast.If):
            d.append("if " + src(n.test, TEXT))
        if isinstance(n, ast.For):
            d.append("for " + src(n.target, TEXT))
    return d

families = {}
for pkg in sorted(p for p in FAM.iterdir() if p.is_dir() and not p.name.startswith("_")):
    specs = []
    for path in sorted(pkg.rglob("*.py")):
        TEXT = path.read_text()
        if "PhaseSpec(" not in TEXT:
            continue
        tree = ast.parse(TEXT)
        parents = {}
        for parent in ast.walk(tree):
            for child in ast.iter_child_nodes(parent):
                parents[child] = parent
        consts = {}
        for n in tree.body:
            if isinstance(n, ast.Assign) and len(n.targets) == 1 and isinstance(n.targets[0], ast.Name):
                consts[n.targets[0].id] = n.value
        for node in ast.walk(tree):
            if isinstance(node, ast.Call) and getattr(node.func, "id", getattr(node.func, "attr", "")) == "PhaseSpec":
                kw = {k.arg: resolve(k.value, consts, TEXT) for k in node.keywords if k.arg}
                func = enclosing(node, parents)
                # find the enclosing function node to compute conditionals inside it only
                fn = node
                while fn in parents and not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    fn = parents[fn]
                specs.append({
                    "file": str(path.relative_to(ROOT)), "line": node.lineno, "in": func,
                    "conditions": conditional_depth(node, parents, fn),
                    **{k: kw.get(k) for k in ("phase_id", "actor_selector", "mode", "next_phases", "action_schema_by_role", "observation_schema_by_role", "invalid_action_policy", "max_logical_actions")},
                })
    if specs:
        families[pkg.name] = specs
json.dump(families, open(OUT, "w"), indent=1, default=str)
for fam, specs in families.items():
    ids = [s["phase_id"] if isinstance(s["phase_id"], str) else f"<{s['phase_id']}>" for s in specs]
    dyn = sum(1 for s in specs if any(isinstance(s[k], dict) and ("dynamic" in s[k] or "variants" in s[k]) for k in ("phase_id","next_phases","actor_selector","mode")))
    cond = sum(1 for s in specs if s["conditions"])
    funcs = sorted({s["in"] for s in specs})
    print(f"{fam:32s} phases={len(specs):2d} dynamic_fields={dyn} conditional={cond} in={funcs} ids={ids}")
