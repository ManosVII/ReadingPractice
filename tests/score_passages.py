"""
Score a texts database against tests/expected_passages.json.

Usage:
    python tests/score_passages.py data/reading.db
    python tests/score_passages.py data/reading_new.db --verbose
    python tests/score_passages.py data/reading_new.db --gt tests/spot_checks.json

The database is opened read-only.
Exit code 0 only when every lesson passes (no FP, FN, boundary, title or format error).
"""
import json
import re
import sqlite3
import sys
import unicodedata
from collections import defaultdict
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

HERE = Path(__file__).parent

# Latin capitals (and o) that the PDFs use inside Greek words.
_LOOKALIKE = str.maketrans("ABEZHIKMNOPTYXo", "ΑΒΕΖΗΙΚΜΝΟΡΤΥΧο")


def key(text: str) -> str:
    """Letters and digits only, lower-case, look-alikes mapped to Greek."""
    text = unicodedata.normalize("NFC", text).replace("­", "").translate(_LOOKALIKE)
    return "".join(c for c in text.lower() if unicodedata.category(c)[0] in "LN")


def lines_and_stanzas(content: str):
    lines = [l for l in content.split("\n") if l.strip()]
    stanzas = [s for s in re.split(r"\n\s*\n", content) if s.strip()]
    return len(lines), len(stanzas)


def check_expected(exp, row):
    """Return (kind, reasons): kind in ok / boundary / format / title."""
    ck = key(row["content"])
    fk, lk = key(exp["first_words"]), key(exp["last_words"])
    reasons = []
    if not ck.startswith(fk):
        reasons.append("does not start at first_words" + (" (starts later)" if fk not in ck else " (extra text before)"))
    if not ck.endswith(lk):
        reasons.append("does not end at last_words" + (" (cut short)" if lk not in ck else " (extra text after)"))
    for s in exp.get("must_contain", []):
        if key(s) not in ck:
            reasons.append(f"missing: {s!r}")
    order = exp.get("must_contain_in_order", [])
    pos = 0
    for s in order:
        i = ck.find(key(s), pos)
        if i < 0:
            reasons.append(f"order/missing: {s!r}")
            break
        pos = i
    for s in exp.get("must_not_contain", []):
        if (key(s) and key(s) in ck) or (not key(s) and s in row["content"]):
            reasons.append(f"contains: {s!r}")
    if reasons:
        return "boundary", reasons
    fmt = []
    n_lines, n_stanzas = lines_and_stanzas(row["content"])
    if "lines" in exp and n_lines != exp["lines"]:
        fmt.append(f"lines {n_lines} != {exp['lines']}")
    if "stanzas" in exp and n_stanzas != exp["stanzas"]:
        fmt.append(f"stanzas {n_stanzas} != {exp['stanzas']}")
    if "paragraphs" in exp and n_lines != exp["paragraphs"]:
        fmt.append(f"paragraphs {n_lines} != {exp['paragraphs']}")
    m = re.search(r"[^\W\d_][-­]\s+[^\W\d_]", row["content"])
    if m:
        fmt.append(f"line-break hyphen not re-joined: {m.group(0)!r}")
    if fmt:
        return "format", fmt
    if key(row["title"]) != key(exp["title"]):
        return "title", [f"title {row['title']!r} != {exp['title']!r}"]
    return "ok", []


def overlaps(spec, row) -> bool:
    ck = key(row["content"])
    probes = [key(spec["first_words"])[:40], key(spec["last_words"])[-40:]]
    probes += [key(s) for s in spec.get("must_contain", [])]
    return any(p and p in ck for p in probes)


def score(db_path: str, verbose: bool = False, gt_path=None):
    gt = json.loads(Path(gt_path or HERE / "expected_passages.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    all_rows = [dict(r) for r in conn.execute("SELECT * FROM texts")]
    conn.close()
    by_source = defaultdict(list)
    for r in all_rows:
        by_source[r["source_id"]].append(r)

    per_class = defaultdict(lambda: defaultdict(int))
    lesson_results = []
    for les in gt["lessons"]:
        lo, hi = les["window"]
        rows = [r for r in by_source[les["source_id"]] if r["page_number"] is not None and lo <= r["page_number"] <= hi]
        used = set()
        res = {"id": les["id"], "class": les["class"], "fp": [], "fn": [], "boundary": [], "format": [], "title": [], "ok": []}
        for exp in les["expected"]:
            cands = [r for r in rows if overlaps(exp, r)]
            if not cands:
                res["fn"].append(exp["title"])
                continue
            for r in cands:
                used.add(r["id"])
            if len(cands) > 1:
                res["boundary"].append((exp["title"], [f"split into {len(cands)} rows: " + ", ".join(r["id"] for r in cands)]))
                continue
            kind, reasons = check_expected(exp, cands[0])
            if kind == "ok":
                res["ok"].append(exp["title"])
            else:
                res[kind].append((exp["title"], reasons + [f"row {cands[0]['id']}"]))
        for opt in les.get("optional", []):
            for r in rows:
                if r["id"] in used or not overlaps(opt, r):
                    continue
                kind, _ = check_expected(dict(opt, title=r["title"]), r)
                if kind in ("ok", "format"):
                    used.add(r["id"])
        for r in rows:
            if r["id"] not in used:
                res["fp"].append((r["id"], r["page_number"], r["title"][:40], r["content"][:70].replace("\n", " / ")))
        forb = [key(s) for s in les.get("forbidden", [])]
        for r in by_source[les["source_id"]]:
            ck = key(r["content"])
            for s, k in zip(les.get("forbidden", []), forb):
                if k and k in ck and r["id"] in used:
                    res["boundary"].append((r["title"], [f"row {r['id']} contains exercise text {s!r}"]))
        lesson_results.append(res)
        c = per_class[les["class"]]
        c["lessons"] += 1
        c["expected"] += len(les["expected"])
        for k in ("fp", "fn", "boundary", "format", "title", "ok"):
            c[k] += len(res[k])

    glob_hits = []
    for s in gt.get("global_forbidden", []):
        k = key(s)
        for r in all_rows:
            if k in key(r["content"]) or k in key(r["title"]):
                glob_hits.append((s, r["id"]))

    # ── report ────────────────────────────────────────────────────────────
    print(f"Database: {db_path}   rows: {len(all_rows)}")
    print()
    hdr = f"{'Class':6} {'Lessons':>7} {'Expected':>8} {'OK':>4} {'FP':>4} {'FN':>4} {'Boundary':>8} {'Format':>6} {'Title':>5}"
    print(hdr)
    print("-" * len(hdr))
    tot = defaultdict(int)
    for cls in ["Α΄", "Β΄", "Γ΄", "Δ΄", "Ε΄", "ΣΤ΄"]:
        c = per_class[cls]
        for k, v in c.items():
            tot[k] += v
        print(f"{cls:6} {c['lessons']:>7} {c['expected']:>8} {c['ok']:>4} {c['fp']:>4} {c['fn']:>4} {c['boundary']:>8} {c['format']:>6} {c['title']:>5}")
    print("-" * len(hdr))
    print(f"{'Total':6} {tot['lessons']:>7} {tot['expected']:>8} {tot['ok']:>4} {tot['fp']:>4} {tot['fn']:>4} {tot['boundary']:>8} {tot['format']:>6} {tot['title']:>5}")
    print(f"\nGlobal forbidden hits: {len(glob_hits)}")
    for s, rid in glob_hits:
        print(f"   {rid}: {s!r}")

    if verbose:
        for res in lesson_results:
            bad = res["fp"] or res["fn"] or res["boundary"] or res["format"] or res["title"]
            print(f"\n[{res['id']}] {'PASS' if not bad else 'FAIL'}   ok={res['ok']}")
            for t in res["fn"]:
                print(f"   FN       {t}")
            for t, why in res["boundary"]:
                print(f"   BOUNDARY {t}: {'; '.join(why)}")
            for t, why in res["format"]:
                print(f"   FORMAT   {t}: {'; '.join(why)}")
            for t, why in res["title"]:
                print(f"   TITLE    {'; '.join(why)}")
            for fp in res["fp"]:
                print(f"   FP       {fp[0]} p{fp[1]} [{fp[2]}] {fp[3]}")

    failed = tot["fp"] + tot["fn"] + tot["boundary"] + tot["format"] + tot["title"] + len(glob_hits)
    print(f"\nRESULT: {'PASS' if failed == 0 else 'FAIL'} ({tot['ok']}/{tot['expected']} expected passages exact)")
    return failed == 0


if __name__ == "__main__":
    argv = sys.argv[1:]
    gt_file = argv[argv.index("--gt") + 1] if "--gt" in argv else None
    args = [a for a in argv if not a.startswith("--") and a != gt_file]
    ok = score(args[0] if args else str(HERE.parent / "data" / "reading.db"), "--verbose" in argv, gt_file)
    sys.exit(0 if ok else 1)
