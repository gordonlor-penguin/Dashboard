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
    return df

# --- SMART SAVING LOGIC ---


def save_transaction(ticker, currency, price, quantity):
    df = load_data()

    clean_ticker = ticker.upper().strip()
    clean_currency = currency.upper().strip()

    # Check if it's Canadian and missing the suffix
    if clean_currency == "CAD" and not clean_ticker.endswith(".TO"):
        print(f"--- 🍁 Auto-adding .TO to {clean_ticker} ---")
        clean_ticker = f"{clean_ticker}.TO"

    new_data = pd.DataFrame({
        "Ticker Symbol": [clean_ticker],
        "Currency": [clean_currency],
        "Price": [price],
        "Quantity": [quantity]
    })
    df = pd.concat([df, new_data], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

# --- 2. FETCH DYNAMIC LIVE PRICES ---


def get_live_price(ticker):
    try:
        stock = yf.Ticker(ticker.strip())
        # We use iloc[-1] to get the absolute latest available price
        live_price = stock.history(period="1d")['Close'].iloc[-1]
        return live_price
    except Exception:
        return 0.0


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
        summary_df = portfolio_df.groupby(["Ticker Symbol", "Currency"]).agg({
            "Quantity": "sum",
            "Price": "mean"
        }).reset_index()

        with st.spinner('Updating live prices...'):
            summary_df["Live Price"] = summary_df["Ticker Symbol"].apply(
                get_live_price)
            summary_df["Total Value"] = summary_df["Quantity"] * \
                summary_df["Live Price"]

        col1, col2 = st.columns(2)
        grand_total = summary_df["Total Value"].sum()
        col1.metric("Total Portfolio Value (Combined)", f"${grand_total:,.2f}")

        st.dataframe(summary_df.style.format({
            "Price": "${:.2f}",
            "Live Price": "${:.2f}",
            "Total Value": "${:.2f}"
        }), use_container_width=True)

        st.write("### Portfolio Allocation")
        fig = px.pie(summary_df, values='Total Value',
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
                st.success(f"Successfully recorded transaction!")
                st.rerun()
            else:
                st.error("Please enter a Ticker Symbol.")

with tab3:
    st.header("Edit or Delete Transactions")
    raw_df = load_data()
    edited_df = st.data_editor(
        raw_df, num_rows="dynamic", use_container_width=True)

    if st.button("Save Changes"):
        edited_df.to_csv(DATA_FILE, index=False)
        st.success("Database updated!")
        st.rerun()
