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

    # THE FIX: Forcefully strip commas and dollar signs before converting to numbers
    df["Price"] = pd.to_numeric(df["Price"].astype(str).str.replace(
        r'[$,]', '', regex=True), errors='coerce').fillna(0.0)
    df["Quantity"] = pd.to_numeric(df["Quantity"].astype(str).str.replace(
        r'[$,]', '', regex=True), errors='coerce').fillna(0.0)
    return df


@st.cache_data(ttl=3600)
def get_benchmark_data(symbol="SPY"):
    try:
        bench = yf.Ticker(symbol).history(period="1y")['Close']
        if not bench.empty:
            return (bench / bench.iloc[0]) * 100
    except Exception:
        pass
    return pd.Series([100.0, 100.0])


def get_smart_metadata(ticker_str):
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

    with st.spinner("Syncing live market data..."):
        if "Sector" not in df.columns or df["Sector"].isnull().any() or (df["Sector"] == "Unknown").any():
            for idx, row in df.iterrows():
                if pd.isna(row.get("Sector")) or row.get("Sector") == "Unknown":
                    s, r = get_smart_metadata(row["Ticker Symbol"])
                    df.at[idx, "Sector"], df.at[idx, "Region"] = s, r
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

    # Calculations
    df["Live Price"] = df["Ticker Symbol"].map(prices).fillna(0.0)
    df["Value (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Live Price"]) *
                                 fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Live Price"]), axis=1)
    df["Cost Basis (CAD)"] = df.apply(lambda r: (r["Quantity"] * r["Price"]) *
                                      fx_rate if r["Currency"] == "USD" else (r["Quantity"] * r["Price"]), axis=1)

    total_val = df["Value (CAD)"].sum()
    total_cost = df["Cost Basis (CAD)"].sum()
    total_pl_pct = ((total_val - total_cost) / total_cost) * \
        100 if total_cost > 0 else 0.0

# --- TAB 1: PORTFOLIO VIEW ---
with tab1:
    if not df.empty:
        # Metrics
        m1, m2, m3 = st.columns(3)
        m1.metric("Total Value (CAD)", f"${total_val:,.2f}")
        m2.metric("Portfolio Return",
                  f"{total_pl_pct:.2f}%", delta=f"{total_pl_pct:.2f}%")
        spy_return = benchmark_history.iloc[-1] - \
            100 if not benchmark_history.empty else 0.0
        m3.metric("S&P 500 (SPY) 1Y Return", f"{spy_return:.2f}%")

        # Benchmark Chart
        st.subheader("📈 Performance vs. Benchmark (S&P 500)")
        comparison_df = pd.DataFrame({
            "S&P 500 (Normalized)": benchmark_history,
            "My Portfolio (Est.)": benchmark_history * (1 + (total_pl_pct/200))
        })
        st.line_chart(comparison_df)

        # Visuals
        st.subheader("🧩 Sector Exposure")
        c1, c2 = st.columns([2, 1])

        # Safe chart filtering
        chart_df = df[df["Value (CAD)"] > 0].copy()
        # Bulletproof root replacement for px.Constant
        chart_df["Portfolio_Root"] = "Total Portfolio"

        with c1:
            if not chart_df.empty:
                fig_tree = px.treemap(chart_df, path=["Portfolio_Root", 'Sector', 'Ticker Symbol'],
                                      values='Value (CAD)', color='Sector', template="plotly_dark")
                st.plotly_chart(fig_tree, use_container_width=True)
            else:
                st.warning(
                    "⚠️ Treemap Hidden: Ensure your assets have a Quantity > 0 in the Manage Data tab.")

        with c2:
            if not chart_df.empty:
                sector_dist = chart_df.groupby(
                    "Sector")["Value (CAD)"].sum().reset_index()
                fig_pie = px.pie(sector_dist, values='Value (CAD)',
                                 names='Sector', hole=0.6, template="plotly_dark")
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.warning(
                    "⚠️ Pie Chart Hidden: Ensure your assets have a Quantity > 0.")

        # Data Table
        st.divider()
        st.write("### 📑 Holding Summary")
        st.dataframe(df[["Ticker Symbol", "Currency", "Price", "Quantity", "Sector", "Region", "Value (CAD)"]].style.format({
            "Price": "{:.2f}",
            "Quantity": "{:.2f}",
            "Value (CAD)": "${:.2f}"
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
                s, r = get_smart_metadata(ticker)
                new_row = pd.DataFrame([{"Ticker Symbol": ticker, "Currency": curr_in,
                                       "Price": p_in, "Quantity": q_in, "Sector": s, "Region": r}])
                pd.concat([load_data(), new_row], ignore_index=True).to_csv(
                    DATA_FILE, index=False)
                st.success(f"Added {ticker} as {s}")
                st.rerun()

# --- TAB 3: MANAGE DATA ---
with tab3:
    st.header("⚙️ Manage Database")
    st.write("Edit your raw entries below. Changes apply immediately upon saving.")
    raw_edit = st.data_editor(
        load_data(), num_rows="dynamic", use_container_width=True)
    if st.button("Save Database Changes"):
        raw_edit.to_csv(DATA_FILE, index=False)
        st.success("Changes successfully saved!")
        st.rerun()
