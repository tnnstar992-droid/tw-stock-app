import pandas as pd
import yfinance as yf
import os
import time

def generate_report(ticker, name):
    print(f"Processing {ticker} ({name})...")
    try:
        stock = yf.Ticker(f"{ticker}.TW")
        info = stock.info
        
        # Basic Info
        sector = info.get('sector', 'N/A')
        industry = info.get('industry', 'N/A')
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
            # Alignment is automatic by index (date)
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
**市值:** {market_cap:,.0f} 百萬台幣
**企業價值:** {enterprise_value:,.0f} 百萬台幣

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

def main():
    excel_path = 'f:/My TW Coverage/Taiwan Stock Coverage.xlsx'
    output_dir = 'f:/My TW Coverage/Pilot_Reports'
    
    if not os.path.exists(output_dir):
        os.makedirs(output_dir)
        
    try:
        df = pd.read_excel(excel_path, header=None)
        sample_df = df.head(5)
        
        for index, row in sample_df.iterrows():
            ticker = str(row[0]).strip()
            name = str(row[1]).strip() if pd.notna(row[1]) else "Unknown"
            
            report = generate_report(ticker, name)
            
            if report:
                filename = f"{ticker}_{name}.md".replace("/", "_")
                with open(os.path.join(output_dir, filename), "w", encoding="utf-8") as f:
                    # Check if previous file had Enrichment
                    if os.path.exists(os.path.join(output_dir, filename)):
                         with open(os.path.join(output_dir, filename), "r", encoding="utf-8") as old_f:
                             old_content = old_f.read()
                             if "## 供應鏈位置\n**" in old_content: 
                                 try:
                                     # Extract Enrichment Block (Supply -> Customers -> before Financials)
                                     supply_idx = old_content.find("## 供應鏈位置")
                                     fin_idx = old_content.find("## 財務概況")
                                     
                                     if supply_idx != -1 and fin_idx != -1:
                                         enrichment_block = old_content[supply_idx:fin_idx]
                                         
                                         # Replace the placeholder block in the new report
                                         placeholder = """## 供應鏈位置
*(待 AI 補充)*

## 主要客戶及供應商
*(待 AI 補充)*
"""
                                         # Strip newlines for safer replacement match if needed, but let's try exact
                                         if placeholder.strip() in report.strip(): # Loose matching
                                             report = report.replace(placeholder, enrichment_block)
                                         else:
                                             # Fallback: Regex or direct construct if placeholder slightly differs
                                             # Let's try direct construction in generate_report to ensure consistent placeholder
                                             pass 
                                         
                                         # Second attempt if valid keys found
                                         if "*(待 AI 補充)*" in report and enrichment_block:
                                              # Force replace the whole section
                                             report_parts = report.split("## 財務概況")
                                             report_head = report_parts[0]
                                             report_tail = "## 財務概況" + report_parts[1]
                                             
                                             # Find where Supply begins in head
                                             head_split = report_head.split("## 供應鏈位置")
                                             if len(head_split) > 1:
                                                 report = head_split[0] + enrichment_block + report_tail
                                                 print(f"   [Preserved AI Enrichment for {ticker}]")

                                 except Exception as e:
                                     print(f"   [Failed to preserve AI Enrichment for {ticker}: {e}]")

                    f.write(report)
                print(f"Report saved: {filename}")
            
            time.sleep(1)
            
    except Exception as e:
        print(f"Critical Error: {e}")

if __name__ == "__main__":
    main()
