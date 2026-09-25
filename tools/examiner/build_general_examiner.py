"""General AERead examiner data: a catalog of every published campaign bundle with its
version chain, incident rows, QC gate mentions and validity facts, plus one lazily
loaded trajectory file per bundle that carries the kernel trajectory grain.

Everything here is read from the repository: publication manifests, bundle README
and reports, the sanitized trajectory grain, the incident log, the family QC
profiles and the evidence index. Nothing is inferred beyond what a sentence says;
where a status is derived, the sentence it came from travels with it."""
from __future__ import annotations

import csv
import json
import os
import re
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

WT = Path(sys.argv[1]); OUT = Path(sys.argv[2])
SC = Path(__file__).resolve().parent
EVID = WT / "evidence"
# Evidence published on branches that have not reached this checkout (a family's
# own working branch, say) is read from extra checkouts of those branches, named
# in AEREAD_EXAMINER_EXTRA_CHECKOUTS (os.pathsep-separated). This checkout wins
# when two carry a bundle of the same name. Each bundle records the branch it
# was read from; the local paths stay in roots.json, which is never published.
EXTRA_ROOTS = [Path(p).resolve() for p in os.environ.get("AEREAD_EXAMINER_EXTRA_CHECKOUTS", "").split(os.pathsep) if p.strip()]
ROOTS = [WT] + [r for r in EXTRA_ROOTS if r != WT.resolve()]
NOT_CAMPAIGNS = {"shared_runner", "errata"}  # kernel and errata records, not campaign bundles


def checkout_label(root: Path) -> str:
    """The branch a checkout is on; for a detached checkout, the remote branch at its head."""
    def git(*args):
        return subprocess.run(["git", *args], cwd=root, capture_output=True, text=True).stdout.strip()
    name = git("rev-parse", "--abbrev-ref", "HEAD")
    if name and name != "HEAD":
        return name
    remote = [b.strip() for b in git("branch", "-r", "--points-at", "HEAD").splitlines() if b.strip() and "->" not in b]
    return remote[0].removeprefix("origin/") if remote else (git("rev-parse", "--short", "HEAD") or root.name)


ROOT_LABEL = {r: checkout_label(r) for r in ROOTS}
FAMILY_ROOT: dict = {}  # family -> the checkout whose docs describe it (the one supplying most of its bundles)
(OUT / "data" / "campaigns").mkdir(parents=True, exist_ok=True)

FAMILY_FROM_PREFIX = [
    ("housing", "housing"), ("procurement_allocation", "procurement_allocation"), ("procurement_grounding", "procurement_grounding"),
    ("datacenter_development_terms", "datacenter_development_terms"), ("datacenter", "datacenter_development"),
    ("refund", "refund"), ("commercial_state", "commercial_state_calibration"), ("econevals", "econevals"), ("govsim", "govsim"),
    ("shared_runner", "shared_runner"), ("termsbench", "termsbench"), ("negarena", "negarena"), ("errata", "errata"),
]
FAMILY_LABEL = {"housing": "Housing", "procurement_allocation": "Procurement allocation", "procurement_grounding": "Procurement grounding",
                "datacenter_development": "Datacenter development", "datacenter_development_terms": "Datacenter development terms",
                "refund": "Refund", "commercial_state_calibration": "Commercial state calibration", "econevals": "EconEvals", "govsim": "GovSim",
                "shared_runner": "Shared runner", "termsbench": "TERMS-Bench", "negarena": "NegArena", "errata": "Errata"}
QC_PROFILE = {"housing": "docs/families/housing/qc.md", "datacenter_development": "docs/families/datacenter/qc.md",
              "datacenter_development_terms": "docs/families/datacenter/qc.md", "procurement_allocation": "docs/families/procurement-allocation/qc.md"}
FACT_KEYS = ["claim_status", "claim_boundary", "status", "readiness", "gate_status", "next_gate", "stop_reason", "interpretation",
             "planned_cells", "completed_cells", "included_cells", "excluded_cells", "operational_failure_cells", "operational_failures",
             "failure_fraction", "missingness_fraction", "eligible", "replay_verified", "receipt_verified", "route_verified",
             "provider_cost_complete", "cost_qualifier", "reported_cost_usd", "total_cost_usd", "cost_note", "winner_claim_allowed",
             "inferential_model_ranking_allowed", "causal_condition_effect_allowed", "ranking_allowed", "ranking_basis",
             "within_declared_campaign_cost_ceiling", "independent_cluster_count", "primary_admission_rate", "acceptance",
             "protocol_gate_assessment", "publication_policy", "complete_pack", "cost_ceiling_usd", "halted_at", "not_attempted_cells"]
GATE_NAMES = {"0": "Profile admission", "1": "Task-distribution admission", "2": "Environment and verifier", "3": "Construct validity and baselines",
              "4": "Attribution and experimental controls", "5": "Confirmatory reliability and publication"}


def short(value, n=220):
    if isinstance(value, (dict, list)):
        s = json.dumps(value, separators=(",", ":"))
    else:
        s = str(value)
    return s if len(s) <= n else s[: n - 1] + "…"


def family_of(bundle: Path, evid: Path = EVID) -> str:
    rel = bundle.relative_to(evid).parts
    if len(rel) >= 2 and rel[0] in FAMILY_LABEL:
        return rel[0]
    for prefix, fam in FAMILY_FROM_PREFIX:
        if bundle.name.startswith(prefix):
            return fam
    if len(rel) >= 2:  # a family directory this builder has never seen: use it as-is
        return rel[0]
    return "other"


def family_root(family: str | None) -> Path:
    return FAMILY_ROOT.get(family, WT)


def family_label(family: str) -> str:
    return FAMILY_LABEL.get(family) or family.replace("_", " ").capitalize()


def qc_profile_for(family: str) -> str | None:
    """The family's QC profile: the known map first, else any docs/families/*/qc.md that names the family."""
    if family in QC_PROFILE:
        return QC_PROFILE[family]
    for cand in sorted((family_root(family) / "docs" / "families").glob("*/qc.md")):
        if cand.parent.name.replace("-", "_") == family or family in cand.read_text():
            QC_PROFILE[family] = str(cand.relative_to(family_root(family)))
            return QC_PROFILE[family]
    return None


def read_json(path: Path):
    try:
        return json.loads(path.read_bytes())
    except Exception:
        return None


def readme_excerpt(bundle: Path) -> dict:
    p = bundle / "README.md"
    if not p.exists():
        return {"title": None, "excerpt": None}
    text = p.read_text(errors="replace")
    title = next((l.lstrip("# ").strip() for l in text.splitlines() if l.startswith("#")), None)
    paras = [para.strip() for para in re.split(r"\n\s*\n", text) if para.strip() and not para.strip().startswith("#")]
    excerpt = " ".join(paras[:2])
    # The first sentences that say what the run is, skipping the provenance boilerplate many bundles open with.
    boiler = re.compile(r"^(Sanitized, digest-bound|This bundle is the sanitized|Raw prompts|Raw provider state|`trajectories/sanitized|"
                        r"Derived publication|The kernel trajectory grain|See `docs/)|remains? under (the )?ignored", re.I)
    sentences = [x.strip() for para in paras for x in re.split(r"(?<=[.!?])\s+(?=[A-Z`])", re.sub(r"\s+", " ", para)) if x.strip()]
    informative = [x for x in sentences if not boiler.search(x) and not x.startswith(("|", "-", "*"))]
    summary = short(" ".join(informative[:2]), 260) if informative else None
    return {"title": title, "excerpt": short(re.sub(r"\s+", " ", excerpt), 700), "summary": summary, "words": len(text.split())}


def headline(bundle: Path, facts: list) -> str | None:
    """What the run was, from facts every bundle can carry: the world pack and the cell count."""
    parts = []
    plan = read_json(bundle / "reports" / "plan.json")
    if isinstance(plan, dict) and isinstance(plan.get("worlds"), list) and plan["worlds"]:
        packs = sorted({Path(str(w.get("path", ""))).parent.name for w in plan["worlds"] if isinstance(w, dict)} - {""})
        if packs:
            parts.append(f"{len(plan['worlds'])} worlds from {', '.join(packs)}")
    fact = {f["key"]: f["value"] for f in facts}
    if isinstance(fact.get("planned_cells"), int) and isinstance(fact.get("completed_cells"), int):
        parts.append(f"{fact['completed_cells']} of {fact['planned_cells']} cells completed")
    return " · ".join(parts) or None


def bundle_models(bundle: Path) -> list:
    """Model ids the bundle's reports name (route or profile ``model`` fields), for a readable model column."""
    found: set[str] = set()
    def walk(node, depth):
        if depth > 5:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if k in ("model", "requested_model") and isinstance(v, str) and re.fullmatch(r"[\w.-]+/[\w.:-]+", v):
                    found.add(v)
                else:
                    walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node[:50]:
                walk(v, depth + 1)
    for path in sorted((bundle / "reports").glob("*.json"))[:12] + [bundle / "publication_manifest.json"]:
        d = read_json(path) if path.exists() else None
        if d is not None:
            walk(d, 0)
    return sorted(found)[:6]


def report_facts(bundle: Path) -> list:
    facts = []
    for folder in ("reports", "qc"):
        for path in sorted((bundle / folder).glob("*.json")):
            d = read_json(path)
            if not isinstance(d, dict):
                continue
            for key in FACT_KEYS:
                if key in d and not isinstance(d[key], (dict, list)):
                    facts.append({"key": key, "value": d[key], "file": f"{folder}/{path.name}"})
                elif key in d and isinstance(d[key], dict) and len(d[key]) <= 6 and all(not isinstance(v, (dict, list)) for v in d[key].values()):
                    facts.append({"key": key, "value": d[key], "file": f"{folder}/{path.name}"})
    # families whose reports nest the same facts under other names (procurement arm reviews, qualification
    # summaries, paired comparisons): scalars are aliased, counts are summed across arm reports, integrity and
    # readiness flags are folded into replay / eligibility facts.  Only used where the flat scan found nothing.
    found = {f["key"] for f in facts}
    alias = {"cost_accounting": "cost_qualifier", "claim_scope": "claim_scope", "inference": "inference_scope",
             "rule_was_frozen_before_execution": "rule_was_frozen_before_execution"}
    counts = {"completed_trajectory_count": "completed_cells", "planned_trajectory_count": "planned_cells",
              "operational_failure_count": "operational_failure_cells", "unattempted_trajectory_count": "not_attempted_cells",
              "total_cost_usd": "total_cost_usd"}
    sums: dict[str, list] = {}; nested: dict[str, dict] = {}; flags: dict[str, dict] = {}
    def walk(node, file, path, depth):
        if not isinstance(node, dict) or depth > 3:
            return
        for k, v in node.items():
            here = f"{path}.{k}" if path else k
            if isinstance(v, dict):
                if k == "integrity":
                    for fk, fv in v.items():
                        if "replay" in fk and isinstance(fv, bool):
                            flags.setdefault("replay_verified", {"value": True, "file": file, "keys": []})
                            flags["replay_verified"]["value"] = flags["replay_verified"]["value"] and fv
                            flags["replay_verified"]["keys"].append(fk)
                if k == "readiness":
                    for fk, fv in v.items():
                        if fk.endswith("_qualified") and isinstance(fv, bool):
                            e = flags.setdefault("eligible", {"value": None, "file": file, "keys": [], "true": [], "false": []})
                            (e["true"] if fv else e["false"]).append(fk)
                            e["value"] = True if not e["false"] else (False if not e["true"] else "mixed")
                            e["keys"] = [f"{x}=True" for x in e["true"]] + [f"{x}=False" for x in e["false"]]
                if k == "confirmation" and isinstance(v.get("status"), str):
                    nested.setdefault("confirmation_status", {"key": "confirmation_status", "value": v["status"], "file": file})
                    if isinstance(v.get("rule_was_frozen_before_execution"), bool):
                        nested.setdefault("rule_was_frozen_before_execution", {"key": "rule_was_frozen_before_execution", "value": v["rule_was_frozen_before_execution"], "file": file})
                walk(v, file, here, depth + 1)
            elif isinstance(v, (int, float)) and not isinstance(v, bool) and k in counts and path.endswith(("summary", "plan")):
                sums.setdefault(counts[k], []).append((v, file))
            elif isinstance(v, str) and k in alias and path.endswith(("summary", "plan", "")) :
                nested.setdefault(alias[k], {"key": alias[k], "value": v, "file": file})
            elif isinstance(v, bool) and k in alias:
                nested.setdefault(alias[k], {"key": alias[k], "value": v, "file": file})
            elif k == "status" and v == "admitted" and path == "":
                nested.setdefault("admission_status", {"key": "admission_status", "value": "admitted", "file": file})
    for folder in ("reports", "qc"):
        for path in sorted((bundle / folder).glob("*.json")):
            d = read_json(path)
            if isinstance(d, dict):
                walk(d, f"{folder}/{path.name}", "", 0)
    for key, items in sums.items():
        if key not in found:
            # one summary per arm/qualification report: sum them (a bundle with several arms reports each arm)
            per_file = {}
            for v, file in items:
                per_file.setdefault(file, v)
            total = sum(per_file.values())
            facts.append({"key": key, "value": int(total) if float(total).is_integer() else total, "file": " + ".join(sorted(per_file)) if len(per_file) > 1 else next(iter(per_file))})
    for key, f in nested.items():
        if key not in found:
            facts.append(f)
    for key, f in flags.items():
        if key not in found:
            facts.append({"key": key, "value": f["value"], "file": f["file"] + " · " + ", ".join(f["keys"][:4])})
    # Campaign bundles that report cell counts as summary {cells, completed, failed, not_attempted} and replay
    # as replay.json {cells: {label: {receipt_sha256_matches_result: bool} | "<status>: not replayable"}}
    # (the procurement repeated-sourcing campaigns). Only used where nothing above named the same fact.
    present = {f["key"] for f in facts}
    summary = read_json(bundle / "reports" / "summary.json")
    if isinstance(summary, dict) and isinstance(summary.get("cells"), int) and isinstance(summary.get("completed"), int):
        for key, source in (("planned_cells", "cells"), ("completed_cells", "completed"),
                            ("operational_failure_cells", "failed"), ("not_attempted_cells", "not_attempted")):
            if key not in present and isinstance(summary.get(source), int):
                facts.append({"key": key, "value": summary[source], "file": "reports/summary.json"})
    replay = read_json(bundle / "reports" / "replay.json")
    if "replay_verified" not in present and isinstance(replay, dict) and isinstance(replay.get("cells"), dict):
        checked = [v for v in replay["cells"].values() if isinstance(v, dict) and "receipt_sha256_matches_result" in v]
        if checked:
            matched = sum(1 for v in checked if v["receipt_sha256_matches_result"] is True)
            facts.append({"key": "replay_verified", "value": matched == len(checked), "file": "reports/replay.json",
                          "detail": f"{matched} of {len(checked)} completed cells replay to their recorded receipt"})
    # Reference policies computed offline per world in the pack manifest the plan's worlds come from.
    plan = read_json(bundle / "reports" / "plan.json")
    if isinstance(plan, dict) and isinstance(plan.get("worlds"), list) and plan["worlds"]:
        packs = {Path(str(w.get("path", ""))).parent for w in plan["worlds"] if isinstance(w, dict)}
        for pack in sorted(packs):
            manifest_path = _bundle_root(bundle) / pack / "pack.json"
            pm = read_json(manifest_path)
            if isinstance(pm, dict) and pm.get("public_policies"):
                facts.append({"key": "reference_policies", "value": ", ".join(pm["public_policies"]),
                              "file": str(pack / "pack.json")})
                break
    seen = set(); out = []
    for f in facts:
        k = (f["key"], json.dumps(f["value"], sort_keys=True, default=str))
        if k in seen:
            continue
        seen.add(k); out.append(f)
    return out


# ---------------- incident log ----------------
def parse_incident_log() -> tuple[list, dict]:
    rows, sections, seen = [], {}, set()
    for root in ROOTS:
        path = root / "docs/operations/incident_log.md"
        if not path.exists():
            continue
        r, s = _parse_incident_text(path.read_text())
        for row in r:
            if row["id"] not in seen:
                seen.add(row["id"]); rows.append(row); sections.setdefault(row["section"], []).append(row["id"])
    return rows, sections


def _parse_incident_text(text: str) -> tuple[list, dict]:
    rows = []; section = None; sections = {}
    for line in text.splitlines():
        if line.startswith("## "):
            section = line[3:].strip(); sections[section] = []
        m = re.match(r"^\| ([A-Z][A-Z-]*-[0-9]+) \| (.*) \|\s*$", line)
        if m and section:
            cells = [c.strip() for c in m.group(2).split(" | ")]
            # cells: defect | detection | cost | disposition (defect may contain ' | ' rarely; take last three as the tail)
            if len(cells) >= 4:
                defect, detection, cost, disposition = " | ".join(cells[:-3]), cells[-3], cells[-2], cells[-1]
            else:
                defect, detection, cost, disposition = (cells + ["", "", ""])[:4]
            disp_l = disposition.lower()
            state = "open" if disp_l.startswith("open") else "fixed" if disp_l.startswith(("fixed", "corrected", "closed")) else "withdrawn" if "withdrawn" in disp_l[:80] else "recorded"
            row = {"id": m.group(1), "section": section, "defect": defect, "detection": detection, "cost": cost, "disposition": disposition, "state": state,
                   "mentions": sorted(set(re.findall(r"`([a-z0-9_]+(?:_v\d+|_20\d{2}-\d{2}-\d{2})?)`", line)))}
            rows.append(row); sections[section].append(row["id"])
    return rows, sections


def section_family(section: str) -> str | None:
    s = section.lower()
    for token, fam in (("housing", "housing"), ("procurement", "procurement_allocation"), ("data-center", "datacenter_development"), ("datacenter", "datacenter_development"),
                       ("terms-bench", "termsbench"), ("econevals", "econevals"), ("refund", "refund"), ("govsim", "govsim")):
        if token in s:
            return fam
    return None


# ---------------- QC profiles ----------------
def qc_sections(family: str) -> list:
    path = qc_profile_for(family)
    root = family_root(family)
    if not path or not (root / path).exists():
        return []
    text = (root / path).read_text(); out = []; cur = None
    for line in text.splitlines():
        if line.startswith("## "):
            cur = {"heading": line[3:].strip(), "text": []}; out.append(cur)
        elif cur is not None:
            cur["text"].append(line)
    for s in out:
        s["text"] = "\n".join(s["text"])
    return out


def qc_mentions(family: str, campaign_id: str, version_token: str | None) -> dict:
    sections = qc_sections(family)
    hits = []
    for s in sections:
        body = s["heading"] + "\n" + s["text"]
        if campaign_id in body or (version_token and re.search(rf"\b{re.escape(version_token)}\b", s["heading"])):
            sentences = re.split(r"(?<=[.!?])\s+", re.sub(r"\s+", " ", s["text"]))
            gate = [x for x in sentences if re.search(r"\bGate[s]? [0-5]\b|\b(all )?five gates\b|\bgates? (passed|failed)\b", x, re.I)]
            status_words = [x for x in sentences if re.search(r"\b(passed|failed|withdrawn|superseded|exploratory|confirmatory|not (?:a )?(?:paper|current) result|development|preliminary|integration gate|no winner|cannot|must not)\b", x, re.I)]
            hits.append({"heading": s["heading"], "gate_sentences": [short(x, 320) for x in gate[:6]], "status_sentences": [short(x, 320) for x in status_words[:6]],
                         "path": qc_profile_for(family)})
    return {"sections": hits}


# ---------------- version chains ----------------
def stem_and_version(cid: str):
    m = re.match(r"^(.*)_(v\d+(?:_\d+)?)(?:_(.*))?$", cid)  # greedy: the LAST version token names the version
    date = re.search(r"(20\d{2}-\d{2}-\d{2})", cid)
    if m:
        v = m.group(2)
        num = float(v[1:].replace("_", ".")) if v[1:].replace("_", "").isdigit() else 0.0
        stem = m.group(1); tail = cid[len(m.group(1)) + len(v) + 1:]
        return stem, v, num, tail.strip("_"), date.group(1) if date else None
    if date:
        return cid.replace(date.group(1), "").strip("_-"), date.group(1), 0.0, "", date.group(1)
    return cid, None, 0.0, "", None


def derive_status(manifest, readme, facts, issues) -> dict:
    """A status label plus the sentence that justifies it. Manifest first, then report
    facts, then README words, then incident dispositions; never more than the text says."""
    ev = []
    claim = (manifest or {}).get("claim_status")
    for f in facts:
        if f["key"] in ("claim_status", "status", "readiness", "gate_status", "claim_boundary") and isinstance(f["value"], str):
            ev.append(f"{f['file']}: {f['key']} = {f['value']}")
    text = ((readme or {}).get("excerpt") or "").lower()
    label = "published"
    if claim:
        label = f"published · {claim}"
    withdrawn = any(w in text for w in ("withdrawn", "superseded", "retracted")) or any(i["state"] == "withdrawn" and i["direct"] for i in issues)
    if withdrawn:
        label = "published · withdrawn or superseded (see sentence)"
    elif any(w in text for w in ("development evidence", "development qualification", "integration", "exploratory", "pilot", "not a paper result", "no winner")):
        label = label if claim else "published · development or exploratory"
    elif any(w in text for w in ("confirmatory",)) and not claim:
        label = "published · confirmatory (as described)"
    sentence = None
    for w in ("withdrawn", "superseded", "confirmatory", "exploratory", "development", "pilot", "integration", "no winner", "not a paper result"):
        m = re.search(r"[^.]*\b" + w + r"\b[^.]*\.", (readme or {}).get("excerpt") or "", re.I)
        if m:
            sentence = m.group(0).strip(); break
    return {"label": label, "claim_status": claim, "readme_sentence": sentence, "fact_evidence": ev[:6],
            "open_issues": sum(1 for i in issues if i["state"] == "open"), "direct_issues": sum(1 for i in issues if i["direct"])}


_FAM_STATUS: dict = {}
def family_qc_status(family) -> str | None:
    """The family QC profile's **Status:** paragraph (family-level gate outcomes)."""
    if family in _FAM_STATUS:
        return _FAM_STATUS[family]
    rel = qc_profile_for(family) if family else None
    root = family_root(family)
    text = (root / rel).read_text() if rel and (root / rel).exists() else ""
    m = re.search(r"\*\*Status:\*\*(.+?)\n\n", text, re.S)
    _FAM_STATUS[family] = re.sub(r"\s+", " ", m.group(1)).strip() if m else None
    return _FAM_STATUS[family]


# ---------------- validity checklist ----------------
def checklist(manifest, facts, grain_summary, issues, gate_hits) -> list:
    def fact(key):
        return next((f for f in facts if f["key"] == key), None)
    items = []
    def add(name, gate, state, detail, source):
        items.append({"item": name, "gate": gate, "state": state, "detail": detail, "source": source})
    flags = {k: (manifest or {}).get(k) for k in ("winner_claim_allowed", "inferential_model_ranking_allowed", "causal_condition_effect_allowed")}
    for f in facts:
        if f["key"] in flags and flags[f["key"]] is None:
            flags[f["key"]] = f["value"]
    stated = {k: v for k, v in flags.items() if v is not None}
    if stated:
        add("Claim boundary declared (no winner, no ranking)", "5", "yes" if all(v is False for v in stated.values()) else "no",
            ", ".join(f"{k} = {v}" for k, v in stated.items()), "publication manifest / reports")
    elif fact("claim_scope") or fact("inference_scope"):
        cs = fact("claim_scope") or fact("inference_scope"); text = str(cs["value"])
        bounded = bool(re.search(r"not (a |an )?(population-level |general )?(model[- ]only |model |provider )?(ranking|estimate)|no winner|diagnostic|qualification|must not be pooled", text, re.I))
        add("Claim boundary declared (no winner, no ranking)", "5", "yes" if bounded else "partial", f"{cs['key']}: {short(text, 220)}", cs["file"])
    else:
        add("Claim boundary declared (no winner, no ranking)", "5", "not stated", "no claim flags or claim scope in the manifest or reports", "")
    planned, completed = fact("planned_cells"), fact("completed_cells")
    fails = fact("operational_failure_cells") or fact("operational_failures") or fact("not_attempted_cells")
    if planned and completed:
        p, c = planned["value"], completed["value"]
        add("Every planned cell has a receipt or typed missingness", "5", "yes" if isinstance(p, int) and isinstance(c, int) else "not stated",
            f"{c} of {p} cells completed" + (f", {fails['value']} typed failures" if fails else ""), planned["file"])
    elif grain_summary.get("cases"):
        add("Every planned cell has a receipt or typed missingness", "5", "partial", f"{grain_summary['cases']} cases carry a trajectory grain; planned count not stated in reports", "trajectories/sanitized.jsonl")
    else:
        add("Every planned cell has a receipt or typed missingness", "5", "not stated", "", "")
    cq = fact("cost_qualifier") or fact("provider_cost_complete")
    if cq:
        v = cq["value"]; ok = v in ("exact", True)
        add("Cost stated as exact or lower bound", "5", "yes" if ok else "partial", f"{cq['key']} = {v}", cq["file"])
    else:
        add("Cost stated as exact or lower bound", "5", "not stated", "", "")
    rv = fact("replay_verified")
    cell_rv = (grain_summary.get("cell_flags") or {}).get("replay_verified")
    if rv is not None:
        add("Replay from sealed evidence reproduces scores", "2", "yes" if rv["value"] is True else "partial",
            f"replay_verified = {rv['value']}" + (f": {rv['detail']}" if rv.get("detail") else "") + " (a recorded flag; a review recomputes it)", rv["file"])
    elif cell_rv and cell_rv["total"]:
        add("Replay from sealed evidence reproduces scores", "2", "yes" if cell_rv["true"] == cell_rv["total"] else "partial",
            f"replay_verified true on {cell_rv['true']} of {cell_rv['total']} published cell rows (a recorded flag; a review recomputes it)", "tables/")
    else:
        add("Replay from sealed evidence reproduces scores", "2", "not stated", "no replay fact in reports; the review recomputes replay from receipts", "")
    mf = fact("missingness_fraction") or fact("failure_fraction")
    if mf:
        add("Operational missingness reported separately", "4", "yes", f"{mf['key']} = {mf['value']}", mf["file"])
    adm = fact("primary_admission_rate") or fact("eligible") or fact("admission_status")
    if adm:
        add("Admission or eligibility computed under the predeclared analysis", "1", "partial" if adm["value"] == "mixed" else ("yes" if adm["value"] not in (False, "failed", "excluded") else "no"), f"{adm['key']} = {short(adm['value'], 160)}", adm["file"])
    conf = fact("confirmation_status")
    if conf:
        frozen = fact("rule_was_frozen_before_execution")
        add("Confirmatory rule frozen before execution and evaluated", "5", "yes" if (frozen and frozen["value"] is True) else "partial",
            f"confirmation status = {conf['value']}" + (f"; rule frozen before execution = {frozen['value']}" if frozen else "; freeze not stated"), conf["file"])
    ctrl = grain_summary.get("scripted_profiles", 0)
    if grain_summary.get("cases"):
        refs = fact("reference_policies")
        if not ctrl and refs:
            add("Scripted controls or baselines present in the run", "3", "partial",
                f"no scripted seat ran; reference policies are computed offline per world in the pack manifest: {refs['value']}", refs["file"])
        else:
            add("Scripted controls or baselines present in the run", "3", "yes" if ctrl else "not stated",
                f"{ctrl} scripted profile(s) among {grain_summary.get('profiles', 0)} profiles in the grain" if ctrl else "no scripted profile appears in the trajectory grain (controls may be in the reports)", "trajectories/sanitized.jsonl")
    gate_sent = [s for h in gate_hits.get("sections", []) for s in h["gate_sentences"]]
    fam_status = family_qc_status(grain_summary.get("family"))
    if gate_sent:
        add("QC profile states gate outcomes for this identity", "0-5", "yes", gate_sent[0], qc_profile_for(grain_summary.get("family")) or "")
    elif fam_status:
        add("QC profile states gate outcomes for this identity", "0-5", "partial",
            "the family profile is written per gate and does not name this identity; its family-level status: " + short(fam_status, 260), qc_profile_for(grain_summary.get("family")) or "")
    else:
        add("QC profile states gate outcomes for this identity", "0-5", "not stated", "no family QC profile mentions this campaign", "")
    open_issues = [i for i in issues if i["state"] == "open"]
    inherited = [i for i in open_issues if not i["direct"]]
    add("No open incident rows name this identity", "4", "yes" if not any(i["direct"] and i["state"] == "open" for i in issues) else "no",
        f"{sum(1 for i in issues if i['direct'])} row(s) name it, {sum(1 for i in issues if i['direct'] and i['state']=='open')} open"
        + (f"; {len(inherited)} open row(s) of the family's design still apply (below)" if inherited else "; no open family-level row applies"), "docs/operations/incident_log.md")
    # an open incident recorded against the family's section or design applies to every run of that design until its disposition changes
    for i in inherited:
        g = re.search(r"Gate\s*(\d)", i.get("section") or "")
        add(f"Open incident {i.get('id')} still applies to this design", g.group(1) if g else "0-5", "no",
            short(f"{i.get('defect', '')} — {i.get('disposition', '')}", 300), f"docs/operations/incident_log.md · {i.get('link')}")
    return items


# ---------------- trajectory grain ----------------
def load_grain(bundle: Path):
    path = bundle / "trajectories" / "sanitized.jsonl"
    if not path.exists():
        return None, None
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    if not rows or "step_index" not in rows[0]:
        return None, {"legacy_rows": len(rows), "note": "cell-level rows without a step grain"}
    return rows, None


def table_rows(bundle: Path) -> dict:
    """Rows of any tables/*.jsonl or *.csv keyed by receipt digest, for per-case outcome facts."""
    by = {}
    for path in sorted((bundle / "tables").glob("*")):
        rows = []
        try:
            if path.suffix == ".jsonl":
                rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
            elif path.suffix == ".csv":
                rows = list(csv.DictReader(path.open()))
        except Exception:
            continue
        for r in rows:
            sha = r.get("receipt_sha256") or r.get("source_receipt_sha256")
            if sha and isinstance(r, dict):
                flat = {}
                for k, v in r.items():
                    if isinstance(v, dict):
                        for kk, vv in v.items():
                            if not isinstance(vv, (dict, list)):
                                flat[f"{k}.{kk}"] = vv
                    elif not isinstance(v, list):
                        flat[k] = v
                by.setdefault(sha, {}).update({f"{path.stem}.{k}": v for k, v in flat.items()})
    return by


def _num(value) -> float | None:
    """A number, or None when the grain says the provider did not report one."""
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def campaign_file(bundle: Path, cid: str, family: str, rows: list, tables: dict) -> dict:
    cases = {}
    for r in rows:
        key = r.get("source_receipt_sha256") or (r["cell_id"], r["episode_attempt_id"])  # one case per receipt: retries of a cell reuse the attempt id
        c = cases.setdefault(key, {"case_id": r["case_id"], "cell_id": r["cell_id"], "episode_attempt_id": r["episode_attempt_id"],
                                   "receipt_sha256": r.get("source_receipt_sha256"), "profiles": set(), "steps": []})
        pcalls = [pc for a in (r.get("attempts") or []) for pc in (a.get("provider_calls") or [])]
        c["profiles"].add(r.get("profile_id"))
        c["steps"].append({
            "i": r["step_index"], "phase": r["phase_id"], "seat": r["seat_id"], "role": r.get("role"), "profile": r.get("profile_id"),
            "action": r.get("action"), "parse": r.get("parse"), "legal": r.get("legality"), "outcome": r.get("outcome"),
            "provider": {"calls": len(pcalls), "cost": round(sum(_num(pc.get("cost_usd")) or 0.0 for pc in pcalls), 6),
                         "cost_unknown": sum(1 for pc in pcalls if _num(pc.get("cost_usd")) is None and pc.get("cost_usd") is not None),
                         "in": sum(int(_num(pc.get("input_tokens")) or 0) for pc in pcalls), "out": sum(int(_num(pc.get("output_tokens")) or 0) for pc in pcalls),
                         "reasoning": sum(int(_num(pc.get("reasoning_tokens")) or 0) for pc in pcalls),
                         "finish": sorted({str(pc.get("finish_reason")) for pc in pcalls}), "attempts": len(r.get("attempts") or []),
                         "failures": [a.get("failure_condition") for a in (r.get("attempts") or []) if a.get("failure_condition")]},
            "tools": r.get("tools") or None,
        })
    out_cases = []
    for c in cases.values():
        c["steps"].sort(key=lambda s: s["i"])
        c["profiles"] = sorted(p for p in c["profiles"] if p)
        c["phases"] = [s["phase"] for s in c["steps"]]
        c["outcome_row"] = tables.get(c["receipt_sha256"]) if c["receipt_sha256"] else None
        c["cost"] = round(sum(s["provider"]["cost"] for s in c["steps"]), 6)
        c["invalid_steps"] = sum(1 for s in c["steps"] if s["outcome"] and s["outcome"].get("valid") is False)
        out_cases.append(c)
    out_cases.sort(key=lambda c: (c["case_id"], c["episode_attempt_id"]))
    # observed phase graph
    edges = Counter(); first = Counter()
    for c in out_cases:
        seq = []
        for s in c["steps"]:
            if not seq or seq[-1] != s["phase"]:
                seq.append(s["phase"])
        if seq:
            first[seq[0]] += 1
        for a, b in zip(seq, seq[1:]):
            edges[(a, b)] += 1
    graph = {"nodes": sorted({p for c in out_cases for p in c["phases"]}), "edges": [{"from": a, "to": b, "n": n} for (a, b), n in sorted(edges.items())],
             "entry": first.most_common(1)[0][0] if first else None, "basis": "observed phase sequence in the sealed grain"}
    return {"campaign_id": cid, "family": family, "cases": out_cases, "graph": graph}


# ---------------- main ----------------
def discover(root: Path) -> set:
    """Bundles under a checkout's evidence/: anything with a publication manifest or a
    sanitized step grain, and the older layout (a reports/ folder of JSON directly under
    evidence/ or evidence/<family>/, as Housing's campaigns and derived analyses use)."""
    ev = root / "evidence"
    found = {p.parent for p in ev.rglob("publication_manifest.json")} | {p.parent.parent for p in ev.rglob("trajectories/sanitized.jsonl")}
    level1 = [d for d in ev.iterdir() if d.is_dir()]
    candidates = level1 + [x for d in level1 if d.name in FAMILY_LABEL for x in d.iterdir() if x.is_dir()]
    for d in candidates:
        if any((d / "reports").glob("*.json")) and not any(a in found for a in d.parents) and d not in found:
            found.add(d)
    return {d for d in found if family_of(d, ev) not in NOT_CAMPAIGNS}


BUNDLE_ROOT: dict = {}
for root in ROOTS:
    for d in sorted(discover(root)):
        if d.name not in {b.name for b in BUNDLE_ROOT}:
            BUNDLE_ROOT[d] = root


def _bundle_root(bundle: Path) -> Path:
    return BUNDLE_ROOT.get(bundle, WT)


_fam_counts: dict = defaultdict(Counter)
for d, root in BUNDLE_ROOT.items():
    _fam_counts[family_of(d, root / "evidence")][root] += 1
FAMILY_ROOT.update({fam: counts.most_common(1)[0][0] for fam, counts in _fam_counts.items()})
(SC / "roots.json").write_text(json.dumps({ROOT_LABEL[r]: str(r) for r in ROOTS}, indent=1))

incident_rows, incident_sections = parse_incident_log()
bundles = sorted(BUNDLE_ROOT, key=lambda b: (str(b.name)))
catalog = []
for bundle in bundles:
    cid = bundle.name
    root = BUNDLE_ROOT[bundle]
    family = family_of(bundle, root / "evidence")
    manifest = read_json(bundle / "publication_manifest.json") or {}
    readme = readme_excerpt(bundle)
    facts = report_facts(bundle)
    rows, legacy = load_grain(bundle)
    stem, version, vnum, tail, date = stem_and_version(cid)
    direct_ids = {cid, manifest.get("campaign_id") or cid}
    STOP = {"housing", "datacenter", "development", "terms", "refund", "procurement", "allocation", "grounding", "public", "campaign", "pilot", "first", "live", "probe",
            "controlled", "canonical", "scripted", "case", "variance", "integrated", "policy", "baselines", "route",
            "commercial", "state", "calibration", "econevals", "govsim", "shared", "runner", "deterministic", "openrouter", "model", "sensitivity", "alt", "morph"}
    distinctive = {t for t in re.split(r"[_-]", cid) if len(t) >= 4 and t not in STOP and not re.fullmatch(r"v\d+|20\d\d.*", t)}
    issues = []
    for r in incident_rows:
        text_all = r["defect"] + " " + r["disposition"] + " " + r["detection"]
        direct = any(d in text_all for d in direct_ids) or any(m in direct_ids for m in r["mentions"])
        heading_hit = section_family(r["section"]) == family and any(tok in r["section"].lower() for tok in distinctive)
        token_hit = section_family(r["section"]) == family and any(re.search(rf"\b{re.escape(tok)}\b", text_all.lower().replace("-", "_")) for tok in distinctive if tok not in ("live", "first", "probe"))
        if direct or heading_hit or token_hit:
            issues.append({**{k: (short(r[k], 420) if k in ("defect", "disposition") else r[k]) for k in ("id", "section", "defect", "detection", "cost", "disposition", "state")},
                           "direct": bool(direct), "link": "names the identity" if direct else ("section names it" if heading_hit else "mentions a token of the identity")})
    gate_hits = qc_mentions(family, cid, version)
    grain_summary = {"family": family}
    traj_path = None
    if rows:
        tables = table_rows(bundle)
        cf = campaign_file(bundle, cid, family, rows, tables)
        traj_path = f"data/campaigns/{cid}.json"
        (OUT / traj_path).write_text(json.dumps(cf, separators=(",", ":"), default=str))
        profiles = sorted({p for c in cf["cases"] for p in c["profiles"]})
        flags = {}
        for c in cf["cases"]:
            for k, v in (c.get("outcome_row") or {}).items():
                base = k.split(".", 1)[1] if "." in k else k
                if base in ("replay_verified", "route_verified", "receipt_verified", "provider_cost_complete"):
                    f = flags.setdefault(base, {"true": 0, "total": 0}); f["total"] += 1; f["true"] += 1 if v in (True, "True", "true") else 0
        grain_summary["cell_flags"] = flags
        grain_summary.update({"rows": len(rows), "cases": len(cf["cases"]), "steps_per_case": round(len(rows) / len(cf["cases"]), 1), "phases": cf["graph"]["nodes"],
                              "profiles": len(profiles), "scripted_profiles": sum(1 for p in profiles if "scripted" in p), "profile_ids": profiles[:12],
                              "invalid_steps": sum(c["invalid_steps"] for c in cf["cases"]), "cost_usd": round(sum(c["cost"] for c in cf["cases"]), 4),
                              "bytes": (OUT / traj_path).stat().st_size})
    elif legacy:
        grain_summary.update(legacy)
    status = derive_status(manifest, readme, facts, issues)
    catalog.append({
        "id": cid, "path": str(bundle.relative_to(root)), "family": family, "family_label": family_label(family),
        "checkout": ROOT_LABEL[root] if root != WT else None,
        "stem": stem, "version": version, "version_number": vnum, "variant": tail, "date": date,
        "manifest": {k: manifest.get(k) for k in ("schema_version", "campaign_id", "publication_id", "claim_status", "cost_qualifier", "total_cost_usd",
                                                    "winner_claim_allowed", "inferential_model_ranking_allowed", "causal_condition_effect_allowed", "prior_pilot_attempts")},
        "artifact_count": len(manifest.get("artifacts") or {}) if isinstance(manifest.get("artifacts"), (dict, list)) else None,
        "source_receipts": len((manifest.get("source_bindings") or {}).get("source_receipt_sha256s") or []) if isinstance(manifest.get("source_bindings"), dict) else None,
        "readme": readme, "models": bundle_models(bundle), "headline": headline(bundle, facts), "facts": facts, "issues": issues, "qc": gate_hits, "status": status,
        "grain": grain_summary, "trajectory_file": traj_path,
        "checklist": checklist(manifest, facts, grain_summary, issues, gate_hits),
    })

# version chains: same family + stem
chains = defaultdict(list)
for c in catalog:
    chains[(c["family"], c["stem"])].append(c["id"])
_spec_co = __import__("importlib.util").util.spec_from_file_location("campaign_order", Path(__file__).with_name("campaign_order.py")); _co_mod = __import__("importlib.util").util.module_from_spec(_spec_co); _spec_co.loader.exec_module(_co_mod)
_idx_file = Path(__file__).with_name("receipt_index.json")
_co_mod.annotate(catalog, WT, json.loads(_idx_file.read_text()) if _idx_file.exists() else {}, roots={ROOT_LABEL[r]: r for r in ROOTS})
for key, ids in chains.items():
    ordered = sorted(ids, key=lambda i: (next(c for c in catalog if c["id"] == i)["version_number"], next(c for c in catalog if c["id"] == i)["date"] or "", ((next(c for c in catalog if c["id"] == i).get("order") or {}).get("at") or ""), i))
    for pos, i in enumerate(ordered):
        c = next(c for c in catalog if c["id"] == i)
        c["chain"] = {"stem": key[1], "position": pos + 1, "length": len(ordered), "latest": pos == len(ordered) - 1, "members": ordered}

# incident rows not tied to any bundle, grouped by family, for the family view
family_rows = defaultdict(list)
for r in incident_rows:
    fam = section_family(r["section"])
    if fam:
        family_rows[fam].append({k: (short(r[k], 300) if k in ("defect", "disposition") else r[k]) for k in ("id", "section", "defect", "detection", "cost", "disposition", "state")})

# phase graphs declared by plugins, from the earlier extraction, keyed by family package
declared = {}
try:
    live = json.load(open(SC / "phase_graphs_live.json")); static = json.load(open(SC / "phase_graphs.json"))
    for key, entry in live.items():
        pkg, plugin = key.split("::")
        for v in entry.get("variants", []):
            declared.setdefault(pkg, []).append({"plugin": plugin, "variant": (v.get("init") or "") + (f" iface{v['developer_interface']}" if v.get("developer_interface") else ""),
                                                 "nodes": [p["phase_id"] for p in v["phases"]], "edges": [{"from": p["phase_id"], "to": n} for p in v["phases"] for n in p["next_phases"]],
                                                 "modes": {p["phase_id"]: p["mode"] for p in v["phases"]}, "actors": {p["phase_id"]: p["actor_selector"] for p in v["phases"]}})
    for pkg, specs in static.items():
        if pkg not in declared and all(isinstance(s.get("phase_id"), str) for s in specs):
            declared[pkg] = [{"plugin": specs[0]["in"].split("::")[0], "variant": "static", "nodes": [s["phase_id"] for s in specs],
                              "edges": [{"from": s["phase_id"], "to": n} for s in specs for n in (s["next_phases"] or []) if isinstance(n, str)],
                              "modes": {s["phase_id"]: s["mode"] for s in specs}, "actors": {s["phase_id"]: (s["actor_selector"] if isinstance(s["actor_selector"], str) else "?") for s in specs}}]
    for pkg, variants in list(declared.items()):
        seen = set(); unique = []
        for v in variants:
            key = json.dumps([v["plugin"], v["nodes"], v["edges"], v["modes"]], sort_keys=True)
            if key in seen:
                continue
            seen.add(key); unique.append(v)
        declared[pkg] = unique
    # housing's phases() branches on the world kind; if the live extraction did not exercise it, use the graphs the plugin returns
    if all(v.get("variant") == "static" for v in declared.get("housing", [])): declared["housing"] = [
        {"plugin": "HousingV1Plugin", "variant": "bid world", "nodes": ["contact", "respond", "commit"],
         "edges": [{"from": "contact", "to": "respond"}, {"from": "respond", "to": "commit"}, {"from": "commit", "to": "contact"}],
         "modes": {"contact": "simultaneous", "respond": "simultaneous", "commit": "simultaneous"},
         "actors": {"contact": "unmatched_tenants", "respond": "open_landlords", "commit": "unmatched_tenants"}},
        {"plugin": "HousingV1Plugin", "variant": "lemons world", "nodes": ["inspect", "contact", "respond", "commit"],
         "edges": [{"from": "inspect", "to": "contact"}, {"from": "contact", "to": "respond"}, {"from": "respond", "to": "commit"}, {"from": "commit", "to": "inspect"}],
         "modes": {"inspect": "simultaneous", "contact": "simultaneous", "respond": "simultaneous", "commit": "simultaneous"},
         "actors": {"inspect": "unmatched_tenants", "contact": "unmatched_tenants", "respond": "open_landlords", "commit": "unmatched_tenants"}},
    ]
except Exception as error:  # the graphs are an aid, not a requirement
    declared = {"_error": str(error)}

def _git_branch():
    import subprocess
    try:
        return subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=WT, capture_output=True, text=True, check=True).stdout.strip() or "unknown"
    except Exception:
        return "unknown"


# chronological order within each family (receipt times on this machine, else git), stated per row
(OUT / "data" / "catalog.json").write_text(json.dumps({
    "generated_from": {"branch": _git_branch(), "extra_branches": [ROOT_LABEL[r] for r in ROOTS[1:]], "evidence_root": "evidence/", "incident_log": "docs/operations/incident_log.md",
                       "qc_profiles": QC_PROFILE, "benchmark_qc": "docs/operations/benchmark_qc.md"},
    "gate_names": GATE_NAMES, "families": sorted({c["family"] for c in catalog}), "family_label": {f: family_label(f) for f in {c["family"] for c in catalog}},
    "campaigns": catalog, "family_incidents": family_rows, "declared_graphs": declared,
    "incident_sections": [{"section": s, "rows": ids} for s, ids in incident_sections.items()],
}, separators=(",", ":"), default=str))
print("bundles", len(catalog), "| with step grain", sum(1 for c in catalog if c["trajectory_file"]), "| legacy grain", sum(1 for c in catalog if c["grain"].get("legacy_rows")),
      "| incident rows", len(incident_rows), "| direct issue links", sum(1 for c in catalog for i in c["issues"] if i["direct"]))
print("catalog bytes", (OUT / "data/catalog.json").stat().st_size, "| trajectory files bytes", sum((OUT / c["trajectory_file"]).stat().st_size for c in catalog if c["trajectory_file"]))
print(Counter(c["family"] for c in catalog))
print("status labels:", Counter(c["status"]["label"] for c in catalog).most_common(8))
