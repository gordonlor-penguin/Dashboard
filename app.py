import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import os

# --- 1. SETUP THE DATABASE ---
DATA_FILE = "my_portfolio.csv"

# Create a brand new file with your EXACT headers if it doesn't exist
if not os.path.exists(DATA_FILE):
    print("--- 📁 Creating a fresh data file with the correct headers ---")
    df_init = pd.DataFrame(
        columns=["Ticker Symbol", "Currency", "Price", "Quantity"])
    df_init.to_csv(DATA_FILE, index=False)

# Function to load data


def load_data():
    return pd.read_csv(DATA_FILE)

# Function to save new data


def save_transaction(ticker, currency, price, quantity):
    df = load_data()
    # Create a new row matching your exact headers
    new_data = pd.DataFrame({
        "Ticker Symbol": [ticker.upper()],
        "Currency": [currency.upper()],
        "Price": [price],
        "Quantity": [quantity]
    })
    # Add it to the bottom of the file
    df = pd.concat([df, new_data], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)
    print(f"--- ✅ Saved: {quantity} of {ticker.upper()} ---")

# --- 2. FETCH DYNAMIC LIVE PRICES ---


def get_live_price(ticker):
    print(f"--- 🌐 Fetching live price for {ticker}... ---")
    try:
        stock = yf.Ticker(ticker)
        # Grab the most recent closing price
        live_price = stock.history(period="1d")['Close'].iloc[0]
        return live_price
    except Exception as e:
        print(f"--- ❌ ERROR fetching price for {ticker}: {e} ---")
        return 0.0


# --- 3. BUILD THE WEB INTERFACE ---
st.set_page_config(page_title="Investment Dashboard", layout="wide")
st.title("📈 My Investment Dashboard")

# We added a third tab here!
tab1, tab2, tab3 = st.tabs(
    ["Dashboard", "Add Transaction", "Edit/Delete Data"])

with tab1:
    st.header("Current Portfolio")

    portfolio_df = load_data()

    if portfolio_df.empty:
        st.info(
            "Your portfolio is empty. Go to the 'Add Transaction' tab to add some investments!")
    else:
        # Group by "Ticker Symbol" to combine the quantities if you buy the same stock twice
        summary_df = portfolio_df.groupby(["Ticker Symbol", "Currency"]).agg({
            "Quantity": "sum",
            "Price": "mean"
        }).reset_index()

        # Add a new column for the Dynamic Live Price from Yahoo Finance
        summary_df["Live Price"] = summary_df["Ticker Symbol"].apply(
            get_live_price)

        # Calculate Total Value (Fixed Quantity * Dynamic Live Price)
        summary_df["Total Value"] = summary_df["Quantity"] * \
            summary_df["Live Price"]

        # Display the data as a clean table on the webpage
        st.dataframe(summary_df, use_container_width=True)

        # Calculate the grand total
        grand_total = summary_df["Total Value"].sum()
        st.subheader(f"Total Portfolio Value: {grand_total:,.2f}")
        st.caption(
            "*Note: If your portfolio contains mixed currencies, this total currently adds the raw numbers together.*")

        # Draw a Pie Chart using Plotly
        st.write("### Portfolio Breakdown")
        fig = px.pie(summary_df, values='Total Value',
                     names='Ticker Symbol', hole=0.4)
        st.plotly_chart(fig)

with tab2:
    st.header("Record a Buy/Sell")

    # The form to type in new transactions
    with st.form("transaction_form"):
        input_ticker = st.text_input("Ticker Symbol (e.g., AAPL, VOO)")
        input_currency = st.text_input("Currency (e.g., USD, CAD)")
        input_price = st.number_input(
            "Purchase Price", min_value=0.0, format="%.2f")
        input_quantity = st.number_input(
            "Quantity (use negative for selling)", value=0.0)

        submitted = st.form_submit_button("Save Transaction")

        if submitted:
            if input_ticker != "" and input_quantity != 0:
                save_transaction(input_ticker, input_currency,
                                 input_price, input_quantity)
                st.success(
                    f"Successfully recorded {input_quantity} of {input_ticker.upper()}!")
            else:
                st.error("Please enter a valid ticker symbol and quantity.")

# --- NEW FEATURE: The Delete/Edit Tab ---
with tab3:
    st.header("Manage Your Database")
    st.write("Click on any cell to edit a typo. To delete a transaction, click the grey box on the far left of the row to select it, then press **Delete** or **Backspace** on your keyboard.")

    # Load the raw data
    raw_df = load_data()

    # Display the interactive editor
    edited_df = st.data_editor(
        raw_df, num_rows="dynamic", use_container_width=True)

    # Save button
    if st.button("Save Database Changes"):
        edited_df.to_csv(DATA_FILE, index=False)
        st.success(
            "✅ Changes saved to your CSV file! Click over to the 'Dashboard' tab to see your updated portfolio.")
