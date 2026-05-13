import yfinance as yf
import pandas as pd

def calculate_dcf(ticker_symbol, discount_rate=0.09, terminal_growth_rate=0.02, growth_rate_5yr=0.05):
    """
    Calculates the intrinsic value of a stock using a basic 5-year DCF model.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        
        # Get financial info
        info = ticker.info
        cashflow = ticker.cashflow
        
        if cashflow.empty:
            return {"error": "No cashflow data available"}
            
        # Get Free Cash Flow (FCF)
        # yfinance cashflow statements sometimes have 'Free Cash Flow' or we calculate it
        if 'Free Cash Flow' in cashflow.index:
            recent_fcf = cashflow.loc['Free Cash Flow'].iloc[0]
        elif 'Operating Cash Flow' in cashflow.index and 'Capital Expenditure' in cashflow.index:
            recent_fcf = cashflow.loc['Operating Cash Flow'].iloc[0] + cashflow.loc['Capital Expenditure'].iloc[0] # CapEx is usually negative
        else:
            return {"error": "Could not find FCF components"}

        # Shares Outstanding
        shares_outstanding = info.get('sharesOutstanding')
        if not shares_outstanding:
            return {"error": "Shares outstanding not found"}
            
        # Current Price
        current_price = info.get('currentPrice', info.get('regularMarketPrice'))
        if not current_price:
            return {"error": "Current price not found"}

        # Project 5 years of FCF
        projected_fcf = []
        current_projected = recent_fcf
        for i in range(5):
            current_projected *= (1 + growth_rate_5yr)
            projected_fcf.append(current_projected)
            
        # Discount the projected FCF
        discounted_fcf = []
        for i, fcf in enumerate(projected_fcf):
            discounted = fcf / ((1 + discount_rate) ** (i + 1))
            discounted_fcf.append(discounted)
            
        # Terminal Value
        terminal_value = (projected_fcf[-1] * (1 + terminal_growth_rate)) / (discount_rate - terminal_growth_rate)
        discounted_terminal_value = terminal_value / ((1 + discount_rate) ** 5)
        
        # Total Intrinsic Value
        total_enterprise_value = sum(discounted_fcf) + discounted_terminal_value
        
        # We simplify Enterprise Value -> Equity Value by assuming debt/cash cancels or using simple model
        # True Equity Value = EV + Cash - Total Debt
        total_cash = info.get('totalCash', 0)
        total_debt = info.get('totalDebt', 0)
        equity_value = total_enterprise_value + total_cash - total_debt
        
        intrinsic_value_per_share = equity_value / shares_outstanding
        
        upside = ((intrinsic_value_per_share - current_price) / current_price) * 100
        
        return {
            "symbol": ticker_symbol,
            "current_price": current_price,
            "intrinsic_value": round(intrinsic_value_per_share, 2),
            "upside_percent": round(upside, 2),
            "is_undervalued": upside > 0
        }
        
    except Exception as e:
        return {"error": str(e)}

def analyze_relative_valuation(ticker_symbol):
    """
    Compares the P/E ratio of a company against its industry.
    Uses a calculated market average based on sector data when available.
    """
    try:
        ticker = yf.Ticker(ticker_symbol)
        info = ticker.info
        
        pe_ratio = info.get('trailingPE')
        forward_pe = info.get('forwardPE')
        industry = info.get('industry', 'Unknown')
        
        try:
            sector = info.get('sector', '')
            sector_pe_map = {
                'Technology': 30.0, 'Financial Services': 15.0, 'Healthcare': 22.0,
                'Consumer Cyclical': 20.0, 'Consumer Defensive': 18.0,
                'Energy': 12.0, 'Industrials': 18.0, 'Materials': 16.0,
                'Real Estate': 25.0, 'Utilities': 18.0, 'Communication Services': 20.0,
            }
            market_average_pe = sector_pe_map.get(sector, 20.0)
        except Exception:
            market_average_pe = 20.0
        
        is_undervalued = pe_ratio and pe_ratio < market_average_pe
        
        return {
            "symbol": ticker_symbol,
            "pe_ratio": pe_ratio,
            "forward_pe": forward_pe,
            "industry": industry,
            "market_average_pe": market_average_pe,
            "is_relatively_undervalued": is_undervalued
        }
        
    except Exception as e:
        return {"error": str(e)}

def format_large_number(num):
    if num is None: return "-"
    try:
        num = float(num)
        if num >= 1e12: return f"{num/1e12:.2f}T"
        elif num >= 1e9: return f"{num/1e9:.2f}B"
        elif num >= 1e6: return f"{num/1e6:.2f}M"
        return f"{num:,.2f}"
    except:
        return num

def format_percent(num):
    if num is None: return "-"
    try:
        return f"{float(num)*100:.2f}%"
    except:
        return num

def get_fundamental_analysis(ticker_symbol):
    dcf = calculate_dcf(ticker_symbol)
    relative = analyze_relative_valuation(ticker_symbol)
    
    logo_url = ''
    domain = ''
    company_name = ticker_symbol
    advanced_metrics = {}
    try:
        info = yf.Ticker(ticker_symbol).info
        company_name = info.get('shortName', info.get('longName', ticker_symbol))
        website = info.get('website', '')
        if website:
            import urllib.parse
            domain = urllib.parse.urlparse(website).netloc
            domain = domain.replace('www.', '')
            logo_url = f"https://www.google.com/s2/favicons?domain={domain}&sz=128"
            
        advanced_metrics = {
            "Market Cap": format_large_number(info.get('marketCap')),
            "Ent. Value": format_large_number(info.get('enterpriseValue')),
            "Revenue": format_large_number(info.get('totalRevenue')),
            "Net Income": format_large_number(info.get('netIncomeToCommon')),
            "Div Yield": format_percent(info.get('dividendYield')),
            "P/E": format_large_number(info.get('trailingPE')),
            "Fwd P/E": format_large_number(info.get('forwardPE')),
            "PEG": format_large_number(info.get('pegRatio')),
            "P/S": format_large_number(info.get('priceToSalesTrailing12Months')),
            "P/B": format_large_number(info.get('priceToBook')),
            "ROA": format_percent(info.get('returnOnAssets')),
            "ROE": format_percent(info.get('returnOnEquity')),
            "Gross Mgn": format_percent(info.get('grossMargins')),
            "Oper Mgn": format_percent(info.get('operatingMargins')),
            "Profit Mgn": format_percent(info.get('profitMargins')),
            "52W High": format_large_number(info.get('fiftyTwoWeekHigh')),
            "52W Low": format_large_number(info.get('fiftyTwoWeekLow')),
            "Beta": format_large_number(info.get('beta')),
            "Target Px": format_large_number(info.get('targetMeanPrice')),
            "Volume": format_large_number(info.get('volume')),
            "Avg Vol": format_large_number(info.get('averageVolume')),
            "Employees": format_large_number(info.get('fullTimeEmployees'))
        }
        
        upgrades = yf.Ticker(ticker_symbol).upgrades_downgrades
        if upgrades is not None and not upgrades.empty:
            upgrades = upgrades.sort_index(ascending=False).head(15)
            upgrades_list = []
            
            action_map = {
                'reit': 'Reiterated',
                'main': 'Maintains',
                'up': 'Upgrade',
                'down': 'Downgrade',
                'init': 'Initiated'
            }
            
            for date, row in upgrades.iterrows():
                date_str = date.strftime('%b-%d-%y')
                
                from_grade = row.get('FromGrade', '')
                to_grade = row.get('ToGrade', '')
                if from_grade and to_grade and from_grade != to_grade:
                    rating_change = f"{from_grade} → {to_grade}"
                else:
                    rating_change = to_grade if to_grade else row.get('Action', '')
                    
                prior_pt = row.get('priorPriceTarget')
                curr_pt = row.get('currentPriceTarget')
                
                pt_change = ""
                if pd.notna(prior_pt) and pd.notna(curr_pt):
                    pt_change = f"${int(prior_pt)} → ${int(curr_pt)}"
                elif pd.notna(curr_pt):
                    pt_change = f"${int(curr_pt)}"
                    
                raw_action = row.get('Action', '')
                action = action_map.get(raw_action, raw_action.capitalize())
                
                upgrades_list.append({
                    "date": date_str,
                    "action": action,
                    "analyst": row.get('Firm', ''),
                    "rating_change": rating_change,
                    "pt_change": pt_change,
                    "is_upgrade": raw_action == 'up',
                    "is_downgrade": raw_action == 'down'
                })
            advanced_metrics['upgrades'] = upgrades_list
            
    except Exception as e:
        print("Error getting fundamentals:", e)
        pass
        
    return {
        "symbol": ticker_symbol,
        "company_name": company_name,
        "logo_url": logo_url,
        "domain": domain,
        "dcf": dcf,
        "relative": relative,
        "metrics": advanced_metrics
    }
