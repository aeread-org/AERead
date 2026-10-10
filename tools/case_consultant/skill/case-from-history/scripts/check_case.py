#!/usr/bin/env python3
"""Check a case design file written by the case-from-history skill.

    check_case.py <file.case.md> --deny <digest folder>/masked-originals.txt

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
            "What we did not ask", "Numbers", "Derived, to confirm", "Open questions", "Audit", "Ready to build from?"]
STUB_HEADINGS = ["The decision", "What the person said", "Derived, to confirm", "Why this is not yet a case", "First questions for an interview"]
SECTIONS = HEADINGS[1:13]
MARK = re.compile(r"\[(said|acted|inferred|asked|derived)\b[^\]]*\]")
OWN = re.compile(r"\[(said|acted|asked)\b")
JUDGMENT = ("The professional's rule", "The level at which it flips", "What would flip the choice")
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


def sensitive(text: str, deny: list[str], bad: list[str]) -> int:
    n = len(bad)
    if SECRET.search(text):
        bad.append("a credential-shaped string is in the file")
    for what, rx in SENSITIVE:
        hit = rx.search(text)
        if hit:
            bad.append(f"sensitive: {what} in the file, line {text.count(chr(10), 0, hit.start()) + 1}")
    for i, term in enumerate(deny, 1):
        rx = re.escape(term) if len(term) >= 4 else r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
        if re.search(rx, text, re.I):
            bad.append(f"sensitive: a masked original appears in the file (entry {i} of the deny list, {len(term)} chars)")
    for b in bad[n:]:
        print("  MALFORMED", b)
    return 1 if bad else 0


def main(path: str, deny: list[str]) -> int:
    text = Path(path).read_text()
    bad, miss = [], []
    stub = text.startswith("# Case stub: ")
    wanted = STUB_HEADINGS if stub else HEADINGS
    if not (stub or text.startswith("# Case design: ")):
        bad.append("the first line is neither '# Case design: ...' nor '# Case stub: ...'")
    found = re.findall(r"^## (.+?)\s*$", text, re.M)
    if [h for h in found if h in wanted] != wanted:
        bad.append("headings missing or out of order: " + (", ".join(h for h in wanted if h not in found) or "order differs from the template"))
    body = {h: b for h, b in zip(found, re.split(r"^## .+?$", text, flags=re.M)[1:])}
    if not re.search(r"^Evidence: (strong|partial|thin)\b", text, re.M):
        bad.append("no 'Evidence: strong | partial | thin' line under the title")
    if re.search(r"\[(said|acted|inferred|asked|derived)\b", body.get("Read-back", "")):
        bad.append("Read-back carries source marks; it is plain prose from the person's own statements")
    lines = text.splitlines()
    for i, l in enumerate(lines):
        header = l.startswith("#") or (l.startswith("|") and i + 1 < len(lines) and re.match(r"\|\s*-", lines[i + 1]))
        if header and MARK.search(l):
            bad.append(f"a source mark sits in a heading or table header: {l[:60]}")
        if re.match(r"- \*\*[^*]+:\*\*\s*$", l):
            bad.append(f"an empty label is printed: {l.strip()}")
        if len(MARK.findall(l)) > 1 and not l.startswith("|") and not l.startswith("Marks:"):
            bad.append(f"more than one source mark on a statement: {l[:70]}")
        if any(l.startswith(f"- **{j}:**") for j in JUDGMENT) and "[derived" in l:
            bad.append(f"a derived statement is filed as the person's judgment: {l[:60]}")
    marks = MARK.findall(text.split("Marks:")[-1] if "Marks:" in text else text)
    own = len(OWN.findall(text)) - (3 if "Marks:" in text else 0)
    total = len(MARK.findall(text)) - (5 if "Marks:" in text else 0)
    if not stub and total >= 6 and own * 2 < total:
        bad.append(f"thin: {own} of {total} marked statements are the person's own (said, acted, asked); rewrite as a stub")
    qs = [l for l in body.get("First questions for an interview" if stub else "Open questions", "").splitlines() if re.match(r"\d+\. |- ", l)]
    if len(qs) > (8 if stub else 12):
        bad.append(f"{len(qs)} open questions; keep the {(8 if stub else 12)} that most block building and count the rest in one line")
    for q in qs:
        if q.count("?") > 1:
            bad.append(f"an open question asks more than one thing: {q[:70]}")
    if stub:
        print(f"{path}: stub, {own} of the person's statements, {len(qs)} interview questions")
        for b in bad:
            print("  MALFORMED", b)
        return sensitive(text, deny, bad)
    if sensitive(text, deny, bad):
        pass
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
        if r[5] == "derived":
            bad.append(f"Numbers: a derived figure is filed as the person's own: {r[0]}")
        elif r[5] not in ("data", "experience", "guess"):
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
        if not b.startswith(("sensitive", "a credential")):
            print("  MALFORMED", b)
    return 1 if bad else 0


if __name__ == "__main__":
    args = sys.argv[1:]
    deny: list[str] = []
    if "--deny" in args:
        i = args.index("--deny")
        if i + 1 >= len(args):
            raise SystemExit("--deny needs the path to masked-originals.txt")
        source = Path(args[i + 1]).expanduser()
        if not source.is_file():
            raise SystemExit(f"--deny: {source} does not exist; the check cannot pass without it")
        deny = [t.strip() for t in source.read_text().splitlines() if t.strip()]
        del args[i:i + 2]
    elif "--no-deny" in args:
        args.remove("--no-deny")
        print("  warning   run without the deny list: only pattern checks were made, masked names were not looked for")
    else:
        raise SystemExit("give --deny <digest folder>/masked-originals.txt (or --no-deny to check patterns only, which does not look for masked names)")
    if len(args) != 1:
        raise SystemExit(__doc__)
    raise SystemExit(main(args[0], deny))
