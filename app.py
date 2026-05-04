import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import os

# --- 1. SETUP THE DATABASE ---
DATA_FILE = "my_portfolio.csv"

# Create a brand new file with your EXACT headers if it doesn't exist
if not os.path.exists(DATA_FILE):
    df_init = pd.DataFrame(
        columns=["Ticker Symbol", "Currency", "Price", "Quantity"])
    df_init.to_csv(DATA_FILE, index=False)

# Function to load data with "Number Protection"


def load_data():
    df = pd.read_csv(DATA_FILE)
    # Ensure Price and Quantity are treated as numbers to prevent TypeErrors
    df["Price"] = pd.to_numeric(df["Price"], errors='coerce').fillna(0)
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors='coerce').fillna(0)
    return df

# Function to save new data


def save_transaction(ticker, currency, price, quantity):
    df = load_data()
    new_data = pd.DataFrame({
        "Ticker Symbol": [ticker.upper().strip()],
        "Currency": [currency.upper().strip()],
        "Price": [price],
        "Quantity": [quantity]
    })
    df = pd.concat([df, new_data], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

# --- 2. FETCH DYNAMIC LIVE PRICES ---


def get_live_price(ticker):
    try:
        # Note: For Canadian stocks, remember to use .TO (e.g., SHOP.TO)
        stock = yf.Ticker(ticker.strip())
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
        # Group data to combine multiple buys of the same stock
        summary_df = portfolio_df.groupby(["Ticker Symbol", "Currency"]).agg({
            "Quantity": "sum",
            "Price": "mean"
        }).reset_index()

        # Fetch live prices
        with st.spinner('Updating live prices...'):
            summary_df["Live Price"] = summary_df["Ticker Symbol"].apply(
                get_live_price)
            summary_df["Total Value"] = summary_df["Quantity"] * \
                summary_df["Live Price"]
            summary_df["Profit/Loss %"] = (
                (summary_df["Live Price"] - summary_df["Price"]) / summary_df["Price"]) * 100

        # Display Key Metrics
        col1, col2 = st.columns(2)
        grand_total = summary_df["Total Value"].sum()
        col1.metric("Total Portfolio Value", f"${grand_total:,.2f}")

        # Table view
        st.dataframe(summary_df.style.format({
            "Price": "${:.2f}",
            "Live Price": "${:.2f}",
            "Total Value": "${:.2f}",
            "Profit/Loss %": "{:.2f}%"
        }), use_container_width=True)

        # Visual Breakdown
        st.write("### Portfolio Allocation")
        fig = px.pie(summary_df, values='Total Value',
                     names='Ticker Symbol', hole=0.4)
        st.plotly_chart(fig, use_container_width=True)

with tab2:
    st.header("Add New Investment")
    with st.form("transaction_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            input_ticker = st.text_input("Ticker (e.g. AAPL or TD.TO)")
            input_currency = st.selectbox(
                "Currency", ["USD", "CAD", "EUR", "GBP"])
        with col2:
            input_price = st.number_input(
                "Purchase Price", min_value=0.0, step=0.01)
            input_quantity = st.number_input(
                "Quantity", min_value=0.0, step=0.1)

        if st.form_submit_button("Save to Portfolio"):
            if input_ticker:
                save_transaction(input_ticker, input_currency,
                                 input_price, input_quantity)
                st.success(f"Added {input_ticker.upper()} to your records!")
                st.rerun()
            else:
                st.error("Please enter a Ticker Symbol.")

with tab3:
    st.header("Edit or Delete Transactions")
    st.write("Modify cells below and click 'Save Changes' to update your database.")

    raw_df = load_data()
    edited_df = st.data_editor(
        raw_df, num_rows="dynamic", use_container_width=True)

    if st.button("Save Changes"):
        edited_df.to_csv(DATA_FILE, index=False)
        st.success("Database updated successfully!")
        st.rerun()
