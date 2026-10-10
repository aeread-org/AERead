#!/usr/bin/env python3
"""Check a case design file written by the case-from-history skill.

    check_case.py <file.case.md> [--deny <digest folder>/masked-originals.txt]

Malformed (exit 1): a heading missing or out of order, a filed statement without a source mark, or
anything sensitive: a credential, an email, a link, a home folder, a network address, a phone- or
card-shaped number, or any original the reader masked (--deny). Missing (reported, exit 0): empty sections, numbers without a range or a
source, unticked readiness lines, open questions.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

HEADINGS = ["Read-back", "The expert", "Decision-maker and goal", "Other parties", "Known and hidden", "Moves, costs and limits",
            "What moves reveal", "Accounting", "Tension", "Variation", "Yardsticks and typical mistakes", "Worked situations",
            "What we did not ask", "Numbers", "Open questions", "Audit", "Ready to build from?"]
SECTIONS = HEADINGS[1:13]
MARK = re.compile(r"\[(said|acted|inferred|asked)\b[^\]]*\]")
SECRET = re.compile(r"sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|-----BEGIN [A-Z ]*PRIVATE KEY-----")


SENSITIVE = [
    ("an email address", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("a link", re.compile(r"\b(?:https?|ssh|ftp|s3|gs)://\S+|\bgit@[\w.\-]+:")),
    ("a home folder", re.compile(r"(?:/Users|/home)/[^/\s]+|[A-Za-z]:\\\\Users\\\\")),
    ("a network address", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("a phone-shaped number", re.compile(r"(?<![\w.])\+?\d{1,3}[ \-.]?\(?\d{2,4}\)?[ \-.]\d{3,4}[ \-.]\d{3,4}(?![\w.])")),
    ("a card-shaped number", re.compile(r"\b(?:\d[ \-]?){13,19}\b")),
    ("a long token", re.compile(r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}\b")),
]


def main(path: str, deny: list[str]) -> int:
    text = Path(path).read_text()
    bad, miss = [], []
    if not text.startswith("# Case design: "):
        bad.append("the first line is not '# Case design: ...'")
    found = re.findall(r"^## (.+?)\s*$", text, re.M)
    if [h for h in found if h in HEADINGS] != HEADINGS:
        bad.append("headings missing or out of order: " + ", ".join(h for h in HEADINGS if h not in found) or "order differs from the template")
    body = {h: b for h, b in zip(found, re.split(r"^## .+?$", text, flags=re.M)[1:])}
    if SECRET.search(text):
        bad.append("a credential-shaped string is in the file")
    for what, rx in SENSITIVE:
        hit = rx.search(text)
        if hit:
            bad.append(f"sensitive: {what} in the file ({hit.group(0)[:4]}...)")
    for term in deny:
        if len(term) >= 4 and re.search(r"(?<!\w)" + re.escape(term) + r"(?!\w)", text, re.I):
            bad.append(f"sensitive: a masked original appears in the file ({term[:3]}..., {len(term)} chars)")
    filed = 0
    for h in SECTIONS:
        b = body.get(h, "")
        lines = [l for l in b.splitlines() if l.startswith("- ") or (l.startswith("|") and not re.match(r"\|[\s\-|]+\|?$", l))]
        rows = [l for l in lines if not (l.startswith("|") and lines and l == next((x for x in lines if x.startswith("|")), None))]
        if "_Nothing filed._" in b or not rows:
            miss.append(f"section empty: {h}")
            continue
        filed += 1
        unmarked = [l for l in rows if not MARK.search(l) and not l.rstrip().endswith("**")]
        if unmarked:
            bad.append(f"{h}: {len(unmarked)} statement(s) without a source mark, first: {unmarked[0][:90]}")
    nums = [[c.strip() for c in l.strip().strip("|").split("|")] for l in body.get("Numbers", "").splitlines() if l.startswith("|")][2:]
    for r in nums:
        if len(r) < 7:
            bad.append(f"Numbers: a row has {len(r)} cells, expected 7")
            continue
        if r[5] not in ("data", "experience", "guess"):
            miss.append(f"number without a source: {r[0]}")
        if not (r[2] and r[4]) and "fixed" not in r[6].lower():
            miss.append(f"number without a range: {r[0]}")
    if not nums:
        miss.append("no numbers filed")
    opens = [l for l in body.get("Open questions", "").splitlines() if l.startswith("- ")]
    unticked = [l[6:] for l in body.get("Ready to build from?", "").splitlines() if l.startswith("- [ ]")]
    print(f"{path}: {filed} of {len(SECTIONS)} sections filed, {len(nums)} numbers, {len(opens)} open questions, {len(unticked)} readiness lines unticked")
    for m in miss:
        print("  missing  ", m)
    for u in unticked:
        print("  not ready", u)
    for b in bad:
        print("  MALFORMED", b)
    return 1 if bad else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    deny: list[str] = []
    if "--deny" in args:
        i = args.index("--deny")
        deny = [t.strip() for t in Path(args[i + 1]).expanduser().read_text().splitlines() if t.strip()]
        del args[i:i + 2]
    if len(args) != 1:
        raise SystemExit(__doc__)
    raise SystemExit(main(args[0], deny))
