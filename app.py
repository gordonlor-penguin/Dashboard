import streamlit as st
import pandas as pd
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
        pd.DataFrame(columns=["Ticker Symbol", "Name", "Currency",
                     "Price", "Quantity", "Sector"]).to_csv(DATA_FILE, index=False)

    df = pd.read_csv(DATA_FILE)

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
        bench = yf.Ticker(symbol).history(period="1y")['Close']
        if not bench.empty:
            # Strip timezones so Plotly and Streamlit render the X-axis dates perfectly
            bench.index = bench.index.tz_localize(None)
            return (bench / bench.iloc[0]) * 100
    except Exception:
        pass

    # Fallback if Yahoo Finance goes offline
    dates = pd.date_range(end=datetime.datetime.today(), periods=2)
    return pd.Series([100.0, 100.0], index=dates)


def get_smart_metadata(ticker_str):
    try:
        tk = yf.Ticker(str(ticker_str))
        info = tk.info
        name = info.get('longName', info.get('shortName', 'Unknown'))

        if info.get('quoteType') == 'ETF':
            try:
                sectors = tk.funds_data.sector_weightings
                if sectors:
                    sorted_sec = sorted(
                        sectors.items(), key=lambda x: x[1], reverse=True)
                    top_sectors = [
                        f"{k.replace('_', ' ').title()} ({v*100:.0f}%)" for k, v in sorted_sec[:3]]
                    sector = "ETF: " + " | ".join(top_sectors)
                else:
                    sector = f"ETF: {info.get('category', 'Index')}"
            except:
                sector = f"ETF: {info.get('category', 'Index')}"
        else:
            sector = info.get('sector', 'Other')

        return name, sector
    except:
        return "Unknown", "Unknown"


# --- 3. DASHBOARD UI SETUP ---
st.set_page_config(page_title="Pro Analytics", layout="wide")
st.title("📊 Portfolio Intelligence & Benchmarking")

tab1, tab2, tab3 = st.tabs(
    ["📊 Strategy & Risk", "➕ Add Asset", "⚙️ Manage Data"])

df = load_data()

# --- DATA PROCESSING ---
if not df.empty:
    df = df.dropna(subset=["Ticker Symbol"])
    tickers = df["Ticker Symbol"].unique()

    with st.spinner("Syncing live market data & asset details..."):
        needs_save = False
        if "Name" not in df.columns:
            df["Name"] = "Unknown"
        if "Sector" not in df.columns:
            df["Sector"] = "Unknown"

        for idx, row in df.iterrows():
            current_sector = str(row.get("Sector"))
            current_name = str(row.get("Name"))

            needs_update = False
            if pd.isna(current_sector) or current_sector == "Unknown" or "Blend" in current_sector or "Value" in current_sector or "Growth" in current_sector:
                needs_update = True
            if pd.isna(current_name) or current_name == "Unknown":
                needs_update = True

            if needs_update:
                n, s = get_smart_metadata(row["Ticker Symbol"])
                if pd.isna(current_name) or current_name == "Unknown":
                    df.at[idx, "Name"] = n
                if pd.isna(current_sector) or current_sector == "Unknown" or "Blend" in current_sector or "Value" in current_sector or "Growth" in current_sector:
                    df.at[idx, "Sector"] = s
                needs_save = True

        if needs_save:
            df.to_csv(DATA_FILE, index=False)

        prices = {}
        for t in tickers:
            try:
                hist = yf.Ticker(t).history(period="5d")
                prices[t] = hist['Close'].iloc[-1] if not hist.empty else 0.0
            except:
                prices[t] = 0.0

        try:
            fx_data = yf.Ticker("USDCAD=X").history(period="5d")
            fx_rate = fx_data['Close'].iloc[-1] if not fx_data.empty else 1.38
        except:
            fx_rate = 1.38

        benchmark_history = get_benchmark_data("SPY")

    # Core Calculations
    df["Live Price"] = df["Ticker Symbol"].map(prices).fillna(0.0)
    df["Value (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Live Price"]) *
                                 fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Live Price"]), axis=1)
    df["Cost Basis (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Price"]) *
                                      fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Price"]), axis=1)

    total_val_cad = df["Value (CAD)"].sum()
    total_val_usd = total_val_cad / fx_rate if fx_rate > 0 else 0.0
    total_cost = df["Cost Basis (CAD)"].sum()
    total_pl_pct = ((total_val_cad - total_cost) / total_cost) * \
        100 if total_cost > 0 else 0.0

# --- TAB 1: PORTFOLIO VIEW ---
with tab1:
    if not df.empty:
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Total Value (CAD)", f"${total_val_cad:,.2f}")
        m2.metric("Total Value (USD)", f"${total_val_usd:,.2f}")
        m3.metric("Portfolio Return",
                  f"{total_pl_pct:.2f}%", delta=f"{total_pl_pct:.2f}%")
        spy_return = benchmark_history.iloc[-1] - \
            100 if not benchmark_history.empty else 0.0
        m4.metric("S&P 500 (SPY) 1Y Return", f"{spy_return:.2f}%")

        # --- THE FIX: Upgraded Plotly Line Chart ---
        st.subheader("📈 Performance vs. Benchmark (S&P 500)")
        comparison_df = pd.DataFrame({
            "S&P 500 (1Y)": benchmark_history,
            "My Portfolio (Est.)": benchmark_history * (1 + (total_pl_pct/100))
        })

        fig_line = px.line(comparison_df, template="plotly_dark")
        fig_line.update_layout(
            xaxis_title="Date",
            yaxis_title="Performance (Indexed to 100)",
            legend_title_text="Legend",
            hovermode="x unified"  # Shows both S&P and Portfolio values when you hover
        )
        st.plotly_chart(fig_line, use_container_width=True)
        # -------------------------------------------

        st.subheader("🧩 Aggregate Sector Exposure")
        c1, c2 = st.columns([2, 1])

        chart_df = df[df["Value (CAD)"] > 0].copy()
        expanded_records = []

        for _, row in chart_df.iterrows():
            val = row["Value (CAD)"]
            ticker = row["Ticker Symbol"]
            sec_str = str(row["Sector"])

            if sec_str.startswith("ETF:") and "%" in sec_str:
                clean_str = sec_str.replace("ETF:", "").strip()
                parts = clean_str.split('|')
                allocated_pct = 0.0

                for p in parts:
                    match = re.search(r'(.*)\((\d+)%\)', p)
                    if match:
                        sec_name = match.group(1).strip()
                        pct = float(match.group(2))
                        allocated_pct += pct
                        expanded_records.append({
                            "Ticker Symbol": ticker,
                            "Sector": sec_name,
                            "Value (CAD)": val * (pct / 100.0)
                        })

                remainder = 100.0 - allocated_pct
                if remainder > 0:
                    expanded_records.append({
                        "Ticker Symbol": ticker,
                        "Sector": "Other / Unclassified",
                        "Value (CAD)": val * (remainder / 100.0)
                    })
            else:
                clean_sec = sec_str.replace("ETF:", "").strip(
                ) if sec_str.startswith("ETF:") else sec_str
                expanded_records.append({
                    "Ticker Symbol": ticker,
                    "Sector": clean_sec,
                    "Value (CAD)": val
                })

        expanded_df = pd.DataFrame(expanded_records)
        expanded_df["Portfolio_Root"] = "Total Portfolio"

        with c1:
            if not expanded_df.empty:
                fig_tree = px.treemap(expanded_df, path=["Portfolio_Root", 'Sector', 'Ticker Symbol'],
                                      values='Value (CAD)', color='Sector', template="plotly_dark")
                st.plotly_chart(fig_tree, use_container_width=True)
            else:
                st.warning(
                    "⚠️ Treemap Hidden: Ensure your assets have a Quantity > 0 in the Manage Data tab.")

        with c2:
            if not expanded_df.empty:
                sector_dist = expanded_df.groupby(
                    "Sector")["Value (CAD)"].sum().reset_index()
                sector_dist = sector_dist.sort_values(
                    "Value (CAD)", ascending=False)
                fig_pie = px.pie(sector_dist, values='Value (CAD)',
                                 names='Sector', hole=0.6, template="plotly_dark")
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.warning(
                    "⚠️ Pie Chart Hidden: Ensure your assets have a Quantity > 0.")

        st.divider()
        st.write("### 📑 Holding Summary")

        df["Original_Cost_Total"] = df["Quantity"] * df["Price"]

        summary_df = df.groupby(["Ticker Symbol", "Name", "Currency", "Sector"]).agg(
            Total_Quantity=('Quantity', 'sum'),
            Total_Original_Cost=('Original_Cost_Total', 'sum'),
            Total_Value_CAD=('Value (CAD)', 'sum')
        ).reset_index()

        summary_df["Avg Purchase Price"] = summary_df.apply(
            lambda r: r["Total_Original_Cost"] / r["Total_Quantity"] if r["Total_Quantity"] > 0 else 0.0, axis=1
        )

        summary_df = summary_df.rename(
            columns={"Total_Quantity": "Quantity", "Total_Value_CAD": "Value (CAD)"})
        summary_df["Value (USD)"] = summary_df["Value (CAD)"] / \
            fx_rate if fx_rate > 0 else 0.0

        display_cols = ["Ticker Symbol", "Name", "Currency", "Avg Purchase Price",
                        "Quantity", "Sector", "Value (CAD)", "Value (USD)"]

        st.dataframe(summary_df[display_cols].style.format({
            "Avg Purchase Price": "${:,.2f}",
            "Quantity": "{:,.2f}",
            "Value (CAD)": "${:,.2f}",
            "Value (USD)": "${:,.2f}"
        }), use_container_width=True)

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
                n, s = get_smart_metadata(ticker)
                new_row = pd.DataFrame(
                    [{"Ticker Symbol": ticker, "Name": n, "Currency": curr_in, "Price": p_in, "Quantity": q_in, "Sector": s}])
                pd.concat([load_data(), new_row], ignore_index=True).to_csv(
                    DATA_FILE, index=False)
                st.success(f"Added {n} ({ticker}) as {s}")
                st.rerun()

# --- TAB 3: MANAGE DATA ---
with tab3:
    st.header("⚙️ Manage Database")
    st.write("Edit your raw individual entries below. (The 'Strategy & Risk' tab will automatically combine matching tickers).")
    raw_edit = st.data_editor(
        load_data(), num_rows="dynamic", use_container_width=True)
    if st.button("Save Database Changes"):
        raw_edit.to_csv(DATA_FILE, index=False)
        st.success("Changes successfully saved!")
        st.rerun()
