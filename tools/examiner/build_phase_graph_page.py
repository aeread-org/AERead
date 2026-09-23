"""Render every AERead family's phase graph as an inline-SVG inspection page."""
from __future__ import annotations

import html
import json
import sys
from pathlib import Path

SC = Path(__file__).resolve().parent
LIVE = json.load(open(SC / "phase_graphs_live.json"))
STATIC = json.load(open(SC / "phase_graphs.json"))
OUT = SC / "aeread_phase_graphs.html"

# ----------------------------------------------------------------------------
# Graph records: {id, title, plugin, file, source, phases:[{phase_id, actor, mode, next, schemas}], notes, variants}
# ----------------------------------------------------------------------------


def live(key, index=0):
    entry = LIVE[key]
    v = entry["variants"][index]
    return {
        "plugin": key.split("::")[1],
        "file": entry["file"],
        "source": f"live plugin, case {Path(v['case']).name}" if v.get("case") else "live plugin (case ignored)",
        "phases": [
            {"phase_id": p["phase_id"], "actor": p["actor_selector"], "mode": p["mode"], "next": p["next_phases"],
             "schemas": p["action_schema_by_role"], "max": p["max_logical_actions"]}
            for p in v["phases"]
        ],
    }


def static(pkg, fixes=None):
    specs = STATIC[pkg]
    fixes = fixes or {}
    phases = []
    for s in specs:
        actor = s["actor_selector"]
        if isinstance(actor, dict):
            actor = fixes.get(actor.get("dynamic"), actor.get("dynamic"))
        schemas = {}
        import re as _re
        for role, schema in (s["action_schema_by_role"] or {}).items():
            m = _re.search(r"'dynamic': '(\w+)'", role)
            role = fixes.get(m.group(1), m.group(1).lower()) if m else role
            schemas[role] = schema
        phases.append({"phase_id": s["phase_id"], "actor": actor, "mode": s["mode"], "next": s["next_phases"] or [],
                       "schemas": schemas, "max": s["max_logical_actions"]})
    return {"plugin": specs[0]["in"].split("::")[0], "file": f"{specs[0]['file']}:{specs[0]['line']}",
            "source": "static read of the PhaseSpec literals (adapter needs an upstream root to instantiate)", "phases": phases}


def stack_variant(init, iface=None):
    entry = LIVE["datacenter_development::DataCenterStackPlugin"]
    for v in entry["variants"]:
        if v["init"] == init and (iface is None and "developer_interface" not in v or v.get("developer_interface") == iface):
            rec = {"plugin": "DataCenterStackPlugin", "file": entry["file"],
                   "source": f"live plugin, case {Path(v['case']).name}" + (f" (developer_interface {iface})" if iface else ""),
                   "phases": [{"phase_id": p["phase_id"], "actor": p["actor_selector"], "mode": p["mode"], "next": p["next_phases"],
                               "schemas": p["action_schema_by_role"], "max": p["max_logical_actions"]} for p in v["phases"]]}
            return rec
    raise KeyError((init, iface))


HOUSING = {
    "bid": [("contact", "unmatched_tenants", "simultaneous", ["respond"], {"tenant": "housing_contact_v1"}),
            ("respond", "open_landlords", "simultaneous", ["commit"], {"landlord": "housing_respond_v1"}),
            ("commit", "unmatched_tenants", "simultaneous", ["contact"], {"tenant": "housing_commit_v1"})],
    "lemons": [("inspect", "unmatched_tenants", "simultaneous", ["contact"], {"tenant": "housing_inspect_v1"}),
               ("contact", "unmatched_tenants", "simultaneous", ["respond"], {"tenant": "housing_contact_v1"}),
               ("respond", "open_landlords", "simultaneous", ["commit"], {"landlord": "housing_respond_v1"}),
               ("commit", "unmatched_tenants", "simultaneous", ["inspect"], {"tenant": "housing_commit_v1"})],
}


def housing(kind):
    return {"plugin": "HousingV1Plugin", "file": "src/aeread_families/housing/runner.py",
            "source": f"live plugin, world_kind {kind}",
            "phases": [{"phase_id": a, "actor": b, "mode": c, "next": d, "schemas": e, "max": "tenants x rounds"} for a, b, c, d, e in HOUSING[kind]]}


FAMILIES = [
    ("agenticpay_bilateral", "AgenticPay bilateral", static("agenticpay_bilateral"), "Alternating bilateral bargaining: buyer then seller, one seat per turn, until the family's own terminal predicate on the state (deal or walk)."),
    ("alympics_wac", "Alympics water allocation", static("alympics_wac"), "One repeated simultaneous bid round among the surviving players; the loop ends when the state says the game is over."),
    ("amazonbarg", "AmazonBarg", static("amazonbarg"), "Alternating buyer and seller turns over a listing; the same shape as AgenticPay with different seats."),
    ("aucarena", "AucArena", live("aucarena::AucArenaPlugin"), "A single simultaneous bid round that repeats until the auction state terminates."),
    ("collusion", "Collusion duopoly", live("collusion::CollusionPlugin"), "One simultaneous pricing round per period; the periods are the state, not the graph."),
    ("commercial_state_calibration", "Commercial state calibration", live("commercial_state_calibration::CommercialStatePlugin"), "One phase, one report: the agent submits a calibrated state report and the episode ends."),
    ("consent_ir", "Consent IR", live("consent_ir::ConsentIRPlugin"), "One phase: the agent proposes a cycle, and the terminal predicate decides."),
    ("datacenter_development", "Datacenter development, scope v1 (service and loan)", live("datacenter_development::DataCenterDevelopmentPlugin"), "Two agreements in sequence, each an offer, a counterparty response that may send the developer back to re-offer or on to commit, and a commit that opens the next agreement. The loan commit has no successor: the episode ends there."),
    ("datacenter_stack_v1", "Datacenter stack, scope v1 (four agreements)", stack_variant("init('v1',)"), "The same three-phase cell repeated per agreement in the declared sequence; a walk is a state transition to terminal, not an edge."),
    ("datacenter_stack_v2", "Datacenter stack, scope v2 (six agreements, developer interface 2 and 3)", stack_variant("init('v2',)"), "Interface 3 adds exactly one edge (drawn in colour): the land-amendment offer may proceed straight to the loan offer, which is the decline the interface-2 graph lacked (DC-D-10). Everything else is identical."),
    ("datacenter_counteroffer", "Datacenter counteroffer variants (land agreement)", None, "Three campaign plugins reshape only the land agreement of the stack graph: adoption delegates unchanged; affordance lets the offer phase go straight to commit (accept by re-emitting the package); action-schema inserts a dedicated accept-by-reference phase after the response."),
    ("datacenter_development_terms", "Datacenter development terms", live("datacenter_development_terms::DataCenterTermsPlugin"), "One phase, one terms report."),
    ("econagent_v1", "EconAgent", static("econagent_v1"), "One simultaneous month for all agents, repeated; the horizon is in the state."),
    ("econevals", "EconEvals", static("econevals"), "One single-seat period, repeated across the declared periods."),
    ("govsim", "GovSim", static("govsim"), "A three-phase round: simultaneous harvest, a single-seat discussion phase, simultaneous reflection, then the next harvest."),
    ("housing", "Housing, bid world and lemons world", None, "The lemons world adds one simultaneous phase at the head of each round. Decisions never choose an edge here: every decision rewrites the state (holds, leases, inspections) and the cycle is fixed."),
    ("negarena", "NegArena", static("negarena", fixes={"RED": "red", "BLUE": "blue"}), "Red and blue seats alternate single turns."),
    ("procurement_allocation", "Procurement allocation", live("procurement_allocation::ProcurementAllocationPlugin"), "One self-looping buyer phase: every action (inquire, defer, award) is a state change and the award ends the episode through the terminal predicate."),
    ("procurement_grounding", "Procurement grounding", live("procurement_grounding::ProcurementGroundingPlugin"), "One phase, one assessment."),
    ("refund_v1", "Refund v1", live("refund::RefundV1Plugin"), "Customer and support alternate single turns until the state resolves."),
    ("refund_v2", "Refund v2.1 (intake, policy, payments)", live("refund::RefundV21Plugin"), "The one family whose graph branches on a decision three ways: the policy seat may request more facts (back to the customer), approve pending confirmation, or approve directly to payments. Payments has no successor."),
    ("single_offer", "Single offer", live("single_offer::SingleOfferPlugin"), "One phase, one offer."),
    ("steer", "STEER", static("steer"), "One question, one answer."),
    ("tau3_retail", "Tau3 retail", static("tau3_retail"), "User and assistant alternate single turns."),
    ("termsbench", "TERMS-Bench", live("termsbench::TermsBenchPlugin"), "Agent and scripted counterpart alternate single turns."),
]

# ----------------------------------------------------------------------------
# Layout and SVG
# ----------------------------------------------------------------------------

NODE_W, NODE_H, GAP_X, GAP_Y = 168, 54, 72, 26


def layers(phases):
    ids = [p["phase_id"] for p in phases]
    nxt = {p["phase_id"]: [n for n in p["next"] if n in ids] for p in phases}
    depth = {ids[0]: 0}
    queue = [ids[0]]
    while queue:
        cur = queue.pop(0)
        for n in nxt[cur]:
            if n not in depth:
                depth[n] = depth[cur] + 1
                queue.append(n)
    for i in ids:
        depth.setdefault(i, max(depth.values(), default=0) + 1)
    return depth, nxt


def esc(s):
    return html.escape(str(s), quote=True)


def node_svg(x, y, p, accent=False):
    double = p["mode"] == "simultaneous"
    parts = [f'<rect x="{x}" y="{y}" width="{NODE_W}" height="{NODE_H}" rx="6" fill="var(--node)" stroke="currentColor" stroke-width="1.4"/>']
    if double:
        parts.append(f'<rect x="{x+4}" y="{y+4}" width="{NODE_W-8}" height="{NODE_H-8}" rx="4" fill="none" stroke="currentColor" stroke-width="0.8"/>')
    parts.append(f'<text x="{x+NODE_W/2}" y="{y+22}" text-anchor="middle" font-family="var(--mono)" font-size="12" fill="currentColor">{esc(p["phase_id"])}</text>')
    sub = f'{p["actor"]} · {p["mode"]}'
    parts.append(f'<text x="{x+NODE_W/2}" y="{y+40}" text-anchor="middle" font-size="10.5" fill="var(--muted)">{esc(sub)}</text>')
    return "\n".join(parts)


def arrow(x1, y1, x2, y2, label=None, accent=False, dashed=False, curve=0.0):
    color = "var(--accent)" if accent else "currentColor"
    marker = "url(#arrow-accent)" if accent else "url(#arrow)"
    dash = ' stroke-dasharray="5 4"' if dashed else ""
    if curve:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2 + curve
        d = f"M{x1},{y1} Q{mx},{my} {x2},{y2}"
        lx, ly = mx, (y1 + y2) / 2 + curve / 2
    else:
        d = f"M{x1},{y1} L{x2},{y2}"
        lx, ly = (x1 + x2) / 2, (y1 + y2) / 2 - 6
    out = [f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.4"{dash} marker-end="{marker}"/>']
    if label:
        out.append(f'<text x="{lx}" y="{ly}" text-anchor="middle" font-size="10.5" fill="{color}">{esc(label)}</text>')
    return "\n".join(out)


def generic_graph(phases, edge_labels=None, accent_edges=(), dashed_edges=()):
    """Layered left-to-right layout; back edges arc below, self loops arc above."""
    edge_labels = edge_labels or {}
    depth, nxt = layers(phases)
    by_layer = {}
    for p in phases:
        by_layer.setdefault(depth[p["phase_id"]], []).append(p)
    ncols = max(by_layer) + 1
    nrows = max(len(v) for v in by_layer.values())
    W = 40 + ncols * (NODE_W + GAP_X) - GAP_X + 40
    H = 60 + nrows * (NODE_H + GAP_Y) - GAP_Y + 70
    pos = {}
    for col, plist in by_layer.items():
        total = len(plist) * (NODE_H + GAP_Y) - GAP_Y
        y0 = 60 + (nrows * (NODE_H + GAP_Y) - GAP_Y - total) / 2
        for i, p in enumerate(plist):
            pos[p["phase_id"]] = (40 + col * (NODE_W + GAP_X), y0 + i * (NODE_H + GAP_Y))
    parts = []
    # entry marker
    ex, ey = pos[phases[0]["phase_id"]]
    parts.append(f'<circle cx="{ex-22}" cy="{ey+NODE_H/2}" r="4" fill="currentColor"/>')
    parts.append(arrow(ex - 18, ey + NODE_H / 2, ex - 2, ey + NODE_H / 2))
    back_count = 0
    for p in phases:
        sx, sy = pos[p["phase_id"]]
        for n in p["next"]:
            if n not in pos:
                continue
            tx, ty = pos[n]
            key = (p["phase_id"], n)
            label = edge_labels.get(key)
            acc = key in accent_edges
            dsh = key in dashed_edges
            if n == p["phase_id"]:
                # self loop above the node
                cx = sx + NODE_W / 2
                d = f"M{cx+18},{sy} C{cx+40},{sy-46} {cx-40},{sy-46} {cx-18},{sy}"
                color = "var(--accent)" if acc else "currentColor"
                parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.4" marker-end="url(#arrow)"/>')
                parts.append(f'<text x="{cx}" y="{sy-38}" text-anchor="middle" font-size="10.5" fill="var(--muted)">{esc(label or "next round")}</text>')
            elif depth[n] > depth[p["phase_id"]]:
                # forward: right middle to left middle (straight if same row)
                parts.append(arrow(sx + NODE_W, sy + NODE_H / 2, tx - 2, ty + NODE_H / 2, label, acc, dsh,
                                   curve=0 if abs(sy - ty) < 1 else 0))
            else:
                # back edge: arc under the row
                back_count += 1
                drop = 40 + 18 * back_count
                x1, y1 = sx + NODE_W / 2, sy + NODE_H
                x2, y2 = tx + NODE_W / 2, ty + NODE_H + 2
                base = max(y1, y2) + drop
                d = f"M{x1},{y1} C{x1},{base} {x2},{base} {x2},{y2}"
                color = "var(--accent)" if acc else "currentColor"
                marker = "url(#arrow-accent)" if acc else "url(#arrow)"
                parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="1.4"{" stroke-dasharray=\"5 4\"" if dsh else ""} marker-end="{marker}"/>')
                parts.append(f'<text x="{(x1+x2)/2}" y="{base-8}" text-anchor="middle" font-size="10.5" fill="{color if acc else "var(--muted)"}">{esc(label or "next round")}</text>')
                H = max(H, base + 30)
        if not p["next"]:
            # terminal bar
            parts.append(f'<line x1="{sx+NODE_W+14}" y1="{sy+10}" x2="{sx+NODE_W+14}" y2="{sy+NODE_H-10}" stroke="currentColor" stroke-width="3"/>')
            parts.append(arrow(sx + NODE_W, sy + NODE_H / 2, sx + NODE_W + 10, sy + NODE_H / 2))
    for p in phases:
        x, y = pos[p["phase_id"]]
        parts.append(node_svg(x, y, p))
    return W, H, "\n".join(parts)


def stack_graph(phases, accent_edges=(), extra_edges=(), edge_labels=None, extra_nodes=(), key_of=None):
    """Grid: one column per agreement, rows offer / response / commit."""
    edge_labels = edge_labels or {}
    key_of = key_of or (lambda pid: pid.rsplit("_", 2)[0])
    order = []
    for p in phases:
        key = key_of(p["phase_id"])
        if key not in order:
            order.append(key)
    rows = {"offer": 0, "response": 1, "commit": 2}
    pos = {}
    for p in phases:
        key, kind = key_of(p["phase_id"]), p["phase_id"].rsplit("_", 1)[1]
        pos[p["phase_id"]] = (40 + order.index(key) * (NODE_W + GAP_X), 60 + rows[kind] * (NODE_H + 46))
    for node in extra_nodes:
        pos[node["phase_id"]] = node["pos"]
    W = 40 + len(order) * (NODE_W + GAP_X) - GAP_X + 60
    H = 60 + 3 * (NODE_H + 46) + 20
    parts = []
    ex, ey = pos[phases[0]["phase_id"]]
    parts.append(f'<circle cx="{ex-22}" cy="{ey+NODE_H/2}" r="4" fill="currentColor"/>')
    parts.append(arrow(ex - 18, ey + NODE_H / 2, ex - 2, ey + NODE_H / 2))
    all_edges = [(p["phase_id"], n) for p in phases for n in p["next"]] + list(extra_edges)
    for s, n in all_edges:
        if n not in pos or s not in pos:
            continue
        sx, sy = pos[s]; tx, ty = pos[n]
        acc = (s, n) in accent_edges
        label = edge_labels.get((s, n))
        if sx == tx and ty > sy:      # down: offer->response, response->commit
            parts.append(arrow(sx + NODE_W / 2 + (14 if s.endswith("_response") else -14), sy + NODE_H, tx + NODE_W / 2 + (14 if s.endswith("_response") else -14), ty - 2, label, acc))
        elif sx == tx and ty < sy:    # up: response -> offer (counter)
            parts.append(arrow(sx + NODE_W / 2 + 40, sy, tx + NODE_W / 2 + 40, ty + NODE_H + 2, label or "counter", acc))
        elif ty < sy:                 # commit -> next offer (diagonal up-right), or amendment offer -> loan offer
            parts.append(arrow(sx + NODE_W, sy + NODE_H / 2, tx - 2, ty + NODE_H / 2, label, acc, curve=0))
        else:
            parts.append(arrow(sx + NODE_W, sy + NODE_H / 2, tx - 2, ty + NODE_H / 2, label, acc))
    # same-row forward edge from an offer to the next offer (interface 3 decline): draw as an arc above
    for p in phases + list(extra_nodes):
        x, y = pos[p["phase_id"]]
        parts.append(node_svg(x, y, p))
    last_commit = [p for p in phases if not p["next"]]
    for p in last_commit:
        sx, sy = pos[p["phase_id"]]
        parts.append(f'<line x1="{sx+NODE_W+14}" y1="{sy+10}" x2="{sx+NODE_W+14}" y2="{sy+NODE_H-10}" stroke="currentColor" stroke-width="3"/>')
        parts.append(arrow(sx + NODE_W, sy + NODE_H / 2, sx + NODE_W + 10, sy + NODE_H / 2))
    return W, H, "\n".join(parts)


DEFS = '''<defs>
<marker id="arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="currentColor"/></marker>
<marker id="arrow-accent" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="8" markerHeight="8" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" fill="var(--accent)"/></marker>
</defs>'''


def figure(fid, title, W, H, body, caption, claim):
    return f'''<figure id="{fid}">
<div class="scroll"><svg viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" role="img" aria-label="{esc(claim)}" style="max-width:100%;height:auto">{DEFS}
{body}
</svg></div>
<figcaption>{caption}</figcaption>
</figure>'''


def meta_line(rec):
    phases = rec["phases"]
    modes = sorted({p["mode"] for p in phases})
    edges = sum(len(p["next"]) for p in phases)
    ids = {p["phase_id"] for p in phases}
    cyc = any(n in ids and (n == p["phase_id"] or True) for p in phases for n in p["next"]) and _has_cycle(phases)
    branch = max((len(p["next"]) for p in phases), default=0)
    roles = sorted({r for p in phases for r in p["schemas"]})
    return phases, modes, edges, cyc, branch, roles


def _has_cycle(phases):
    ids = [p["phase_id"] for p in phases]
    nxt = {p["phase_id"]: [n for n in p["next"] if n in ids] for p in phases}
    state = {}

    def visit(u):
        state[u] = 1
        for v in nxt[u]:
            if state.get(v) == 1 or (state.get(v) is None and visit(v)):
                return True
        state[u] = 2
        return False
    return any(state.get(i) is None and visit(i) for i in ids)


# ----------------------------------------------------------------------------
# Page
# ----------------------------------------------------------------------------

rows_html = []
figs_html = []
index_html = []

for fid, title, rec, claim in FAMILIES:
    index_html.append(f'<a href="#{fid}">{esc(title)}</a>')
    if fid == "housing":
        recs = [("bid world", housing("bid")), ("lemons world", housing("lemons"))]
        bodies = []
        for label, r in recs:
            W, H, body = generic_graph(r["phases"])
            bodies.append((label, W, H, body))
        inner = "".join(
            f'<div class="pair"><div class="pairlabel">{esc(l)}</div><div class="scroll"><svg viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" role="img" aria-label="{esc(l)}: {esc(claim)}" style="max-width:100%;height:auto">{DEFS}{b}</svg></div></div>'
            for l, W, H, b in bodies)
        r = recs[1][1]
        phases, modes, edges, cyc, branch, roles = meta_line(r)
        figs_html.append(f'''<figure id="{fid}"><h2>{esc(title)}</h2><p class="meta">{esc(r["plugin"])} · <code>{esc(r["file"])}</code> · source: {esc(r["source"])} and world_kind bid</p>
<div class="pairs">{inner}</div>
<figcaption>{esc(claim)} Bid: 3 phases, 3 edges. Lemons: 4 phases, 4 edges. All phases simultaneous; actor selectors <code>unmatched_tenants</code> and <code>open_landlords</code>; roles tenant, landlord.</figcaption></figure>''')
        rows_html.append(f'<tr><td><a href="#{fid}">{esc(title)}</a></td><td>3 / 4</td><td>3 / 4</td><td>simultaneous</td><td>yes</td><td>1</td><td>live plugin</td></tr>')
        continue
    if fid == "datacenter_counteroffer":
        base = stack_variant("init('v2',)")
        key_of = lambda pid: pid.rsplit("_", 2)[0]
        land = [p for p in base["phases"] if key_of(p["phase_id"]) == "land"]
        land_ids = {p["phase_id"].rsplit("_", 1)[1]: p["phase_id"] for p in land}
        land = [dict(p, next=[n for n in p["next"] if n in land_ids.values()]) for p in land]
        dedicated = {"phase_id": "land_developer_accept_counteroffer", "actor": "developer", "mode": "single", "next": [land_ids["commit"]], "schemas": {"developer": "datacenter_land_accept_counteroffer_v1"}, "max": 1, "pos": (40 + (NODE_W + GAP_X) + 60, 60 + (NODE_H + 46) + 50)}
        extra = [(land_ids["offer"], land_ids["commit"]), (land_ids["response"], "land_developer_accept_counteroffer")]
        W, H, body = stack_graph(land, accent_edges=set(extra), extra_edges=extra, extra_nodes=[dedicated],
                                 edge_labels={extra[0]: "affordance: re-emit the package", extra[1]: "action-schema: dedicated accept phase"})
        W += NODE_W + 120
        H += 60
        r = base
        figs_html.append(f'''<figure id="{fid}"><h2>{esc(title)}</h2><p class="meta">CounterofferAdoptionPlugin, CounterofferAffordancePlugin, CounterofferActionSchemaPlugin · <code>src/aeread_families/datacenter_development/adoption_environment.py, affordance_environment.py, action_schema_environment.py</code> · source: read from the three phases() bodies (no fixture validated)</p>
<div class="scroll"><svg viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" role="img" aria-label="{esc(claim)}" style="max-width:100%;height:auto">{DEFS}{body}</svg></div>
<figcaption>{esc(claim)} Black edges are the stack graph's land agreement; coloured edges and the extra node are what each variant adds. The rest of the stack is unchanged.</figcaption></figure>''')
        rows_html.append(f'<tr><td><a href="#{fid}">{esc(title)}</a></td><td>18 or 19</td><td>+1 or +2</td><td>single</td><td>yes</td><td>3</td><td>read from source</td></tr>')
        continue
    phases, modes, edges, cyc, branch, roles = meta_line(rec)
    if fid.startswith("datacenter_stack") or fid == "datacenter_development":
        accent = set()
        labels = {}
        if fid == "datacenter_stack_v2":
            v3 = stack_variant("init('v2',)", iface=3)
            base_edges = {(p["phase_id"], n) for p in rec["phases"] for n in p["next"]}
            v3_edges = {(p["phase_id"], n) for p in v3["phases"] for n in p["next"]}
            accent = v3_edges - base_edges
            labels = {e: "interface 3: decline the amendment" for e in accent}
            merged = [dict(p, next=list(dict.fromkeys(p["next"] + [n for (s, n) in accent if s == p["phase_id"]]))) for p in rec["phases"]]
            W, H, body = stack_graph(merged, accent_edges=accent, edge_labels=labels)
            edges_text = f"{edges} edges under interface 2, {edges + len(accent)} under interface 3"
        else:
            W, H, body = stack_graph(rec["phases"])
            edges_text = f"{edges} edges"
        caption = f"{esc(claim)} {len(phases)} phases, {edges_text}; every phase single-seat; seats {', '.join(esc(r) for r in roles)}. Response phases may return to the offer (counter) or proceed to commit; a walk ends the episode through the terminal predicate, not an edge."
        rows_html.append(f'<tr><td><a href="#{fid}">{esc(title)}</a></td><td>{len(phases)}</td><td>{esc(edges_text.split(" edges")[0] if "under" not in edges_text else edges_text.replace(" edges under interface 2, ", " / ").replace(" under interface 3", ""))}</td><td>{", ".join(modes)}</td><td>{"yes" if cyc else "no"}</td><td>{branch}</td><td>{esc(rec["source"].split(",")[0])}</td></tr>')
        figs_html.append(f'''<figure id="{fid}"><h2>{esc(title)}</h2><p class="meta">{esc(rec["plugin"])} · <code>{esc(rec["file"])}</code> · source: {esc(rec["source"])}</p>
<div class="scroll"><svg viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" role="img" aria-label="{esc(claim)}" style="max-width:100%;height:auto">{DEFS}{body}</svg></div>
<figcaption>{caption}</figcaption></figure>''')
        continue
    W, H, body = generic_graph(rec["phases"])
    terminal_note = "The last phase has no successor, so the episode ends there." if any(not p["next"] for p in phases) else "No phase is a sink: the episode ends only when the family's terminal predicate on the state says so."
    caption = f"{esc(claim)} {len(phases)} phase{'s' if len(phases) != 1 else ''}, {edges} edge{'s' if edges != 1 else ''}; mode {', '.join(modes)}; actor selector{'s' if len(phases) > 1 else ''} {', '.join(sorted({esc(p['actor']) for p in phases}))}; roles {', '.join(esc(r) for r in roles) or 'none declared'}. {terminal_note}"
    rows_html.append(f'<tr><td><a href="#{fid}">{esc(title)}</a></td><td>{len(phases)}</td><td>{edges}</td><td>{", ".join(modes)}</td><td>{"yes" if cyc else "no"}</td><td>{branch}</td><td>{esc(rec["source"].split(" (")[0].split(",")[0])}</td></tr>')
    figs_html.append(f'''<figure id="{fid}"><h2>{esc(title)}</h2><p class="meta">{esc(rec["plugin"])} · <code>{esc(rec["file"])}</code> · source: {esc(rec["source"])}</p>
<div class="scroll"><svg viewBox="0 0 {W:.0f} {H:.0f}" width="{W:.0f}" role="img" aria-label="{esc(claim)}" style="max-width:100%;height:auto">{DEFS}{body}</svg></div>
<figcaption>{caption}</figcaption></figure>''')

page = f'''<title>AERead Phase Graphs</title>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500&display=swap">
<style>
:root {{
  --bg: #F6F5F1; --ink: #1E2126; --muted: #6A6F78; --rule: #D9D6CE; --node: #FFFFFF;
  --accent: #B4530B; --accent-soft: #F3E3D3; --table: #EEECE6;
  --sans: "IBM Plex Sans", "Helvetica Neue", Arial, sans-serif; --mono: "IBM Plex Mono", "SFMono-Regular", Menlo, Consolas, monospace;
}}
@media (prefers-color-scheme: dark) {{ :root:not([data-theme="light"]) {{
  --bg: #15171B; --ink: #E6E7EA; --muted: #9AA0AA; --rule: #33373F; --node: #1E2127; --accent: #F0A15C; --accent-soft: #3A2A1A; --table: #1B1E24; }} }}
:root[data-theme="dark"] {{
  --bg: #15171B; --ink: #E6E7EA; --muted: #9AA0AA; --rule: #33373F; --node: #1E2127; --accent: #F0A15C; --accent-soft: #3A2A1A; --table: #1B1E24; }}
body {{ background: var(--bg); color: var(--ink); font-family: var(--sans); font-size: 15px; line-height: 1.5; margin: 0; padding-inline: max(16px, 4vw); padding-block: 28px 64px; }}
main {{ max-width: 1180px; margin: 0 auto; }}
h1 {{ font-size: 28px; font-weight: 600; letter-spacing: -0.01em; margin: 0 0 6px; text-wrap: balance; }}
h2 {{ font-size: 18px; font-weight: 600; margin: 0 0 4px; text-wrap: balance; }}
p.lede {{ max-width: 68ch; margin: 0 0 18px; color: var(--ink); }}
p.meta {{ font-size: 12.5px; color: var(--muted); margin: 0 0 10px; }}
code {{ font-family: var(--mono); font-size: 12px; }}
nav.index {{ display: flex; flex-wrap: wrap; gap: 6px 14px; font-size: 13px; padding: 12px 0 16px; border-top: 1px solid var(--rule); border-bottom: 1px solid var(--rule); margin-bottom: 22px; }}
nav.index a {{ color: var(--ink); text-decoration: none; border-bottom: 1px dotted var(--muted); }}
nav.index a:hover, nav.index a:focus-visible {{ border-bottom-color: var(--accent); outline: none; }}
.legend {{ display: flex; flex-wrap: wrap; gap: 10px 22px; font-size: 13px; color: var(--muted); margin: 0 0 26px; align-items: center; }}
.legend svg {{ vertical-align: middle; }}
table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; margin: 0 0 34px; font-variant-numeric: tabular-nums; }}
th, td {{ text-align: left; padding: 7px 10px; border-bottom: 1px solid var(--rule); vertical-align: top; }}
th {{ font-weight: 600; background: var(--table); font-size: 12.5px; letter-spacing: 0.02em; text-transform: uppercase; }}
td:nth-child(n+2):nth-child(-n+6) {{ white-space: nowrap; }}
table a {{ color: var(--ink); text-decoration: none; border-bottom: 1px dotted var(--muted); }}
figure {{ margin: 0 0 40px; padding-top: 18px; border-top: 1px solid var(--rule); }}
figure svg {{ color: var(--ink); display: block; }}
.scroll {{ overflow-x: auto; padding-bottom: 4px; }}
figcaption {{ font-size: 13.5px; color: var(--muted); max-width: 78ch; margin-top: 8px; }}
.pairs {{ display: flex; flex-wrap: wrap; gap: 24px 40px; align-items: flex-start; }}
.pair {{ min-width: 0; }}
.pairlabel {{ font-size: 12.5px; color: var(--muted); margin-bottom: 4px; font-family: var(--mono); }}
.wrapper {{ overflow-x: auto; }}
@media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior: auto; }} }}
</style>
<main>
<h1>AERead Phase Graphs</h1>
<p class="lede">Every family plugin's declared phase graph, drawn from the code as of branch <code>codex/housing-lemons-refusal</code> (origin/main 96ab6af0 plus the lemons world). Nodes are <code>PhaseSpec</code> declarations; an arrow means the phase may hand the episode to that phase next. Fourteen graphs were read from the live plugin with a real case, eight adapter graphs from their literal declarations, and the counteroffer variants from their <code>phases()</code> bodies.</p>
<div class="legend">
<span><svg width="44" height="22" viewBox="0 0 44 22"><rect x="1" y="1" width="42" height="20" rx="4" fill="var(--node)" stroke="currentColor" stroke-width="1.4"/></svg> single-seat phase</span>
<span><svg width="44" height="22" viewBox="0 0 44 22"><rect x="1" y="1" width="42" height="20" rx="4" fill="var(--node)" stroke="currentColor" stroke-width="1.4"/><rect x="4" y="4" width="36" height="14" rx="3" fill="none" stroke="currentColor" stroke-width="0.8"/></svg> simultaneous phase (all eligible seats act on one frozen state)</span>
<span><svg width="30" height="14" viewBox="0 0 30 14"><circle cx="5" cy="7" r="4" fill="currentColor"/><line x1="10" y1="7" x2="28" y2="7" stroke="currentColor" stroke-width="1.4"/></svg> entry (the first declared phase)</span>
<span><svg width="30" height="14" viewBox="0 0 30 14"><line x1="2" y1="7" x2="20" y2="7" stroke="currentColor" stroke-width="1.4"/><line x1="24" y1="1" x2="24" y2="13" stroke="currentColor" stroke-width="3"/></svg> phase with no successor (episode ends)</span>
<span><svg width="30" height="14" viewBox="0 0 30 14"><line x1="2" y1="7" x2="28" y2="7" stroke="var(--accent)" stroke-width="1.6"/></svg> edge that exists only under one variant or interface</span>
</div>
<nav class="index" aria-label="families">{"".join(index_html)}</nav>
<table>
<thead><tr><th>family</th><th>phases</th><th>edges</th><th>mode</th><th>cycle</th><th>max out-degree</th><th>read from</th></tr></thead>
<tbody>{"".join(rows_html)}</tbody>
</table>
{"".join(figs_html)}
<p class="meta">Where a family loops on itself the terminal predicate on the state, not the graph, ends the episode; where a phase branches, the family's <code>step</code> chooses the successor from the batch of legal actions. Both are outside the drawing by design.</p>
</main>
'''
OUT.write_text(page)
print("wrote", OUT, len(page) // 1024, "KB;", len(FAMILIES), "figures")
