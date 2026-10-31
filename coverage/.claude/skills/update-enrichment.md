---
name: update-enrichment
description: Update business descriptions, supply chain, and customer/supplier sections for ticker reports
user_invocable: true
---

# Update Enrichment

Re-research and update the enrichment content (業務簡介, 供應鏈位置, 主要客戶及供應商) for existing ticker reports. Financial tables are preserved.

## Usage

- `/update-enrichment 2330` — single ticker
- `/update-enrichment 2330 2317 3034` — multiple tickers
- `/update-enrichment --batch 101` — all tickers in a batch
- `/update-enrichment --sector Semiconductors` — entire sector folder
- `/update-enrichment` — all tickers (will ask for confirmation first)

## Instructions

### Step 1: Identify targets

Parse the user's scope from their message. If scope is "all" or very large (>50 tickers), ask for confirmation.

### Step 2: Research

For each ticker in scope:
1. Read the current file to understand existing content
2. Web search: `[Ticker] 法說會`, `[Ticker] 年報 主要客戶`, `[Company] supplier customer`
3. **VERIFY**: company name in filename matches research (Golden Rule #2)
4. Prepare enrichment with:
   - `desc`: Traditional Chinese business description with [[wikilinks]] for companies, technologies, and materials
   - `supply_chain`: Segmented upstream/midstream/downstream with specific names
   - `cust`: Customers and suppliers by business segment with specific names

### Step 3: Apply

Write enrichment data as a JSON file, then run:

```bash
cd "f:\My TW Coverage" && python scripts/update_enrichment.py --data enrichment.json [scope]
```

Scope options: `2330`, `2330 2317`, `--batch 101`, `--sector Semiconductors`, or omit for all entries in JSON.

### Step 4: Audit

```bash
python scripts/audit_batch.py <batch> -v
```

Verify all targets pass (8+ wikilinks, no generics, no placeholders, no English).

### Quality Rules (from CLAUDE.md)

- Every `[[wikilink]]` must be a specific proper noun
- Minimum 8 wikilinks per file
- Technology/material wikilinks equally important: `[[CoWoS]]`, `[[HBM]]`, `[[光阻液]]`, `[[碳化矽]]`
- NO generic words inside brackets: 供應商, 客戶, 大廠, 企業
- All content in Traditional Chinese
- Supply chain must be segmented by category, not single-line stubs
