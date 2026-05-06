import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import os
from datetime import datetime, timedelta

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

# --- 2. DATA ENGINES ---
DATA_FILE = "my_portfolio.csv"


def load_data():
    if not os.path.exists(DATA_FILE):
        pd.DataFrame(columns=["Ticker Symbol", "Currency", "Price",
                     "Quantity", "Sector", "Region"]).to_csv(DATA_FILE, index=False)
    df = pd.read_csv(DATA_FILE)
    df["Price"] = pd.to_numeric(df["Price"], errors='coerce').fillna(0)
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors='coerce').fillna(0)
    return df


@st.cache_data(ttl=3600)
def get_benchmark_data(symbol="SPY", days=365):
    """Fetches benchmark performance for comparison"""
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    bench = yf.download(symbol, start=start_date, progress=False)['Close']
    # Normalize to 100 (percentage growth)
    return (bench / bench.iloc[0]) * 100


def get_smart_metadata(ticker_str):
    """Auto-identifies Sector and Region"""
    try:
        info = yf.Ticker(ticker_str).info
        if info.get('quoteType') == 'ETF':
            sector = f"ETF: {info.get('category', 'Index')}"
        else:
            sector = info.get('sector', 'Other')

        country = info.get('country', 'Unknown')
        region = 'USA' if country in ['United States', 'USA'] else (
            'Canada' if country == 'Canada' else 'International')
        return sector, region
    except:
        return "Unknown", "International"


# --- 3. UI LAYOUT ---
st.set_page_config(page_title="Pro Analytics", layout="wide")
st.title("📊 Portfolio Intelligence & Benchmarking")

df = load_data()

if not df.empty:
    # 1. LIVE MARKET SYNC
    tickers = df["Ticker Symbol"].unique()
    with st.spinner("Syncing live market data..."):
        # Auto-fill missing sectors/regions
        if "Sector" not in df.columns or df["Sector"].isnull().any() or (df["Sector"] == "Unknown").any():
            for idx, row in df.iterrows():
                if pd.isna(row.get("Sector")) or row.get("Sector") == "Unknown":
                    s, r = get_smart_metadata(row["Ticker Symbol"])
                    df.at[idx, "Sector"], df.at[idx, "Region"] = s, r
            df.to_csv(DATA_FILE, index=False)

        prices = {t: yf.Ticker(t).history(period="1d")[
            'Close'].iloc[-1] for t in tickers}
        fx_rate = yf.Ticker("USDCAD=X").history(period="1d")['Close'].iloc[-1]
        benchmark_history = get_benchmark_data("SPY")

    # 2. CALCULATIONS
    df["Live Price"] = df["Ticker Symbol"].map(prices)
    df["Value (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Live Price"]) *
                                 fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Live Price"]), axis=1)
    df["Cost Basis (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Price"]) *
                                      fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Price"]), axis=1)

    total_val = df["Value (CAD)"].sum()
    total_cost = df["Cost Basis (CAD)"].sum()
    total_pl_pct = ((total_val - total_cost) / total_cost) * 100

    # 3. TOP METRICS
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Value (CAD)", f"${total_val:,.2f}")
    m2.metric("Portfolio Return",
              f"{total_pl_pct:.2f}%", delta=f"{total_pl_pct:.2f}%")
    m3.metric("S&P 500 (SPY) 1Y Return",
              f"{(benchmark_history.iloc[-1]-100):.2f}%")

    # --- BENCHMARK COMPARISON CHART ---
    st.subheader("📈 Performance vs. Benchmark (S&P 500)")
    # Simple simulation of portfolio growth vs benchmark for visualization
    # In a real app, you'd calculate weighted historical returns
    comparison_df = pd.DataFrame({
        "S&P 500 (Normalized)": benchmark_history,
        # Illustrative trend
        "My Portfolio (Est.)": benchmark_history * (1 + (total_pl_pct/200))
    })
    st.line_chart(comparison_df)

    # --- SECTOR EXPOSURE ---
    st.subheader("🧩 Sector Exposure")
    c1, c2 = st.columns([2, 1])
    with c1:
        fig_tree = px.treemap(df, path=[px.Constant("Portfolio"), 'Sector', 'Ticker Symbol'],
                              values='Value (CAD)', color='Sector', template="plotly_dark")
        st.plotly_chart(fig_tree, use_container_width=True)
    with c2:
        sector_dist = df.groupby("Sector")["Value (CAD)"].sum()
        st.write(sector_dist)

    st.divider()
    st.write("### 📑 Holding Summary")
    st.dataframe(df[["Ticker Symbol", "Sector", "Region", "Value (CAD)"]].style.format(
        {"Value (CAD)": "${:.2f}"}), use_container_width=True)

else:
    st.info("Your portfolio is empty. Add assets in the sidebar or 'Manage Data' tab.")

# --- SIDEBAR: QUICK ADD ---
with st.sidebar:
    st.header("➕ Add Asset")
    with st.form("sidebar_form", clear_on_submit=True):
        t_in = st.text_input("Ticker (AAPL, SHOP)")
        curr_in = st.selectbox("Currency", ["USD", "CAD"])
        p_in = st.number_input("Purchase Price", min_value=0.0)
        q_in = st.number_input("Quantity", min_value=0.0)
        if st.form_submit_button("Add Asset"):
            ticker = t_in.upper().strip()
            if curr_in == "CAD" and not ticker.endswith(".TO"):
                ticker += ".TO"
            s, r = get_smart_metadata(ticker)
            new_row = pd.DataFrame([{"Ticker Symbol": ticker, "Currency": curr_in,
                                   "Price": p_in, "Quantity": q_in, "Sector": s, "Region": r}])
            pd.concat([df, new_row], ignore_index=True).to_csv(
                DATA_FILE, index=False)
            st.rerun()
