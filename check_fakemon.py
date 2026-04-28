#!/usr/bin/env python3
"""
check_fakemon.py
────────────────
All-in-one Fakemon submission checker. Combines scan, sanitize, and
fakemonlist rebuild into a single tool.

Checks performed on every .json file:
  • Forbidden content (profanity, slurs, sexual, drugs, self-harm)
  • Political content  — flags but does NOT auto-sanitize
  • Bullying language  — flags but does NOT auto-sanitize
  • ID / filename mismatch — case-sensitive exact match required;
    near-misses (case difference, extra/missing chars) get a specific warning
  • Fakemonlist rebuild (--rebuild flag)

Usage:
    python check_fakemon.py                      # scan only, dry-run report
    python check_fakemon.py --apply              # scan + sanitize forbidden content
    python check_fakemon.py --rebuild            # also rebuild fakemonlist.json
    python check_fakemon.py --dir path/to/fakemon
    python check_fakemon.py --out report.md

Exit codes:
    0 — nothing flagged
    1 — at least one file flagged
    2 — usage / directory error
"""

import re
import os
import sys
import json
import glob
import difflib
import argparse
from datetime import datetime
from pathlib import Path


# ═════════════════════════════════════════════════════════════════════════════
#  PATTERN LISTS
# ═════════════════════════════════════════════════════════════════════════════

# Each entry: (category_label, compiled_regex, auto_sanitize)
# auto_sanitize=True  → replaced with ? on --apply
# auto_sanitize=False → reported only (teacher reviews)

PATTERNS = []

def add(category, auto_sanitize, *patterns):
    for p in patterns:
        PATTERNS.append((category, re.compile(p, re.IGNORECASE), auto_sanitize))

# ── Profanity (auto-sanitize) ──────────────────────────────────────────────
add("Profanity", True,
    r"\bass(?:es|hole)?\b",
    r"\bbitch(?:es)?\b",
    r"\bbastard\b",
    r"\bcrap\b",
    r"\bdamn\b",
    r"\bdick\b",
    r"f+u+c+k+",
    r"sh[i1!]+t+",
    r"\bpiss\b",
    r"\bpussy\b",
    r"\bcunt\b",
    r"\bslut\b",
    r"\bwhore\b",
    r"\bcock\b",
    r"\bwtf\b",
    r"\bstfu\b",
    r"\bomfg\b",
)

# ── Slurs (auto-sanitize) ──────────────────────────────────────────────────
add("Slur", True,
    r"\bnigger\b",
    r"\bnigga\b",
    r"\bfaggot\b",
    r"\bretard\b",
    r"\bdyke\b",
    r"\bkike\b",
    r"\bspic\b",
    r"\bwetback\b",
    r"\bchink\b",
    r"\bgook\b",
    r"\bcoon\b",
)

# ── Sexual / pornographic (auto-sanitize) ─────────────────────────────────
add("Sexual/Pornographic", True,
    r"\bporn\b",
    r"\bxxx\b",
    r"\bnudes?\b",
    r"\bsex\b",
    r"\bsexual\b",
    r"\berotic\b",
    r"\bfetish\b",
    r"\bboobs?\b",
    r"\bpenis\b",
    r"\bvagina\b",
    r"\bmasturbat\w*",
    r"\borgasm\b",
    r"\bhentai\b",
    r"\bnsfw\b",
    r"\bnaked\b",
    r"\bstriptease\b",
    r"\bintercourse\b",
)

# ── Self-harm / crisis (auto-sanitize) ────────────────────────────────────
add("Self-Harm/Crisis", True,
    r"\bsuicide\b",
    r"\bself-?harm\b",
    r"\bkill\s+myself\b",
    r"\bslit\s+(?:my\s+)?wrist",
    r"\bhang\s+myself\b",
)

# ── Drug references (auto-sanitize) ───────────────────────────────────────
add("Drugs", True,
    r"\bweed\b",
    r"\bmarijuana\b",
    r"\bcocaine\b",
    r"\bheroin\b",
    r"\bmeth\b",
    r"\bcrack\b",
    r"\bget\s+high\b",
    r"\bstoned\b",
    r"\bblazed\b",
)

# ── Flag emojis / nationalism (auto-sanitize) ─────────────────────────────
add("Flag/Nationalism", True,
    r"[\U0001F1E6-\U0001F1FF]{2}",
    r"\b(?:american|british|chinese|russian|german|french|mexican|"
    r"canadian|japanese|korean|israeli|palestinian|ukrainian|iranian|"
    r"north\s*korean|cuban)\s*flag\b",
    r":flag_[a-z_]+:",
)

# ── Political — REVIEW ONLY (do not auto-sanitize) ────────────────────────
#
# This list is intentionally broad: anything that might spark political
# debate in a middle-school classroom is flagged for teacher review.
# It does NOT include swear words (those are in Profanity above).
#
add("Political", False,
    # US politicians & parties
    r"\btrump\b",
    r"\bbiden\b",
    r"\bobama\b",
    r"\bclinton\b",
    r"\bbush\b",
    r"\breagan\b",
    r"\bbernie\b",
    r"\bsanders\b",
    r"\bpelosi\b",
    r"\bmcconnell\b",
    r"\bdesantis\b",
    r"\brepublican\b",
    r"\bdemocrat\b",
    r"\bgop\b",
    r"\bmaga\b",
    r"\bantifa\b",
    r"\bblm\b",
    # Ideologies & systems
    r"\bliberal\b",
    r"\bconservative\b",
    r"\bsocialist\b",
    r"\bsocialism\b",
    r"\bcommunist\b",
    r"\bcommunism\b",
    r"\bfascist\b",
    r"\bfascism\b",
    r"\bnazi\b",
    r"\bmarxist\b",
    r"\bcapitalist\b",
    r"\banarchist\b",
    # Hot-button issues
    r"\babortion\b",
    r"\bpro-?life\b",
    r"\bpro-?choice\b",
    r"\bgun\s+control\b",
    r"\bgun\s+rights\b",
    r"\bimmigration\b",
    r"\bdeportation\b",
    r"\bborder\s+wall\b",
    r"\binsurrection\b",
    r"\bpropaganda\b",
    r"\belection\s+(?:fraud|steal|rigg)",
    r"\bvaccine\s+(?:mandate|choice|refusal)\b",
    r"\bmandatory\s+vaccine\b",
    # Countries that are common political flashpoints
    r"\brussia\b",
    r"\bchina\b",
    r"\bnorth\s*korea\b",
    r"\biran\b",
    r"\bisrael\b",
    r"\bpalestine\b",
    r"\bpalestinian\b",
    r"\bukraine\b",
    r"\btaiwan\b",
    r"\bcuba\b",
    r"\bvenezuela\b",
    # Political offices (context-independent flag)
    r"\bpresident\b",
    r"\bcongressm(?:an|en|woman|women)\b",
    r"\bsenator\b",
    r"\bgovernor\b",
    r"\bprime\s+minister\b",
    r"\bdictator\b",
)

# ── Bullying language — REVIEW ONLY (do not auto-sanitize) ────────────────
#
# Words that are often benign on their own but frequently appear in
# submissions targeting specific classmates. Teacher reviews in context.
#
add("Bullying/Targeting", False,
    r"\bstinky\b",
    r"\bsmelly\b",
    r"\bstinks\b",
    r"\bdumb\b",
    r"\bdumbass\b",      # also caught by Profanity but listed here for clarity
    r"\bstupid\b",
    r"\bidiot\b",
    r"\bloser\b",
    r"\blosers\b",
    r"\blame\b",
    r"\bnerd\b",
    r"\bgeek\b",
    r"\bfreak\b",
    r"\bugly\b",
    r"\bfat\b",
    r"\bskinny\b",
    r"\bweak\b",
    r"\bpathetic\b",
    r"\buseless\b",
    r"\bworthless\b",
    r"\bcry(?:baby|babies)\b",
    r"\bbaby\b",
    r"\bpunk\b",
    r"\bwimp\b",
    r"\bpushy\b",
    r"\bbully\b",
    r"\bbullied\b",
    r"\bbullying\b",
    r"\bhate\s+you\b",
    r"\byou\s+suck\b",
    r"\bget\s+(?:lost|rekt|owned|wrecked)\b",
    r"\bkill\s+you\b",
    r"\bgo\s+away\b",
    r"\bnobody\s+likes\b",
    r"\beveryone\s+hates\b",
)


# ═════════════════════════════════════════════════════════════════════════════
#  ID / FILENAME CHECKER
# ═════════════════════════════════════════════════════════════════════════════

def check_id_filename(filepath):
    issues = []
    stem = os.path.splitext(os.path.basename(filepath))[0]

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            raw = f.read()
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        issues.append(("ID/Filename", f"Could not parse JSON to check id field: {e}"))
        return issues
    except OSError:
        return issues

    fid = data.get("id")

    if fid is None:
        issues.append(("ID/Filename", 'Missing "id" field — cannot verify filename match'))
        return issues

    if not isinstance(fid, str):
        issues.append(("ID/Filename", f'"id" field is not a string (got {type(fid).__name__})'))
        return issues

    if fid == stem:
        return []

    if fid.lower() == stem.lower():
        issues.append((
            "ID/Filename",
            f'Case mismatch — filename is "{stem}.json" but id is "{fid}". '
            f'Did you mean id: "{stem}"?  (IDs are case-sensitive)'
        ))
        return issues

    ratio = difflib.SequenceMatcher(None, fid, stem).ratio()
    if ratio >= 0.80:
        issues.append((
            "ID/Filename",
            f'Near-miss — filename is "{stem}.json" but id is "{fid}" '
            f'({int(ratio*100)}% similar). Did you mean id: "{stem}"?'
        ))
        return issues

    issues.append((
        "ID/Filename",
        f'Mismatch — filename is "{stem}.json" but id is "{fid}". '
        f'The "id" field must exactly match the filename (case-sensitive).'
    ))
    return issues


# ═════════════════════════════════════════════════════════════════════════════
#  SCANNER
# ═════════════════════════════════════════════════════════════════════════════

def scan_file(filepath):
    findings = []

    for category, message in check_id_filename(filepath):
        findings.append((0, category, message, "", False))

    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
    except OSError as e:
        findings.append(("ERR", "File Read Error", str(e), "", False))
        return findings

    for lineno, line in enumerate(lines, start=1):
        seen_on_this_line = set()
        for category, pattern, auto_sanitize in PATTERNS:
            for match in pattern.finditer(line):
                key = (lineno, match.group(0).lower(), category)
                if key not in seen_on_this_line:
                    seen_on_this_line.add(key)
                    findings.append((
                        lineno, category, match.group(0),
                        line.rstrip(), auto_sanitize
                    ))

    return findings


def scan_all(fakemon_dir):
    """Scans all *.json files (excluding fakemonlist.json)."""
    pattern   = os.path.join(fakemon_dir, "**", "*.json")
    all_files = sorted(
        f for f in glob.glob(pattern, recursive=True)
        if os.path.basename(f) != "fakemonlist.json"
    )

    top_pattern = os.path.join(fakemon_dir, "*.json")
    top_files   = sorted(
        f for f in glob.glob(top_pattern)
        if os.path.basename(f) != "fakemonlist.json"
    )
    all_files = sorted(set(all_files + top_files))

    if not all_files:
        print(f"[check_fakemon] No .json files found in: {fakemon_dir}")
        return all_files, {}

    print(f"[check_fakemon] Scanning {len(all_files)} file(s) in '{fakemon_dir}' …\n")

    flagged = {}
    for filepath in all_files:
        findings = scan_file(filepath)
        name     = os.path.basename(filepath)
        if findings:
            flagged[filepath] = findings
            count = len(findings)
            print(f"  ⚠  FLAGGED  {name}  ({count} hit(s))")
        else:
            print(f"  ✓  clean    {name}")

    return all_files, flagged


# ═════════════════════════════════════════════════════════════════════════════
#  SANITIZER  (only rewrites auto_sanitize=True hits)
# ═════════════════════════════════════════════════════════════════════════════

def replacement_for(matched_text):
    return "?" * len(matched_text)


def sanitize_text(text):
    hits = []
    for category, pattern, auto_sanitize in PATTERNS:
        if not auto_sanitize:
            continue
        for m in pattern.finditer(text):
            hits.append((m.start(), m.end(), category, m.group(0)))

    if not hits:
        return text, []

    hits.sort(key=lambda h: h[0], reverse=True)

    deduped   = []
    occupied  = set()
    for start, end, category, matched in hits:
        span = range(start, end)
        if not any(i in occupied for i in span):
            deduped.append((start, end, category, matched))
            occupied.update(span)

    result = list(text)
    changes = []
    for start, end, category, matched in deduped:
        result[start:end] = list(replacement_for(matched))
        changes.append((category, matched, start))

    return "".join(result), changes


def sanitize_file(filepath, apply=False):
    try:
        with open(filepath, "r", encoding="utf-8", errors="replace") as f:
            original = f.read()
    except OSError as e:
        print(f"  ERROR reading {filepath}: {e}")
        return False, []

    sanitized, changes = sanitize_text(original)

    if not changes:
        return False, []

    if apply:
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(sanitized)
        except OSError as e:
            print(f"  ERROR writing {filepath}: {e}")
            return False, changes

    return True, changes


def sanitize_all(fakemon_dir, apply=False):
    pattern   = os.path.join(fakemon_dir, "*.json")
    all_files = sorted(
        f for f in glob.glob(pattern)
        if os.path.basename(f) != "fakemonlist.json"
    )

    if not all_files:
        return

    mode = "APPLYING CHANGES" if apply else "DRY RUN (no files written)"
    print(f"\n[check_fakemon] SANITIZE — {mode}")

    total_files_changed = 0
    total_replacements  = 0

    for filepath in all_files:
        name = os.path.basename(filepath)
        changed, changes = sanitize_file(filepath, apply=apply)
        if not changed:
            print(f"  ✓  no sanitize changes  {name}")
        else:
            total_files_changed += 1
            total_replacements  += len(changes)
            action = "WROTE" if apply else "WOULD CHANGE"
            print(f"  ⚠  {action}  {name}  ({len(changes)} replacement(s))")
            for category, matched, pos in sorted(changes, key=lambda c: c[2]):
                print(f"       [{category}]  '{matched}'  @ char {pos}")

    print(f"\n[check_fakemon] Sanitize summary: {total_files_changed} file(s) affected, "
          f"{total_replacements} replacement(s) total.")
    if not apply and total_files_changed > 0:
        print("\n[check_fakemon] DRY RUN — to write changes, run with --apply")


# ═════════════════════════════════════════════════════════════════════════════
#  FAKEMONLIST REBUILDER
# ═════════════════════════════════════════════════════════════════════════════

def rebuild_fakemonlist(fakemon_dir):
    """
    Rebuilds fakemonlist.json from all *.json files in fakemon/json/,
    falling back to top-level fakemon_dir if json/ subdir doesn't exist.
    Always runs automatically (not gated behind --rebuild).
    """
    json_subdir = os.path.join(fakemon_dir, "json")
    if os.path.isdir(json_subdir):
        source_dir = json_subdir
    else:
        source_dir = fakemon_dir

    files = sorted(
        os.path.splitext(os.path.basename(f))[0]
        for f in glob.glob(os.path.join(source_dir, "*.json"))
        if os.path.basename(f) != "fakemonlist.json"
    )

    output_path = os.path.join(fakemon_dir, "fakemonlist.json")
    payload     = json.dumps({"fakemon": files}, indent=2)

    with open(output_path, "w", encoding="utf-8") as fh:
        fh.write(payload)

    print(f"\n[check_fakemon] Rebuilt fakemonlist.json — {len(files)} entry/entries:")
    for name in files:
        print(f"  {name}")


# ═════════════════════════════════════════════════════════════════════════════
#  REPORT WRITER
# ═════════════════════════════════════════════════════════════════════════════

_CATEGORY_EMOJI = {
    "Profanity":          "🤬",
    "Slur":               "🚫",
    "Sexual/Pornographic":"🔞",
    "Self-Harm/Crisis":   "🆘",
    "Drugs":              "💊",
    "Flag/Nationalism":   "🚩",
    "Political":          "🗳️",
    "Bullying/Targeting": "😠",
    "ID/Filename":        "📛",
}

def _category_label(cat):
    emoji = _CATEGORY_EMOJI.get(cat, "⚠️")
    return f"{emoji} {cat}"

def _sanitize_note(auto_sanitize):
    if auto_sanitize:
        return "AUTO-SANITIZE"
    return "REVIEW ONLY"

# Categories that are purely structural — no content concern
_SYNTAX_ONLY_CATS = {"ID/Filename", "ERR"}

def _is_syntax_only(findings):
    return all(cat in _SYNTAX_ONLY_CATS for _, cat, _, _, _ in findings)

def _render_file_block(lines, filepath, findings):
    filename = os.path.basename(filepath)
    lines.append(f"### 🚩 `{filename}`\n")
    lines.append(f"**{len(findings)} issue(s)**\n")
    lines.append("| Line | Category | Action | Matched / Message | Full Line |")
    lines.append("|------|----------|--------|-------------------|-----------|")
    for lineno, category, matched, content, auto_sanitize in findings:
        line_display = str(lineno) if lineno > 0 else "—"
        safe_matched = matched.replace("|", "\\|")
        safe_content = content.strip().replace("|", "\\|")
        if len(safe_content) > 120:
            safe_content = safe_content[:117] + "…"
        action    = _sanitize_note(auto_sanitize)
        cat_label = _category_label(category)
        lines.append(
            f"| {line_display} | {cat_label} | {action} | `{safe_matched}` | `{safe_content}` |"
        )
    lines.append("")


def write_report(flagged, total_scanned, output_path="flagged_files.md"):
    now   = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lines = []

    lines.append("# Fakemon Content Check Report")
    lines.append(f"\n**Generated:** {now}  ")
    lines.append(f"**Files scanned:** {total_scanned}  ")
    lines.append(f"**Files flagged:** {len(flagged)}  ")
    lines.append("\n---\n")

    if not flagged:
        lines.append("✅ **No issues found.** All files passed the content check.")
    else:
        # Summary of category types present
        review_only_cats = set()
        auto_cats        = set()
        for findings in flagged.values():
            for lineno, category, matched, content, auto_sanitize in findings:
                if auto_sanitize:
                    auto_cats.add(category)
                else:
                    review_only_cats.add(category)

        lines.append("> ⚠️ **Issues found.** Review each file below.\n>")
        if auto_cats:
            lines.append(f"> 🔧 **AUTO-SANITIZE** categories (replaced with `?` on `--apply`): "
                         f"{', '.join(sorted(auto_cats))}")
        if review_only_cats:
            lines.append(f"> 👀 **REVIEW ONLY** categories (teacher must decide): "
                         f"{', '.join(sorted(review_only_cats))}")
        lines.append(">")
        lines.append("> To auto-sanitize eligible content, run:")
        lines.append("> ```")
        lines.append("> python check_fakemon.py --apply")
        lines.append("> ```\n")

        # ── Split into two buckets ────────────────────────────────────────
        concerning  = {fp: f for fp, f in flagged.items() if not _is_syntax_only(f)}
        syntax_only = {fp: f for fp, f in flagged.items() if     _is_syntax_only(f)}

        # ── Bucket 1: content concerns (bullying, political, profanity…) ─
        if concerning:
            lines.append("## ⚠️ Needs Teacher Review — Content Flags\n")
            for filepath, findings in concerning.items():
                _render_file_block(lines, filepath, findings)

        # ── Bucket 2: structural / syntax errors only ─────────────────────
        if syntax_only:
            if concerning:
                lines.append("\n---\n")
            lines.append("## 🔧 Syntax / ID Errors Only\n")
            for filepath, findings in syntax_only.items():
                _render_file_block(lines, filepath, findings)

    report_text = "\n".join(lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(report_text)

    print(f"\n[check_fakemon] Report written → {output_path}")


# ═════════════════════════════════════════════════════════════════════════════
#  MAIN
# ═════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(
        description=(
            "check_fakemon.py — scan, sanitize, and validate Fakemon JSON files.\n"
            "Combines scan_fakemon.py + sanitize_fakemon.py + clean_fakemonlist.py."
        )
    )
    parser.add_argument(
        "--dir", default="fakemon",
        help="Path to the fakemon folder (default: ./fakemon)"
    )
    parser.add_argument(
        "--out", default="flagged_files.md",
        help="Output report file path (default: flagged_files.md)"
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="Replace auto-sanitize hits with ? characters (default: dry-run)"
    )
    args = parser.parse_args()

    if not os.path.isdir(args.dir):
        print(f"ERROR: Directory not found: '{args.dir}'")
        sys.exit(2)

    # ── Step 1: Scan ──────────────────────────────────────────────────────
    all_files, flagged = scan_all(args.dir)

    # ── Step 2: Sanitize (if --apply) ────────────────────────────────────
    if args.apply:
        sanitize_all(args.dir, apply=True)
        # Re-scan after sanitizing so the report reflects the cleaned state
        print("\n[check_fakemon] Re-scanning after sanitize…")
        all_files, flagged = scan_all(args.dir)
    else:
        sanitize_all(args.dir, apply=False)

    # ── Step 3: Always rebuild fakemonlist.json ───────────────────────────
    rebuild_fakemonlist(args.dir)

    # ── Step 4: Write report ──────────────────────────────────────────────
    write_report(flagged, total_scanned=len(all_files), output_path=args.out)

    # ── Summary ───────────────────────────────────────────────────────────
    if flagged:
        review_needed = any(
            not auto
            for findings in flagged.values()
            for _, _, _, _, auto in findings
        )
        print(f"\n[check_fakemon] ⚠  {len(flagged)} file(s) flagged. See {args.out}")
        if review_needed:
            print("[check_fakemon] 👀  Some flags require TEACHER REVIEW (Political / Bullying / ID mismatch).")
        sys.exit(1)
    else:
        print("\n[check_fakemon] ✅ All files clean.")
        sys.exit(0)


if __name__ == "__main__":
    main()