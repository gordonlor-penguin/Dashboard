import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px
import plotly.graph_objects as go
import os
import re
import datetime

# --- 1. PASSWORD PROTECTION ---


def check_password():
    if st.session_state.get("password_correct"):
        return True

    def password_entered():
        if st.session_state["password_input"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password_input"]
    st.title("🔒 Portfolio Locked")
    st.text_input("Password", type="password",
                  on_change=password_entered, key="password_input")
    return False


if not check_password():
    st.stop()

# --- 2. DATA & METADATA ENGINES ---
DATA_FILE = "my_portfolio.csv"


def load_data():
    if not os.path.exists(DATA_FILE):
        pd.DataFrame(columns=["Ticker Symbol", "Name", "Currency", "Price",
                     "Quantity", "Sector", "Yield (%)"]).to_csv(DATA_FILE, index=False)

    df = pd.read_csv(DATA_FILE)
    if "Yield (%)" not in df.columns:
        df["Yield (%)"] = 0.0
    if "Region" in df.columns:
        df = df.drop(columns=["Region"])

    df["Price"] = pd.to_numeric(df["Price"].astype(str).str.replace(
        r'[$,]', '', regex=True), errors='coerce').fillna(0.0)
    df["Quantity"] = pd.to_numeric(df["Quantity"].astype(str).str.replace(
        r'[$,]', '', regex=True), errors='coerce').fillna(0.0)

    if not df.empty and "Currency" in df.columns and "Ticker Symbol" in df.columns:
        mask = (df["Currency"] == "CAD") & (~df["Ticker Symbol"].astype(
            str).str.upper().str.endswith(".TO", na=False))
        df.loc[mask, "Ticker Symbol"] = df.loc[mask,
                                               "Ticker Symbol"].astype(str).str.upper() + ".TO"

    return df


@st.cache_data(ttl=3600)
def get_benchmark_data(symbol="SPY"):
    try:
        bench = yf.Ticker(symbol).history(period="5y")['Close']
        if not bench.empty:
            bench.index = bench.index.tz_localize(None)
            return bench
    except Exception:
        pass
    dates = pd.date_range(end=datetime.datetime.today(), periods=1260)
    return pd.Series([100.0] * 1260, index=dates)


def get_smart_metadata(ticker_str):
    try:
        tk = yf.Ticker(str(ticker_str))
        info = tk.info
        name = info.get('longName', info.get('shortName', 'Unknown'))
        div_yield = info.get('dividendYield', info.get(
            'trailingAnnualDividendYield', 0.0))
        div_yield = float(div_yield) * 100 if div_yield else 0.0

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
                    sector = f"ETF: {info.get('category', 'Index')}"
            except:
                sector = f"ETF: {info.get('category', 'Index')}"
            # ETFs often report yield differently
            if div_yield == 0.0:
                div_yield = info.get('yield', 0.0) * 100
        else:
            sector = info.get('sector', 'Other')

        return name, sector, div_yield
    except:
        return "Unknown", "Unknown", 0.0


# --- 3. DASHBOARD UI SETUP ---
st.set_page_config(page_title="Pro Analytics", layout="wide", page_icon="📈")

st.markdown("""
    <style>
    .metric-card { background-color: #1E1E1E; padding: 15px; border-radius: 10px; border: 1px solid #333; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    </style>
""", unsafe_allow_html=True)

st.title("📊 Portfolio Intelligence")

tab1, tab2, tab3 = st.tabs(
    ["📈 Command Center", "➕ Add Asset", "⚙️ Manage Data"])

df = load_data()

# --- DATA PROCESSING ---
if not df.empty:
    df = df.dropna(subset=["Ticker Symbol"])
    tickers = df["Ticker Symbol"].unique()

    with st.spinner("Syncing 5-year data, dividends, and risk metrics..."):
        needs_save = False
        if "Name" not in df.columns:
            df["Name"] = "Unknown"
        if "Sector" not in df.columns:
            df["Sector"] = "Unknown"

        for idx, row in df.iterrows():
            current_sector = str(row.get("Sector"))
            current_name = str(row.get("Name"))

            needs_update = pd.isna(current_sector) or current_sector == "Unknown" or pd.isna(
                current_name) or current_name == "Unknown" or (current_sector.startswith("ETF:") and current_sector.count("|") == 2)

            if needs_update:
                n, s, dy = get_smart_metadata(row["Ticker Symbol"])
                df.at[idx, "Name"] = n
                df.at[idx, "Sector"] = s
                df.at[idx, "Yield (%)"] = dy
                needs_save = True

        if needs_save:
            df.to_csv(DATA_FILE, index=False)

        try:
            fx_hist = yf.Ticker("USDCAD=X").history(period="5y")['Close']
            fx_hist.index = fx_hist.index.tz_localize(None)
        except:
            fx_hist = pd.Series(1.38, index=pd.date_range(
                end=datetime.datetime.today(), periods=1260))

        fx_rate = fx_hist.iloc[-1] if not fx_hist.empty else 1.38

        hist_prices = {}
        prices = {}
        for t in tickers:
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

        benchmark_history_raw = get_benchmark_data("SPY")
        master_dates = fx_hist.index
        port_val_series_all = pd.Series(0.0, index=master_dates)

        for _, row in df.iterrows():
            t = row["Ticker Symbol"]
            q = row["Quantity"]
            curr = row["Currency"]

            if t in hist_prices and not hist_prices[t].empty:
                asset_history = hist_prices[t].reindex(
                    master_dates).ffill().bfill()
                if curr == "USD":
                    daily_val = asset_history * q * fx_hist
                else:
                    daily_val = asset_history * q
                port_val_series_all += daily_val.fillna(0.0)

    # Core Calculations
    df["Live Price"] = df["Ticker Symbol"].map(prices).fillna(0.0)
    df["Value (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Live Price"]) *
                                 fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Live Price"]), axis=1)
    df["Cost Basis (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Price"]) *
                                      fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Price"]), axis=1)
    df["Annual Income (CAD)"] = df["Value (CAD)"] * (df["Yield (%)"] / 100)

    total_val_cad = df["Value (CAD)"].sum()
    total_val_usd = total_val_cad / fx_rate if fx_rate > 0 else 0.0
    total_cost = df["Cost Basis (CAD)"].sum()
    total_pl_pct = ((total_val_cad - total_cost) / total_cost) * \
        100 if total_cost > 0 else 0.0

    total_income = df["Annual Income (CAD)"].sum()
    portfolio_yield = (total_income / total_val_cad) * \
        100 if total_val_cad > 0 else 0.0

    if len(port_val_series_all) >= 2 and port_val_series_all.iloc[-2] > 0:
        daily_pl_pct = (
            (port_val_series_all.iloc[-1] - port_val_series_all.iloc[-2]) / port_val_series_all.iloc[-2]) * 100
    else:
        daily_pl_pct = 0.0

# --- TAB 1: COMMAND CENTER ---
with tab1:
    if not df.empty:
        # 1. TOP METRICS ROW
        st.markdown("### 💰 Portfolio Overview")
        col1, col2, col3, col4, col5 = st.columns(5)
        col1.metric("Total Value (CAD)",
                    f"${total_val_cad:,.2f}", f"1-Day: {daily_pl_pct:.2f}%")
        col2.metric("Total Value (USD)", f"${total_val_usd:,.2f}")
        col3.metric("All-Time Return", f"{total_pl_pct:.2f}%")
        col4.metric("Est. Annual Income", f"${total_income:,.2f}",
                    f"Yield: {portfolio_yield:.2f}%", delta_color="off")
        col5.metric("USD/CAD Rate", f"{fx_rate:.4f}")

        st.divider()

        # 2. TIMEFRAME CONTROLS & FILTERING
        timeframe = st.radio("Select Timeframe", [
                             "1M", "YTD", "1Y", "3Y", "5Y"], horizontal=True, index=2)

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

        # Slice data
        port_val_series = port_val_series_all[port_val_series_all.index >= start_date]
        bench_slice = benchmark_history_raw[benchmark_history_raw.index >= start_date]

        # Risk Math on Sliced Data
        daily_returns = port_val_series.pct_change().dropna()
        bench_returns = bench_slice.pct_change().dropna()

        # Align index for beta calc
        aligned_returns = pd.concat(
            [daily_returns, bench_returns], axis=1).dropna()
        aligned_returns.columns = ['Port', 'Bench']

        if len(aligned_returns) > 2 and aligned_returns['Bench'].var() != 0:
            beta = aligned_returns['Port'].cov(
                aligned_returns['Bench']) / aligned_returns['Bench'].var()
        else:
            beta = 1.0

        sharpe = (daily_returns.mean() * 252 - 0.04) / (daily_returns.std()
                                                        * np.sqrt(252)) if daily_returns.std() != 0 else 0
        drawdown = (port_val_series / port_val_series.cummax()) - 1
        max_dd = drawdown.min() * 100 if not drawdown.empty else 0.0

        # 3. CHARTS & RISK METRICS
        c_chart, c_risk = st.columns([3, 1])

        with c_chart:
            st.markdown(f"**Performance Trend ({timeframe})**")
            port_val_df = port_val_series.reset_index()
            port_val_df.columns = ["Date", "Value (CAD)"]
            fig_area = px.area(port_val_df, x="Date", y="Value (CAD)",
                               template="plotly_dark", color_discrete_sequence=['#00C9B1'])
            fig_area.update_layout(xaxis_title="", yaxis_title="CAD",
                                   hovermode="x unified", margin=dict(l=0, r=0, t=10, b=10))
            st.plotly_chart(fig_area, use_container_width=True)

            port_normalized = (
                port_val_series / port_val_series.iloc[0]) * 100 if not port_val_series.empty else pd.Series()
            bench_normalized = (
                bench_slice / bench_slice.iloc[0]) * 100 if not bench_slice.empty else pd.Series()

            comp_df = pd.DataFrame(
                {"S&P 500": bench_normalized, "My Portfolio": port_normalized}).dropna()
            fig_line = px.line(comp_df, template="plotly_dark", color_discrete_map={
                               "My Portfolio": "#00C9B1", "S&P 500": "#A0A0A0"})
            fig_line.update_layout(xaxis_title="", yaxis_title="Indexed to 100",
                                   legend_title="", hovermode="x unified", margin=dict(l=0, r=0, t=10, b=10))
            st.markdown(f"**Vs. S&P 500 Benchmark ({timeframe})**")
            st.plotly_chart(fig_line, use_container_width=True)

        with c_risk:
            st.markdown("**Risk Profile**")
            st.info(
                f"**Beta:** {beta:.2f}\n\n*<1.0 = Less volatile than market. >1.0 = More volatile.*")
            st.warning(
                f"**Max Drawdown:** {max_dd:.2f}%\n\n*Worst drop from peak in this timeframe.*")

            if sharpe > 1:
                st.success(
                    f"**Sharpe Ratio:** {sharpe:.2f}\n\n*Excellent risk-adjusted returns.*")
            elif sharpe > 0:
                st.info(
                    f"**Sharpe Ratio:** {sharpe:.2f}\n\n*Positive risk-adjusted returns.*")
            else:
                st.error(
                    f"**Sharpe Ratio:** {sharpe:.2f}\n\n*Sub-optimal risk-adjusted returns.*")

        st.divider()

        # 4. WINNERS, LOSERS & WEIGHTING
        st.markdown("### 🏆 Asset Breakdown: Winners vs. Losers")

        # Calculate individual returns
        df["Asset Return (%)"] = np.where(df["Cost Basis (CAD)"] > 0, ((
            df["Value (CAD)"] - df["Cost Basis (CAD)"]) / df["Cost Basis (CAD)"]) * 100, 0)
        df["Portfolio Weight (%)"] = (df["Value (CAD)"] / total_val_cad) * 100

        bar_df = df[df["Value (CAD)"] > 0].sort_values(
            "Asset Return (%)", ascending=True)
        bar_df["Color"] = np.where(
            bar_df["Asset Return (%)"] > 0, '#00C9B1', '#FF4B4B')

        fig_bar = px.bar(bar_df, x="Asset Return (%)", y="Ticker Symbol", orientation='h',
                         hover_data=["Name", "Portfolio Weight (%)"], color="Color", color_discrete_map="identity",
                         template="plotly_dark")
        fig_bar.update_layout(showlegend=False, xaxis_title="All-Time Return (%)",
                              yaxis_title="", margin=dict(l=0, r=0, t=10, b=10))
        st.plotly_chart(fig_bar, use_container_width=True)

        # 5. ALLOCATION
        st.markdown("### 🧩 Portfolio Allocation")
        c1, c2 = st.columns([2, 1])

        chart_df = df[df["Value (CAD)"] > 0].copy()
        expanded_records = []
        for _, row in chart_df.iterrows():
            val = row["Value (CAD)"]
            ticker, name, sec_str = row["Ticker Symbol"], str(
                row.get("Name", "Unknown")), str(row["Sector"])
            display_label = f"{ticker} - {name}"

            if sec_str.startswith("ETF:") and "%" in sec_str:
                parts = sec_str.replace("ETF:", "").strip().split('|')
                allocated = 0.0
                for p in parts:
                    match = re.search(r'(.*)\(([\d.]+)%\)', p)
                    if match:
                        pct = float(match.group(2))
                        allocated += pct
                        expanded_records.append({"Label": display_label, "Sector": match.group(
                            1).strip(), "Value": val * (pct / 100.0)})
                if 100.0 - allocated > 0.5:
                    expanded_records.append(
                        {"Label": display_label, "Sector": "Other", "Value": val * ((100.0 - allocated) / 100.0)})
            else:
                expanded_records.append({"Label": display_label, "Sector": sec_str.replace(
                    "ETF:", "").strip() if sec_str.startswith("ETF:") else sec_str, "Value": val})

        expanded_df = pd.DataFrame(expanded_records)
        expanded_df["Root"] = "Total"

        with c1:
            if not expanded_df.empty:
                fig_tree = px.treemap(expanded_df, path=[
                                      "Root", 'Sector', 'Label'], values='Value', color='Sector', template="plotly_dark")
                fig_tree.update_layout(margin=dict(t=0, l=0, r=0, b=0))
                st.plotly_chart(fig_tree, use_container_width=True)

        with c2:
            if not expanded_df.empty:
                sector_dist = expanded_df.groupby(
                    "Sector")["Value"].sum().reset_index()
                fig_pie = px.pie(sector_dist, values='Value',
                                 names='Sector', hole=0.6, template="plotly_dark")
                fig_pie.update_layout(margin=dict(t=0, l=0, r=0, b=0))
                st.plotly_chart(fig_pie, use_container_width=True)

        # 6. LEDGER
        st.divider()
        st.markdown("### 📑 Detailed Ledger")

        display_cols = ["Ticker Symbol", "Name", "Sector", "Quantity", "Avg Purchase Price",
                        "Live Price", "Value (CAD)", "Portfolio Weight (%)", "Yield (%)", "Asset Return (%)"]

        # Group to combine identical tickers
        df["Cost * Qty"] = df["Price"] * df["Quantity"]
        grouped = df.groupby(["Ticker Symbol", "Name", "Sector", "Live Price", "Yield (%)"]).agg(
            Quantity=('Quantity', 'sum'), Total_Cost=('Cost * Qty', 'sum'), Value_CAD=('Value (CAD)', 'sum')
        ).reset_index()

        grouped["Avg Purchase Price"] = grouped["Total_Cost"] / \
            grouped["Quantity"]
        grouped["Portfolio Weight (%)"] = (
            grouped["Value_CAD"] / total_val_cad) * 100
        grouped["Asset Return (%)"] = (
            (grouped["Value_CAD"] - grouped["Total_Cost"]) / grouped["Total_Cost"]) * 100
        grouped = grouped.rename(
            columns={"Value_CAD": "Value (CAD)"}).fillna(0)

        st.dataframe(grouped[display_cols].style.format({
            "Avg Purchase Price": "${:,.2f}", "Live Price": "${:,.2f}", "Value (CAD)": "${:,.2f}",
            "Quantity": "{:,.4g}", "Portfolio Weight (%)": "{:.2f}%", "Yield (%)": "{:.2f}%", "Asset Return (%)": "{:+.2f}%"
        }).map(lambda x: 'color: #00C9B1' if x > 0 else ('color: #FF4B4B' if x < 0 else ''), subset=["Asset Return (%)"]),
            use_container_width=True, hide_index=True)

    else:
        st.info("Your portfolio is empty. Add assets in the 'Add Asset' tab.")

# --- TAB 2: ADD ASSET ---
with tab2:
    st.header("➕ Add New Asset")
    with st.form("add_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        t_in = c1.text_input("Ticker Symbol (e.g., AAPL, TD)")
        curr_in = c1.selectbox("Currency", ["USD", "CAD"])
        p_in = c2.number_input("Avg Purchase Price", min_value=0.0)
        q_in = c2.number_input("Quantity", min_value=0.0)

        if st.form_submit_button("Identify & Save"):
            ticker = t_in.upper().strip()
            if curr_in == "CAD" and not ticker.endswith(".TO"):
                ticker += ".TO"
            with st.spinner(f"Analyzing {ticker}..."):
                n, s, dy = get_smart_metadata(ticker)
                new_row = pd.DataFrame([{"Ticker Symbol": ticker, "Name": n, "Currency": curr_in,
                                       "Price": p_in, "Quantity": q_in, "Sector": s, "Yield (%)": dy}])
                pd.concat([load_data(), new_row], ignore_index=True).to_csv(
                    DATA_FILE, index=False)
                st.success(f"Added {n} ({ticker})")
                st.rerun()

# --- TAB 3: MANAGE DATA ---
with tab3:
    st.header("⚙️ Manage Database")
    st.write("Edit raw database entries here.")
    raw_edit = st.data_editor(
        load_data(), num_rows="dynamic", use_container_width=True)
    if st.button("Save Database Changes"):
        raw_edit.to_csv(DATA_FILE, index=False)
        st.success("Changes successfully saved!")
        st.rerun()
