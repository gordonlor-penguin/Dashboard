import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import os

# --- 1. SETUP THE DATABASE ---
DATA_FILE = "my_portfolio.csv"

if not os.path.exists(DATA_FILE):
    df_init = pd.DataFrame(
        columns=["Ticker Symbol", "Currency", "Price", "Quantity"])
    df_init.to_csv(DATA_FILE, index=False)


def load_data():
    df = pd.read_csv(DATA_FILE)
    df["Price"] = pd.to_numeric(df["Price"], errors='coerce').fillna(0)
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors='coerce').fillna(0)

    def sanitize_ticker(row):
        ticker = str(row["Ticker Symbol"]).upper().strip()
        currency = str(row["Currency"]).upper().strip()
        if currency == "CAD" and not ticker.endswith(".TO") and ticker != "NAN":
            return f"{ticker}.TO"
        return ticker

    if not df.empty:
        df["Ticker Symbol"] = df.apply(sanitize_ticker, axis=1)
    return df


def save_transaction(ticker, currency, price, quantity):
    df = load_data()
    clean_ticker = ticker.upper().strip()
    clean_currency = currency.upper().strip()
    if clean_currency == "CAD" and not clean_ticker.endswith(".TO"):
        clean_ticker = f"{clean_ticker}.TO"
    new_data = pd.DataFrame({"Ticker Symbol": [clean_ticker], "Currency": [
                            clean_currency], "Price": [price], "Quantity": [quantity]})
    df = pd.concat([df, new_data], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

# --- 2. LIVE PRICE & EXCHANGE RATE ENGINE ---


def get_live_price(ticker):
    try:
        stock = yf.Ticker(ticker.strip())
        data = stock.history(period="1d")
        return data['Close'].iloc[-1] if not data.empty else 0.0
    except:
        return 0.0


def get_exchange_rate():
    """Fetches the live USD to CAD exchange rate"""
    try:
        rate = yf.Ticker("USDCAD=X").history(period="1d")['Close'].iloc[-1]
        return rate
    except:
        return 1.35  # Fallback rate if Yahoo is down


# --- 3. BUILD THE WEB INTERFACE ---
st.set_page_config(page_title="Investment Dashboard", layout="wide")
st.title("📈 My Investment Dashboard")

tab1, tab2, tab3 = st.tabs(
    ["📊 Dashboard", "➕ Add Transaction", "⚙️ Manage Data"])

with tab1:
    st.header("Current Portfolio")
    portfolio_df = load_data()

    if portfolio_df.empty:
        st.info("Your portfolio is empty. Add some investments in the next tab!")
    else:
        summary_df = portfolio_df.groupby(["Ticker Symbol", "Currency"]).agg(
            {"Quantity": "sum", "Price": "mean"}).reset_index()

        with st.spinner('Calculating values and exchange rates...'):
            usdcad_rate = get_exchange_rate()
            summary_df["Live Price"] = summary_df["Ticker Symbol"].apply(
                get_live_price)

            # Calculate value in native currency first
            summary_df["Value (Native)"] = summary_df["Quantity"] * \
                summary_df["Live Price"]

            # Convert everything to USD and CAD for totals
            def convert_to_usd(row):
                return row["Value (Native)"] / usdcad_rate if row["Currency"] == "CAD" else row["Value (Native)"]

            def convert_to_cad(row):
                return row["Value (Native)"] * usdcad_rate if row["Currency"] == "USD" else row["Value (Native)"]

            summary_df["Value (USD)"] = summary_df.apply(
                convert_to_usd, axis=1)
            summary_df["Value (CAD)"] = summary_df.apply(
                convert_to_cad, axis=1)

        # --- DISPLAY METRICS ---
        total_usd = summary_df["Value (USD)"].sum()
        total_cad = summary_df["Value (CAD)"].sum()

        m1, m2, m3 = st.columns(3)
        m1.metric("Total Value (USD)", f"${total_usd:,.2f}")
        m2.metric("Total Value (CAD)", f"${total_cad:,.2f}")
        m3.metric("Exchange Rate (USD/CAD)", f"{usdcad_rate:.4f}")

        st.divider()

        # Table View
        st.write("### Asset Breakdown")
        st.dataframe(summary_df[[
            "Ticker Symbol", "Currency", "Quantity", "Live Price", "Value (Native)", "Value (CAD)"
        ]].style.format({
            "Live Price": "{:.2f}",
            "Value (Native)": "{:.2f}",
            "Value (CAD)": "{:.2f}"
        }), use_container_width=True)

        # Charts
        st.write("### Portfolio Allocation (CAD Equivalent)")
        fig = px.pie(summary_df, values='Value (CAD)',
                     names='Ticker Symbol', hole=0.4)
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.header("Add New Investment")
    with st.form("transaction_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            input_ticker = st.text_input("Ticker (e.g. SHOP, TD, or AAPL)")
            input_currency = st.selectbox("Currency", ["USD", "CAD"])
        with col2:
            input_price = st.number_input(
                "Purchase Price", min_value=0.0, step=0.01)
            input_quantity = st.number_input(
                "Quantity", min_value=0.0, step=0.1)

        if st.form_submit_button("Save to Portfolio"):
            if input_ticker:
                save_transaction(input_ticker, input_currency,
                                 input_price, input_quantity)
                st.success("Successfully recorded!")
                st.rerun()

with tab3:
    st.header("Edit or Delete Transactions")
    raw_df = load_data()
    edited_df = st.data_editor(
        raw_df, num_rows="dynamic", use_container_width=True)
    if st.button("Save Changes"):
        edited_df.to_csv(DATA_FILE, index=False)
        st.success("Database updated!")
        st.rerun()
