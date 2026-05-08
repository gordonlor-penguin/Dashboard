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

    st.title("📊 Portfolio Tracker")
    st.markdown("### 🔐 Secure Login")
    st.text_input("Enter Access Key", type="password",
                  on_change=password_entered, key="password_input")
    return False


if not check_password():
    st.stop()

# --- 2. DATA ENGINES ---
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

    df["Book Price"] = pd.to_numeric(df["Book Price"].astype(str).str.replace(
        r'[$,]', '', regex=True), errors='coerce').fillna(0.0)
    df["Quantity"] = pd.to_numeric(df["Quantity"].astype(str).str.replace(
        r'[$,]', '', regex=True), errors='coerce').fillna(0.0)

    if not df.empty:
        mask = (df["Currency"] == "CAD") & (~df["Ticker Symbol"].astype(str).str.upper().str.endswith(
            ".TO", na=False)) & (~df["Ticker Symbol"].astype(str).str.upper().str.startswith("CASH"))
        df.loc[mask, "Ticker Symbol"] = df.loc[mask,
                                               "Ticker Symbol"].astype(str).str.upper() + ".TO"
    return df


@st.cache_data(ttl=86400)
def get_smart_metadata(ticker_str):
    if str(ticker_str).upper().startswith("CASH"):
        return {"Name": "Cash Position", "Sector": "Cash", "Yield (%)": 0.0, "P/E": np.nan, "1Y Target": np.nan}

    try:
        tk = yf.Ticker(str(ticker_str))
        info = tk.info
        name = info.get('longName', info.get('shortName', 'Unknown Asset'))
        raw_yield = info.get('dividendYield', info.get(
            'trailingAnnualDividendYield', 0.0))
        div_yield = (float(raw_yield) * 100) if (raw_yield and raw_yield <
                                                 0.30) else (raw_yield or 0.0)

        if info.get('quoteType') == 'ETF':
            try:
                sectors = tk.funds_data.sector_weightings
                if sectors:
                    sorted_sec = sorted(
                        sectors.items(), key=lambda x: x[1], reverse=True)
                    sector = "ETF: " + \
                        " | ".join(
                            [f"{k.replace('_', ' ').title()} ({v*100:.1f}%)" for k, v in sorted_sec if v > 0.01])
                else:
                    sector = f"ETF: {info.get('category', 'Index')}"
            except:
                sector = f"ETF: {info.get('category', 'Index')}"
        else:
            sector = info.get('sector', 'Other')

        return {"Name": name, "Sector": sector, "Yield (%)": div_yield, "P/E": info.get('trailingPE', np.nan), "1Y Target": info.get('targetMeanPrice', np.nan)}
    except:
        return {"Name": "Unknown", "Sector": "Unknown", "Yield (%)": 0.0, "P/E": np.nan, "1Y Target": np.nan}


@st.cache_data(ttl=300)
def get_market_data(tickers_tuple):
    try:
        fx_hist = yf.Ticker("USDCAD=X").history(
            period="5y")['Close'].tz_localize(None)
        fx_rate = fx_hist.iloc[-1]
    except:
        fx_hist = pd.Series(1.38, index=pd.date_range(
            end=datetime.datetime.today(), periods=1260))
        fx_rate = 1.38

    hist_prices, prices = {}, {}
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
        except:
            pass

    return hist_prices, prices, fx_hist, fx_rate


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
        except:
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
        except:
            pass

    news_items.sort(key=lambda x: x['Time'], reverse=True)
    return news_items


@st.cache_data(ttl=86400)
def get_macro_data():
    try:
        api_key = st.secrets["fred_api_key"]
        r_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=FEDFUNDS&api_key={api_key}&file_type=json"
        c_url = f"https://api.stlouisfed.org/fred/series/observations?series_id=CPIAUCSL&api_key={api_key}&file_type=json"
        r_data = requests.get(r_url).json()
        c_data = requests.get(c_url).json()

        rates = pd.DataFrame(r_data['observations'])[['date', 'value']]
        rates['date'] = pd.to_datetime(rates['date'])
        rates['value'] = pd.to_numeric(rates['value'], errors='coerce')

        cpi = pd.DataFrame(c_data['observations'])[['date', 'value']]
        cpi['date'] = pd.to_datetime(cpi['date'])
        cpi['value'] = pd.to_numeric(cpi['value'], errors='coerce')
        cpi['YoY Inflation (%)'] = cpi['value'].pct_change(12) * 100

        rates.set_index('date', inplace=True)
        cpi.set_index('date', inplace=True)
        return rates.dropna().tail(1260), cpi.dropna().tail(1260)
    except:
        return pd.DataFrame(), pd.DataFrame()

# --- 3. OPTIMIZER ENGINES ---


@st.cache_data(ttl=86400)
def get_sp500_ndx_tickers():
    """Scrapes S&P 500 and Nasdaq 100 tickers from Wikipedia."""
    try:
        # S&P 500
        sp500_table = pd.read_html(
            'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies')[0]
        sp_tickers = sp500_table['Symbol'].str.replace('.', '-').tolist()

        # Nasdaq 100
        ndx_table = pd.read_html('https://en.wikipedia.org/wiki/Nasdaq-100')[4]
        ndx_tickers = ndx_table['Ticker'].str.replace('.', '-').tolist()

        combined = list(set(sp_tickers + ndx_tickers))
        return combined
    except:
        return ['AAPL', 'MSFT', 'GOOGL', 'AMZN', 'NVDA', 'META', 'TSLA', 'AVGO', 'PEP', 'COST']


@st.cache_data(ttl=86400)
def download_universe_data(tickers):
    """Downloads 2 years of daily closing prices for the massive universe."""
    data = yf.download(tickers, period="2y", interval="1d")['Close']
    return data.dropna(axis=1, thresh=len(data)*0.9).ffill()


def find_top_10_optimal_portfolio(price_data, risk_free_rate=0.04):
    returns = price_data.pct_change().dropna()

    ind_ret = returns.mean() * 252
    ind_vol = returns.std() * np.sqrt(252)
    ind_sharpe = (ind_ret - risk_free_rate) / ind_vol

    top_10_tickers = ind_sharpe.nlargest(10).index.tolist()
    top_10_returns = returns[top_10_tickers]

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

    results_df = pd.DataFrame({
        "Ticker": top_10_tickers,
        "Optimal Weight (%)": optimal_weights
    }).sort_values(by="Optimal Weight (%)", ascending=False)

    return results_df, final_ret, final_vol


# --- 4. DASHBOARD UI SETUP ---
st.set_page_config(page_title="Portfolio Tracker",
                   layout="wide", page_icon="📈")
st.title("📊 Portfolio Tracker")

# ADDED TAB 6 FOR OPTIMIZER
tab1, tab_news, tab4, tab5, tab_opt, tab2, tab3 = st.tabs(
    ["📈 Command Center", "📰 Live News", "🔮 Forecast", "🌍 Macro", "🧠 Optimizer Lab", "➕ Add Asset", "⚙️ Manage Data"])
df = load_data()

# --- DATA PROCESSING ---
if not df.empty:
    tickers = df["Ticker Symbol"].unique()
    with st.spinner("Syncing Market Engines..."):
        needs_save = False
        for idx, row in df.iterrows():
            if pd.isna(row.get("Sector")) or row.get("Sector") == "Unknown":
                meta = get_smart_metadata(row["Ticker Symbol"])
                for k, v in meta.items():
                    df.at[idx, k] = v
                needs_save = True
        if needs_save:
            df.to_csv(DATA_FILE, index=False)

        hist_prices, prices, fx_hist, fx_rate = get_market_data(tuple(tickers))
        master_dates = fx_hist.index
        port_val_series = pd.Series(0.0, index=master_dates)

        for _, row in df.iterrows():
            t, q, curr = row["Ticker Symbol"], row["Quantity"], row["Currency"]
            if t in hist_prices:
                asset_h = hist_prices[t].reindex(master_dates).ffill().bfill()
                port_val_series += (asset_h * q *
                                    fx_hist if curr == "USD" else asset_h * q)

    df["Live Price"] = df["Ticker Symbol"].map(prices).fillna(0.0)
    df["Value (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Live Price"]) *
                                 fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Live Price"]), axis=1)
    df["Cost Basis (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Book Price"]) *
                                      fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Book Price"]), axis=1)
    df["Income (CAD)"] = df["Value (CAD)"] * \
        (pd.to_numeric(df["Yield (%)"], errors='coerce').fillna(0)/100)

    total_val = df["Value (CAD)"].sum()
    total_cost = df["Cost Basis (CAD)"].sum()
    total_ret_pct = ((total_val - total_cost)/total_cost) * \
        100 if total_cost > 0 else 0

    grouped = df.groupby(["Ticker Symbol", "Name", "Sector", "Live Price", "Yield (%)"]).agg(
        {"Quantity": "sum", "Value (CAD)": "sum", "Cost Basis (CAD)": "sum", "Income (CAD)": "sum"}).reset_index()
    grouped["Gain/Loss ($)"] = grouped["Value (CAD)"] - \
        grouped["Cost Basis (CAD)"]
    grouped["Weight (%)"] = (grouped["Value (CAD)"]/total_val)*100
    grouped["Return (%)"] = ((grouped["Value (CAD)"] -
                              grouped["Cost Basis (CAD)"])/grouped["Cost Basis (CAD)"])*100

# --- TAB 1: COMMAND CENTER ---
with tab1:
    if not df.empty:
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Value (CAD)", f"${total_val:,.2f}")
        c2.metric("Total Gain/Loss",
                  f"${total_val - total_cost:,.2f}", f"{total_ret_pct:+.2f}%")
        c3.metric("Annual Income", f"${df['Income (CAD)'].sum():,.2f}")
        c4.metric("USD/CAD", f"{fx_rate:.4f}")

        st.divider()
        col_chart, col_risk = st.columns([3, 1])
        with col_chart:
            timeframe = st.radio(
                "Chart View", ["1Y", "3Y", "5Y"], horizontal=True)
            days = 365 if timeframe == "1Y" else (
                1095 if timeframe == "3Y" else 1825)
            start_date = datetime.datetime.now() - datetime.timedelta(days=days)

            port_slice = port_val_series[port_val_series.index >= start_date]
            fig_main = px.line(
                port_slice, title="Historical Portfolio Value ($ CAD)", template="plotly_dark")
            fig_main.update_layout(yaxis_title="Value ($ CAD)", xaxis_title="")
            st.plotly_chart(fig_main, use_container_width=True)

        with col_risk:
            st.markdown("### 🛡️ Risk Profile")
            daily_ret = port_val_series.pct_change().dropna()
            vol = daily_ret.std() * np.sqrt(252) * 100
            dd = (port_val_series / port_val_series.cummax() - 1).min() * 100
            st.info(f"**Annual Volatility:** {vol:.2f}%")
            st.warning(f"**Max Drawdown:** {dd:.2f}%")
            st.success(
                f"**Sharpe Ratio:** {((total_ret_pct/5) - 4) / vol:.2f}" if vol > 0 else "N/A")

        st.divider()
        st.markdown("### 🧩 Allocation")
        st.plotly_chart(px.treemap(grouped, path=["Sector", "Ticker Symbol"], values="Value (CAD)",
                        color="Return (%)", color_continuous_scale='RdYlGn', template="plotly_dark"), use_container_width=True)

        st.divider()
        display_columns = ["Ticker Symbol", "Name", "Sector", "Quantity",
                           "Live Price", "Value (CAD)", "Gain/Loss ($)", "Return (%)", "Weight (%)"]
        st.dataframe(grouped[display_columns].style.format({
            "Live Price": "${:.2f}", "Value (CAD)": "${:,.2f}", "Gain/Loss ($)": "${:+,.2f}",
            "Weight (%)": "{:.1f}%", "Return (%)": "{:+.1f}%"
        }), use_container_width=True, hide_index=True)
    else:
        st.info("Welcome! Add assets in the 'Add Asset' tab to begin.")

# --- TAB 2: NEWS ---
with tab_news:
    st.header("📰 Live Market News")
    if not df.empty:
        news = get_portfolio_news(grouped.sort_values(
            "Weight (%)", ascending=False).head(5)["Ticker Symbol"].tolist())
        if news and news[0]["Ticker"] == "MARKET":
            st.warning("Showing general market news.")
        if news:
            for n in news:
                tag = f"🌎 {n['Ticker']}" if n['Ticker'] == "MARKET" else f"📌 {n['Ticker']}"
                st.markdown(f"**[{tag}]** [{n['Title']}]({n['Link']})")
                st.caption(
                    f"{n['Publisher']} • {n['Time'].strftime('%b %d, %Y')}")
                st.divider()
        else:
            st.error("No news found. Please check your internet connection.")

# --- TAB 3: FORECAST ---
with tab4:
    if not df.empty:
        st.header("🎲 Wealth Projection")
        years = st.slider("Years to Forecast", 1, 30, 10)
        mu, vol, sims = 0.08, 0.15, 500
        res = np.zeros((years + 1, sims))
        res[0, :] = total_val
        for y in range(1, years + 1):
            res[y, :] = res[y-1, :] * \
                np.exp((mu - 0.5 * vol**2) + vol *
                       np.random.normal(0, 1, sims))
        p = np.percentile(res, [10, 50, 90], axis=1)
        fig_mc = go.Figure()
        for i, (name, color) in enumerate([('Bear Case', '#FF4B4B'), ('Base Case', '#3b82f6'), ('Bull Case', '#00C9B1')]):
            fig_mc.add_trace(go.Scatter(x=np.arange(
                years+1), y=p[i], name=name, line=dict(color=color, width=3 if i == 1 else 1)))
        st.plotly_chart(fig_mc.update_layout(template="plotly_dark",
                        yaxis_title="Portfolio Value (CAD)"), use_container_width=True)

# --- TAB 4: MACRO ---
with tab5:
    st.header("🌍 Macro Environment")
    r, c = get_macro_data()
    if not r.empty:
        cm1, cm2 = st.columns(2)
        cm1.plotly_chart(px.line(r, y="FEDFUNDS", title="US Fed Funds Rate",
                         template="plotly_dark"), use_container_width=True)
        cm2.plotly_chart(px.line(c, y="YoY Inflation (%)", title="US Inflation (YoY)",
                         template="plotly_dark").add_hline(y=2.0, line_dash="dash"), use_container_width=True)
    else:
        st.error("Please ensure your FRED API key is set in Streamlit Secrets.")

# --- TAB 5: OPTIMIZER LAB ---
with tab_opt:
    st.header("🧠 S&P 500 / Nasdaq 100 Optimizer")
    st.markdown("This lab downloads the **~550 stocks** making up the S&P 500 and Nasdaq 100, finds the top 10 individual performers based on Sharpe Ratio, and calculates the absolute mathematically optimal portfolio weights to maximize returns and minimize risk.")
    st.info("💡 **Note:** Downloading 2 years of data for 550 stocks takes a minute or two. Please be patient on the first run!")

    if st.button("Run Market Optimization", type="primary"):
        with st.spinner("Downloading 550+ stocks and running 10,000+ simulations (this may take up to 60 seconds)..."):
            universe = get_sp500_ndx_tickers()
            price_history = download_universe_data(universe)

            if not price_history.empty:
                opt_df, exp_ret, exp_vol = find_top_10_optimal_portfolio(
                    price_history)

                st.success("Optimization Complete!")
                c1, c2 = st.columns(2)
                c1.metric("Expected Annual Return", f"{exp_ret:.2f}%")
                c2.metric("Expected Volatility (Risk)", f"{exp_vol:.2f}%")

                st.dataframe(opt_df.style.format(
                    {"Optimal Weight (%)": "{:.1f}%"}), use_container_width=True, hide_index=True)

                fig_opt = px.pie(opt_df, values='Optimal Weight (%)', names='Ticker',
                                 title="Optimal Portfolio Allocation", template="plotly_dark")
                st.plotly_chart(fig_opt, use_container_width=True)
            else:
                st.error("Failed to download market data. Please try again.")

# --- TAB 6 & 7: MANAGEMENT ---
with tab2:
    with st.form("add_asset", clear_on_submit=True):
        st.header("➕ Add Asset")
        c1, c2 = st.columns(2)
        t_in = c1.text_input("Ticker Symbol (Type 'CASH' for cash positions)")
        curr_in = c1.selectbox("Currency", ["USD", "CAD"])
        p_in = c2.number_input(
            "Avg Book Price (Set to 1.0 for Cash)", min_value=0.01, value=1.00)
        q_in = c2.number_input("Quantity", min_value=0.01, value=100.00)

        if st.form_submit_button("Add to Portfolio"):
            ticker_input = t_in.upper().strip()
            if ticker_input == "CASH":
                ticker = "CASH.CAD" if curr_in == "CAD" else "CASH.USD"
            else:
                ticker = ticker_input + \
                    (".TO" if curr_in ==
                     "CAD" and not ticker_input.endswith(".TO") else "")

            meta = get_smart_metadata(ticker)
            new_row = pd.DataFrame([{"Ticker Symbol": ticker, "Name": meta["Name"], "Currency": curr_in,
                                   "Book Price": p_in, "Quantity": q_in, "Sector": meta["Sector"], "Yield (%)": meta["Yield (%)"]}])
            pd.concat([load_data(), new_row], ignore_index=True).to_csv(
                DATA_FILE, index=False)
            st.success(f"Added {ticker}!")
            st.rerun()

with tab3:
    st.header("⚙️ Data Management")
    edited_df = st.data_editor(
        load_data(), num_rows="dynamic", use_container_width=True)
    if st.button("Save Database Changes"):
        edited_df.to_csv(DATA_FILE, index=False)
        st.success("Database Updated!")
        st.rerun()
