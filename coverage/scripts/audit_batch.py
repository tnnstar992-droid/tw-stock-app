"""
audit_batch.py — Quality audit for ticker reports.

Checks: wikilink count, generic wikilinks, placeholders, English text,
metadata completeness, section depth.

Usage:
  python scripts/audit_batch.py <batch_number> [-v]     Audit a single batch
  python scripts/audit_batch.py --all [-v]              Audit all completed batches
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import REPORTS_DIR, TASK_FILE, get_batch_tickers, setup_stdout

# --- Quality Rules (aligned with CLAUDE.md Golden Rules) ---

MIN_WIKILINKS = 8

GENERIC_WIKILINK_MARKERS = [
    "大廠", "供應商", "客戶", "廠商", "原廠", "經銷商",
    "製造商", "業者", "企業", "公司", "代理商", "品牌商",
    "營運商", "貿易商", "通路商", "零售商", "承包商",
    "開發商", "服務商", "整合商",
]

PLACEHOLDER_STRINGS = [
    "待 AI 補充",
    "待 [[AI]] 補充",
    "(待更新)",
    "基於嚴格實名制",
    "待enrichment",
]

REQUIRED_METADATA = ["板塊:", "產業:", "市值:", "企業價值:"]
REQUIRED_SECTIONS = ["## 業務簡介", "## 供應鏈位置", "## 主要客戶及供應商", "## 財務概況"]

ENGLISH_INDICATORS = [
    "Business Description", "Inc.", "Ltd.", "manufactures",
    "provides", "is a company", "headquartered", "was founded",
    "specializes in", "engages in", "operates through",
]


def extract_wikilinks(content):
    return re.findall(r"\[\[([^\]]+)\]\]", content)


def find_generic_wikilinks(wikilinks):
    generic = []
    for wl in wikilinks:
        for marker in GENERIC_WIKILINK_MARKERS:
            if marker in wl:
                generic.append(wl)
                break
    return generic


def check_metadata(content):
    issues = []
    for field in REQUIRED_METADATA:
        if field not in content:
            issues.append(f"Missing metadata: {field}")
        else:
            for line in content.split("\n"):
                if field in line:
                    after_field = line.split(field, 1)[1].strip()
                    if not after_field or "(待更新)" in line:
                        issues.append(f"Empty metadata: {field}")
                    break
    return issues


def check_sections(content):
    return [s for s in REQUIRED_SECTIONS if s not in content]


def check_section_depth(content):
    issues = []
    sc_match = re.search(
        r"## 供應鏈位置\n(.*?)(?=\n## 主要客戶及供應商|\Z)", content, re.DOTALL
    )
    if sc_match:
        sc_lines = [l for l in sc_match.group(1).strip().split("\n") if l.strip()]
        if len(sc_lines) < 3:
            issues.append(f"Supply chain too thin ({len(sc_lines)} lines)")

    cs_match = re.search(
        r"## 主要客戶及供應商\n(.*?)(?=\n## 財務概況|\Z)", content, re.DOTALL
    )
    if cs_match:
        cs_lines = [l for l in cs_match.group(1).strip().split("\n") if l.strip()]
        if len(cs_lines) < 4:
            issues.append(f"Customers/suppliers too thin ({len(cs_lines)} lines)")

    return issues


def check_english(content):
    for line in content.split("\n")[:20]:
        if "**" in line or ":" in line:
            continue
        for indicator in ENGLISH_INDICATORS:
            if indicator in line:
                return indicator
    return None


def audit_ticker(content):
    """Run all quality checks. Returns (is_clean, issues_list)."""
    issues = []

    if len(content) < 200:
        issues.append("Content too short (<200 chars)")
        return False, issues

    for ph in PLACEHOLDER_STRINGS:
        if ph in content:
            issues.append(f"Placeholder found: '{ph}'")

    eng = check_english(content)
    if eng:
        issues.append(f"English text detected: '{eng}'")

    for ms in check_sections(content):
        issues.append(f"Missing section: {ms}")

    issues.extend(check_metadata(content))

    wikilinks = extract_wikilinks(content)
    if len(wikilinks) < MIN_WIKILINKS:
        issues.append(f"Only {len(wikilinks)} wikilinks (minimum {MIN_WIKILINKS})")

    generic = find_generic_wikilinks(wikilinks)
    if generic:
        issues.append(f"Generic wikilinks ({len(generic)}): {generic}")

    issues.extend(check_section_depth(content))

    return len(issues) == 0, issues


def find_batch_files(tickers):
    """Find files for a list of tickers."""
    found = {}
    for root, dirs, files in os.walk(REPORTS_DIR):
        for file in files:
            if file.endswith(".md"):
                match = re.match(r"^(\d{4})", file)
                if match and match.group(1) in tickers:
                    found[match.group(1)] = os.path.join(root, file)
    return found


def audit_batch(batch_num, verbose=False):
    tickers = get_batch_tickers(batch_num)
    if not tickers:
        return

    print(f"QUALITY AUDIT: Checking {len(tickers)} tickers in Batch {batch_num}...")
    print(f"Rules: min {MIN_WIKILINKS} wikilinks, no generics, no placeholders, no English")
    print("=" * 60)

    clean, enrichment, quality_fix, missing = [], [], [], []
    found = find_batch_files(tickers)

    for ticker in tickers:
        if ticker not in found:
            missing.append(ticker)
            continue

        try:
            with open(found[ticker], "r", encoding="utf-8") as f:
                content = f.read()

            is_clean, issues = audit_ticker(content)

            if is_clean:
                clean.append(ticker)
                if verbose:
                    wl_count = len(extract_wikilinks(content))
                    print(f"  {ticker}: CLEAN ({wl_count} wikilinks)")
            else:
                has_placeholder = any(ph in content for ph in PLACEHOLDER_STRINGS)
                has_english = check_english(content) is not None
                is_short = len(content) < 200

                if has_placeholder or has_english or is_short:
                    enrichment.append(ticker)
                    cat = "NEEDS ENRICHMENT"
                else:
                    quality_fix.append(ticker)
                    cat = "NEEDS QUALITY FIX"

                if verbose:
                    print(f"  {ticker}: {cat}")
                    for issue in issues:
                        print(f"    - {issue}")

        except Exception as e:
            print(f"Error reading {found[ticker]}: {e}")
            enrichment.append(ticker)

    print("=" * 60)
    print(f"CLEAN ({len(clean)}): {clean}")
    print(f"NEEDS ENRICHMENT ({len(enrichment)}): {enrichment}")
    if quality_fix:
        print(f"NEEDS QUALITY FIX ({len(quality_fix)}): {quality_fix}")
    print(f"MISSING ({len(missing)}): {missing}")

    total = len(tickers)
    pct = len(clean) / total * 100 if total > 0 else 0
    print(f"\nScore: {len(clean)}/{total} ({pct:.0f}%) pass quality audit")


def audit_all_completed(verbose=False):
    """Audit all batches marked [x] in task.md."""
    try:
        with open(TASK_FILE, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading task.md: {e}")
        return

    completed = re.findall(r"\[x\]\s*\*\*Batch\s+(\d+)\*\*", content)
    if not completed:
        print("No completed batches found in task.md")
        return

    print(f"Auditing {len(completed)} completed batches: {', '.join(completed)}")
    print("=" * 60)

    total_clean = total_tickers = 0
    all_issues = []

    for batch_num in completed:
        tickers = get_batch_tickers(batch_num)
        if not tickers:
            continue

        found = find_batch_files(tickers)
        batch_issues = []

        for ticker in tickers:
            if ticker not in found:
                continue
            try:
                with open(found[ticker], "r", encoding="utf-8") as f:
                    file_content = f.read()
                is_clean, issues = audit_ticker(file_content)
                total_tickers += 1
                if is_clean:
                    total_clean += 1
                else:
                    batch_issues.append((ticker, issues))
            except Exception:
                pass

        if batch_issues:
            print(f"\nBatch {batch_num}: {len(batch_issues)} tickers need quality fixes")
            if verbose:
                for ticker, issues in batch_issues:
                    print(f"  {ticker}:")
                    for issue in issues:
                        print(f"    - {issue}")
            all_issues.extend(batch_issues)

    print("\n" + "=" * 60)
    pct = total_clean / total_tickers * 100 if total_tickers > 0 else 0
    print(f"OVERALL: {total_clean}/{total_tickers} ({pct:.0f}%) pass quality audit")
    print(f"Total tickers needing quality fix: {len(all_issues)}")


if __name__ == "__main__":
    setup_stdout()

    if len(sys.argv) < 2:
        print("Usage:")
        print("  python scripts/audit_batch.py <batch_number> [-v]")
        print("  python scripts/audit_batch.py --all [-v]")
        sys.exit(1)

    verbose = "-v" in sys.argv

    if sys.argv[1] == "--all":
        audit_all_completed(verbose)
    else:
        audit_batch(sys.argv[1], verbose)
