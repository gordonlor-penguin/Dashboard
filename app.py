import subprocess
import sys
import concurrent.futures
import io
import requests

# --- AUTO-UPDATE YFINANCE ---
try:
    subprocess.check_call([sys.executable, "-m", "pip",
                          "install", "--upgrade", "--quiet", "yfinance"])
except Exception:
    pass

import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
import scipy.optimize as sco
import os
import datetime
import xml.etree.ElementTree as ET

# --- 1. PASSWORD PROTECTION ---


def check_password():
    if st.session_state.get("password_correct"):
        return True

    def password_entered():
        if st.session_state["password_input"] == st.secrets.get("password", "admin"):
            st.session_state["password_correct"] = True
            del st.session_state["password_input"]

    st.title("🐧🔒 Portfolio Locked")
    st.markdown("### Welcome back! Please authenticate to view your assets.")
    st.text_input("Password", type="password",
                  on_change=password_entered, key="password_input")
    return False


if not check_password():
    st.stop()

# --- 2. DATA ENGINES ---
DATA_FILE = "my_portfolio.csv"


def load_data():
    if not os.path.exists(DATA_FILE):
        pd.DataFrame(columns=["Ticker Symbol", "Name", "Currency", "Book Price", "Quantity",
                     "Sector", "Yield (%)", "Target Weight (%)", "Country"]).to_csv(DATA_FILE, index=False)

    df = pd.read_csv(DATA_FILE)
    if "Price" in df.columns:
        df.rename(columns={"Price": "Book Price"}, inplace=True)

    for col in ["Yield (%)", "P/E", "1Y Target", "Target Weight (%)", "Book Price", "Country"]:
        if col not in df.columns:
            if col == "Country":
                df[col] = "Unknown"
            else:
                df[col] = 0.0 if col in [
                    "Target Weight (%)", "Book Price"] else np.nan

    if "Region" in df.columns:
        df = df.drop(columns=["Region"])

    df["Book Price"] = pd.to_numeric(df["Book Price"].astype(str).str.replace(
        r'[$,]', '', regex=True), errors='coerce').fillna(0.0)
    df["Quantity"] = pd.to_numeric(df["Quantity"].astype(str).str.replace(
        r'[$,]', '', regex=True), errors='coerce').fillna(0.0)
    df["Target Weight (%)"] = pd.to_numeric(df["Target Weight (%)"].astype(
        str).str.replace(r'[%]', '', regex=True), errors='coerce').fillna(0.0)
    df["P/E"] = pd.to_numeric(df["P/E"], errors='coerce')
    df["Yield (%)"] = pd.to_numeric(df["Yield (%)"], errors='coerce')

    if "Sector" in df.columns:
        df["Sector"] = df["Sector"].fillna("Unknown").replace(
            {"nan": "Unknown", "NaN": "Unknown", "": "Unknown"})

    if not df.empty and "Currency" in df.columns and "Ticker Symbol" in df.columns:
        mask = (df["Currency"] == "CAD") & (~df["Ticker Symbol"].astype(str).str.upper().str.endswith(
            ".TO", na=False)) & (~df["Ticker Symbol"].astype(str).str.upper().str.startswith("CASH"))
        df.loc[mask, "Ticker Symbol"] = df.loc[mask,
                                               "Ticker Symbol"].astype(str).str.upper() + ".TO"

    return df


@st.cache_data(ttl=86400)
def get_smart_metadata(ticker_str):
    if str(ticker_str).upper().startswith("CASH"):
        country = "Canada" if "CAD" in str(
            ticker_str).upper() else "United States"
        return {"Name": "Cash Position", "Sector": "Cash", "Yield (%)": 0.0, "P/E": np.nan, "1Y Target": np.nan, "Country": country}
    try:
        tk = yf.Ticker(str(ticker_str))
        info = tk.info
        if not info:
            return {"Name": str(ticker_str), "Sector": "Unknown", "Yield (%)": 0.0, "P/E": np.nan, "1Y Target": np.nan, "Country": "Unknown"}

        name = info.get('longName') or info.get('shortName') or str(ticker_str)
        raw_yield = info.get('dividendYield') or info.get(
            'trailingAnnualDividendYield') or info.get('yield')
        div_yield = 0.0
        if raw_yield is not None:
            try:
                if isinstance(raw_yield, str) and '%' in raw_yield:
                    div_yield = float(raw_yield.replace('%', '').strip())
                else:
                    div_yield = float(raw_yield)
                    if 0.0 < div_yield < 0.30:
                        div_yield *= 100
            except:
                pass

        pe = info.get('trailingPE')
        if pe is None or str(pe).strip() in ["", "nan", "None", "N/A"]:
            live_price = info.get('currentPrice') or info.get('previousClose')
            eps = info.get('trailingEps')
            try:
                if live_price and eps and float(eps) > 0:
                    pe = float(live_price) / float(eps)
                else:
                    pe = np.nan
            except:
                pe = np.nan
        else:
            try:
                pe = float(pe)
                if pe <= 0:
                    pe = np.nan
            except:
                pe = np.nan

        try:
            target = float(info.get('targetMeanPrice', np.nan))
        except:
            target = np.nan

        if info.get('quoteType') == 'ETF':
            try:
                sectors = tk.funds_data.sector_weightings
                if sectors:
                    sorted_sec = sorted(
                        sectors.items(), key=lambda x: x[1], reverse=True)
                    top_sectors = [
                        f"{k.replace('_', ' ').title()} ({v*100:.1f}%)" for k, v in sorted_sec if (v*100) >= 1.0]
                    sector = "ETF: " + " | ".join(top_sectors)
                else:
                    sector = "ETF (Broad)"
            except:
                sector = "ETF (Broad)"
        else:
            sector = info.get('sector')
            if not sector or pd.isna(sector):
                sector = 'Unknown'

        country = info.get('country')
        if not country or pd.isna(country) or str(country).lower() == 'nan':
            t_str = str(ticker_str).upper()
            if t_str.endswith(".TO") or t_str.endswith(".V"):
                country = "Canada"
            elif t_str.endswith(".L"):
                country = "United Kingdom"
            elif t_str.endswith(".DE"):
                country = "Germany"
            elif t_str.endswith(".PA"):
                country = "France"
            else:
                country = "United States"

        return {"Name": name, "Sector": sector, "Yield (%)": div_yield, "P/E": pe, "1Y Target": target, "Country": country}
    except:
        return {"Name": str(ticker_str), "Sector": "Unknown", "Yield (%)": 0.0, "P/E": np.nan, "1Y Target": np.nan, "Country": "Unknown"}

# --- 3. RECURSIVE ETF SCRAPING ENGINE (INVESCO & VANGUARD) ---


@st.cache_data(ttl=86400)
def get_direct_etf_holdings(ticker):
    ticker = ticker.upper()
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'}

    if ticker in ["QQQ", "QQC", "QQC.TO"]:
        try:
            url = "https://www.invesco.com/us/financial-products/etfs/holdings/main/holdings/0?audienceType=Investor&action=download&ticker=QQQ"
            res = requests.get(url, headers=headers, timeout=5)
            df = pd.read_csv(io.StringIO(res.text))

            ticker_col = next(
                (col for col in df.columns if 'Holding Ticker' in col or 'Ticker' in col), None)
            weight_col = next(
                (col for col in df.columns if 'Weight' in col), None)

            if ticker_col and weight_col:
                df = df.dropna(subset=[ticker_col])
                df = df.rename(
                    columns={ticker_col: "Asset", weight_col: "Weight (%)"})
                df['Weight (%)'] = pd.to_numeric(df['Weight (%)'].astype(
                    str).str.replace(r'[%]', '', regex=True), errors='coerce') / 100
                return df[['Asset', 'Weight (%)']].dropna()
        except:
            pass

    # Vanguard Dictionary Extended
    vanguard_urls = {
        "VFV.TO": "https://funddetails.vanguard.com/fund/holdings/export/csv?portId=9563",
        "VEQT.TO": "https://funddetails.vanguard.com/fund/holdings/export/csv?portId=9692",
        "VUN.TO": "https://funddetails.vanguard.com/fund/holdings/export/csv?portId=9557",
        "VCN.TO": "https://funddetails.vanguard.com/fund/holdings/export/csv?portId=9561",
        "VIU.TO": "https://funddetails.vanguard.com/fund/holdings/export/csv?portId=9560",
        "VEE.TO": "https://funddetails.vanguard.com/fund/holdings/export/csv?portId=9556"
    }

    if ticker in vanguard_urls:
        try:
            res = requests.get(
                vanguard_urls[ticker], headers=headers, timeout=5)
            df = pd.read_csv(io.StringIO(res.text), skiprows=4)
            ticker_col = next(
                (col for col in df.columns if 'Ticker' in col), None)
            weight_col = next(
                (col for col in df.columns if 'Weight' in col), None)

            if ticker_col and weight_col:
                df = df.dropna(subset=[ticker_col])
                df = df.rename(
                    columns={ticker_col: "Asset", weight_col: "Weight (%)"})
                df['Weight (%)'] = pd.to_numeric(df['Weight (%)'].astype(
                    str).str.replace(r'[%]', '', regex=True), errors='coerce') / 100

                internal_vanguard_map = {
                    "VUN": "VUN.TO", "VCN": "VCN.TO", "VIU": "VIU.TO", "VEE": "VEE.TO"}
                df['Asset'] = df['Asset'].replace(internal_vanguard_map)

                return df[['Asset', 'Weight (%)']].dropna()
        except:
            pass

    try:
        tk = yf.Ticker(ticker)
        holdings = tk.funds_data.top_holdings
        if holdings is not None and not holdings.empty:
            holdings = holdings.reset_index()
            holdings = holdings.rename(
                columns={holdings.columns[0]: "Asset", "Holding Percent": "Weight (%)"})
            return holdings[['Asset', 'Weight (%)']].dropna()
    except:
        pass

    return None


@st.cache_data(ttl=604800)
def get_bulk_countries(tickers):
    countries = {}

    def fetch(t):
        try:
            t_str = str(t).upper()
            if t_str.endswith(".TO") or t_str.endswith(".V"):
                return t, "Canada"
            elif t_str.endswith(".L"):
                return t, "United Kingdom"
            elif t_str.endswith(".DE"):
                return t, "Germany"
            elif t_str.endswith(".PA"):
                return t, "France"

            info = yf.Ticker(t).info
            c = info.get('country')
            if not c or pd.isna(c):
                return t, "United States"
            return t, c
        except:
            return t, "United States"

    with concurrent.futures.ThreadPoolExecutor(max_workers=15) as executor:
        for t, c in executor.map(fetch, tickers):
            countries[t] = c
    return countries

# --- YAHOO FINANCE TRENDING API ---


@st.cache_data(ttl=1800)
def get_trending_market_tickers():
    try:
        url = "https://query1.finance.yahoo.com/v1/finance/trending/US"
        headers = {'User-Agent': 'Mozilla/5.0'}
        res = requests.get(url, headers=headers, timeout=5)
        if res.status_code == 200:
            quotes = res.json()['finance']['result'][0]['quotes']
            trends = []
            for q in quotes[:10]:
                trends.append({
                    "Ticker": q['symbol'],
                    "Trend Status": "🔥 Highly Active",
                    "Source": "Yahoo Finance"
                })
            return trends
    except:
        pass
    return []


@st.cache_data(ttl=300)
def get_market_data(tickers_tuple):
    hist_prices, prices = {}, {}
    try:
        fx_hist = yf.Ticker("USDCAD=X").history(period="5y")['Close']
        fx_hist.index = fx_hist.index.tz_localize(None)
        fx_rate = fx_hist.iloc[-1] if not fx_hist.empty else 1.38
    except:
        fx_hist = pd.Series(1.38, index=pd.date_range(
            end=datetime.datetime.today(), periods=1260))
        fx_rate = 1.38

    def fetch_single_ticker(t):
        if str(t).upper().startswith("CASH"):
            return t, pd.Series(1.0, index=fx_hist.index), 1.0
        try:
            t_hist = yf.Ticker(t).history(period="5y")['Close']
            if not t_hist.empty:
                t_hist.index = t_hist.index.tz_localize(None)
                return t, t_hist, t_hist.iloc[-1]
        except:
            pass
        return t, pd.Series(dtype=float), 0.0

    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        results = executor.map(fetch_single_ticker, tickers_tuple)
        for t, hist, price in results:
            hist_prices[t] = hist
            prices[t] = price

    return hist_prices, prices, fx_hist, fx_rate


@st.cache_data(ttl=3600)
def get_benchmarks(tickers_tuple):
    benchmarks = {}

    def fetch_bench(t):
        if str(t).upper().startswith("CASH"):
            return t, pd.Series(dtype=float)
        try:
            df_b = yf.Ticker(t).history(period="5y")['Close']
            if not df_b.empty:
                df_b.index = df_b.index.tz_localize(None)
                return t, df_b
        except:
            pass
        return t, pd.Series(dtype=float)

    with concurrent.futures.ThreadPoolExecutor(max_workers=5) as executor:
        results = executor.map(fetch_bench, tickers_tuple)
        for t, data in results:
            if not data.empty:
                benchmarks[t] = data
    return benchmarks


@st.cache_data(ttl=1800)
def get_news():
    news_items = []
    headers = {'User-Agent': 'Mozilla/5.0'}
    try:
        rss_url = "https://news.google.com/rss/search?q=finance+when:7d&hl=en-US&gl=US&ceid=US:en"
        resp = requests.get(rss_url, headers=headers, timeout=5)
        root = ET.fromstring(resp.content)

        for item in root.findall('./channel/item'):
            pub_date = item.find('pubDate').text if item.find(
                'pubDate') is not None else ""
            try:
                dt = datetime.datetime.strptime(
                    pub_date[5:25], "%d %b %Y %H:%M:%S")
            except:
                dt = datetime.datetime.now()

            source = item.find('source').text if item.find(
                'source') is not None else "Google News"
            news_items.append({"Ticker": "FINANCE NEWS", "Title": item.find(
                'title').text, "Publisher": source, "Link": item.find('link').text, "Time": dt})

        news_items.sort(key=lambda x: x["Time"], reverse=True)
        return news_items[:10]
    except:
        pass
    return []


@st.cache_data(ttl=86400)
def get_macro_data():
    try:
        api_key = st.secrets.get("fred_api_key", "")
        if not api_key:
            return pd.DataFrame(), pd.DataFrame()
        rates_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=FEDFUNDS&api_key={api_key}&file_type=json"
        cpi_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={api_key}&file_type=json"
        r_data = requests.get(rates_url, timeout=5).json()
        rates = pd.DataFrame(r_data['observations'])[['date', 'value']]
        rates['date'], rates['value'] = pd.to_datetime(
            rates['date']), pd.to_numeric(rates['value'], errors='coerce')
        rates.set_index('date', inplace=True)
        rates.rename(columns={'value': 'FEDFUNDS'}, inplace=True)
        c_data = requests.get(cpi_url, timeout=5).json()
        cpi = pd.DataFrame(c_data['observations'])[['date', 'value']]
        cpi['date'], cpi['value'] = pd.to_datetime(
            cpi['date']), pd.to_numeric(cpi['value'], errors='coerce')
        cpi.set_index('date', inplace=True)
        cpi.rename(columns={'value': 'CPIAUCSL'}, inplace=True)
        cpi['YoY Inflation (%)'] = cpi['CPIAUCSL'].pct_change(12) * 100
        start_date = pd.Timestamp.now() - pd.DateOffset(years=5)
        return rates[rates.index >= start_date].dropna().tz_localize(None), cpi[cpi.index >= start_date].dropna().tz_localize(None)
    except:
        return pd.DataFrame(), pd.DataFrame()


@st.cache_data(ttl=86400)
def get_sp500_ndx_tickers():
    try:
        sp_tickers = pd.read_html('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')[
            0]['Symbol'].str.replace('.', '-').tolist()
        ndx_tickers = pd.read_html(
            'https://en.wikipedia.org/wiki/Nasdaq-100')[4]['Ticker'].str.replace('.', '-').tolist()
        return list(set(sp_tickers + ndx_tickers))
    except:
        return ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO', 'PEP', 'COST']


@st.cache_data(ttl=86400)
def download_universe_data(tickers):
    data = yf.download(tickers, period="2y", interval="1d")['Close']
    return data.dropna(axis=1, thresh=len(data)*0.9).ffill()


def find_top_10_optimal_portfolio(price_data, risk_free_rate=0.04):
    valid_cols = [c for c in price_data.columns if c not in ['SPY', 'QQQ']]
    returns = price_data[valid_cols].pct_change().dropna()
    ind_sharpe = ((returns.mean() * 252) - risk_free_rate) / \
        (returns.std() * np.sqrt(252))
    top_10 = ind_sharpe.nlargest(10).index.tolist()
    top_10_ret = returns[top_10]

    def negative_sharpe(weights):
        port_ret = np.sum(top_10_ret.mean() * weights) * 252
        port_vol = np.sqrt(
            np.dot(weights.T, np.dot(top_10_ret.cov() * 252, weights)))
        return -(port_ret - risk_free_rate) / port_vol

    optimized = sco.minimize(negative_sharpe, 10 * [1./10,], method='SLSQP', bounds=tuple(
        (0.01, 0.30) for _ in range(10)), constraints=({'type': 'eq', 'fun': lambda x: np.sum(x) - 1}))
    final_ret = np.sum(top_10_ret.mean() * optimized['x']) * 252 * 100
    final_vol = np.sqrt(np.dot(optimized['x'].T, np.dot(
        top_10_ret.cov() * 252, optimized['x']))) * 100
    return pd.DataFrame({"Ticker": top_10, "Individual Sharpe Ratio": ind_sharpe[top_10].values, "Optimal Weight (%)": [round(w*100, 2) for w in optimized['x']]}).sort_values("Optimal Weight (%)", ascending=False), final_ret, final_vol, ((final_ret/100) - risk_free_rate) / (final_vol/100) if final_vol > 0 else 0, (top_10_ret * optimized['x']).sum(axis=1)


# --- 4. DASHBOARD UI & CORE PROCESSING ---
st.set_page_config(page_title="Portfolio Tracker",
                   layout="wide", page_icon="📈")

st.markdown("""
    <style>
    .stProgress .st-bo { background-color: #00C9B1; }
    .metric-card { background-color: #1E1E1E; padding: 20px; border-radius: 10px; border: 1px solid #333; }
    </style>
""", unsafe_allow_html=True)

with st.sidebar:
    st.title("📊 Master Tracker")
    st.write("Navigation")
    page = st.radio("", ["📈 Command Center", "⚖️ Re-balance", "📰 Global Market News",
                    "🔮 Wealth Forecast", "🌍 Macro Environment", "🧠 AI Optimizer Lab", "⚙️ Database Control"])
    st.divider()
    st.caption("Auto-Sync Engine Active 🟢")

df = load_data()
port_val_series_all = pd.Series(dtype=float)
total_val_cad = 0.0

if not df.empty:
    df = df.dropna(subset=["Ticker Symbol"])
    tickers = df["Ticker Symbol"].unique()

    with st.spinner("Syncing Live Engines (Accelerated)..."):
        needs_save = False
        needs_update_tickers = []
        for idx, row in df.iterrows():
            sec, ctry = str(row.get("Sector")), str(row.get("Country"))
            if pd.isna(sec) or sec in ["Unknown", "nan", "NaN"] or pd.isna(ctry) or ctry in ["Unknown", "nan", "NaN"]:
                needs_update_tickers.append(
                    (idx, row["Ticker Symbol"], row.get("Yield (%)")))

        if needs_update_tickers:
            def sync_meta(task):
                idx, t, old_y = task
                return idx, get_smart_metadata(t), old_y

            with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
                for idx, meta, old_y in executor.map(sync_meta, needs_update_tickers):
                    for k, v in meta.items():
                        if k == "Yield (%)" and pd.notna(old_y) and old_y > 0:
                            continue
                        df.at[idx, k] = v
                    needs_save = True

        if needs_save:
            df.to_csv(DATA_FILE, index=False)

        hist_prices, prices, fx_hist, fx_rate = get_market_data(tuple(tickers))
        master_dates = fx_hist.index
        port_val_series_all = pd.Series(0.0, index=master_dates)

        for _, row in df.iterrows():
            t, q, curr = row["Ticker Symbol"], row["Quantity"], row["Currency"]
            if t in hist_prices and not hist_prices[t].empty:
                asset_history = hist_prices[t].reindex(
                    master_dates).ffill().bfill()
                port_val_series_all += (asset_history * q * fx_hist if curr ==
                                        "USD" else asset_history * q).fillna(0.0)

    # Fast Vectorized Math
    df["Live Price"] = df["Ticker Symbol"].map(prices).fillna(0.0)
    df["Value (CAD)"] = np.where(df["Currency"] == "USD", df["Quantity"]
                                 * df["Live Price"] * fx_rate, df["Quantity"] * df["Live Price"])
    df["Value (USD)"] = df["Value (CAD)"] / fx_rate if fx_rate > 0 else 0.0
    df["Cost Basis (CAD)"] = np.where(df["Currency"] == "USD", df["Quantity"]
                                      * df["Book Price"] * fx_rate, df["Quantity"] * df["Book Price"])
    df["Annual Income (CAD)"] = df["Value (CAD)"] * \
        (df["Yield (%)"].fillna(0) / 100)

    total_val_cad = df["Value (CAD)"].sum()
    total_cost_cad = df["Cost Basis (CAD)"].sum()
    total_income = df["Annual Income (CAD)"].sum()

    df["Native_Cost_Total"] = df["Book Price"] * df["Quantity"]
    grouped = df.groupby(["Ticker Symbol", "Name", "Currency", "Country", "Sector", "Live Price", "Target Weight (%)"], dropna=False).agg(
        Quantity=('Quantity', 'sum'), Yield_Pct=('Yield (%)', 'max'), PE_Ratio=('P/E', 'max'), Total_Native_Cost=('Native_Cost_Total', 'sum'),
        Total_Cost_CAD=('Cost Basis (CAD)', 'sum'), Value_CAD=('Value (CAD)', 'sum'), Value_USD=('Value (USD)', 'sum')
    ).reset_index()

    grouped["Yield (%)"], grouped["P/E"] = grouped["Yield_Pct"], grouped["PE_Ratio"]
    grouped["Avg Book Price"] = grouped["Total_Native_Cost"] / \
        grouped["Quantity"]
    grouped["Portfolio Weight (%)"] = (
        grouped["Value_CAD"] / total_val_cad) * 100 if total_val_cad > 0 else 0.0
    grouped["Asset Return (%)"] = np.where(grouped["Total_Cost_CAD"] > 0, ((
        grouped["Value_CAD"] - grouped["Total_Cost_CAD"]) / grouped["Total_Cost_CAD"]) * 100, 0)
    grouped = grouped.rename(columns={"Value_CAD": "Value (CAD)", "Value_USD": "Value (USD)"}).sort_values(
        "Portfolio Weight (%)", ascending=False)

# --- PAGE ROUTING ---
if page == "📈 Command Center":
    if not df.empty:
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Value (CAD)", f"${total_val_cad:,.2f}",
                  f"USD: ${total_val_cad/fx_rate if fx_rate > 0 else 0:,.2f}", delta_color="off")
        c2.metric("Total Book (CAD)", f"${total_cost_cad:,.2f}",
                  f"USD: ${total_cost_cad/fx_rate if fx_rate > 0 else 0:,.2f}", delta_color="off")
        c3.metric("All-Time Return", f"{((total_val_cad - total_cost_cad)/total_cost_cad)*100 if total_cost_cad > 0 else 0:+.2f}%",
                  f"${total_val_cad - total_cost_cad:,.2f}")
        c4.metric("Est. Annual Income", f"${total_income:,.2f}",
                  f"Yield: {(total_income/total_val_cad)*100 if total_val_cad > 0 else 0:.2f}%", delta_color="off")
        c5.metric("USD/CAD Rate", f"{fx_rate:.4f}")
        st.divider()

        c_time, c_bench = st.columns([1, 1])
        with c_time:
            timeframe = st.radio("Select Timeframe", [
                                 "1M", "YTD", "1Y", "3Y", "5Y"], horizontal=True, index=2)
        with c_bench:
            bench_input = st.text_input(
                "📈 Add Extra Benchmarks (Comma-separated)", placeholder="e.g. DIA, IWM")
            custom_bench_tickers = list(dict.fromkeys(
                ["SPY", "QQQ"] + [x.strip().upper() for x in bench_input.split(",") if x.strip()]))
            benchmarks = get_benchmarks(tuple(custom_bench_tickers))

        now = datetime.datetime.now()
        days_map = {"1M": 30, "YTD": (
            now - datetime.datetime(now.year, 1, 1)).days, "1Y": 365, "3Y": 3*365, "5Y": 5*365}
        start_date = now - datetime.timedelta(days=days_map[timeframe])
        port_slice = port_val_series_all[port_val_series_all.index >= start_date]

        c_chart, c_risk = st.columns([3, 1])
        with c_chart:
            if len(port_slice) > 0:
                chart_data = pd.DataFrame({"My Portfolio": port_slice})
                start_val = port_slice.iloc[0]
                for b_tick in custom_bench_tickers:
                    if b_tick in benchmarks:
                        b_slice = benchmarks[b_tick][benchmarks[b_tick].index >= start_date]
                        if not b_slice.empty:
                            chart_data[b_tick] = (
                                b_slice / b_slice.iloc[0]) * start_val

                fig_line = px.line(chart_data.dropna().reset_index().melt(id_vars="Date", var_name="Asset", value_name="Value ($ CAD)"),
                                   x="Date", y="Value ($ CAD)", color="Asset", template="plotly_dark", title="Historical Value Overlay ($ CAD)")
                fig_line.update_traces(
                    line=dict(width=3), selector=dict(name="My Portfolio"))
                fig_line.update_layout(
                    xaxis_title="", hovermode="x unified", margin=dict(l=0, r=0, t=30, b=10))
                st.plotly_chart(fig_line, use_container_width=True)

        with c_risk:
            st.markdown("### Risk & Return Profile")
            if len(port_slice) > 1 and port_slice.iloc[0] > 0:
                days = (port_slice.index[-1] - port_slice.index[0]).days
                ret = ((port_slice.iloc[-1] / port_slice.iloc[0]) ** (365.25 / days) - 1) * \
                    100 if days >= 365 else (
                        port_slice.iloc[-1] / port_slice.iloc[0] - 1) * 100
                st.success(
                    f"**{'Avg Annual Return' if days >= 365 else 'Period Return'}:** {ret:.2f}%")
                max_dd = ((port_slice / port_slice.cummax()) - 1).min() * 100
                st.warning(f"**Max Drawdown:** {max_dd:.2f}%\n\n*Worst drop.*")
                vol = port_slice.pct_change().dropna().std() * np.sqrt(252) * 100
                if vol > 0:
                    st.info(
                        f"**Sharpe Ratio:** {((ret*(365.25/days if days < 365 else 1))-4) / vol:.2f}")

        st.divider()

        # --- YAHOO FINANCE TRENDING STOCKS EXPANDER ---
        with st.expander("🔥 Trending Market Tickers (Yahoo Finance)", expanded=False):
            with st.spinner("Scanning active retail & institutional trends..."):
                trends = get_trending_market_tickers()
                if trends:
                    st.markdown(
                        "These are the **Top 10 most actively searched stocks & ETFs** on Yahoo Finance right now:")
                    st.dataframe(pd.DataFrame(trends),
                                 use_container_width=True, hide_index=True)
                else:
                    st.info(
                        "Trending data is currently unavailable. Try again later.")

        st.markdown("### 📑 Detailed Ledger & Fundamentals")
        display_cols = ["Ticker Symbol", "Name", "Sector", "Country", "Quantity", "Avg Book Price",
                        "Live Price", "Value (CAD)", "Portfolio Weight (%)", "Yield (%)", "P/E", "Asset Return (%)"]

        st.dataframe(
            grouped[display_cols],
            column_config={
                "Quantity": st.column_config.NumberColumn("Quantity", format="%,.4g"),
                "Portfolio Weight (%)": st.column_config.ProgressColumn("Weight (%)", format="%.2f%%", min_value=0, max_value=100),
                "Asset Return (%)": st.column_config.NumberColumn("Return (%)", format="%+.2f%%"),
                "Yield (%)": st.column_config.NumberColumn("Yield (%)", format="%.2f%%"),
                "P/E": st.column_config.NumberColumn("P/E (TTM)", format="%.1f"),
                "Value (CAD)": st.column_config.NumberColumn("Value (CAD)", format="$%,.2f"),
                "Avg Book Price": st.column_config.NumberColumn("Avg Book", format="$%,.2f"),
                "Live Price": st.column_config.NumberColumn("Live Price", format="$%,.2f"),
            },
            use_container_width=True, hide_index=True
        )

        st.divider()
        st.markdown("### 🧩 Portfolio Allocation & Performance")

        c_pie, c_tree = st.columns([1, 1])
        chart_df = grouped[grouped["Value (CAD)"] > 0].copy()

        exploded_rows = []
        for _, row in chart_df.iterrows():
            val = row["Value (CAD)"]
            ticker = row["Ticker Symbol"]
            ret = row["Asset Return (%)"]
            sec_raw = str(row["Sector"])

            if sec_raw.startswith("ETF: ") and "|" in sec_raw:
                sec_str = sec_raw.replace("ETF: ", "")
                parts = [p.strip() for p in sec_str.split("|")]
                total_allocated = 0.0
                for p in parts:
                    try:
                        sec_name = p.split(" (")[0].strip()
                        pct_str = p.split(" (")[1].replace("%)", "")
                        weight = float(pct_str) / 100.0
                        allocated_val = val * weight
                        total_allocated += weight
                        exploded_rows.append({"Ticker Symbol": ticker, "Sector": sec_name,
                                             "Value (CAD)": allocated_val, "Asset Return (%)": ret, "Portfolio": "My Portfolio"})
                    except Exception:
                        pass
                if total_allocated < 1.0:
                    exploded_rows.append({"Ticker Symbol": ticker, "Sector": "Other", "Value (CAD)": max(
                        0, val * (1.0 - total_allocated)), "Asset Return (%)": ret, "Portfolio": "My Portfolio"})
            elif sec_raw in ["ETF", "ETF (Broad)"]:
                exploded_rows.append({"Ticker Symbol": ticker, "Sector": "ETF (Broad)",
                                     "Value (CAD)": val, "Asset Return (%)": ret, "Portfolio": "My Portfolio"})
            else:
                sec_clean = sec_raw if pd.notna(sec_raw) and sec_raw.strip() not in [
                    "", "nan", "Unknown", "NaN"] else "Other/Unknown"
                exploded_rows.append({"Ticker Symbol": ticker, "Sector": sec_clean,
                                     "Value (CAD)": val, "Asset Return (%)": ret, "Portfolio": "My Portfolio"})

        exploded_df = pd.DataFrame(exploded_rows)

        with c_pie:
            pie_df = exploded_df.groupby("Sector", as_index=False)[
                "Value (CAD)"].sum()
            fig_pie = px.pie(pie_df, names="Sector", values="Value (CAD)",
                             template="plotly_dark", title="Sector Breakdown", hole=0.4)
            fig_pie.update_traces(textposition='inside',
                                  textinfo='percent+label')
            fig_pie.update_layout(margin=dict(
                t=40, l=0, r=0, b=0), showlegend=False)
            st.plotly_chart(fig_pie, use_container_width=True)

        with c_tree:
            fig_tree = px.treemap(
                exploded_df, path=["Portfolio", "Sector", "Ticker Symbol"], values="Value (CAD)",
                color="Asset Return (%)", color_continuous_scale=['#FF4B4B', '#262730', '#00C9B1'],
                color_continuous_midpoint=0, template="plotly_dark", title="Allocation & Return Heatmap"
            )
            fig_tree.update_layout(margin=dict(t=40, l=0, r=0, b=0))
            st.plotly_chart(fig_tree, use_container_width=True)

        st.divider()

        # --- RECURSIVE GEOGRAPHIC MAP + COUNTRY PIE CHART ---
        with st.expander("🌍 Geographic Exposure Map (True Underlying Stock Lookup)", expanded=False):
            with st.spinner("Executing Recursive Look-Through of Nested ETFs..."):
                stock_exposure = []
                exploded_geo_rows = []
                all_underlying_tickers = set()

                # List of ETFs we can recursively unpack
                KNOWN_RECURSIVE_ETFS = ["VTI", "VFV.TO", "VEQT.TO", "VUN.TO",
                                        "VCN.TO", "VIU.TO", "VEE.TO", "VOO", "QQQ", "QQC", "QQC.TO"]

                for _, row in grouped[grouped["Value (CAD)"] > 0].iterrows():
                    val = row["Value (CAD)"]
                    root_ticker = str(row["Ticker Symbol"]).upper()
                    sector = str(row["Sector"])
                    base_country = str(row["Country"])

                    if "ETF" in sector:
                        # Use a queue to unpack nested ETFs layer by layer
                        queue = [(root_ticker, val, root_ticker)]

                        while queue:
                            current_ticker, current_val, parent = queue.pop(0)

                            holdings_df = get_direct_etf_holdings(
                                current_ticker)
                            if holdings_df is not None and not holdings_df.empty:
                                total_allocated_weight = 0.0
                                for _, h_row in holdings_df.iterrows():
                                    u_ticker = h_row["Asset"]
                                    weight = h_row["Weight (%)"]

                                    if weight > 0:
                                        a_val = current_val * weight
                                        total_allocated_weight += weight

                                        # If the underlying asset is ALSO an ETF, put it back in the queue!
                                        if u_ticker in KNOWN_RECURSIVE_ETFS:
                                            queue.append(
                                                (u_ticker, a_val, parent))
                                        else:
                                            stock_exposure.append({
                                                "Asset": u_ticker,
                                                "Value (CAD)": a_val,
                                                "Type": "Hidden ETF Holding",
                                                "Parent ETF": parent
                                            })
                                            all_underlying_tickers.add(
                                                u_ticker)

                                # Assign any remaining cash/dust to the country of origin
                                if total_allocated_weight < 1.0:
                                    remainder = current_val * \
                                        (1.0 - total_allocated_weight)
                                    if remainder > 1.0:
                                        exploded_geo_rows.append(
                                            {"Country": base_country, "Value (CAD)": remainder})
                            else:
                                # Fallback if we fail to scrape
                                stock_exposure.append({
                                    "Asset": current_ticker,
                                    "Value (CAD)": current_val,
                                    "Type": "Direct Holding" if current_ticker == root_ticker else "Hidden ETF Holding",
                                    "Parent ETF": parent if current_ticker != root_ticker else "N/A"
                                })
                                exploded_geo_rows.append(
                                    {"Country": base_country, "Value (CAD)": current_val})
                    else:
                        # Direct Stock Picks
                        stock_exposure.append({
                            "Asset": root_ticker,
                            "Value (CAD)": val,
                            "Type": "Direct Holding",
                            "Parent ETF": "N/A"
                        })
                        exploded_geo_rows.append(
                            {"Country": base_country, "Value (CAD)": val})

                # Resolve all underlying stock countries
                if all_underlying_tickers:
                    countries_map = get_bulk_countries(
                        list(all_underlying_tickers))
                else:
                    countries_map = {}

                for item in stock_exposure:
                    if item["Type"] == "Hidden ETF Holding":
                        country = countries_map.get(
                            item["Asset"], "United States")
                        if country == "U.S.":
                            country = "United States"
                        if country == "U.K.":
                            country = "United Kingdom"
                        exploded_geo_rows.append(
                            {"Country": country, "Value (CAD)": item["Value (CAD)"]})

                # Format geographic data for plotting
                geo_df = pd.DataFrame(exploded_geo_rows)
                map_df = geo_df.groupby("Country", as_index=False)[
                    "Value (CAD)"].sum()

                # --- NEW: Layout for Map and Pie Chart side-by-side ---
                c_map, c_pie_geo = st.columns([2, 1])

                with c_map:
                    fig_map = px.choropleth(
                        map_df, locations="Country", locationmode="country names", color="Value (CAD)",
                        hover_name="Country", color_continuous_scale="Viridis", template="plotly_dark",
                        title="True Geographic Exposure Map"
                    )
                    fig_map.update_layout(geo=dict(showframe=False, showcoastlines=False,
                                          projection_type='equirectangular'), margin=dict(l=0, r=0, t=40, b=0))
                    st.plotly_chart(fig_map, use_container_width=True)

                with c_pie_geo:
                    fig_pie_geo = px.pie(
                        map_df, names="Country", values="Value (CAD)",
                        template="plotly_dark", title="Country Allocation", hole=0.4
                    )
                    fig_pie_geo.update_traces(
                        textposition='inside', textinfo='percent+label')
                    fig_pie_geo.update_layout(margin=dict(
                        t=40, l=0, r=0, b=0), showlegend=False)
                    st.plotly_chart(fig_pie_geo, use_container_width=True)

                    # Place the ledger right underneath the pie chart
                    st.dataframe(
                        map_df.sort_values("Value (CAD)", ascending=False).style.format(
                            {"Value (CAD)": "${:,.2f}"}),
                        use_container_width=True, hide_index=True
                    )

                if stock_exposure:
                    stock_df = pd.DataFrame(stock_exposure)
                    stock_df = stock_df.groupby(["Type", "Asset"], as_index=False)[
                        "Value (CAD)"].sum()
                    stock_df = stock_df[stock_df["Value (CAD)"] >= 1.0]

                    fig_stock = px.treemap(
                        stock_df, path=["Type", "Asset"], values="Value (CAD)",
                        template="plotly_dark", title="Deep Look-Through: True Underlying Stock Holdings ($ CAD)",
                        color="Type", color_discrete_sequence=["#00C9B1", "#3b82f6", "#FF4B4B"]
                    )
                    fig_stock.update_layout(margin=dict(t=40, l=0, r=0, b=0))
                    st.plotly_chart(fig_stock, use_container_width=True)

    else:
        st.info("Your portfolio is empty. Go to Database Control to add assets.")

elif page == "⚖️ Re-balance":
    st.header("⚖️ Re-balance Engine")
    st.markdown(
        "Compares your `Target Weight (%)` to your `Live Weight (%)` to calculate exactly what you need to buy or sell.")
    if not df.empty and total_val_cad > 0:
        reb_df = grouped[["Ticker Symbol", "Name", "Currency", "Live Price", "Quantity",
                          "Value (CAD)", "Portfolio Weight (%)", "Target Weight (%)"]].copy()
        target_sum = reb_df["Target Weight (%)"].sum()
        if target_sum == 0:
            st.warning(
                "⚠️ Go to **Database Control** to set your Target Weight (%) for each asset.")
        elif not np.isclose(target_sum, 100.0, atol=0.1):
            st.warning(
                f"⚠️ Your Target Weights sum to **{target_sum:.1f}%**. They should add up to exactly 100%.")

        reb_df["Target Value (CAD)"] = total_val_cad * \
            (reb_df["Target Weight (%)"] / 100)
        reb_df["Difference (CAD)"] = reb_df["Target Value (CAD)"] - \
            reb_df["Value (CAD)"]
        reb_df["Live Price (CAD Eqv)"] = np.where(
            reb_df["Currency"] == "USD", reb_df["Live Price"] * fx_rate, reb_df["Live Price"])
        reb_df["Action Shares"] = np.where(
            reb_df["Live Price (CAD Eqv)"] > 0, reb_df["Difference (CAD)"] / reb_df["Live Price (CAD Eqv)"], 0)
        reb_df["Action"] = np.where(reb_df["Action Shares"] > 0, "🛒 BUY", np.where(
            reb_df["Action Shares"] < 0, "💰 SELL", "✅ HOLD"))
        reb_df["Action Shares"] = reb_df["Action Shares"].abs()

        st.dataframe(
            reb_df[["Action", "Action Shares", "Ticker Symbol", "Name", "Portfolio Weight (%)", "Target Weight (%)", "Difference (CAD)"]].sort_values("Difference (CAD)").style.format({
                "Action Shares": "{:,.2f}", "Portfolio Weight (%)": "{:.2f}%", "Target Weight (%)": "{:.2f}%", "Difference (CAD)": "${:+,.2f}"
            }).map(lambda x: 'color: #00C9B1' if "BUY" in str(x) or (isinstance(x, (int, float)) and x > 0) else ('color: #FF4B4B' if "SELL" in str(x) or (isinstance(x, (int, float)) and x < 0) else ''), subset=["Action", "Difference (CAD)"]),
            use_container_width=True, hide_index=True
        )

        fig_reb = go.Figure()
        fig_reb.add_trace(go.Bar(
            x=reb_df["Ticker Symbol"], y=reb_df["Portfolio Weight (%)"], name="Current Weight (%)", marker_color="#3b82f6"))
        fig_reb.add_trace(go.Bar(
            x=reb_df["Ticker Symbol"], y=reb_df["Target Weight (%)"], name="Target Weight (%)", marker_color="#00C9B1"))
        st.plotly_chart(fig_reb.update_layout(barmode='group', template="plotly_dark",
                        title="Current vs Target Allocations", xaxis_title="", yaxis_title="Weight (%)"), use_container_width=True)
    else:
        st.info("Portfolio is empty.")

elif page == "📰 Global Market News":
    st.header("📰 Top 10 Most Recent Finance Headlines")
    with st.spinner("Fetching breaking finance news..."):
        news = get_news()
        if news:
            for n in news:
                st.markdown(
                    f"**[🌎 {n['Ticker']}]** [{n['Title']}]({n['Link']})")
                st.caption(
                    f"🗞️ {n['Publisher']} • 🕒 {n['Time'].strftime('%b %d, %Y - %H:%M')}")
                st.divider()
        else:
            st.info("No recent news found right now.")

elif page == "🔮 Wealth Forecast":
    if not df.empty and total_val_cad > 0:
        st.header("🎲 Monte Carlo Simulator")
        c_p1, c_p2, c_p3 = st.columns(3)
        with c_p1:
            yrs = st.slider("Forecast Years", 1, 40, 15)
        with c_p2:
            contrib = st.number_input(
                "Monthly Contribution (CAD)", min_value=0.0, value=500.0, step=100.0)
        with c_p3:
            cagr = st.number_input("Expected Return (%)", value=8.0, step=1.0)
            vol = st.number_input(
                "Expected Volatility (%)", value=15.0, step=1.0)

        mu, v, sims = cagr/100, vol/100, 1000
        res = np.zeros((yrs + 1, sims))
        res[0, :] = total_val_cad
        for y in range(1, yrs + 1):
            res[y, :] = (res[y-1, :] + (contrib*12)) * \
                np.exp((mu - (v**2)/2) + v * np.random.normal(0, 1, sims))
        p = np.percentile(res, [10, 50, 90], axis=1)

        fig = go.Figure()
        fig.add_trace(go.Scatter(x=np.arange(
            yrs+1), y=p[2], name='Bull', line=dict(color='#00C9B1', dash='dash')))
        fig.add_trace(go.Scatter(x=np.arange(yrs+1),
                      y=p[1], name='Base', line=dict(color='#3b82f6', width=4)))
        fig.add_trace(go.Scatter(x=np.arange(
            yrs+1), y=p[0], name='Bear', line=dict(color='#FF4B4B', dash='dash')))
        st.plotly_chart(fig.update_layout(template="plotly_dark",
                        yaxis_title="CAD Value"), use_container_width=True)

elif page == "🌍 Macro Environment":
    st.header("🌍 Central Bank & Inflation Data")
    rates, cpi = get_macro_data()
    if not rates.empty:
        c1, c2 = st.columns(2)
        c1.plotly_chart(px.line(rates, y='FEDFUNDS', template="plotly_dark",
                        title="Fed Funds Rate"), use_container_width=True)
        c2.plotly_chart(px.line(cpi, y='YoY Inflation (%)', template="plotly_dark", title="US Inflation").add_hline(
            2.0, line_dash="dash", annotation_text="2% Target"), use_container_width=True)
    else:
        st.error("Macro data missing. Check FRED API Key in Secrets.")

elif page == "🧠 AI Optimizer Lab":
    st.header("🧠 Portfolio Optimizer")
    st.markdown(
        "Scans 550+ S&P and Nasdaq stocks to find the mathematically ideal Top 10 Portfolio based on the Sharpe Ratio.")
    if st.button("Run Market Optimization", type="primary"):
        with st.spinner("Analyzing 550 stocks... (This takes ~60 seconds to download the daily data)"):
            univ = get_sp500_ndx_tickers()
            for b in ["SPY", "QQQ"]:
                if b not in univ:
                    univ.append(b)
            history = download_universe_data(univ)
            if not history.empty:
                opt_df, exp_ret, exp_vol, exp_sh, port_ret = find_top_10_optimal_portfolio(
                    history)
                c1, c2, c3 = st.columns(3)
                c1.metric("Expected Return", f"{exp_ret:.2f}%")
                c2.metric("Expected Volatility", f"{exp_vol:.2f}%")
                c3.metric("Sharpe Ratio", f"{exp_sh:.2f}")
                st.dataframe(opt_df.style.format(
                    {"Optimal Weight (%)": "{:.1f}%", "Individual Sharpe Ratio": "{:.2f}"}), use_container_width=True, hide_index=True)
                c_ch1, c_ch2 = st.columns(2)
                with c_ch1:
                    st.plotly_chart(px.pie(opt_df, values='Optimal Weight (%)', names='Ticker',
                                    template="plotly_dark", hole=0.3, title="Allocation"), use_container_width=True)
                with c_ch2:
                    bench = history[['SPY', 'QQQ']].pct_change().dropna()
                    combined = pd.concat(
                        [port_ret.rename('AI Portfolio'), bench], axis=1).dropna()
                    cum_perf = (1 + combined).cumprod() * 100
                    start = pd.DataFrame(
                        [[100.0]*3], columns=cum_perf.columns, index=[cum_perf.index[0]-pd.Timedelta(days=1)])
                    fig = px.line(pd.concat([start, cum_perf]).reset_index().melt(id_vars="index", var_name="Asset", value_name="Growth"),
                                  x="index", y="Growth", color="Asset", template="plotly_dark", title="2-Year Backtest ($100)")
                    st.plotly_chart(fig.update_traces(line=dict(width=3), selector=dict(
                        name="AI Portfolio")).update_layout(xaxis_title=""), use_container_width=True)

elif page == "⚙️ Database Control":
    st.header("⚙️ Database Control")
    with st.expander("➕ Add New Asset to Database", expanded=True):
        with st.form("add_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            t_in = c1.text_input("Ticker Symbol (Type 'CASH' for cash)")
            curr_in = c1.selectbox("Currency", ["USD", "CAD"])
            p_in = c2.number_input("Book Price", min_value=0.0)
            q_in = c2.number_input("Quantity", min_value=0.0)
            if st.form_submit_button("Identify & Save"):
                ticker = t_in.upper().strip()
                if ticker == "CASH":
                    ticker = "CASH.CAD" if curr_in == "CAD" else "CASH.USD"
                elif curr_in == "CAD" and not ticker.endswith(".TO"):
                    ticker += ".TO"
                meta = get_smart_metadata(ticker)
                pd.concat([load_data(), pd.DataFrame([{"Ticker Symbol": ticker, "Name": meta["Name"], "Currency": curr_in, "Book Price": p_in, "Quantity": q_in, "Sector": meta["Sector"],
                          "Yield (%)": meta["Yield (%)"], "P/E": meta["P/E"], "1Y Target": meta["1Y Target"], "Target Weight (%)": 0.0, "Country": meta["Country"]}])], ignore_index=True).to_csv(DATA_FILE, index=False)
                st.success(f"Added {ticker}")
                st.rerun()

    with st.expander("📝 Manual Edit Database", expanded=True):
        raw_edit = st.data_editor(
            load_data(), num_rows="dynamic", use_container_width=True)
        if st.button("Save Manual Changes"):
            raw_edit.to_csv(DATA_FILE, index=False)
            st.success("Changes saved!")
            st.rerun()
