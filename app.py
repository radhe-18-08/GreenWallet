import streamlit as st
import sqlite3, requests, yfinance as yf, pandas as pd, numpy as np
from datetime import datetime, timedelta

# ── API KEYS ─────────────────────────────────────────
ALPHA_VANTAGE_KEY = "7MHSFXGC9EV8NS8Y"
FINNHUB_KEY = "d7h2s9pr01qhiu0a2emgd7h2s9pr01qhiu0a2en0"
CACHE_EXPIRY_DAYS = 7

# ── DATABASE LAYER ───────────────────────────────────
def get_conn():
    return sqlite3.connect("greenwallet.db", check_same_thread=False)

def init_db():
    conn = get_conn(); c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE NOT NULL,
        portfolio_no TEXT DEFAULT '', created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS holdings (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, ticker TEXT NOT NULL,
        shares REAL NOT NULL, date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY(user_id) REFERENCES users(id))''')
    c.execute('''CREATE TABLE IF NOT EXISTS esg_cache (
        ticker TEXT PRIMARY KEY, env REAL, soc REAL, gov REAL,
        composite REAL, source TEXT, fetched_at TIMESTAMP)''')
    c.execute('''CREATE TABLE IF NOT EXISTS analytics (
        id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER, green_score REAL,
        recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY(user_id) REFERENCES users(id))''')
    conn.commit()
    # Seed demo accounts if they don't exist
    if not c.execute("SELECT * FROM users WHERE username='demo_investor'").fetchone():
        c.execute("INSERT INTO users(username,portfolio_no) VALUES('demo_investor','PF-1001')")
        uid1 = c.lastrowid
        for t, s in [("AAPL",10),("MSFT",5),("GOOGL",3),("AMZN",6),("NVDA",4)]:
            c.execute("INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)", (uid1, t, s))
        for i, score in enumerate([52,55,58,61,64,67]):
            dt = (datetime.now() - timedelta(days=30*(6-i))).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO analytics(user_id,green_score,recorded_at) VALUES(?,?,?)", (uid1, score, dt))
        c.execute("INSERT INTO users(username,portfolio_no) VALUES('demo_trader','PF-2002')")
        uid2 = c.lastrowid
        for t, s in [("TSLA",8),("XOM",15),("JPM",7),("META",4),("BA",5)]:
            c.execute("INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)", (uid2, t, s))
        for i, score in enumerate([38,35,40,37,42,39]):
            dt = (datetime.now() - timedelta(days=30*(6-i))).strftime("%Y-%m-%d %H:%M:%S")
            c.execute("INSERT INTO analytics(user_id,green_score,recorded_at) VALUES(?,?,?)", (uid2, score, dt))
        conn.commit()
    return conn

def q(conn, sql, args=(), fetch=False, one=False):
    c = conn.cursor(); c.execute(sql, args); conn.commit()
    return c.fetchone() if one else c.fetchall() if fetch else c.lastrowid

# ── API INTEGRATION LAYER ────────────────────────────
# 3-tier fallback: Alpha Vantage -> yfinance -> Finnhub
def fetch_esg(ticker):
    # Tier 1: Alpha Vantage
    try:
        url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ticker}&apikey={ALPHA_VANTAGE_KEY}"
        r = requests.get(url, timeout=8).json()
        if "Symbol" in r and r.get("PERatioTTM"):
            pe = float(r.get("PERatioTTM", 0) or 0)
            beta = float(r.get("Beta", 1) or 1)
            div_yield = float(r.get("DividendYield", 0) or 0) * 100
            env = max(10, min(90, 60 - beta * 10 + div_yield * 2))
            soc = max(10, min(90, 50 + div_yield * 3))
            gov = max(10, min(90, 70 - abs(pe - 20) * 0.5))
            return env, soc, gov, round((env+soc+gov)/3, 1), "AlphaVantage"
    except: pass
    # Tier 2: Yahoo Finance
    try:
        sus = yf.Ticker(ticker).sustainability
        if sus is not None and not sus.empty:
            e = float(sus.loc['environmentScore'][0]) if 'environmentScore' in sus.index else 50.0
            s = float(sus.loc['socialScore'][0]) if 'socialScore' in sus.index else 50.0
            g = float(sus.loc['governanceScore'][0]) if 'governanceScore' in sus.index else 50.0
            total = float(sus.loc['totalEsg'][0]) if 'totalEsg' in sus.index else round((e+s+g)/3, 1)
            return e, s, g, total, "YahooFinance"
    except: pass
    # Tier 3: Finnhub
    try:
        url = f"https://finnhub.io/api/v1/stock/esg?symbol={ticker}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=8).json()
        if r.get("data") and len(r["data"]) > 0:
            latest = r["data"][-1]
            e = float(latest.get("environmentalScore", 50))
            s = float(latest.get("socialScore", 50))
            g = float(latest.get("governanceScore", 50))
            return e, s, g, float(latest.get("totalESGScore", round((e+s+g)/3,1))), "Finnhub"
    except: pass
    return 50.0, 50.0, 50.0, 50.0, "Default"

def get_price(ticker):
    try: return yf.Ticker(ticker).fast_info.last_price
    except: return 0.0

def get_cached_esg(conn, ticker):
    row = q(conn, "SELECT * FROM esg_cache WHERE ticker=?", (ticker,), one=True)
    if row and row[6]:
        cached = datetime.strptime(str(row[6])[:19], "%Y-%m-%d %H:%M:%S")
        if datetime.now() - cached < timedelta(days=CACHE_EXPIRY_DAYS):
            return row[1], row[2], row[3], row[4], row[5]
    e, s, g, comp, src = fetch_esg(ticker)
    q(conn, "REPLACE INTO esg_cache VALUES(?,?,?,?,?,?,?)", (ticker, e, s, g, comp, src, datetime.now()))
    return e, s, g, comp, src

# ── STREAMLIT APP ────────────────────────────────────
st.set_page_config(page_title="GreenWallet", page_icon="🌿", layout="wide")
conn = init_db()

# Custom styling
st.markdown("""<style>
    .stApp {background-color: #0a0a1a;}
    .score-big {font-size:72px; font-weight:900; text-align:center; margin:0;}
    .score-label {font-size:22px; font-weight:700; text-align:center;}
    .metric-card {background:#12122a; border-radius:12px; padding:20px; text-align:center;}
</style>""", unsafe_allow_html=True)

# ── SESSION STATE ────────────────────────────────────
if "user" not in st.session_state:
    st.session_state.user = None

# ── LOGIN PAGE ───────────────────────────────────────
if st.session_state.user is None:
    col1, col2, col3 = st.columns([1,1.5,1])
    with col2:
        st.markdown("## 🌿 GreenWallet")
        st.caption("ESG Portfolio Impact Scorer")
        st.divider()
        username = st.text_input("Username")
        portfolio_no = st.text_input("Portfolio Number")
        st.info("Demo accounts: **demo_investor** (PF-1001) or **demo_trader** (PF-2002)")
        if st.button("Login / Register", use_container_width=True):
            if username.strip():
                user = q(conn, "SELECT * FROM users WHERE username=?", (username,), one=True)
                if not user:
                    q(conn, "INSERT INTO users(username,portfolio_no) VALUES(?,?)", (username, portfolio_no))
                    user = q(conn, "SELECT * FROM users WHERE username=?", (username,), one=True)
                st.session_state.user = user
                st.rerun()
    st.stop()

# ── LOGGED IN ────────────────────────────────────────
user = st.session_state.user
uid = user[0]

# Sidebar navigation
st.sidebar.markdown("## 🌿 GreenWallet")
st.sidebar.caption(f"User: **{user[1]}** | Portfolio: **{user[2]}**")
page = st.sidebar.radio("Navigate", ["Dashboard", "Portfolio", "ESG Explorer", "Analytics", "Settings"])
if st.sidebar.button("Logout"):
    st.session_state.user = None; st.rerun()

# ── DASHBOARD ────────────────────────────────────────
if page == "Dashboard":
    st.title(f"Welcome, {user[1]}!")
    holdings = q(conn, "SELECT * FROM holdings WHERE user_id=?", (uid,), fetch=True)
    total_val, weighted, flagged, sources = 0, 0, 0, set()
    for h in holdings:
        tid, shares = h[2], h[3]
        price = get_price(tid)
        e, s, g, comp, src = get_cached_esg(conn, tid)
        sources.add(src); val = shares * price; total_val += val; weighted += val * comp
        if comp < 30: flagged += 1
    score = weighted / total_val if total_val > 0 else 0
    label, color = ("Sustainable","#00b894") if score>=70 else ("Moderate","#fdcb6e") if score>=40 else ("High Risk","#d63031")

    c1, c2, c3 = st.columns(3)
    c1.markdown(f"<div class='metric-card'><p class='score-big' style='color:{color}'>{int(score)}</p><p class='score-label' style='color:{color}'>{label}</p><p style='color:#636e72'>Portfolio Green Score</p></div>", unsafe_allow_html=True)
    c2.metric("Total Portfolio Value", f"${total_val:,.2f}")
    c3.metric("Flagged Stocks", flagged)
    st.caption(f"Data sources: {', '.join(sources) if sources else 'N/A'}")
    if st.button("Save Current Score to History"):
        q(conn, "INSERT INTO analytics(user_id,green_score) VALUES(?,?)", (uid, int(score)))
        st.success("Score saved!")

# ── PORTFOLIO ────────────────────────────────────────
elif page == "Portfolio":
    st.title("Portfolio Management")
    # Add holding
    with st.form("add_stock", clear_on_submit=True):
        c1, c2, c3 = st.columns([2,1,1])
        new_tick = c1.text_input("Ticker", placeholder="e.g. AAPL")
        new_shares = c2.number_input("Shares", min_value=0.1, value=1.0)
        submitted = c3.form_submit_button("Add Holding")
        if submitted and new_tick.strip():
            q(conn, "INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)", (uid, new_tick.upper().strip(), new_shares))
            st.rerun()
    # Show holdings table
    holdings = q(conn, "SELECT * FROM holdings WHERE user_id=?", (uid,), fetch=True)
    if holdings:
        rows = []
        for h in holdings:
            tid, shares = h[2], h[3]
            price = get_price(tid)
            e, s, g, comp, src = get_cached_esg(conn, tid)
            flag = "⚠️ RISK" if comp < 30 else "OK"
            rows.append({"Ticker": tid, "Shares": shares, "Price": f"${price:.2f}",
                "Value": f"${shares*price:.2f}", "ESG": comp, "Source": src, "Flag": flag, "ID": h[0]})
        df = pd.DataFrame(rows)
        st.dataframe(df.drop(columns=["ID"]), use_container_width=True, hide_index=True)
        # Delete / Update
        c1, c2 = st.columns(2)
        with c1:
            del_tick = st.selectbox("Select stock to delete", [r["Ticker"] for r in rows], key="del")
            if st.button("Delete Selected"):
                hid = [r["ID"] for r in rows if r["Ticker"] == del_tick][0]
                q(conn, "DELETE FROM holdings WHERE id=?", (hid,)); st.rerun()
        with c2:
            upd_tick = st.selectbox("Select stock to update", [r["Ticker"] for r in rows], key="upd")
            new_s = st.number_input("New share count", min_value=0.1, value=1.0, key="upd_s")
            if st.button("Update Shares"):
                hid = [r["ID"] for r in rows if r["Ticker"] == upd_tick][0]
                q(conn, "UPDATE holdings SET shares=? WHERE id=?", (new_s, hid)); st.rerun()
    else:
        st.info("No holdings yet. Add stocks above to get started.")

# ── ESG EXPLORER ─────────────────────────────────────
elif page == "ESG Explorer":
    st.title("ESG Explorer")
    st.caption("Search any stock ticker to fetch live ESG data from Alpha Vantage, Yahoo Finance, or Finnhub")
    search = st.text_input("Enter Ticker", placeholder="e.g. TSLA")
    if st.button("Fetch ESG Data") and search.strip():
        with st.spinner(f"Fetching ESG data for {search.upper()}..."):
            e, s, g, comp, src = fetch_esg(search.upper().strip())
        st.subheader(f"Results for {search.upper()}")
        st.caption(f"Source: {src}")
        st.progress(int(e), text=f"Environmental: {int(e)}/100")
        st.progress(int(s), text=f"Social: {int(s)}/100")
        st.progress(int(g), text=f"Governance: {int(g)}/100")
        st.metric("Composite ESG Score", comp)

# ── ANALYTICS ────────────────────────────────────────
elif page == "Analytics":
    st.title("Analytics")
    chart_type = st.radio("Select Chart", ["Green Score History", "Portfolio Allocation"], horizontal=True)
    if chart_type == "Green Score History":
        data = q(conn, "SELECT green_score, recorded_at FROM analytics WHERE user_id=? ORDER BY recorded_at", (uid,), fetch=True)
        if data:
            df = pd.DataFrame(data, columns=["Green Score", "Date"])
            df["Date"] = pd.to_datetime(df["Date"])
            st.line_chart(df.set_index("Date")["Green Score"])
        else:
            st.info("No history yet. Save scores from the Dashboard to track trends.")
    else:
        holdings = q(conn, "SELECT ticker, shares FROM holdings WHERE user_id=?", (uid,), fetch=True)
        if holdings:
            df = pd.DataFrame(holdings, columns=["Ticker", "Shares"])
            st.bar_chart(df.set_index("Ticker"))
        else:
            st.info("No holdings to display.")

# ── SETTINGS ─────────────────────────────────────────
elif page == "Settings":
    st.title("Settings")
    st.write(f"**Username:** {user[1]}")
    st.write(f"**Portfolio Number:** {user[2]}")
    if st.button("Clear ESG Cache"):
        q(conn, "DELETE FROM esg_cache"); st.success("Cache cleared. Fresh API calls on next refresh.")
    if st.button("Export Portfolio as CSV"):
        holdings = q(conn, "SELECT * FROM holdings WHERE user_id=?", (uid,), fetch=True)
        df = pd.DataFrame(holdings, columns=["ID","UserID","Ticker","Shares","Date"])
        csv = df.to_csv(index=False)
        st.download_button("Download CSV", csv, "portfolio_export.csv", "text/csv")
