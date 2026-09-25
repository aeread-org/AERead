"""Live extraction: instantiate every *Plugin class, feed it a real case, call phases()."""
import importlib, inspect, json, sys, traceback, glob, re
from pathlib import Path
ROOT = Path(sys.argv[1]); OUT = Path(sys.argv[2])
sys.path.insert(0, str(ROOT / "src"))
FAM = ROOT / "src/aeread_families"
CASE_DIRS = {p.name: p for p in (ROOT / "cases").iterdir() if p.is_dir()}

def case_files(pkg, family_id=None):
    # A plugin's cases live under its package's name, or under its own FAMILY_ID when a package
    # holds several families (datacenter_development holds datacenter_risk_allocation_v1).
    names = [d for d in CASE_DIRS if d.startswith(pkg) or pkg.startswith(d.split("_v")[0]) or (family_id and d == family_id)]
    files = []
    for n in sorted(names):
        files += sorted(glob.glob(str(CASE_DIRS[n] / "**" / "*.json"), recursive=True))
    return [f for f in files if "payload" in Path(f).read_text()[:20000] and not f.endswith("schema.json")]

def spec_row(ph):
    return {"phase_id": ph.phase_id, "actor_selector": ph.actor_selector, "mode": ph.mode,
            "next_phases": list(ph.next_phases), "action_schema_by_role": dict(ph.action_schema_by_role),
            "max_logical_actions": ph.max_logical_actions, "invalid_action_policy": ph.invalid_action_policy}

results = {}
for pkg in sorted(p.name for p in FAM.iterdir() if p.is_dir() and not p.name.startswith("_")):
    for py in sorted((FAM / pkg).rglob("*.py")):
        text = py.read_text()
        if "def phases" not in text:
            continue
        modname = "aeread_families." + str(py.relative_to(ROOT / "src" / "aeread_families")).replace("/", ".").removesuffix(".py").removeprefix(".")
        modname = "aeread_families." + pkg + "." + py.stem if py.parent == FAM / pkg else modname
        try:
            mod = importlib.import_module(modname)
        except Exception as e:
            results[f"{pkg}::{py.stem}"] = {"error": f"import: {type(e).__name__}: {e}"[:200]}; continue
        for name, cls in inspect.getmembers(mod, inspect.isclass):
            if cls.__module__ != mod.__name__ or not hasattr(cls, "phases") or not hasattr(cls, "validate_payload"):
                continue
            key = f"{pkg}::{name}"
            entry = {"module": modname, "file": str(py.relative_to(ROOT)), "variants": []}
            try:
                sig = inspect.signature(cls.__init__)
                required = [p for p in list(sig.parameters.values())[1:] if p.default is p.empty and p.kind in (p.POSITIONAL_OR_KEYWORD, p.KEYWORD_ONLY)]
                plugins = []
                if not required:
                    plugins.append(("default", cls()))
                else:
                    # datacenter stack plugin takes a scope/sequence: try known constructors
                    for args in (("v2",), ("v1",)):
                        try: plugins.append((f"init{args}", cls(*args)))
                        except Exception: pass
                    if not plugins:
                        entry["error"] = f"constructor needs {[p.name for p in required]}"
                for label, plugin in plugins:
                    seen = {}
                    files = case_files(pkg, getattr(mod, "FAMILY_ID", None))
                    tried = 0
                    for f in files[:400]:
                        try:
                            payload = json.loads(Path(f).read_text()).get("payload")
                            if payload is None: continue
                            case = plugin.validate_payload(payload)
                            phases = plugin.phases(case)
                        except Exception as e:
                            tried += 1; continue
                        sigkey = json.dumps([spec_row(p) for p in phases], sort_keys=True)
                        if sigkey not in seen:
                            raw = json.loads(Path(f).read_text())
                            seen[sigkey] = {"case": str(Path(f).relative_to(ROOT)), "phases": [spec_row(p) for p in phases],
                                            "family_id": raw.get("family_id"), "family_version": raw.get("family_version")}
                            # try to note the developer interface for datacenter cases
                            m = re.search(r'"developer_interface":\s*(\d+)', Path(f).read_text())
                            if m: seen[sigkey]["developer_interface"] = int(m.group(1))
                    if not seen:
                        try:  # plugins that ignore the case
                            phases = plugin.phases(None)
                            seen["none"] = {"case": None, "phases": [spec_row(p) for p in phases]}
                        except Exception as e:
                            entry.setdefault("notes", []).append(f"{label}: no fixture validated ({tried} tried); phases(None): {type(e).__name__}")
                    for v in seen.values():
                        v["init"] = label
                        entry["variants"].append(v)
            except Exception as e:
                entry["error"] = f"{type(e).__name__}: {e}"[:200]
            results[key] = entry
json.dump(results, open(OUT, "w"), indent=1, default=str)
for key, entry in results.items():
    if "error" in entry and not entry.get("variants"):
        print(f"{key:60s} ERROR {entry['error']}"); continue
    for v in entry.get("variants", []):
        ids = [p["phase_id"] for p in v["phases"]]
        edges = sum(len(p["next_phases"]) for p in v["phases"])
        di = f" iface={v['developer_interface']}" if "developer_interface" in v else ""
        print(f"{key:60s} {v['init']:10s} phases={len(ids):2d} edges={edges:2d}{di} case={v['case'] and Path(v['case']).name}")
    if not entry.get("variants"):
        print(f"{key:60s} NO VARIANTS {entry.get('notes')}")
