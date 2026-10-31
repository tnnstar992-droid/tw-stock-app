---
name: discover
description: Reverse discovery — find Taiwan-listed companies related to a buzzword, with web research fallback when no results exist in the database
user_invocable: true
---

# Discover Companies by Buzzword

Find every Taiwan-listed company related to a keyword, technology, or trend. Two modes:

1. **Database search** — instant scan of all 1,733 reports for existing mentions
2. **Web research fallback** — when no results found, research online and enrich the database

## Usage

- `/discover 液冷散熱` — find all companies mentioning liquid cooling
- `/discover 核融合` — find companies related to nuclear fusion
- `/discover CoWoS` — find the CoWoS supply chain
- `/discover 鈣鈦礦` — find perovskite solar cell players

## Instructions

### Step 1: Database Search

Run the discover script to scan existing reports:

```bash
cd "f:\My TW Coverage" && python scripts/discover.py "<BUZZWORD>"
```

Report the results to the user: how many companies found, grouped by relationship type.

### Step 2: If Results Found

Ask the user:
- "是否要將未標記的提及加上 [[wikilink]]？" (Apply wikilinks?)
- If yes, run: `python scripts/discover.py "<BUZZWORD>" --apply --rebuild`
- Report how many wikilinks were added and which files were updated.

### Step 3: If NO Results Found (Web Research Fallback)

This is the key differentiator. When the database has zero mentions:

1. **Research the buzzword** using web search:
   - Search: `"<BUZZWORD>" 台灣 上市 供應鏈 概念股`
   - Search: `"<BUZZWORD>" Taiwan listed company supply chain`
   - Search: `"<BUZZWORD>" 台股 相關個股`

2. **Identify companies** from search results. For each company found:
   - Verify it exists in our database (match ticker or company name to a file in Pilot_Reports/)
   - Note the relationship: supplier, manufacturer, customer, technology developer, etc.

3. **Present findings** to the user in a structured format:
   ```
   Web 研究結果：「<BUZZWORD>」相關台灣上市櫃公司

   已在資料庫中：
   - XXXX 公司名 (Sector) — 關係描述
   - YYYY 公司名 (Sector) — 關係描述

   不在資料庫中：
   - ZZZZ 公司名 — 需要新增 ticker
   ```

4. **Ask the user** which companies to update:
   - "是否要將這些公司的報告加入「<BUZZWORD>」相關描述？"
   - If yes, for each confirmed company:
     a. Read the existing ticker .md file
     b. Add the buzzword as a [[wikilink]] in the relevant section (業務簡介 or 供應鏈位置)
     c. Preserve all existing content — only ADD, don't rewrite
     d. Run wikilink normalization after writing

5. **Rebuild indexes** after all updates:
   ```bash
   cd "f:\My TW Coverage" && python scripts/discover.py "<BUZZWORD>" --rebuild
   ```

### Step 4: Offer to Create Theme

If the buzzword has 5+ related companies, offer:
- "「<BUZZWORD>」有 N 家相關公司，是否要建立主題投資頁？"
- If yes, add the buzzword to `THEME_DEFINITIONS` in `scripts/build_themes.py` and rebuild.

## Quality Rules (from CLAUDE.md)

- The buzzword MUST be a specific proper noun or named technology — not a generic term
- When editing ticker files, follow ALL Golden Rules (wikilink standards, no generic terms, etc.)
- VERIFY company identity matches filename before editing
- Preserve financial tables (財務概況) — never modify them
- Run `python scripts/audit_batch.py --all` after bulk edits to verify no quality regressions
