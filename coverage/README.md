# Taiwan Stock Coverage Database

A structured equity research database covering **1,735 Taiwan-listed companies** (TWSE + OTC) across **99 industry sectors**. Each report contains a business overview, supply chain mapping, customer/supplier relationships, and financial data — all cross-referenced through **4,900+ wikilinks** that form a searchable knowledge graph.

## Why This Exists

Taiwan's stock market has 1,800+ listed companies, many of which are critical nodes in global supply chains (semiconductors, electronics, automotive, textiles). Public information is fragmented across Chinese-language filings, investor presentations, and industry reports. This database consolidates that research into a consistent, searchable format.

**The wikilink graph is the core feature.** Searching `[[Apple]]` reveals 207 Taiwanese companies in Apple's supply chain. Searching `[[CoWoS]]` shows every company involved in TSMC's advanced packaging. Searching `[[光阻液]]` (photoresist) maps every supplier and consumer of that material.

## Quick Start

### Prerequisites

```bash
pip install yfinance pandas tabulate
```

### Browse Reports

Reports are markdown files organized by industry:

```
Pilot_Reports/
├── Semiconductors/           (155 tickers)
│   ├── 2330_台積電.md        # TSMC
│   ├── 2454_聯發科.md        # MediaTek
│   └── ...
├── Electronic Components/    (267 tickers)
├── Computer Hardware/        (114 tickers)
└── ... (99 sector folders)
```

Each report follows a consistent structure:

```markdown
# 2330 - [[台積電]]

## 業務簡介
**板塊:** Technology
**產業:** Semiconductors
**市值:** 47,326,857 百萬台幣
**企業價值:** 44,978,990 百萬台幣

[Traditional Chinese business description with [[wikilinks]]...]

## 供應鏈位置
**上游:** [[ASML]], [[Applied Materials]], [[SUMCO]]...
**中游:** **台積電** (晶圓代工)
**下游:** [[Apple]], [[NVIDIA]], [[AMD]], [[Broadcom]]...

## 主要客戶及供應商
### 主要客戶
- [[Apple]], [[NVIDIA]], [[AMD]], [[Qualcomm]]...
### 主要供應商
- [[ASML]], [[Tokyo Electron]], [[Shin-Etsu]]...

## 財務概況
### 估值指標
| P/E (TTM) | Forward P/E | P/S (TTM) | P/B | EV/EBITDA |
[Valuation multiples from yfinance]

### 年度/季度財務數據
[Annual (3yr) and Quarterly (4Q) financial tables with 14 metrics]
```

### Add a New Ticker

```bash
python scripts/add_ticker.py 2330 台積電
python scripts/add_ticker.py 2330 台積電 --sector Semiconductors
```

### Update Financial Data

```bash
python scripts/update_financials.py 2330                        # Single ticker
python scripts/update_financials.py 2330 2454 3034              # Multiple tickers
python scripts/update_financials.py --batch 101                 # By batch
python scripts/update_financials.py --sector Semiconductors     # By sector
python scripts/update_financials.py                             # ALL tickers
```

### Update Valuation Only (Fast)

Refreshes only the 估值指標 table (P/E, Forward P/E, P/S, P/B, EV/EBITDA, stock price) without re-fetching full financial statements. ~3x faster than `update_financials`.

```bash
python scripts/update_valuation.py 2330                         # Single ticker
python scripts/update_valuation.py --batch 101                  # By batch
python scripts/update_valuation.py --sector Semiconductors      # By sector
python scripts/update_valuation.py                              # ALL tickers
```

### Update Enrichment Content

Prepare a JSON file with enrichment data, then apply:

```bash
python scripts/update_enrichment.py --data enrichment.json 2330
python scripts/update_enrichment.py --data enrichment.json --batch 101
python scripts/update_enrichment.py --data enrichment.json --sector Semiconductors
```

JSON format:

```json
{
  "2330": {
    "desc": "台積電為全球最大晶圓代工廠，專注於 [[CoWoS]]、[[3奈米]] 先進製程...",
    "supply_chain": "**上游:**\n- [[ASML]]...\n**中游:**\n- **台積電**...\n**下游:**\n- [[Apple]]...",
    "cust": "### 主要客戶\n- [[Apple]]...\n\n### 主要供應商\n- [[ASML]]..."
  }
}
```

### Audit Quality

```bash
python scripts/audit_batch.py 101 -v      # Single batch
python scripts/audit_batch.py --all -v    # All batches
```

The audit checks: minimum 8 wikilinks, no generic terms in brackets, no placeholders, no English text, metadata completeness, and section depth.

### Rebuild Wikilink Index

```bash
python scripts/build_wikilink_index.py
```

Regenerates [WIKILINKS.md](WIKILINKS.md) — a browsable index of all 4,900+ wikilinks categorized by type (Technologies, Materials, Applications, Companies). Run after any enrichment update.

### Discover Companies by Buzzword

Hear a buzzword on the news? Find every related Taiwan-listed company instantly.

```bash
python scripts/discover.py "液冷散熱"                    # Search all sectors
python scripts/discover.py "液冷散熱" --smart            # Auto-detect relevant sectors
python scripts/discover.py "液冷散熱" --apply            # Tag [[wikilinks]] in reports
python scripts/discover.py "液冷散熱" --apply --rebuild  # Also rebuild themes + network
python scripts/discover.py "液冷散熱" --sector Semiconductors  # Limit to specific sector
```

Results show companies grouped by relationship type (core business, supply chain, customer/supplier) with context snippets. Use `--smart` to auto-filter irrelevant sectors (tech buzzwords skip banks/insurance/real estate).

### Generate Wikilink Network Graph

Interactive D3.js force-directed graph showing wikilink co-occurrences across all tickers. Hover to highlight neighbors, search by name, adjust edge weight threshold.

```bash
python scripts/build_network.py                    # Default: min 5 co-occurrences
python scripts/build_network.py --min-weight 10    # Fewer edges, cleaner view
python scripts/build_network.py --top 200          # Only top 200 nodes
```

Open `network/index.html` in your browser. Node colors: red = Taiwan company, blue = international, green = technology, orange = material, purple = application.

### Generate Thematic Investment Screens

```bash
python scripts/build_themes.py               # Build all 20 themes
python scripts/build_themes.py "CoWoS"       # Single theme
python scripts/build_themes.py --list        # List available themes
```

Generates [themes/](themes/) — supply chain maps for key investment themes. Each page shows companies grouped by upstream/midstream/downstream role. See [themes/README.md](themes/README.md) for the full index.

## Token Usage & Cost Guide

Tools fall into two categories: **Python scripts** (free, run locally) and **Claude Code skills** (consume API tokens for AI research).

### Free — Python Scripts (No Tokens)

These run 100% locally with Python + yfinance. No AI, no API cost.

| Script | Command | What it does |
|---|---|---|
| Update Financials | `python scripts/update_financials.py [scope]` | Refresh financial tables from yfinance |
| Update Valuation | `python scripts/update_valuation.py [scope]` | Refresh P/E, P/B, EV/EBITDA only (fast) |
| Update Enrichment | `python scripts/update_enrichment.py --data <json> [scope]` | Apply pre-prepared enrichment data |
| Audit | `python scripts/audit_batch.py <batch> -v` | Quality check reports |
| Discover (search) | `python scripts/discover.py "<buzzword>"` | Scan reports for keyword matches |
| Build Themes | `python scripts/build_themes.py` | Generate thematic supply chain pages |
| Build Network | `python scripts/build_network.py` | Generate interactive D3.js graph |
| Build Wikilink Index | `python scripts/build_wikilink_index.py` | Rebuild WIKILINKS.md |

### Consumes Tokens — Claude Code Skills (Requires AI)

These use Claude AI for web research, content generation, and intelligent enrichment. They require [Claude Code](https://claude.ai/claude-code) and consume API tokens.

| Slash Command | Token Usage | What it does |
|---|---|---|
| `/add-ticker 2330 台積電` | Medium | Generate .md + fetch financials + **AI researches** business desc, supply chain, customers |
| `/update-enrichment 2330` | Medium | **AI re-researches** and rewrites business content (preserves financials) |
| `/discover 液冷散熱` | Low-High | Scans database (free) → if no results, **AI researches** online and enriches reports |

**Token cost drivers:**
- `/add-ticker`: ~1 web search + content generation per ticker
- `/update-enrichment`: ~3-5 web searches + content synthesis per ticker
- `/discover` with results: **zero tokens** (Python scan only)
- `/discover` without results: varies by research depth (web searches + file edits)

**Tip:** For bulk operations, use Python scripts directly. Use slash commands for individual tickers or when AI research is needed.

## Wikilink Graph

Browse the full index: **[WIKILINKS.md](WIKILINKS.md)**

The database contains **4,900+ unique wikilinks** across three categories:

| Category | Examples | Purpose |
|---|---|---|
| **Companies** | `[[台積電]]`, `[[Apple]]`, `[[Bosch]]` | Map supply chain relationships |
| **Technologies** | `[[CoWoS]]`, `[[HBM]]`, `[[矽光子]]`, `[[EUV]]` | Find all companies in a technology ecosystem |
| **Materials** | `[[光阻液]]`, `[[碳化矽]]`, `[[ABF 載板]]` | Track material suppliers and consumers |

### Top Referenced Entities

| Entity | Mentions | What it reveals |
|---|---|---|
| `[[台積電]]` | 469 | Taiwan's semiconductor ecosystem revolves around TSMC |
| `[[NVIDIA]]` | 277 | AI supply chain — who makes NVIDIA's components |
| `[[Apple]]` | 207 | Apple's Taiwanese supplier network |
| `[[AI 伺服器]]` | 237 | AI server supply chain mapping |
| `[[電動車]]` | 223 | EV component suppliers |
| `[[5G]]` | 232 | 5G infrastructure companies |
| `[[PCB]]` | 263 | Printed circuit board ecosystem |

## Project Structure

```
├── CLAUDE.md                  # Project rules and quality standards
├── WIKILINKS.md               # Browsable wikilink index (auto-generated)
├── task.md                    # Batch definitions and progress tracking
├── requirements.txt           # Python dependencies
├── README.md
├── scripts/
│   ├── utils.py               # Shared utilities (file discovery, wikilink normalization)
│   ├── add_ticker.py          # Generate new ticker reports
│   ├── update_financials.py   # Refresh financial tables + valuation multiples
│   ├── update_enrichment.py   # Update business descriptions from JSON
│   ├── audit_batch.py         # Quality auditing
│   ├── update_valuation.py     # Refresh valuation multiples only (fast)
│   ├── discover.py            # Reverse search: buzzword → related companies
│   ├── build_wikilink_index.py # Rebuild WIKILINKS.md index
│   ├── build_themes.py        # Generate thematic investment screens
│   ├── build_network.py       # Generate interactive network graph
│   └── generators/            # Historical base report generators
├── Pilot_Reports/             # 1,735 ticker reports across 99 sectors
│   ├── Semiconductors/
│   ├── Electronic Components/
│   └── ... (99 folders)
├── network/                   # Interactive wikilink network graph (auto-generated)
│   ├── index.html             # D3.js visualization (open in browser)
│   └── graph_data.json        # Raw graph data (339 nodes, 1,452 edges)
├── themes/                    # Thematic investment screens (auto-generated)
│   ├── README.md              # Theme index
│   ├── CoWoS.md               # 39 companies in CoWoS supply chain
│   ├── AI_伺服器.md            # 148 companies in AI server ecosystem
│   ├── NVIDIA.md              # 104 companies in NVIDIA supply chain
│   └── ... (20 themes)
└── .claude/
    └── skills/                # Claude Code skill definitions
```

## Quality Standards

Every report is validated against 8 quality rules (defined in `CLAUDE.md`):

1. **Wikilinks must be specific proper nouns** — no generic terms like 供應商 or 大廠
2. **Ticker-company identity verification** — filename is ground truth
3. **Minimum 8 wikilinks per report**
4. **Financial tables preserved** — never modified during enrichment
5. **All content in Traditional Chinese**
6. **No placeholders** in completed reports
7. **Complete metadata** (sector, industry, market cap, enterprise value)
8. **Segmented supply chain** — upstream/midstream/downstream by category

Current audit score: **1,733/1,733 (100%)** pass all quality checks.

## Data Sources

- **Financial data**: [yfinance](https://github.com/ranaroussi/yfinance) (Yahoo Finance Taiwan)
- **Business content**: Company IR pages, MOPS filings (公開資訊觀測站), investor conference transcripts (法說會), annual reports (年報)
- **Supply chain data**: Industry reports, news sources, company disclosures

## Limitations

- Financial data depends on yfinance availability — some OTC stocks may have gaps
- Business descriptions reflect research as of the enrichment date — they don't auto-update
- Wikilinks are manually curated — new technologies or companies need manual addition
- Content is in Traditional Chinese — English speakers will need translation

## Wikilink Naming Convention

| Category | Canonical form | Examples |
|---|---|---|
| Taiwan companies | Chinese | `[[台積電]]`, `[[鴻海]]`, `[[聯發科]]` |
| Foreign companies | English | `[[NVIDIA]]`, `[[Samsung]]`, `[[Micron]]` |
| Materials/substrates | Chinese | `[[碳化矽]]`, `[[氮化鎵]]`, `[[電動車]]` |
| Industry acronyms | Acronym | `[[PCB]]`, `[[CPO]]`, `[[HBM]]`, `[[CoWoS]]` |

Wikilink normalization is built into the enrichment pipeline — aliases are automatically merged to canonical form on every write.

## Contributing

Contributions are welcome. When adding or updating ticker reports:

1. Follow the quality rules in `CLAUDE.md`
2. Run `python scripts/audit_batch.py --all -v` before submitting
3. Ensure every `[[wikilink]]` is a specific proper noun
4. Verify the company name matches the ticker number

## License

MIT License. See [LICENSE](LICENSE) for details.

Financial data sourced from Yahoo Finance via yfinance. Business descriptions are original research.
