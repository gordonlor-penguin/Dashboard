import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.express as px
import os

# --- 1. PASSWORD PROTECTION LOGIC ---
def check_password():
    """Returns True if the user had the correct password."""
    def password_entered():
        """Checks whether a password entered by the user is correct."""
        if st.session_state["password_input"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password_input"]  # remove password from session state
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input for password.
        st.title("🔒 Private Portfolio Access")
        st.text_input("Please enter the password to view your investments:", 
                      type="password", on_change=password_entered, key="password_input")
        return False
    elif not st.session_state["password_correct"]:
        # Password not correct, show input + error.
        st.title("🔒 Private Portfolio Access")
        st.text_input("Please enter the password to view your investments:", 
                      type="password", on_change=password_entered, key="password_input")
        st.error("😕 Password incorrect")
        return False
    else:
        # Password correct.
        return True

# --- 2. DATABASE & UTILITY FUNCTIONS ---
DATA_FILE = "my_portfolio.csv"

if not os.path.exists(DATA_FILE):
    df_init = pd.DataFrame(columns=["Ticker Symbol", "Currency", "Price", "Quantity"])
    df_init.to_csv(DATA_FILE, index=False)

def load_data():
    df = pd.read_csv(DATA_FILE)
    df["Price"] = pd.to_numeric(df["Price"], errors='coerce').fillna(0)
    df["Quantity"] = pd.to_numeric(df["Quantity"], errors='coerce').fillna(0)
    
    # Auto-sanitize existing CAD tickers
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
    # Smart suffix for Canadian stocks
    if clean_currency == "CAD" and not clean_ticker.endswith(".TO"):
        clean_ticker = f"{clean_ticker}.TO"
    
    new_data = pd.DataFrame({
        "Ticker Symbol": [clean_ticker], 
        "Currency": [clean_currency], 
        "Price": [price], 
        "Quantity": [quantity]
    })
    df = pd.concat([df, new_data], ignore_index=True)
    df.to_csv(DATA_FILE, index=False)

def get_live_price(ticker):
    try:
        stock = yf.Ticker(ticker.strip())
        data = stock.history(period="1d")
        return data['Close'].iloc[-1] if not data.empty else 0.0
    except:
        return 0.0

def get_exchange_rate():
    try:
        rate = yf.Ticker("USDCAD=X").history(period="1d")['Close'].iloc[-1]
        return rate
    except:
        return 1.35 # Fallback

# --- 3. MAIN APP INTERFACE ---
if check_password():
    st.set_page_config(page_title="Investment Dashboard", layout="wide")
    st.title("📈 My Investment Dashboard")

    tab1, tab2, tab3 = st.tabs(["📊 Dashboard", "➕ Add Transaction", "⚙️ Manage Data"])

    with tab1:
        st.header("Current Portfolio")
        portfolio_df = load_data()
        
        if portfolio_df.empty:
            st.info("Your portfolio is empty. Add some investments in the next tab!")
        else:
            summary_df = portfolio_df.groupby(["Ticker Symbol", "Currency"]).agg({"Quantity": "sum", "Price": "mean"}).reset_index()
            
            with st.spinner('Calculating values and live exchange rates...'):
                usdcad_rate = get_exchange_rate()
                summary_df["Live Price"] = summary_df["Ticker Symbol"].apply(get_live_price)
                summary_df["Value (Native)"] = summary_df["Quantity"] * summary_df["Live Price"]
                
                # Conversions
                summary_df["Value (USD)"] = summary_df.apply(lambda r: r["Value (Native)"] / usdcad_rate if r["Currency"] == "CAD" else r["Value (Native)"], axis=1)
                summary_df["Value (CAD)"] = summary_df.apply(lambda r: r["Value (Native)"] * usdcad_rate if r["Currency"] == "USD" else r["Value (Native)"], axis=1)

            # Metrics
            t1, t2, t3 = st.columns(3)
            t1.metric("Total Value (USD)", f"${summary_df['Value (USD)'].sum():,.2f}")
            t2.metric("Total Value (CAD)", f"${summary_df['Value (CAD)'].sum():,.2f}")
            t3.metric("USD/CAD Rate", f"{usdcad_rate:.4f}")

            st.dataframe(summary_df[["Ticker Symbol", "Currency", "Quantity", "Live Price", "Value (Native)", "Value (CAD)"]].style.format({
                "Live Price": "{:.2f}", "Value (Native)": "{:.2f}", "Value (CAD)": "{:.2f}"
            }), use_container_width=True)
            
            st.write("### Portfolio Breakdown (CAD Equivalent)")
            fig = px.pie(summary_df, values='Value (CAD)', names='Ticker Symbol', hole=0.4)
            st.plotly_chart(fig, use_container_width=True)

    with tab2:
        st.header("Record a Transaction")
        with st.form("transaction_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            with c1:
                input_t = st.text_input("Ticker Symbol")
                input_c = st.selectbox("Currency", ["USD", "CAD"])
            with c2:
                input_p = st.number_input("Price", min_value=0.0)
                input_q = st.number_input("Quantity", min_value=0.0)
            
            if st.form_submit_button("Save to Database"):
                if input_t:
                    save_transaction(input_t, input_c, input_p, input_q)
                    st.success("Successfully saved! Refreshing...")
                    st.rerun()

    with tab3:
        st.header("Database Management")
        raw_df = load_data()
        edited_df = st.data_editor(raw_df, num_rows="dynamic", use_container_width=True)
        if st.button("Commit Changes"):
            edited_df.to_csv(DATA_FILE, index=False)
            st.success("Changes saved to your permanent record!")
            st.rerun()