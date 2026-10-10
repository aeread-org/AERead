#!/usr/bin/env python3
"""Read Claude Code and Codex session histories on this machine. Nothing leaves it.

    sessions.py list   [--days 30] [--project TEXT] [--tool claude|codex] [--limit 40]
    sessions.py digest ID_OR_PATH [ID_OR_PATH ...] [--out DIR] [--max-chars 60000] [--with-commands]

`list` prints one line per session, newest first: tool, date, id, turns, working folder, first request.
`digest` writes one plain-text file per session holding what the person asked and what the assistant
answered, in order, with tool output dropped. Credentials, emails, links, home folders, network
addresses, phone- and card-shaped numbers, long tokens, your user name and any --mask names are replaced by tags. Long sessions are cut into numbered
parts of --max-chars so each can be read whole.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

CLAUDE = Path(os.environ.get("CLAUDE_CONFIG_DIR", Path.home() / ".claude")) / "projects"
CODEX = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "sessions"
SECRET = re.compile(
    r"(sk-[A-Za-z0-9_\-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|xox[abprs]-[A-Za-z0-9\-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_\-]{30,}"
    r"|eyJ[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{10,}\.[A-Za-z0-9_\-]{6,}|-----BEGIN [A-Z ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z ]*PRIVATE KEY-----"
    r"|(?i:(?:api[_-]?key|secret|token|password|passwd|authorization)\s*[=:]\s*)[\"']?[^\s\"']{8,})")
NOISE = re.compile(r"<(system-reminder|environment_context|user_instructions|local-command-stdout|command-name|command-message|command-args|task-notification)[\s\S]*?</\1>")


#: Specifics that identify a person, a machine or an account. Each becomes a neutral tag; the originals are
#: collected so the finished case file can be checked against them (check_case.py --deny).
IDENTIFIERS = [
    ("[email]", re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")),
    ("[link]", re.compile(r"\b(?:https?|ssh|ftp|s3|gs)://[^\s)>\]\"']+")),
    ("[link]", re.compile(r"\bgit@[\w.\-]+:[\w./\-]+")),
    ("[home]", re.compile(r"(?:/Users|/home)/[^/\s\"']+|[A-Za-z]:\\\\Users\\\\[^\\\\\s]+")),
    ("[ip]", re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b")),
    ("[phone]", re.compile(r"(?<![\w.])\+?\d{1,3}[ \-.]?\(?\d{2,4}\)?[ \-.]\d{3,4}[ \-.]\d{3,4}(?![\w.])")),
    ("[card]", re.compile(r"\b(?:\d[ \-]?){13,19}\b")),
    ("[id]", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("[token]", re.compile(r"\b(?=[A-Za-z0-9_\-]*\d)(?=[A-Za-z0-9_\-]*[A-Za-z])[A-Za-z0-9_\-]{32,}\b")),
]
SEEN: set[str] = set()      # originals masked so far
EXTRA: list[str] = []       # terms the user asked to mask (--mask, --mask-file): names of people, firms, clients, products
KEEP_NUMBERS = re.compile(r"^[\d ,.\-]+$")


def clean(text: str) -> str:
    text = SECRET.sub("[masked]", NOISE.sub("", text or ""))
    for tag, rx in IDENTIFIERS:
        def swap(m, tag=tag):
            SEEN.add(m.group(0))
            return tag
        text = rx.sub(swap, text)
    for i, term in enumerate(EXTRA, 1):
        text, n = re.subn(re.escape(term), f"[name {i}]", text, flags=re.I)
        if n:
            SEEN.add(term)
    return text.strip()


def _blocks(content, kinds) -> str:
    if isinstance(content, str):
        return content
    out = []
    for b in content or []:
        if isinstance(b, dict) and b.get("type") in kinds:
            out.append(b.get("text") or "")
    return "\n".join(out)


def read_claude(path: Path, commands: bool):
    meta = {"tool": "claude", "id": path.stem, "cwd": "", "start": ""}
    turns = []
    for line in path.open(errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        if d.get("isSidechain") or d.get("isMeta"):
            continue
        meta["cwd"] = meta["cwd"] or d.get("cwd") or ""
        meta["start"] = meta["start"] or d.get("timestamp") or ""
        msg = d.get("message") or {}
        if d.get("type") == "user":
            text = clean(_blocks(msg.get("content"), {"text"}))
            if text and not text.startswith("This session is being continued from a previous conversation"):
                turns.append(("you", d.get("timestamp", ""), text))
        elif d.get("type") == "assistant":
            text = clean(_blocks(msg.get("content"), {"text"}))
            if text:
                turns.append(("assistant", d.get("timestamp", ""), text))
            if commands:
                for b in msg.get("content") or []:
                    if isinstance(b, dict) and b.get("type") == "tool_use":
                        inp = b.get("input") or {}
                        what = inp.get("description") or inp.get("command") or inp.get("file_path") or inp.get("query") or ""
                        turns.append(("did", d.get("timestamp", ""), clean(f"{b.get('name')}: {str(what)[:200]}")))
    return meta, turns


def read_codex(path: Path, commands: bool):
    meta = {"tool": "codex", "id": path.stem.split("rollout-")[-1][20:] or path.stem, "cwd": "", "start": ""}
    turns = []
    for line in path.open(errors="replace"):
        try:
            d = json.loads(line)
        except ValueError:
            continue
        p = d.get("payload") if isinstance(d.get("payload"), dict) else d
        ts = d.get("timestamp", "")
        meta["start"] = meta["start"] or ts
        meta["cwd"] = meta["cwd"] or p.get("cwd") or ""
        kind = p.get("type")
        if kind == "message" and p.get("role") in ("user", "assistant"):
            text = clean(_blocks(p.get("content"), {"input_text", "output_text", "text"}))
            if text:
                turns.append(("you" if p["role"] == "user" else "assistant", ts, text))
        elif commands and kind in ("function_call", "custom_tool_call", "local_shell_call"):
            what = p.get("arguments") or p.get("input") or p.get("action") or ""
            turns.append(("did", ts, clean(f"{p.get('name', kind)}: {str(what)[:200]}")))
    return meta, turns


def every(tool=None):
    found = []
    if tool in (None, "claude") and CLAUDE.is_dir():
        found += [("claude", p) for p in CLAUDE.glob("*/*.jsonl")]
    if tool in (None, "codex") and CODEX.is_dir():
        found += [("codex", p) for p in CODEX.rglob("rollout-*.jsonl")]
    return sorted(found, key=lambda x: x[1].stat().st_mtime, reverse=True)


def read(tool, path, commands=False):
    return (read_claude if tool == "claude" else read_codex)(path, commands)


def cmd_list(a):
    cutoff = time.time() - a.days * 86400
    shown = 0
    for tool, path in every(a.tool):
        if path.stat().st_mtime < cutoff:
            break
        meta, turns = read(tool, path)
        asks = [t for t in turns if t[0] == "you"]
        if len(asks) < a.min_turns or (a.project and a.project.lower() not in (meta["cwd"] + str(path)).lower()):
            continue
        first = re.sub(r"\s+", " ", asks[0][2])[:110]
        print(f"{tool:6} {meta['start'][:10]}  {meta['id'][:36]:36}  {len(asks):4} asks  {Path(meta['cwd']).name[:22]:22}  {first}")
        shown += 1
        if shown >= a.limit:
            break
    if not shown:
        print(f"No sessions in the last {a.days} days under {CLAUDE} or {CODEX}.", file=sys.stderr)


def find(ref):
    p = Path(ref).expanduser()
    if p.is_file():
        return ("codex" if "rollout-" in p.name else "claude"), p
    hits = [(t, q) for t, q in every() if ref in q.name]
    if len(hits) != 1:
        raise SystemExit(f"{ref}: {'no session matches' if not hits else str(len(hits)) + ' sessions match; give more of the id'}")
    return hits[0]


def cmd_digest(a):
    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    for ref in a.sessions:
        tool, path = find(ref)
        meta, turns = read(tool, path, a.with_commands)
        head = f"SESSION {tool} {meta['id']} · started {meta['start'][:10]} · folder {Path(meta['cwd']).name}\n\n"
        parts, cur = [], head
        for i, (who, ts, text) in enumerate(turns, 1):
            piece = f"[{i} · {who} · {ts[:16]}]\n{text[: 6000 if who == 'you' else 2500]}\n\n"
            if len(cur) + len(piece) > a.max_chars and cur != head:
                parts.append(cur)
                cur = head
            cur += piece
        parts.append(cur)
        for n, body in enumerate(parts, 1):
            f = out / f"{tool}-{meta['id'][:12]}-{n:02d}of{len(parts):02d}.txt"
            f.write_text(body)
            print(f"{f}  {len(body):,} chars")
    deny = out / "masked-originals.txt"
    deny.write_text("\n".join(sorted(SEEN)) + "\n")
    deny.chmod(0o600)
    print(f"{deny}  {len(SEEN)} masked originals (emails, links, home folders, addresses, numbers that look like phones or cards, long tokens, your --mask terms). Never copy from this file; pass it to check_case.py --deny.")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    l = sub.add_parser("list"); l.add_argument("--days", type=int, default=30); l.add_argument("--project"); l.add_argument("--tool", choices=["claude", "codex"])
    l.add_argument("--limit", type=int, default=40); l.add_argument("--min-turns", type=int, default=3); l.set_defaults(fn=cmd_list)
    g = sub.add_parser("digest"); g.add_argument("sessions", nargs="+"); g.add_argument("--out", default="case-history-digest"); g.add_argument("--max-chars", type=int, default=60000)
    g.add_argument("--with-commands", action="store_true"); g.set_defaults(fn=cmd_digest)
    for sp in (l, g):
        sp.add_argument("--mask", action="append", default=[], help="a name to mask: a person, firm, client or product (repeatable)")
        sp.add_argument("--mask-file", help="a file with one name to mask per line")
    args = ap.parse_args()
    EXTRA.extend(t for t in args.mask if t.strip())
    if args.mask_file:
        EXTRA.extend(t.strip() for t in Path(args.mask_file).expanduser().read_text().splitlines() if t.strip())
    EXTRA.append(Path.home().name)
    EXTRA.sort(key=len, reverse=True)
    args.fn(args)
