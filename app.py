import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import os

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
        pd.DataFrame(columns=["Ticker Symbol", "Currency", "Price",
                     "Quantity", "Sector", "Region"]).to_csv(DATA_FILE, index=False)
    df = pd.read_csv(DATA_FILE)
    df["Price"] = pd.to_numeric(df["Price"], errors='coerce').fillna(0.0)
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors='coerce').fillna(0.0)
    return df


@st.cache_data(ttl=3600)
def get_benchmark_data(symbol="SPY"):
    """Safely fetches 1 year of benchmark data"""
    try:
        # Using Ticker.history instead of yf.download is much more stable
        bench = yf.Ticker(symbol).history(period="1y")['Close']
        if not bench.empty:
            return (bench / bench.iloc[0]) * 100
    except Exception:
        pass
    # If internet fails or market is closed, return a flat fallback line
    return pd.Series([100.0, 100.0])


def get_smart_metadata(ticker_str):
    """Auto-identifies Sector and Region"""
    try:
        info = yf.Ticker(str(ticker_str)).info
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


# --- 3. DASHBOARD UI ---
st.set_page_config(page_title="Pro Analytics", layout="wide")
st.title("📊 Portfolio Intelligence & Benchmarking")

df = load_data()

if not df.empty:
    # Remove any completely blank ticker rows
    df = df.dropna(subset=["Ticker Symbol"])
    tickers = df["Ticker Symbol"].unique()

    with st.spinner("Syncing live market data..."):
        # Auto-fill missing sectors/regions
        if "Sector" not in df.columns or df["Sector"].isnull().any() or (df["Sector"] == "Unknown").any():
            for idx, row in df.iterrows():
                if pd.isna(row.get("Sector")) or row.get("Sector") == "Unknown":
                    s, r = get_smart_metadata(row["Ticker Symbol"])
                    df.at[idx, "Sector"], df.at[idx, "Region"] = s, r
            df.to_csv(DATA_FILE, index=False)

        # 1. SAFE PRICE FETCH (Uses 5d lookback to avoid weekend crashes)
        prices = {}
        for t in tickers:
            try:
                hist = yf.Ticker(t).history(period="5d")
                prices[t] = hist['Close'].iloc[-1] if not hist.empty else 0.0
            except:
                prices[t] = 0.0

        # 2. SAFE FX FETCH
        try:
            fx_data = yf.Ticker("USDCAD=X").history(period="5d")
            fx_rate = fx_data['Close'].iloc[-1] if not fx_data.empty else 1.38
        except:
            fx_rate = 1.38

        benchmark_history = get_benchmark_data("SPY")

    # --- CALCULATIONS ---
    df["Live Price"] = df["Ticker Symbol"].map(prices)
    df["Value (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Live Price"]) *
                                 fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Live Price"]), axis=1)
    df["Cost Basis (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Price"]) *
                                      fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Price"]), axis=1)

    total_val = df["Value (CAD)"].sum()
    total_cost = df["Cost Basis (CAD)"].sum()

    # Safe Zero-Division Check
    total_pl_pct = ((total_val - total_cost) / total_cost) * \
        100 if total_cost > 0 else 0.0

    # --- TOP METRICS ---
    m1, m2, m3 = st.columns(3)
    m1.metric("Total Value (CAD)", f"${total_val:,.2f}")
    m2.metric("Portfolio Return",
              f"{total_pl_pct:.2f}%", delta=f"{total_pl_pct:.2f}%")

    # Safe benchmark display
    spy_return = benchmark_history.iloc[-1] - \
        100 if not benchmark_history.empty else 0.0
    m3.metric("S&P 500 (SPY) 1Y Return", f"{spy_return:.2f}%")

    # --- CHARTS ---
    st.subheader("📈 Performance vs. Benchmark (S&P 500)")
    comparison_df = pd.DataFrame({
        "S&P 500 (Normalized)": benchmark_history,
        # Illustrative trend
        "My Portfolio (Est.)": benchmark_history * (1 + (total_pl_pct/200))
    })
    st.line_chart(comparison_df)

    st.subheader("🧩 Sector Exposure")
    c1, c2 = st.columns([2, 1])
    with c1:
        fig_tree = px.treemap
