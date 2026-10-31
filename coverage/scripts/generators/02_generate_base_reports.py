import pandas as pd
import yfinance as yf
import os
import time

def generate_report(ticker, name):
    print(f"Processing {ticker} ({name})...")
    try:
        stock = yf.Ticker(f"{ticker}.TW")
        info = stock.info
        
        # Retry with .TWO if .TW fails (common for OTC stocks)
        if not info or 'longName' not in info:
            print(f"Retrying {ticker} with .TWO suffix...")
            stock = yf.Ticker(f"{ticker}.TWO")
            info = stock.info

        if not info or 'longName' not in info:
             print(f"Failed to fetch data for {ticker} (tried .TW and .TWO)")
             return None
        
        # Basic Info
        sector = info.get('sector', 'N/A')
        industry = info.get('industry', 'N/A')
        # Keep English summary for now, will be translated by AI later
        business_summary = info.get('longBusinessSummary', 'No description available.')
        
        # Valuation (Million NTD)
        market_cap = info.get('marketCap', 0) / 1_000_000 if info.get('marketCap') else 'N/A'
        enterprise_value = info.get('enterpriseValue', 0) / 1_000_000 if info.get('enterpriseValue') else 'N/A'
        
        # Helper to safely get series
        def get_series(df, keys):
            for key in keys:
                if key in df.index:
                    return df.loc[key]
            return pd.Series(dtype=float)

        # Calculate Margins (%)
        def calc_margin(numerator, denominator):
            if denominator.empty or numerator.empty:
                return pd.Series(dtype=float)
            return (numerator / denominator) * 100

        def extract_metrics(income_stmt, cashflow):
            if income_stmt.empty and cashflow.empty:
                 return pd.DataFrame()

            revenue = get_series(income_stmt, ['Total Revenue'])
            gross_profit = get_series(income_stmt, ['Gross Profit'])
            selling_exp = get_series(income_stmt, ['Selling And Marketing Expense'])
            admin_exp = get_series(income_stmt, ['General And Administrative Expense'])
            operating_income = get_series(income_stmt, ['Operating Income'])
            net_income = get_series(income_stmt, ['Net Income', 'Net Income Common Stockholders'])
            
            ocf = get_series(cashflow, ['Operating Cash Flow', 'Total Cash From Operating Activities'])
            icf = get_series(cashflow, ['Investing Cash Flow', 'Total Cashflows From Investing Activities'])
            fcf_act = get_series(cashflow, ['Financing Cash Flow', 'Total Cash From Financing Activities'])
            capex = get_series(cashflow, ['Capital Expenditure', 'Capital Expenditures'])

            gp_margin = calc_margin(gross_profit, revenue)
            op_margin = calc_margin(operating_income, revenue)
            ni_margin = calc_margin(net_income, revenue)

            data = {
                'Revenue': revenue,
                'Gross Profit': gross_profit,
                'Gross Margin (%)': gp_margin,
                'Selling & Marketing Exp': selling_exp,
                'General & Admin Exp': admin_exp,
                'Operating Income': operating_income,
                'Operating Margin (%)': op_margin,
                'Net Income': net_income,
                'Net Margin (%)': ni_margin,
                'Op Cash Flow': ocf,
                'Investing Cash Flow': icf,
                'Financing Cash Flow': fcf_act,
                'CAPEX': capex
            }
            return pd.DataFrame(data).T

        # Annual Data
        df_annual = extract_metrics(stock.income_stmt, stock.cashflow)
        if not df_annual.empty:
            cols_to_scale = [c for c in df_annual.index if '%' not in c]
            df_annual.loc[cols_to_scale] = df_annual.loc[cols_to_scale] / 1_000_000
            df_annual = df_annual.iloc[:, :3] # Last 3 years

        # Quarterly Data
        df_quarterly = extract_metrics(stock.quarterly_income_stmt, stock.quarterly_cashflow)
        if not df_quarterly.empty:
            cols_to_scale = [c for c in df_quarterly.index if '%' not in c]
            df_quarterly.loc[cols_to_scale] = df_quarterly.loc[cols_to_scale] / 1_000_000
            df_quarterly = df_quarterly.iloc[:, :4] # Last 4 provided quarters

        # Markdown Content
        md_content = f"""# {ticker} - {name}

## 業務簡介
**板塊:** {sector}
**產業:** {industry}
**市值:** {f'{market_cap:,.0f}' if isinstance(market_cap, (int, float)) else market_cap} 百萬台幣
**企業價值:** {f'{enterprise_value:,.0f}' if isinstance(enterprise_value, (int, float)) else enterprise_value} 百萬台幣

{business_summary}

## 供應鏈位置
*(待 AI 補充)*

## 主要客戶及供應商
*(待 AI 補充)*

## 財務概況 (單位: 百萬台幣, 只有 Margin 為 %)
### 年度關鍵財務數據 (近 3 年)
"""
        if not df_annual.empty:
            md_content += df_annual.to_markdown(floatfmt=".2f") + "\n\n"
        else:
            md_content += "無可用數據。\n\n"

        md_content += "### 季度關鍵財務數據 (近 4 季)\n"
        if not df_quarterly.empty:
             md_content += df_quarterly.to_markdown(floatfmt=".2f") + "\n\n"
        else:
            md_content += "無可用數據。\n\n"
            
        return md_content

    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return None

import argparse

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ticker", type=str, help="Generate report for a specific ticker only")
    parser.add_argument("--name", type=str, help="Specify company name for the report (optional)")
    args = parser.parse_args()

    excel_path = 'f:/My TW Coverage/Taiwan Stock Coverage.xlsx'
    exception_path = 'f:/My TW Coverage/Taiwan Stock Exception.xlsx'
    output_dir = 'f:/My TW Coverage/Pilot_Reports'
    # batch_size = 20 # Process all
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    try:
        # Load Exception List
        excluded_tickers = []
        if os.path.exists(exception_path):
            try:
                # Assuming ticker is in the first column (index 0)
                ex_df = pd.read_excel(exception_path, header=None)
                excluded_tickers = ex_df[0].astype(str).str.strip().tolist()
                print(f"Loaded {len(excluded_tickers)} excluded tickers.")
            except Exception as e:
                print(f"Warning: Failed to read exception list: {e}")
        
        df = pd.read_excel(excel_path, header=None)
        
        # Process All or Single
        batch_df = df # Default to all
        
        if args.ticker:
            target_ticker = str(args.ticker).strip()
            
            # Check Exception List
            if target_ticker in excluded_tickers:
                print(f"Skipping {target_ticker} (In Exception List)")
                return

            # Filter for specific ticker (ensure string comparison)
            batch_df = df[df[0].astype(str).str.strip() == target_ticker]
            if batch_df.empty:
                name_to_use = args.name if args.name else "Unknown"
                print(f"Warning: Ticker {args.ticker} not found in Excel. Processing with name '{name_to_use}'.")
                # Create a 1-row DataFrame manually if not found in Excel
                batch_df = pd.DataFrame([[args.ticker, name_to_use]], columns=[0, 1])
            elif args.name:
                 # Override name if provided
                 batch_df.iloc[0, 1] = args.name
        
        for index, row in batch_df.iterrows():
            ticker = str(row[0]).strip()
            name = str(row[1]).strip() if pd.notna(row[1]) else "Unknown"
            
            # Check if finalized report already exists (preserve work if needed)
            safe_name = name.replace("*", "").replace("/", "").replace("\\", "").replace(":", "").replace("?", "").replace("\"", "").replace("<", "").replace(">", "").replace("|", "")
            filename = f"{ticker}_{safe_name}.md"
            # Note: We rely on generate_report to print where it's saving or we might need to search for it if we want to return the path.
            # But the existing logic saves to `output_dir/filename`.
            filepath = os.path.join(output_dir, filename)

            if os.path.exists(filepath):
                 print(f"Skipping {filename} (Already exists)")
                 # If user specifically asked for this ticker, maybe they want to overwrite? 
                 # For now, stick to safe "Skip". User can delete file if they want regeneration.
                 continue

            report = generate_report(ticker, name)
            
            if report:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(report)
                print(f"Report generated: {filename}")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"Critical Error: {e}")

if __name__ == "__main__":
    main()
