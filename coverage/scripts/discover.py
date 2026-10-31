"""
discover.py — Reverse discovery: find companies related to a buzzword.

User hears a buzzword (e.g., 液冷散熱, 核融合, CPO) and wants to know which
Taiwan-listed companies are connected. The script:

1. Searches all relevant ticker reports for mentions of the buzzword
2. Wikilinks the buzzword where it appears but isn't yet tagged
3. Reports which companies are related and how
4. Optionally updates themes and network

Usage:
  python scripts/discover.py "液冷散熱"                    # Search ALL sectors (recommended)
  python scripts/discover.py "液冷散熱" --apply            # Apply wikilinks to files
  python scripts/discover.py "液冷散熱" --apply --rebuild  # Also rebuild themes + network
  python scripts/discover.py "液冷散熱" --smart            # Auto-filter sectors (faster but may miss)
  python scripts/discover.py "液冷散熱" --sector Semiconductors  # Limit to one sector
  python scripts/discover.py "液冷散熱" --sectors "Semiconductors,Electronic Components"

Sector filtering:
  Tech buzzwords skip: Banks, Insurance, Real Estate, Food, Textile, etc.
  Use --smart to auto-filter, or --sector/--sectors to specify manually.
"""

import os
import re
import sys
import subprocess
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils import REPORTS_DIR, PROJECT_ROOT, setup_stdout

# Sector groups for smart filtering
TECH_SECTORS = {
    "Semiconductors", "Semiconductor Equipment & Materials",
    "Electronic Components", "Computer Hardware", "Communication Equipment",
    "Consumer Electronics", "Software (Application)", "Software (Infrastructure)",
    "Electronics & Computer Distribution", "Information Technology Services",
    "Scientific & Technical Instruments",
}

INDUSTRIAL_SECTORS = {
    "Specialty Industrial Machinery", "Industrial Distribution",
    "Metal Fabrication", "Electrical Equipment & Parts",
    "Pollution & Treatment Controls", "Conglomerates",
    "Engineering & Construction", "Building Products & Equipment",
    "Tools & Accessories", "Auto Parts", "Aerospace & Defense",
}

MATERIALS_SECTORS = {
    "Chemicals", "Specialty Chemicals", "Steel", "Aluminum",
    "Copper", "Other Industrial Metals & Mining",
}

ENERGY_SECTORS = {
    "Solar", "Utilities - Renewable", "Utilities - Regulated Electric",
    "Oil & Gas Equipment & Services",
}

CONSUMER_SECTORS = {
    "Footwear & Accessories", "Textile Manufacturing",
    "Household & Personal Products", "Packaging & Containers",
    "Furnishings, Fixtures & Appliances", "Leisure",
    "Restaurants", "Grocery Stores", "Specialty Retail",
}

FINANCE_SECTORS = {
    "Banks - Diversified", "Banks - Regional", "Insurance - Life",
    "Insurance - Property & Casualty", "Capital Markets",
    "Financial - Credit Services", "Financial Conglomerates",
}

REAL_ESTATE_SECTORS = {
    "Real Estate - Development", "Real Estate - Diversified",
    "REIT - Diversified",
}

# Smart sector mapping: buzzword category -> which sector groups to search
SMART_PROFILES = {
    "tech": TECH_SECTORS | INDUSTRIAL_SECTORS | MATERIALS_SECTORS,
    "energy": TECH_SECTORS | INDUSTRIAL_SECTORS | ENERGY_SECTORS | MATERIALS_SECTORS,
    "consumer": CONSUMER_SECTORS | TECH_SECTORS,
    "all": None,  # None = search everything
}

# Buzzword hints for smart detection
TECH_KEYWORDS = [
    "半導體", "晶片", "IC", "AI", "伺服器", "封裝", "製程", "光電",
    "通訊", "5G", "衛星", "記憶體", "電池", "充電", "散熱", "矽",
    "雷射", "光纖", "感測", "量子", "ASIC", "GPU", "HBM", "PCB",
    "LED", "OLED", "EUV", "SiC", "GaN", "MEMS", "RF", "CPO",
]

ENERGY_KEYWORDS = [
    "能源", "電力", "風電", "太陽能", "儲能", "氫能", "核", "碳",
    "綠電", "充電", "電網",
]


def detect_profile(buzzword):
    """Auto-detect which sector profile to use based on buzzword content."""
    for kw in TECH_KEYWORDS:
        if kw in buzzword:
            return "tech"
    for kw in ENERGY_KEYWORDS:
        if kw in buzzword:
            return "energy"
    return "all"


def search_reports(buzzword, sectors_filter=None):
    """Search all reports for mentions of the buzzword.
    Returns list of {ticker, company, sector, filepath, linked, context}.
    """
    results = []

    for sector_dir in sorted(os.listdir(REPORTS_DIR)):
        sector_path = os.path.join(REPORTS_DIR, sector_dir)
        if not os.path.isdir(sector_path):
            continue

        # Apply sector filter
        if sectors_filter and sector_dir not in sectors_filter:
            continue

        for f in sorted(os.listdir(sector_path)):
            if not f.endswith(".md"):
                continue
            m = re.match(r"^(\d{4})_(.+)\.md$", f)
            if not m:
                continue

            ticker, company = m.group(1), m.group(2)
            filepath = os.path.join(sector_path, f)

            with open(filepath, "r", encoding="utf-8") as fh:
                content = fh.read()

            # Only search before 財務概況
            text = content.split("## 財務概況")[0] if "## 財務概況" in content else content

            # Check for linked mentions [[buzzword]]
            linked_count = len(re.findall(r"\[\[" + re.escape(buzzword) + r"\]\]", text))

            # Check for bare mentions (not inside [[ ]])
            bare_pattern = r"(?<!\[\[)" + re.escape(buzzword) + r"(?!\]\])"
            bare_matches = list(re.finditer(bare_pattern, text))
            bare_count = len(bare_matches)

            if linked_count > 0 or bare_count > 0:
                # Extract context snippets for bare mentions
                contexts = []
                for match in bare_matches[:3]:  # Max 3 snippets
                    start = max(0, match.start() - 30)
                    end = min(len(text), match.end() + 30)
                    snippet = text[start:end].replace("\n", " ").strip()
                    contexts.append(f"...{snippet}...")

                # Determine relationship from section
                role = "mentioned"
                for section_name, role_name in [
                    ("## 業務簡介", "core_business"),
                    ("## 供應鏈位置", "supply_chain"),
                    ("## 主要客戶及供應商", "customer_supplier"),
                ]:
                    section_match = re.search(
                        rf"{section_name}\n(.*?)(?=\n## |\Z)", text, re.DOTALL
                    )
                    if section_match and buzzword in section_match.group(1):
                        role = role_name
                        break

                results.append({
                    "ticker": ticker,
                    "company": company,
                    "sector": sector_dir,
                    "filepath": filepath,
                    "linked": linked_count,
                    "bare": bare_count,
                    "role": role,
                    "contexts": contexts,
                })

    return results


def apply_wikilinks(results, buzzword):
    """Add [[buzzword]] wikilinks to files where it's mentioned but not linked."""
    applied = 0
    for r in results:
        if r["bare"] == 0:
            continue

        with open(r["filepath"], "r", encoding="utf-8") as f:
            content = f.read()

        # Split to protect financial tables
        parts = content.split("## 財務概況")
        if len(parts) < 2:
            continue

        text = parts[0]
        # Replace bare mentions with wikilinked version
        # Be careful not to double-link
        pattern = r"(?<!\[\[)" + re.escape(buzzword) + r"(?!\]\])(?![A-Za-z\u4e00-\u9fff])"
        new_text, count = re.subn(pattern, f"[[{buzzword}]]", text)

        if count > 0:
            content = new_text + "## 財務概況" + parts[1]
            with open(r["filepath"], "w", encoding="utf-8") as f:
                f.write(content)
            applied += count

    return applied


def print_report(results, buzzword):
    """Print discovery results in a readable format."""
    if not results:
        print(f"\n找不到任何提及「{buzzword}」的公司。")
        return

    # Group by role
    by_role = defaultdict(list)
    for r in results:
        by_role[r["role"]].append(r)

    print(f"\n{'=' * 60}")
    print(f"「{buzzword}」關聯公司：共 {len(results)} 家")
    print(f"{'=' * 60}")

    role_labels = {
        "core_business": "核心業務相關",
        "supply_chain": "供應鏈相關",
        "customer_supplier": "客戶/供應商相關",
        "mentioned": "其他提及",
    }

    for role, label in role_labels.items():
        entries = by_role.get(role, [])
        if not entries:
            continue
        print(f"\n### {label} ({len(entries)})")
        for r in sorted(entries, key=lambda x: x["ticker"]):
            link_status = "✓" if r["linked"] > 0 else "○"
            bare_note = f" (+{r['bare']} 未標記)" if r["bare"] > 0 else ""
            print(f"  {link_status} {r['ticker']} {r['company']} ({r['sector']}){bare_note}")
            for ctx in r["contexts"][:1]:  # Show 1 context snippet
                print(f"    → {ctx}")


def main():
    setup_stdout()

    if len(sys.argv) < 2:
        print("Usage:")
        print('  python scripts/discover.py "液冷散熱"                  # Search all')
        print('  python scripts/discover.py "液冷散熱" --smart          # Auto-filter sectors')
        print('  python scripts/discover.py "液冷散熱" --sector Semiconductors')
        print('  python scripts/discover.py "液冷散熱" --apply          # Apply wikilinks')
        print('  python scripts/discover.py "液冷散熱" --apply --rebuild # + rebuild themes/network')
        sys.exit(1)

    buzzword = sys.argv[1]
    args = sys.argv[2:]

    # Parse flags
    do_apply = "--apply" in args
    do_rebuild = "--rebuild" in args
    smart = "--smart" in args

    # Parse sector filter
    sectors_filter = None
    if "--sector" in args:
        idx = args.index("--sector")
        if idx + 1 < len(args):
            sectors_filter = {args[idx + 1]}
    elif "--sectors" in args:
        idx = args.index("--sectors")
        if idx + 1 < len(args):
            sectors_filter = set(s.strip() for s in args[idx + 1].split(","))
    elif smart:
        profile = detect_profile(buzzword)
        sectors_filter = SMART_PROFILES[profile]
        if sectors_filter:
            print(f"Smart mode: detected profile '{profile}', searching {len(sectors_filter)} sectors")
            print(f"  ⚠ May miss cross-sector results. Use without --smart for full coverage.")

    # Search
    print(f"搜尋「{buzzword}」...")
    results = search_reports(buzzword, sectors_filter)

    # Report
    print_report(results, buzzword)

    # Apply wikilinks
    if do_apply and results:
        bare_count = sum(r["bare"] for r in results)
        if bare_count > 0:
            applied = apply_wikilinks(results, buzzword)
            print(f"\n已將 {applied} 處「{buzzword}」加上 [[wikilink]] 標記。")
        else:
            print(f"\n所有提及均已標記為 [[{buzzword}]]。")

    # Rebuild themes and network
    if do_rebuild:
        print("\n重建主題頁面...")
        subprocess.run(
            [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "build_themes.py")],
            cwd=PROJECT_ROOT,
        )
        print("重建網路圖...")
        subprocess.run(
            [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "build_network.py")],
            cwd=PROJECT_ROOT,
        )
        print("重建 wikilink 索引...")
        subprocess.run(
            [sys.executable, os.path.join(PROJECT_ROOT, "scripts", "build_wikilink_index.py")],
            cwd=PROJECT_ROOT,
        )

    # Summary
    linked = sum(1 for r in results if r["linked"] > 0)
    unlinked = sum(1 for r in results if r["bare"] > 0 and r["linked"] == 0)
    print(f"\n總結：{len(results)} 家公司提及「{buzzword}」")
    print(f"  已標記：{linked} | 未標記：{unlinked}")


if __name__ == "__main__":
    main()
