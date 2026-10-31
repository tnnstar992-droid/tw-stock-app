"""
build_wikilink_index.py — Regenerate WIKILINKS.md from all ticker reports.

Usage:
    python scripts/build_wikilink_index.py

This scans every .md file under Pilot_Reports/ and builds a categorized
index of all [[wikilinks]] with occurrence counts. Run after any enrichment
update to keep the index current.
"""

import os
import re
import sys

REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "Pilot_Reports")
OUTPUT_FILE = os.path.join(os.path.dirname(__file__), "..", "WIKILINKS.md")

# --- Classification sets ---

TECH_TERMS = {
    "AI", "PCB", "5G", "HBM", "CoWoS", "InFO", "EUV", "CPO", "FOPLP",
    "VCSEL", "EML", "MLCC", "MOSFET", "IGBT", "DRAM", "NAND", "SSD",
    "DDR5", "DDR4", "PCIe", "USB", "WiFi", "Bluetooth",
    "OLED", "AMOLED", "Mini LED", "Micro LED",
    "MCU", "SoC", "ASIC", "FPGA", "RF", "IC", "LED", "LCD", "TFT",
    "CMP", "CVD", "PVD", "ALD", "AOI", "SMT", "BGA", "QFN", "SOP",
    "ABF 載板", "BT 載板", "ABF", "SerDes", "PMIC", "LDO",
    "TSV", "RDL", "WLCSP", "FC-BGA", "FCCSP",
    "NOR Flash", "NAND Flash", "eMMC", "UFS",
    "MEMS", "CIS", "ToF", "LiDAR",
    "矽光子", "光收發模組",
    "磊晶", "蝕刻", "微影", "封裝測試", "晶圓代工",
    "2.5D 封裝", "3D 封裝",
}

MATERIAL_TERMS = {
    "碳化矽", "氮化鎵", "磷化銦", "砷化鎵", "矽晶圓",
    "銅箔", "玻纖布", "光阻液", "研磨液", "超純水",
    "氦氣", "氖氣", "鈦酸鋇", "聚醯亞胺",
    "導線架", "探針卡", "BT 樹脂", "銀漿", "銅漿", "氧化鋁",
}

APP_TERMS = {
    "AI 伺服器", "電動車", "物聯網", "資料中心", "低軌衛星",
    "智慧家庭", "車用電子", "消費電子", "綠能", "太陽能",
    "風電", "儲能系統", "離岸風電", "自動駕駛", "智慧城市",
    "行車記錄器", "無人機",
}


def is_cjk(s):
    """Check if string is predominantly CJK characters."""
    return sum(1 for c in s if "\u4e00" <= c <= "\u9fff") > len(s) * 0.3


def collect_wikilinks():
    """Scan all reports and return {name: count} dict."""
    wikilinks = {}
    for root, dirs, files in os.walk(REPORTS_DIR):
        for f in files:
            if not f.endswith(".md"):
                continue
            with open(os.path.join(root, f), "r", encoding="utf-8") as fh:
                content = fh.read()
            for wl in re.findall(r"\[\[([^\]]+)\]\]", content):
                wikilinks[wl] = wikilinks.get(wl, 0) + 1
    return wikilinks


def categorize(wikilinks):
    """Split wikilinks into categories."""
    technologies = {}
    materials = {}
    applications = {}
    companies_tw = {}
    companies_intl = {}

    for name, count in wikilinks.items():
        if name in TECH_TERMS:
            technologies[name] = count
        elif name in MATERIAL_TERMS:
            materials[name] = count
        elif name in APP_TERMS:
            applications[name] = count
        elif is_cjk(name) and count >= 2:
            companies_tw[name] = count
        elif not is_cjk(name) and count >= 2:
            companies_intl[name] = count
        # Single-mention entries are omitted from the index

    return technologies, materials, applications, companies_intl, companies_tw


def build_section(title, items, limit=None):
    """Build a markdown section from a dict."""
    lines = []
    sorted_items = sorted(items.items(), key=lambda x: -x[1])
    if limit:
        shown = sorted_items[:limit]
        total_label = f" ({len(items)} total, showing top {limit})"
    else:
        shown = sorted_items
        total_label = f" ({len(items)})"

    lines.append(f"## {title}{total_label}")
    lines.append("")
    for name, count in shown:
        lines.append(f"- [[{name}]] ({count})")
    lines.append("")
    return lines


def main():
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")

    wikilinks = collect_wikilinks()
    tech, mat, app, intl, tw = categorize(wikilinks)

    lines = [
        "# Wikilink Index",
        "",
        f"> **{len(wikilinks)} unique wikilinks** across 1,733 ticker reports. Auto-generated — do not edit manually.",
        f"> Regenerate: `python scripts/build_wikilink_index.py`",
        "",
        "---",
        "",
    ]

    lines.extend(build_section("Technologies & Standards", tech))
    lines.extend(build_section("Materials & Substrates", mat))
    lines.extend(build_section("Applications & End Markets", app))
    lines.extend(build_section("International Companies", intl, limit=200))
    lines.extend(build_section("Taiwan Companies", tw, limit=300))

    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))

    print(f"Generated WIKILINKS.md: {len(wikilinks)} unique wikilinks")
    print(f"  Technologies: {len(tech)}")
    print(f"  Materials: {len(mat)}")
    print(f"  Applications: {len(app)}")
    print(f"  International companies: {len(intl)}")
    print(f"  Taiwan companies: {len(tw)}")


if __name__ == "__main__":
    main()
