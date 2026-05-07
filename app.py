import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
import plotly.express as px
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

    df["Book Price"] = pd.to_numeric(df["Book Price"].astype(str).str.replace(
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
def get_benchmarks():
    benchmarks = {}
    for ticker in ["SPY", "QQQ"]:
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
    try:
        tk = yf.Ticker(str(ticker_str))
        info = tk.info
        name = info.get('longName', info.get('shortName', 'Unknown'))

        raw_yield = info.get('dividendYield', info.get(
            'trailingAnnualDividendYield', info.get('yield', 0.0)))

        if raw_yield is None:
            div_yield = 0.0
        elif isinstance(raw_yield, str) and '%' in raw_yield:
            div_yield = float(raw_yield.replace('%', '').strip())
        else:
            div_yield = float(raw_yield)
            if 0.0 < div_yield < 0.30:
                div_yield *= 100

        pe = info.get('trailingPE', np.nan)
        target = info.get('targetMeanPrice', np.nan)

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
        else:
            sector = info.get('sector', 'Other')

        return {"Name": name, "Sector": sector, "Yield (%)": div_yield, "P/E": pe, "1Y Target": target}
    except:
        return {"Name": "Unknown", "Sector": "Unknown", "Yield (%)": 0.0, "P/E": np.nan, "1Y Target": np.nan}


@st.cache_data(ttl=300)
def get_market_data(tickers_tuple):
    hist_prices, prices = {}, {}
    for t in tickers_tuple:
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

    try:
        fx_hist = yf.Ticker("USDCAD=X").history(period="5y")['Close']
        fx_hist.index = fx_hist.index.tz_localize(None)
        fx_rate = fx_hist.iloc[-1] if not fx_hist.empty else 1.38
    except:
        fx_hist = pd.Series(1.38, index=pd.date_range(
            end=datetime.datetime.today(), periods=1260))
        fx_rate = 1.38

    return hist_prices, prices, fx_hist, fx_rate


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

    with st.spinner("Syncing live market data and fundamentals..."):
        needs_save = False
        progress_bar = st.progress(0)
        total_tickers = len(tickers)

        for idx, row in df.iterrows():
            current_sector = str(row.get("Sector"))
            current_name = str(row.get("Name"))
            needs_update = (
                pd.isna(current_sector) or current_sector == "Unknown" or
                pd.isna(current_name) or current_name == "Unknown" or
                pd.isna(row.get("P/E"))
            )
            if needs_update:
                meta = get_smart_metadata(row["Ticker Symbol"])
                for k, v in meta.items():
                    if k == "Yield (%)" and pd.notna(row.get("Yield (%)")) and row.get("Yield (%)") > 0:
                        continue
                    df.at[idx, k] = v
                needs_save = True

            ticker_idx = np.where(tickers == row["Ticker Symbol"])[0][0]
            progress_bar.progress((ticker_idx + 1) / total_tickers)

        if needs_save:
            df.to_csv(DATA_FILE, index=False)
        progress_bar.empty()

        hist_prices, prices, fx_hist, fx_rate = get_market_data(tuple(tickers))
        benchmarks = get_benchmarks()

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
    total_cost = df["Cost Basis (CAD)"].sum()
    total_pl_pct = ((total_val_cad - total_cost) / total_cost) * \
        100 if total_cost > 0 else 0.0

    total_income = df["Annual Income (CAD)"].sum()
    portfolio_yield = (total_income / total_val_cad) * \
        100 if total_val_cad > 0 else 0.0

    daily_pl_pct = ((port_val_series_all.iloc[-1] - port_val_series_all.iloc[-2]) / port_val_series_all.iloc[-2]) * 100 if len(
        port_val_series_all) >= 2 and port_val_series_all.iloc[-2] > 0 else 0.0

    df["Native_Cost_Total"] = df["Book Price"] * df["Quantity"]
    grouped = df.groupby(["Ticker Symbol", "Name", "Currency", "Sector", "Live Price", "Yield (%)", "P/E", "1Y Target"], dropna=False).agg(
        Quantity=('Quantity', 'sum'),
        Total_Native_Cost=('Native_Cost_Total', 'sum'),
        Total_Cost_CAD=('Cost Basis (CAD)', 'sum'),
        Value_CAD=('Value (CAD)', 'sum'),
        Value_USD=('Value (USD)', 'sum'),
        Target_Weight=('Target Weight (%)', 'max')
    ).reset_index()

    grouped["Avg Book Price"] = grouped["Total_Native_Cost"] / \
        grouped["Quantity"]
    grouped["Portfolio Weight (%)"] = (
        grouped["Value_CAD"] / total_val_cad) * 100 if total_val_cad > 0 else 0.0
    grouped["Asset Return (%)"] = np.where(grouped["Total_Cost_CAD"] > 0, ((
        grouped["Value_CAD"] - grouped["Total_Cost_CAD"]) / grouped["Total_Cost_CAD"]) * 100, 0)

    grouped = grouped.rename(columns={
        "Value_CAD": "Value (CAD)",
        "Value_USD": "Value (USD)",
        "Target_Weight": "Target Weight (%)"
    }).fillna(np.nan)

# --- TAB 1: COMMAND CENTER ---
with tab1:
    if not df.empty:
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

        port_slice = port_val_series_all[port_val_series_all.index >= start_date]
        spy_slice = benchmarks.get("SPY", pd.Series())[
            benchmarks.get("SPY", pd.Series()).index >= start_date]
        qqq_slice = benchmarks.get("QQQ", pd.Series())[
            benchmarks.get("QQQ", pd.Series()).index >= start_date]

        c_chart, c_risk = st.columns([3, 1])
        with c_chart:
            st.markdown(f"**Comparative Return ({timeframe})**")
            if len(port_slice) > 0:
                port_norm = (port_slice / port_slice.iloc[0] - 1) * 100
                chart_data = pd.DataFrame({"My Portfolio": port_norm})
                if not spy_slice.empty and len(spy_slice) > 0:
                    chart_data["S&P 500"] = (
                        spy_slice / spy_slice.iloc[0] - 1) * 100
                if not qqq_slice.empty and len(qqq_slice) > 0:
                    chart_data["Nasdaq 100"] = (
                        qqq_slice / qqq_slice.iloc[0] - 1) * 100

                chart_data = chart_data.dropna().reset_index().melt(
                    id_vars="Date", var_name="Asset", value_name="Return (%)")
                fig_line = px.line(chart_data, x="Date", y="Return (%)", color="Asset", template="plotly_dark",
                                   color_discrete_map={"My Portfolio": "#00C9B1", "S&P 500": "#888888", "Nasdaq 100": "#4B8BFF"})
                fig_line.update_layout(xaxis_title="", yaxis_title="Return (%)",
                                       hovermode="x unified", margin=dict(l=0, r=0, t=10, b=10))
                st.plotly_chart(fig_line, use_container_width=True)

        with c_risk:
            daily_returns = port_slice.pct_change().dropna()
            bench_returns = spy_slice.pct_change().dropna(
            ) if not spy_slice.empty else pd.Series(0, index=daily_returns.index)
            aligned_returns = pd.concat(
                [daily_returns, bench_returns], axis=1).dropna()
            aligned_returns.columns = ['Port', 'Bench']

            beta = aligned_returns['Port'].cov(aligned_returns['Bench']) / aligned_returns['Bench'].var(
            ) if len(aligned_returns) > 2 and aligned_returns['Bench'].var() != 0 else 1.0
            sharpe = (daily_returns.mean() * 252 - 0.04) / (daily_returns.std()
                                                            * np.sqrt(252)) if daily_returns.std() != 0 else 0
            drawdown = (port_slice / port_slice.cummax()) - 1
            max_dd = drawdown.min() * 100 if not drawdown.empty else 0.0

            st.markdown("**Risk Profile**")
            st.info(
                f"**Beta (vs SPY):** {beta:.2f}\n\n*<1.0 = Less volatile.*")
            st.warning(f"**Max Drawdown:** {max_dd:.2f}%\n\n*Worst drop.*")
            if sharpe > 1:
                st.success(
                    f"**Sharpe:** {sharpe:.2f}\n\n*Good risk-adj returns.*")
            else:
                st.error(
                    f"**Sharpe:** {sharpe:.2f}\n\n*Sub-optimal risk-adj returns.*")

        st.divider()

        st.markdown("### 🧩 Portfolio Allocation & Performance")
        c_pie, c_tree = st.columns([1, 1])
        chart_df = grouped[grouped["Value (CAD)"] > 0].copy()

        # --- NEW: ETF SECTOR EXPLOSION LOGIC ---
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

                        exploded_rows.append({
                            "Ticker Symbol": ticker, "Sector": sec_name, "Value (CAD)": allocated_val,
                            "Asset Return (%)": ret, "Portfolio": "My Portfolio"
                        })
                    except Exception:
                        pass

                if total_allocated < 1.0:
                    exploded_rows.append({
                        "Ticker Symbol": ticker, "Sector": "Other", "Value (CAD)": max(0, val * (1.0 - total_allocated)),
                        "Asset Return (%)": ret, "Portfolio": "My Portfolio"
                    })
            else:
                exploded_rows.append({
                    "Ticker Symbol": ticker, "Sector": sec_raw if pd.notna(sec_raw) and sec_raw != "" else "Other",
                    "Value (CAD)": val, "Asset Return (%)": ret, "Portfolio": "My Portfolio"
                })

        exploded_df = pd.DataFrame(exploded_rows)
        # ---------------------------------------

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

        bar_df = grouped[grouped["Value (CAD)"] > 0].sort_values(
            "Asset Return (%)", ascending=True)
        bar_df["Color"] = np.where(
            bar_df["Asset Return (%)"] > 0, '#00C9B1', '#FF4B4B')
        fig_bar = px.bar(bar_df, x="Asset Return (%)", y="Ticker Symbol", orientation='h', hover_data=[
                         "Name"], color="Color", color_discrete_map="identity", template="plotly_dark", title="Individual Asset Returns")
        fig_bar.update_layout(showlegend=False, xaxis_title="All-Time Return (%)",
                              yaxis_title="", margin=dict(l=0, r=0, t=40, b=10))
        st.plotly_chart(fig_bar, use_container_width=True)

        st.divider()
        st.markdown("### 📑 Detailed Ledger & Fundamentals")
        st.caption(
            "Native currency visibility and total values in both CAD and USD.")

        display_cols = ["Ticker Symbol", "Name", "Sector", "Quantity", "Currency", "Avg Book Price", "Live Price",
                        "Value (CAD)", "Value (USD)", "Portfolio Weight (%)", "Yield (%)", "P/E", "1Y Target", "Asset Return (%)"]

        st.dataframe(grouped[display_cols].style.format({
            "Avg Book Price": "${:,.2f}", "Live Price": "${:,.2f}", "Value (CAD)": "${:,.2f}", "Value (USD)": "${:,.2f}", "1Y Target": "${:,.2f}",
            "Quantity": "{:,.4g}", "Portfolio Weight (%)": "{:.2f}%", "Yield (%)": "{:.2f}%", "P/E": "{:.1f}", "Asset Return (%)": "{:+.2f}%"
        }, na_rep="N/A").map(lambda x: 'color: #00C9B1' if pd.notna(x) and x > 0 else ('color: #FF4B4B' if pd.notna(x) and x < 0 else ''), subset=["Asset Return (%)"]),
            use_container_width=True, hide_index=True)

        st.markdown("<br>", unsafe_allow_html=True)
        with st.expander("⚖️ Automated Rebalancing Engine", expanded=False):
            st.write("Set your ideal portfolio target weights below. The engine calculates exactly how many shares to buy or sell *today* to realign your portfolio.")

            rebal_cols = ["Ticker Symbol", "Live Price",
                          "Value (CAD)", "Portfolio Weight (%)", "Target Weight (%)"]
            rebal_df = grouped[rebal_cols].copy()

            st.markdown(
                "**1. Set Target Weights (Double click to edit. Weights save automatically!)**")
            edited_rebal = st.data_editor(
                rebal_df,
                column_config={
                    "Ticker Symbol": st.column_config.TextColumn("Asset", disabled=True),
                    "Live Price": st.column_config.NumberColumn("Live Price", format="$%.2f", disabled=True),
                    "Value (CAD)": st.column_config.NumberColumn("Current Value", format="$%.2f", disabled=True),
                    "Portfolio Weight (%)": st.column_config.NumberColumn("Current Weight", format="%.2f%%", disabled=True),
                    "Target Weight (%)": st.column_config.NumberColumn("Target Weight (%)", min_value=0.0, max_value=100.0, step=0.5)
                },
                hide_index=True, use_container_width=True
            )

            if not edited_rebal["Target Weight (%)"].equals(rebal_df["Target Weight (%)"]):
                target_map = dict(
                    zip(edited_rebal["Ticker Symbol"], edited_rebal["Target Weight (%)"]))
                raw_df = pd.read_csv(DATA_FILE)
                mapped_weights = raw_df["Ticker Symbol"].map(target_map)
                raw_df["Target Weight (%)"] = mapped_weights.combine_first(
                    raw_df["Target Weight (%)"]).fillna(0.0)
                raw_df.to_csv(DATA_FILE, index=False)
                st.toast("💾 Target weights successfully auto-saved!")

            total_target = edited_rebal["Target Weight (%)"].sum()
            if total_target != 100.0:
                st.warning(
                    f"⚠️ Your target weights sum to **{total_target:.1f}%**. They should equal exactly 100%.")

            edited_rebal["Target Value (CAD)"] = total_val_cad * \
                (edited_rebal["Target Weight (%)"] / 100)
            edited_rebal["Value Difference"] = edited_rebal["Target Value (CAD)"] - \
                edited_rebal["Value (CAD)"]

            currency_map = dict(
                zip(grouped["Ticker Symbol"], grouped["Currency"]))
            edited_rebal["Currency"] = edited_rebal["Ticker Symbol"].map(
                currency_map)
            edited_rebal["Action Price (CAD)"] = np.where(
                edited_rebal["Currency"] == "USD", edited_rebal["Live Price"] * fx_rate, edited_rebal["Live Price"])

            edited_rebal["Shares to Action"] = np.where(
                edited_rebal["Action Price (CAD)"] > 0, edited_rebal["Value Difference"] / edited_rebal["Action Price (CAD)"], 0)

            actions_df = edited_rebal[[
                "Ticker Symbol", "Portfolio Weight (%)", "Target Weight (%)", "Value Difference", "Shares to Action"]].copy()
            actions_df.columns = [
                "Asset", "Current Weight (%)", "Target Weight (%)", "Capital Required (CAD)", "Shares to Buy/Sell"]
            actions_df["Action"] = np.where(actions_df["Shares to Buy/Sell"] > 0, "BUY", np.where(
                actions_df["Shares to Buy/Sell"] < 0, "SELL", "HOLD"))

            st.markdown("**2. Required Actions**")
            st.dataframe(actions_df.style.format({
                "Current Weight (%)": "{:.2f}%", "Target Weight (%)": "{:.2f}%", "Capital Required (CAD)": "${:+,.2f}", "Shares to Buy/Sell": "{:+.2f}"
            }).map(lambda x: 'color: #00C9B1' if x == "BUY" else ('color: #FF4B4B' if x == "SELL" else 'color: #888888'), subset=["Action"]),
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
        p_in = c2.number_input("Book Price (Avg Cost)", min_value=0.0)
        q_in = c2.number_input("Quantity", min_value=0.0)

        if st.form_submit_button("Identify & Save"):
            ticker = t_in.upper().strip()
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

# --- TAB 3: MANAGE DATA ---
with tab3:
    st.header("⚙️ Manage Database")
    st.write("Edit raw database entries here. Manually enter your true **Book Price** to get accurate all-time return metrics.")
    raw_edit = st.data_editor(
        load_data(), num_rows="dynamic", use_container_width=True)
    if st.button("Save Database Changes"):
        raw_edit.to_csv(DATA_FILE, index=False)
        st.success("Changes successfully saved!")
        st.rerun()
