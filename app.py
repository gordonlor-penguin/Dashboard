import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
import scipy.optimize as sco
import os
import datetime
import requests
import xml.etree.ElementTree as ET

# --- 1. PASSWORD PROTECTION ---


def check_password():
    if st.session_state.get("password_correct"):
        return True

    def password_entered():
        if st.session_state["password_input"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password_input"]

    st.title("🐧🔒 Portfolio Locked")
    st.markdown("### Welcome back! Please authenticate to view your assets.")
    st.text_input("Password", type="password",
                  on_change=password_entered, key="password_input")
    return False


if not check_password():
    st.stop()

# --- 2. DATA & METADATA ENGINES ---
DATA_FILE = "my_portfolio.csv"


def load_data():
    if not os.path.exists(DATA_FILE):
        pd.DataFrame(columns=["Ticker Symbol", "Name", "Currency", "Book Price", "Quantity",
                     "Sector", "Yield (%)", "Target Weight (%)"]).to_csv(DATA_FILE, index=False)

    df = pd.read_csv(DATA_FILE)

    if "Price" in df.columns:
        df.rename(columns={"Price": "Book Price"}, inplace=True)

    for col in ["Yield (%)", "P/E", "1Y Target", "Target Weight (%)", "Book Price"]:
        if col not in df.columns:
            df[col] = 0.0 if col in [
                "Target Weight (%)", "Book Price"] else np.nan

    if "Region" in df.columns:
        df = df.drop(columns=["Region"])

    # Force numeric types to prevent groupby/ledger display issues
    df["Book Price"] = pd.to_numeric(df["Book Price"].astype(str).str.replace(
        r'[$,]', '', regex=True), errors='coerce').fillna(0.0)
    df["Quantity"] = pd.to_numeric(df["Quantity"].astype(str).str.replace(
        r'[$,]', '', regex=True), errors='coerce').fillna(0.0)
    df["P/E"] = pd.to_numeric(df["P/E"], errors='coerce')
    df["Yield (%)"] = pd.to_numeric(df["Yield (%)"], errors='coerce')

    # Clean up empty sectors
    if "Sector" in df.columns:
        df["Sector"] = df["Sector"].fillna("Unknown").replace(
            {"nan": "Unknown", "NaN": "Unknown", "": "Unknown"})

    if not df.empty and "Currency" in df.columns and "Ticker Symbol" in df.columns:
        mask = (df["Currency"] == "CAD") & (~df["Ticker Symbol"].astype(
            str).str.upper().str.endswith(".TO", na=False)) & (~df["Ticker Symbol"].astype(str).str.upper().str.startswith("CASH"))
        df.loc[mask, "Ticker Symbol"] = df.loc[mask,
                                               "Ticker Symbol"].astype(str).str.upper() + ".TO"

    return df


@st.cache_data(ttl=3600)
def get_benchmarks(tickers_tuple):
    benchmarks = {}
    for ticker in tickers_tuple:
        if str(ticker).upper().startswith("CASH"):
            continue
        try:
            df_b = yf.Ticker(ticker).history(period="5y")['Close']
            if not df_b.empty:
                df_b.index = df_b.index.tz_localize(None)
                benchmarks[ticker] = df_b
        except Exception:
            pass
    return benchmarks


@st.cache_data(ttl=86400)
def get_smart_metadata(ticker_str):
    if str(ticker_str).upper().startswith("CASH"):
        return {"Name": "Cash Position", "Sector": "Cash", "Yield (%)": 0.0, "P/E": np.nan, "1Y Target": np.nan}

    try:
        tk = yf.Ticker(str(ticker_str))
        info = tk.info
        name = info.get('longName', info.get('shortName', 'Unknown'))

        # Robust Yield Extraction
        raw_yield = info.get('dividendYield', info.get(
            'trailingAnnualDividendYield', info.get('yield', 0.0)))
        if pd.isna(raw_yield) or raw_yield is None:
            div_yield = 0.0
        elif isinstance(raw_yield, str) and '%' in raw_yield:
            div_yield = float(raw_yield.replace('%', '').strip())
        else:
            div_yield = float(raw_yield)
            if 0.0 < div_yield < 0.30:
                div_yield *= 100

        # Robust P/E Extraction
        pe = info.get('trailingPE', info.get('forwardPE', np.nan))
        target = info.get('targetMeanPrice', np.nan)

        # Robust Sector Extraction
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
            sector = info.get('sector', 'Unknown')
            if pd.isna(sector):
                sector = 'Unknown'

        return {"Name": name, "Sector": sector, "Yield (%)": div_yield, "P/E": pe, "1Y Target": target}
    except:
        return {"Name": "Unknown", "Sector": "Unknown", "Yield (%)": 0.0, "P/E": np.nan, "1Y Target": np.nan}


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

    for t in tickers_tuple:
        if str(t).upper().startswith("CASH"):
            prices[t] = 1.0
            hist_prices[t] = pd.Series(1.0, index=fx_hist.index)
            continue

        try:
            t_hist = yf.Ticker(t).history(period="5y")['Close']
            if not t_hist.empty:
                t_hist.index = t_hist.index.tz_localize(None)
                hist_prices[t] = t_hist
                prices[t] = t_hist.iloc[-1]
            else:
                prices[t] = 0.0
                hist_prices[t] = pd.Series(dtype=float)
        except:
            prices[t] = 0.0
            hist_prices[t] = pd.Series(dtype=float)

    return hist_prices, prices, fx_hist, fx_rate


def get_correlation_matrix(hist_prices):
    valid_hist = {t: p for t, p in hist_prices.items() if not str(
        t).upper().startswith("CASH") and not p.empty}
    if not valid_hist or len(valid_hist) < 2:
        return pd.DataFrame()

    returns_df = pd.DataFrame({ticker: prices.pct_change()
                              for ticker, prices in valid_hist.items()})
    returns_df = returns_df.dropna(how='all').fillna(0)
    return returns_df.corr()


@st.cache_data(ttl=1800)
def get_portfolio_news(tickers_list):
    news_items = []
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)'}

    for t in tickers_list:
        if str(t).upper().startswith("CASH"):
            continue
        try:
            search_t = str(t).replace(".TO", "")
            rss_url = f"https://news.google.com/rss/search?q={search_t}+stock&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(rss_url, headers=headers, timeout=5)
            root = ET.fromstring(resp.content)
            for item in root.findall('./channel/item')[:3]:
                pub_date = item.find('pubDate').text if item.find(
                    'pubDate') is not None else ""
                try:
                    dt = datetime.datetime.strptime(
                        pub_date[5:25], "%d %b %Y %H:%M:%S")
                except:
                    dt = datetime.datetime.now()
                source = item.find('source').text if item.find(
                    'source') is not None else "Google News"
                news_items.append({"Ticker": t, "Title": item.find(
                    'title').text, "Publisher": source, "Link": item.find('link').text, "Time": dt})
        except Exception:
            pass

    if not news_items:
        try:
            rss_url = "https://news.google.com/rss/search?q=stock+market+finance&hl=en-US&gl=US&ceid=US:en"
            resp = requests.get(rss_url, headers=headers, timeout=5)
            root = ET.fromstring(resp.content)
            for item in root.findall('./channel/item')[:5]:
                source = item.find('source').text if item.find(
                    'source') is not None else "Google News"
                news_items.append({"Ticker": "MARKET", "Title": item.find(
                    'title').text, "Publisher": source, "Link": item.find('link').text, "Time": datetime.datetime.now()})
        except Exception:
            pass

    news_items.sort(key=lambda x: x['Time'], reverse=True)
    return news_items


@st.cache_data(ttl=86400)
def get_macro_data():
    try:
        api_key = st.secrets["fred_api_key"]
        rates_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=FEDFUNDS&api_key={api_key}&file_type=json"
        cpi_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={api_key}&file_type=json"

        r_data = requests.get(rates_url, timeout=10).json()
        rates = pd.DataFrame(r_data['observations'])[['date', 'value']]
        rates['date'] = pd.to_datetime(rates['date'])
        rates['value'] = pd.to_numeric(rates['value'], errors='coerce')
        rates.set_index('date', inplace=True)
        rates.rename(columns={'value': 'FEDFUNDS'}, inplace=True)

        c_data = requests.get(cpi_url, timeout=10).json()
        cpi = pd.DataFrame(c_data['observations'])[['date', 'value']]
        cpi['date'] = pd.to_datetime(cpi['date'])
        cpi['value'] = pd.to_numeric(cpi['value'], errors='coerce')
        cpi.set_index('date', inplace=True)
        cpi.rename(columns={'value': 'CPIAUCSL'}, inplace=True)

        cpi['YoY Inflation (%)'] = cpi['CPIAUCSL'].pct_change(12) * 100

        start_date = pd.Timestamp.now() - pd.DateOffset(years=5)
        rates = rates[rates.index >= start_date].dropna()
        cpi = cpi[cpi.index >= start_date].dropna()

        rates.index = rates.index.tz_localize(None)
        cpi.index = cpi.index.tz_localize(None)

        return rates, cpi
    except Exception as e:
        return pd.DataFrame(), pd.DataFrame()

# --- 3. OPTIMIZER ENGINES ---


@st.cache_data(ttl=86400)
def get_sp500_ndx_tickers():
    try:
        sp500_table = pd.read_html(
            'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')[0]
        sp_tickers = sp500_table['Symbol'].str.replace('.', '-').tolist()
        ndx_table = pd.read_html('https://en.wikipedia.org/wiki/Nasdaq-100')[4]
        ndx_tickers = ndx_table['Ticker'].str.replace('.', '-').tolist()
        return list(set(sp_tickers + ndx_tickers))
    except:
        return ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO', 'PEP', 'COST']


@st.cache_data(ttl=86400)
def download_universe_data(tickers):
    data = yf.download(tickers, period="2y", interval="1d")['Close']
    return data.dropna(axis=1, thresh=len(data)*0.9).ffill()


def find_top_10_optimal_portfolio(price_data, risk_free_rate=0.04):
    returns = price_data.pct_change().dropna()
    ind_ret = returns.mean() * 252
    ind_vol = returns.std() * np.sqrt(252)
    ind_sharpe = (ind_ret - risk_free_rate) / ind_vol

    top_10_tickers = ind_sharpe.nlargest(10).index.tolist()
    top_10_returns = returns[top_10_tickers]
    top_10_individual_sharpes = ind_sharpe[top_10_tickers].values

    num_assets = 10

    def negative_sharpe(weights):
        port_ret = np.sum(top_10_returns.mean() * weights) * 252
        port_vol = np.sqrt(np.dot(weights.T, np.dot(
            top_10_returns.cov() * 252, weights)))
        return -(port_ret - risk_free_rate) / port_vol

    constraints = ({'type': 'eq', 'fun': lambda x: np.sum(x) - 1})
    bounds = tuple((0.01, 0.30) for asset in range(num_assets))
    init_guess = num_assets * [1. / num_assets,]

    optimized = sco.minimize(negative_sharpe, init_guess,
                             method='SLSQP', bounds=bounds, constraints=constraints)
    optimal_weights = [round(w * 100, 2) for w in optimized['x']]

    final_ret = np.sum(top_10_returns.mean() * optimized['x']) * 252 * 100
    final_vol = np.sqrt(np.dot(optimized['x'].T, np.dot(
        top_10_returns.cov() * 252, optimized['x']))) * 100
    final_sharpe = ((final_ret / 100) - risk_free_rate) / \
        (final_vol / 100) if final_vol > 0 else 0

    results_df = pd.DataFrame({
        "Ticker": top_10_tickers,
        "Individual Sharpe Ratio": top_10_individual_sharpes,
        "Optimal Weight (%)": optimal_weights
    }).sort_values(by="Optimal Weight (%)", ascending=False)

    return results_df, final_ret, final_vol, final_sharpe


# --- 4. DASHBOARD UI SETUP ---
st.set_page_config(page_title="Portfolio Tracker",
                   layout="wide", page_icon="📈")

st.markdown("""
    <style>
    .metric-card { background-color: #1E1E1E; padding: 15px; border-radius: 10px; border: 1px solid #333; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    </style>
""", unsafe_allow_html=True)

st.title("📊 Portfolio Tracker")

tab1, tab_news, tab4, tab5, tab_opt, tab2, tab3 = st.tabs(
    ["📈 Command Center", "📰 Live News", "🔮 Forecast", "🌍 Macro", "🧠 Optimizer Lab", "➕ Add Asset", "⚙️ Manage Data"])

df = load_data()

# --- DATA PROCESSING ---
port_val_series_all = pd.Series(dtype=float)
total_val_cad = 0.0
hist_prices = {}

if not df.empty:
    df = df.dropna(subset=["Ticker Symbol"])
    tickers = df["Ticker Symbol"].unique()

    with st.spinner("Syncing live market data and fundamentals..."):
        needs_save = False
        for idx, row in df.iterrows():
            current_sector = str(row.get("Sector"))
            if pd.isna(current_sector) or current_sector in ["Unknown", "nan", "NaN"] or pd.isna(row.get("P/E")):
                meta = get_smart_metadata(row["Ticker Symbol"])
                for k, v in meta.items():
                    if k == "Yield (%)" and pd.notna(row.get("Yield (%)")) and row.get("Yield (%)") > 0:
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
                daily_val = asset_history * q * fx_hist if curr == "USD" else asset_history * q
                port_val_series_all += daily_val.fillna(0.0)

    # Core Calculations
    df["Live Price"] = df["Ticker Symbol"].map(prices).fillna(0.0)
    df["Value (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Live Price"]) *
                                 fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Live Price"]), axis=1)
    df["Value (USD)"] = df["Value (CAD)"] / fx_rate if fx_rate > 0 else 0.0

    df["Cost Basis (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Book Price"]) *
                                      fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Book Price"]), axis=1)
    df["Annual Income (CAD)"] = df["Value (CAD)"] * \
        (pd.to_numeric(df["Yield (%)"], errors='coerce').fillna(0) / 100)

    total_val_cad = df["Value (CAD)"].sum()
    total_val_usd = total_val_cad / fx_rate if fx_rate > 0 else 0.0
    total_cost_cad = df["Cost Basis (CAD)"].sum()
    total_cost_usd = total_cost_cad / fx_rate if fx_rate > 0 else 0.0

    total_pl_pct = ((total_val_cad - total_cost_cad) /
                    total_cost_cad) * 100 if total_cost_cad > 0 else 0.0
    total_income = df["Annual Income (CAD)"].sum()
    portfolio_yield = (total_income / total_val_cad) * \
        100 if total_val_cad > 0 else 0.0

    df["Native_Cost_Total"] = df["Book Price"] * df["Quantity"]

    # Safely group elements allowing NaN for P/E and Yield to persist natively without dropping rows
    grouped = df.groupby(["Ticker Symbol", "Name", "Currency", "Sector", "Live Price"], dropna=False).agg(
        Quantity=('Quantity', 'sum'),
        Yield_Pct=('Yield (%)', 'max'),
        PE_Ratio=('P/E', 'max'),
        Total_Native_Cost=('Native_Cost_Total', 'sum'),
        Total_Cost_CAD=('Cost Basis (CAD)', 'sum'),
        Value_CAD=('Value (CAD)', 'sum'),
        Value_USD=('Value (USD)', 'sum'),
        Target_Weight=('Target Weight (%)', 'max')
    ).reset_index()

    grouped["Yield (%)"] = grouped["Yield_Pct"]
    grouped["P/E"] = grouped["PE_Ratio"]
    grouped["Avg Book Price"] = grouped["Total_Native_Cost"] / \
        grouped["Quantity"]
    grouped["Portfolio Weight (%)"] = (
        grouped["Value_CAD"] / total_val_cad) * 100 if total_val_cad > 0 else 0.0
    grouped["Asset Return (%)"] = np.where(grouped["Total_Cost_CAD"] > 0, ((
        grouped["Value_CAD"] - grouped["Total_Cost_CAD"]) / grouped["Total_Cost_CAD"]) * 100, 0)

    grouped = grouped.rename(
        columns={"Value_CAD": "Value (CAD)", "Value_USD": "Value (USD)"})

# --- TAB 1: COMMAND CENTER ---
with tab1:
    if not df.empty:
        st.markdown("### 💰 Portfolio Overview")

        # Upgraded Metric Cards with CAD/USD Book Value
        c1, c2, c3, c4, c5 = st.columns(5)
        c1.metric("Total Value (CAD)", f"${total_val_cad:,.2f}",
                  f"USD: ${total_val_usd:,.2f}", delta_color="off")
        c2.metric("Total Book (CAD)", f"${total_cost_cad:,.2f}",
                  f"USD: ${total_cost_usd:,.2f}", delta_color="off")
        c3.metric("All-Time Return", f"{total_pl_pct:+.2f}%",
                  f"${total_val_cad - total_cost_cad:,.2f}")
        c4.metric("Est. Annual Income", f"${total_income:,.2f}",
                  f"Yield: {portfolio_yield:.2f}%", delta_color="off")
        c5.metric("USD/CAD Rate", f"{fx_rate:.4f}")
        st.divider()

        c_time, c_bench = st.columns([1, 1])
        with c_time:
            timeframe = st.radio("Select Timeframe", [
                                 "1M", "YTD", "1Y", "3Y", "5Y"], horizontal=True, index=2)
        with c_bench:
            bench_input = st.text_input(
                "📈 Add Extra Benchmarks (Comma-separated)", value="", placeholder="e.g. DIA, IWM")
            custom_bench_tickers = [
                "SPY", "QQQ"] + [x.strip().upper() for x in bench_input.split(",") if x.strip()]
            custom_bench_tickers = list(dict.fromkeys(custom_bench_tickers))
            benchmarks = get_benchmarks(tuple(custom_bench_tickers))

        now = datetime.datetime.now()
        if timeframe == "1M":
            start_date = now - datetime.timedelta(days=30)
        elif timeframe == "YTD":
            start_date = datetime.datetime(now.year, 1, 1)
        elif timeframe == "1Y":
            start_date = now - datetime.timedelta(days=365)
        elif timeframe == "3Y":
            start_date = now - datetime.timedelta(days=3*365)
        else:
            start_date = now - datetime.timedelta(days=5*365)

        port_slice = port_val_series_all[port_val_series_all.index >= start_date]

        c_chart, c_risk = st.columns([3, 1])
        with c_chart:
            if len(port_slice) > 0:
                chart_data = pd.DataFrame({"My Portfolio": port_slice})
                start_val = port_slice.iloc[0]

                for b_tick in custom_bench_tickers:
                    if b_tick in benchmarks:
                        b_slice = benchmarks[b_tick][benchmarks[b_tick].index >= start_date]
                        if not b_slice.empty and len(b_slice) > 0:
                            chart_data[b_tick] = (
                                b_slice / b_slice.iloc[0]) * start_val

                chart_data = chart_data.dropna().reset_index().melt(
                    id_vars="Date", var_name="Asset", value_name="Value ($ CAD)")
                fig_line = px.line(chart_data, x="Date", y="Value ($ CAD)", color="Asset",
                                   template="plotly_dark", title="Historical Value Overlay ($ CAD)")
                fig_line.update_traces(
                    line=dict(width=3), selector=dict(name="My Portfolio"))
                fig_line.update_layout(xaxis_title="", yaxis_title="Value ($ CAD)",
                                       hovermode="x unified", margin=dict(l=0, r=0, t=30, b=10))
                st.plotly_chart(fig_line, use_container_width=True)

        with c_risk:
            st.markdown("**Risk & Return Profile**")

            if len(port_slice) > 1 and port_slice.iloc[0] > 0:
                days = (port_slice.index[-1] - port_slice.index[0]).days

                if days >= 365:
                    port_ann = (
                        (port_slice.iloc[-1] / port_slice.iloc[0]) ** (365.25 / days) - 1) * 100
                    st.success(
                        f"**Avg Annual Return:**\n\nPort: **{port_ann:.2f}%**")
                    ann_return_for_sharpe = port_ann
                else:
                    port_ret = (
                        port_slice.iloc[-1] / port_slice.iloc[0] - 1) * 100
                    st.success(
                        f"**Period Return:**\n\nPort: **{port_ret:.2f}%**")
                    ann_return_for_sharpe = port_ret * \
                        (365.25 / days) if days > 0 else 0

                drawdown = (port_slice / port_slice.cummax()) - 1
                max_dd = drawdown.min() * 100 if not drawdown.empty else 0.0
                st.warning(f"**Max Drawdown:** {max_dd:.2f}%\n\n*Worst drop.*")

                daily_returns = port_slice.pct_change().dropna()
                if not daily_returns.empty:
                    port_vol = daily_returns.std() * np.sqrt(252) * 100
                    risk_free_rate = 4.0
                    sharpe_ratio = (
                        ann_return_for_sharpe - risk_free_rate) / port_vol if port_vol > 0 else 0
                    st.info(
                        f"**Sharpe Ratio:** {sharpe_ratio:.2f}\n\n*(>1.0 is Good)*")

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
                exploded_df,
                path=["Portfolio", "Sector", "Ticker Symbol"],
                values="Value (CAD)",
                color="Asset Return (%)",
                color_continuous_scale=['#FF4B4B', '#262730', '#00C9B1'],
                color_continuous_midpoint=0,
                template="plotly_dark",
                title="Allocation & Return Heatmap"
            )
            fig_tree.update_layout(margin=dict(t=40, l=0, r=0, b=0))
            st.plotly_chart(fig_tree, use_container_width=True)

        st.divider()

        st.markdown("### 🧬 Diversification & Correlation")
        st.caption(
            "Values near 1.0 mean assets move together. Values near 0.0 mean they are independent.")

        corr_matrix = get_correlation_matrix(hist_prices)

        if not corr_matrix.empty:
            fig_corr = px.imshow(
                corr_matrix, text_auto=".2f", aspect="auto", color_continuous_scale='RdBu_r',
                zmin=-1, zmax=1, template="plotly_dark"
            )
            fig_corr.update_layout(margin=dict(t=0, l=0, r=0, b=0))
            st.plotly_chart(fig_corr, use_container_width=True)
        else:
            st.warning(
                "Not enough historical data to generate correlation matrix (Note: Cash positions are excluded).")

        st.divider()

        st.markdown("### 📑 Detailed Ledger & Fundamentals")
        display_cols = ["Ticker Symbol", "Name", "Sector", "Quantity", "Avg Book Price",
                        "Live Price", "Value (CAD)", "Portfolio Weight (%)", "Yield (%)", "P/E", "Asset Return (%)"]

        st.dataframe(grouped[display_cols].style.format({
            "Avg Book Price": "${:,.2f}", "Live Price": "${:,.2f}", "Value (CAD)": "${:,.2f}",
            "Quantity": "{:,.4g}", "Portfolio Weight (%)": "{:.2f}%", "Yield (%)": "{:.2f}%",
            "P/E": "{:.1f}", "Asset Return (%)": "{:+.2f}%"
        }, na_rep="N/A").map(lambda x: 'color: #00C9B1' if pd.notna(x) and x > 0 else ('color: #FF4B4B' if pd.notna(x) and x < 0 else ''), subset=["Asset Return (%)"]),
            use_container_width=True, hide_index=True)

    else:
        st.info("Your portfolio is empty. Add assets in the 'Add Asset' tab.")

# --- TAB NEWS: LIVE MARKET NEWS ---
with tab_news:
    st.header("📰 Live Market News")
    st.write(
        "Real-time headlines for the top 5 heaviest-weighted assets in your portfolio.")

    if not df.empty and total_val_cad > 0:
        top_tickers = grouped.sort_values(
            by="Portfolio Weight (%)", ascending=False).head(5)["Ticker Symbol"].tolist()

        with st.spinner("Fetching latest headlines..."):
            news_feed = get_portfolio_news(top_tickers)

        if news_feed:
            if news_feed[0]["Ticker"] == "MARKET":
                st.warning(
                    "Showing general market news as specific asset news was unavailable.")
            for item in news_feed:
                tag = f"🌎 {item['Ticker']}" if item['Ticker'] == "MARKET" else f"📌 {item['Ticker']}"
                st.markdown(f"**[{tag}]** [{item['Title']}]({item['Link']})")
                st.caption(
                    f"🗞️ {item['Publisher']} • 🕒 {item['Time'].strftime('%b %d, %Y - %I:%M %p')}")
                st.divider()
        else:
            st.info("No recent news found right now.")
    else:
        st.info("Add some assets to your portfolio first to see related news!")

# --- TAB 4: FORECASTING (MONTE CARLO) ---
with tab4:
    if not df.empty and total_val_cad > 0 and not port_val_series_all.empty:
        st.header("🎲 Monte Carlo Wealth Simulator")
        overall_daily_returns = port_val_series_all.pct_change().dropna()
        if len(port_val_series_all) >= 252:
            days = (port_val_series_all.index[-1] -
                    port_val_series_all.index[0]).days
            hist_cagr = (
                (port_val_series_all.iloc[-1] / port_val_series_all.iloc[0]) ** (365.25 / days) - 1) * 100
        else:
            hist_cagr = 8.0
        hist_vol = overall_daily_returns.std() * np.sqrt(252) * \
            100 if not overall_daily_returns.empty else 15.0

        c_p1, c_p2, c_p3 = st.columns(3)
        with c_p1:
            sim_years = st.slider("Years to Forecast",
                                  min_value=1, max_value=40, value=15)
        with c_p2:
            monthly_contrib = st.number_input(
                "Monthly Contribution (CAD)", min_value=0.0, value=500.0, step=100.0)
        with c_p3:
            user_cagr = st.number_input("Expected Annual Return (%)", value=float(
                max(0, min(hist_cagr, 20))), step=1.0)
            user_vol = st.number_input("Expected Volatility (%)", value=float(
                max(1, min(hist_vol, 40))), step=1.0)

        mu, vol, num_sims, annual_contrib = user_cagr / \
            100.0, user_vol / 100.0, 1000, monthly_contrib * 12
        sim_results = np.zeros((sim_years + 1, num_sims))
        sim_results[0, :] = total_val_cad
        drift = mu - (vol ** 2) / 2

        for y in range(1, sim_years + 1):
            shock = np.exp(drift + vol * np.random.normal(0, 1, num_sims))
            sim_results[y, :] = (sim_results[y-1, :] + annual_contrib) * shock

        percentiles = np.percentile(sim_results, [10, 50, 90], axis=1)
        years_arr = np.arange(sim_years + 1)
        fig_mc = go.Figure()

        for i in range(50):
            fig_mc.add_trace(go.Scatter(x=years_arr, y=sim_results[:, i], mode='lines', line=dict(
                color='rgba(255, 255, 255, 0.05)', width=1), showlegend=False, hoverinfo='skip'))

        fig_mc.add_trace(go.Scatter(x=years_arr, y=percentiles[2], mode='lines', name='90th Percentile (Bull Case)', line=dict(
            color='#00C9B1', dash='dash', width=2)))
        fig_mc.add_trace(go.Scatter(
            x=years_arr, y=percentiles[1], mode='lines', name='50th Percentile (Base Case)', line=dict(color='#3b82f6', width=4)))
        fig_mc.add_trace(go.Scatter(x=years_arr, y=percentiles[0], mode='lines', name='10th Percentile (Bear Case)', line=dict(
            color='#FF4B4B', dash='dash', width=2)))

        fig_mc.update_layout(template="plotly_dark", xaxis_title="Years from Today",
                             yaxis_title="Estimated Value (CAD)", hovermode="x unified")
        st.plotly_chart(fig_mc, use_container_width=True)
    else:
        st.info(
            "Add some assets to your portfolio first so the engine has data to simulate!")

# --- TAB 5: MACRO ENVIRONMENT ---
with tab5:
    st.header("🌍 Macro Environment")
    st.write("Understand the broader economic conditions driving market returns. Data sourced directly from the Federal Reserve Economic Data (FRED) API.")

    with st.spinner("Fetching Federal Reserve data..."):
        rates_df, cpi_df = get_macro_data()

    if not rates_df.empty and not cpi_df.empty:
        col_m1, col_m2 = st.columns(2)

        with col_m1:
            st.markdown("### 🏦 US Federal Funds Rate")
            st.caption(
                "The baseline interest rate. High rates pressure growth stocks and increase bond yields.")
            fig_rates = px.line(rates_df, x=rates_df.index,
                                y='FEDFUNDS', template="plotly_dark")
            fig_rates.update_traces(line_color="#3b82f6", line_width=3)
            fig_rates.update_layout(
                xaxis_title="", yaxis_title="Interest Rate (%)", margin=dict(t=10, l=0, r=0, b=0))
            st.plotly_chart(fig_rates, use_container_width=True)

        with col_m2:
            st.markdown("### 🛒 YoY US Inflation (CPI)")
            st.caption(
                "The rate at which prices are rising. High inflation generally hurts market valuations.")
            fig_cpi = px.line(cpi_df, x=cpi_df.index,
                              y='YoY Inflation (%)', template="plotly_dark")
            fig_cpi.update_traces(line_color="#FF4B4B", line_width=3)
            fig_cpi.add_hline(y=2.0, line_dash="dash",
                              line_color="white", annotation_text="2% Target")
            fig_cpi.update_layout(
                xaxis_title="", yaxis_title="Inflation (%)", margin=dict(t=10, l=0, r=0, b=0))
            st.plotly_chart(fig_cpi, use_container_width=True)
    else:
        st.error(
            "Could not fetch macroeconomic data. Check your API key or internet connection.")

# --- TAB OPTIMIZER ---
with tab_opt:
    st.header("🧠 S&P 500 / Nasdaq 100 Optimizer")
    st.markdown("This lab downloads the **~550 stocks** making up the S&P 500 and Nasdaq 100, finds the top 10 individual performers based on Sharpe Ratio, and calculates the mathematically optimal portfolio weights to maximize returns and minimize risk.")

    if st.button("Run Market Optimization", type="primary"):
        with st.spinner("Downloading 550+ stocks and running 10,000+ simulations (this may take up to 60 seconds)..."):
            universe = get_sp500_ndx_tickers()
            price_history = download_universe_data(universe)

            if not price_history.empty:
                opt_df, exp_ret, exp_vol, exp_sharpe = find_top_10_optimal_portfolio(
                    price_history)

                st.success("Optimization Complete!")
                c1, c2, c3 = st.columns(3)
                c1.metric("Expected Annual Return", f"{exp_ret:.2f}%")
                c2.metric("Expected Volatility (Risk)", f"{exp_vol:.2f}%")
                c3.metric("Expected Total Sharpe Ratio", f"{exp_sharpe:.2f}")

                st.dataframe(opt_df.style.format(
                    {"Optimal Weight (%)": "{:.1f}%", "Individual Sharpe Ratio": "{:.2f}"}), use_container_width=True, hide_index=True)

                fig_opt = px.pie(opt_df, values='Optimal Weight (%)', names='Ticker',
                                 title="Optimal Portfolio Allocation", template="plotly_dark")
                st.plotly_chart(fig_opt, use_container_width=True)
            else:
                st.error("Failed to download market data. Please try again.")

# --- TAB 2 & 3: ADD/MANAGE ASSETS ---
with tab2:
    st.header("➕ Add New Asset")
    with st.form("add_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        t_in = c1.text_input("Ticker Symbol (Type 'CASH' for cash positions)")
        curr_in = c1.selectbox("Currency", ["USD", "CAD"])
        p_in = c2.number_input(
            "Book Price (Set to 1.0 for Cash)", min_value=0.0)
        q_in = c2.number_input("Quantity", min_value=0.0)

        if st.form_submit_button("Identify & Save"):
            ticker_input = t_in.upper().strip()
            if ticker_input == "CASH":
                ticker = "CASH.CAD" if curr_in == "CAD" else "CASH.USD"
            else:
                ticker = ticker_input
                if curr_in == "CAD" and not ticker.endswith(".TO"):
                    ticker += ".TO"

            with st.spinner(f"Analyzing {ticker}..."):
                meta = get_smart_metadata(ticker)
                new_row = pd.DataFrame([{
                    "Ticker Symbol": ticker, "Name": meta["Name"], "Currency": curr_in, "Book Price": p_in,
                    "Quantity": q_in, "Sector": meta["Sector"], "Yield (%)": meta["Yield (%)"],
                    "P/E": meta["P/E"], "1Y Target": meta["1Y Target"], "Target Weight (%)": 0.0
                }])
                pd.concat([load_data(), new_row], ignore_index=True).to_csv(
                    DATA_FILE, index=False)
                st.success(f"Added {meta['Name']} ({ticker})")
                st.rerun()

with tab3:
    st.header("⚙️ Manage Database")
    st.write("Edit raw database entries here.")
    raw_edit = st.data_editor(
        load_data(), num_rows="dynamic", use_container_width=True)
    if st.button("Save Database Changes"):
        raw_edit.to_csv(DATA_FILE, index=False)
        st.success("Changes successfully saved!")
        st.rerun()
