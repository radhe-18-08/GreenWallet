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
def fetch_esg(ticker):
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
    try:
        sus = yf.Ticker(ticker).sustainability
        if sus is not None and not sus.empty:
            e = float(sus.loc['environmentScore'][0]) if 'environmentScore' in sus.index else 50.0
            s = float(sus.loc['socialScore'][0]) if 'socialScore' in sus.index else 50.0
            g = float(sus.loc['governanceScore'][0]) if 'governanceScore' in sus.index else 50.0
            total = float(sus.loc['totalEsg'][0]) if 'totalEsg' in sus.index else round((e+s+g)/3, 1)
            return e, s, g, total, "YahooFinance"
    except: pass
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

# ── APP CONFIG ───────────────────────────────────────
st.set_page_config(page_title="GreenWallet", page_icon="🌿", layout="wide")
conn = init_db()

# ── CUSTOM CSS ───────────────────────────────────────
st.markdown("""<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;700;900&display=swap');
    html, body, .stApp {background-color: #0a0a1a; font-family: 'DM Sans', sans-serif;}
    .block-container {padding-top: 2rem;}
    h1, h2, h3 {color: #ffffff !important;}

    .card {background: linear-gradient(135deg, #12122a 0%, #1a1a3e 100%);
        border-radius: 16px; padding: 28px; border: 1px solid #1f1f3a; margin-bottom: 16px;}
    .card-green {background: linear-gradient(135deg, #0a2e1f 0%, #12122a 100%);
        border: 1px solid #00b89433;}
    .card-red {background: linear-gradient(135deg, #2e0a0a 0%, #12122a 100%);
        border: 1px solid #d6303133;}

    .score-huge {font-size: 86px; font-weight: 900; line-height: 1; margin: 0; text-align: center;}
    .score-tag {font-size: 20px; font-weight: 700; text-align: center; margin-top: 8px;
        padding: 4px 16px; border-radius: 20px; display: inline-block;}
    .tag-green {background: #00b89422; color: #00b894;}
    .tag-yellow {background: #fdcb6e22; color: #fdcb6e;}
    .tag-red {background: #d6303122; color: #d63031;}

    .stat-value {font-size: 28px; font-weight: 800; color: #ffffff; margin: 0;}
    .stat-label {font-size: 13px; color: #636e72; margin: 0; text-transform: uppercase; letter-spacing: 1px;}
    .source-tag {font-size: 11px; background: #1f1f3a; color: #00b894; padding: 3px 10px;
        border-radius: 12px; display: inline-block; margin-top: 8px;}

    .esg-bar-bg {background: #0d0d1a; border-radius: 8px; height: 14px; width: 100%;
        overflow: hidden; margin: 4px 0 12px 0;}
    .esg-bar-fill {height: 100%; border-radius: 8px; transition: width 0.5s ease;}
    .esg-label {display: flex; justify-content: space-between; font-size: 13px; color: #b2bec3;}

    .login-box {background: linear-gradient(135deg, #12122a, #1a1a3e); border-radius: 24px;
        padding: 48px 40px; border: 1px solid #1f1f3a; max-width: 420px; margin: 80px auto;
        box-shadow: 0 20px 60px rgba(0,184,148,0.06);}
    .login-title {text-align: center; font-size: 42px; margin-bottom: 4px;}
    .login-sub {text-align: center; color: #636e72; font-size: 14px; margin-bottom: 28px;}

    div[data-testid="stDataFrame"] {border-radius: 12px; overflow: hidden;}
    .stTabs [data-baseweb="tab-list"] {gap: 8px;}
    .stTabs [data-baseweb="tab"] {background: #12122a; border-radius: 8px 8px 0 0; color: white; padding: 8px 20px;}
    .stTabs [aria-selected="true"] {background: #00b894 !important;}

    .stButton>button {background: linear-gradient(135deg, #00b894, #00a884) !important;
        color: white !important; border: none !important; border-radius: 10px !important;
        font-weight: 700 !important; padding: 8px 24px !important; transition: all 0.2s !important;}
    .stButton>button:hover {background: linear-gradient(135deg, #00d1a0, #00b894) !important;
        transform: translateY(-1px); box-shadow: 0 4px 15px rgba(0,184,148,0.3) !important;}

    div[data-testid="stSidebar"] {background: #0d0d1a; border-right: 1px solid #1f1f3a;}
    .sidebar-logo {font-size: 28px; font-weight: 900; color: #00b894; margin-bottom: 4px;}
    .sidebar-user {font-size: 13px; color: #636e72;}
</style>""", unsafe_allow_html=True)

if "user" not in st.session_state:
    st.session_state.user = None

# ── LOGIN PAGE ───────────────────────────────────────
if st.session_state.user is None:
    st.markdown("<div class='login-box'>", unsafe_allow_html=True)
    st.markdown("<div class='login-title'>🌿</div>", unsafe_allow_html=True)
    st.markdown("<h2 style='text-align:center;color:#00b894;margin:0'>GreenWallet</h2>", unsafe_allow_html=True)
    st.markdown("<p class='login-sub'>ESG Portfolio Impact Scorer</p>", unsafe_allow_html=True)
    username = st.text_input("Username", placeholder="Enter username")
    portfolio_no = st.text_input("Portfolio Number", placeholder="Enter portfolio number")
    st.caption("Demo accounts: **demo_investor** (PF-1001) · **demo_trader** (PF-2002)")
    if st.button("Login / Register", use_container_width=True):
        if username.strip():
            user = q(conn, "SELECT * FROM users WHERE username=?", (username,), one=True)
            if not user:
                q(conn, "INSERT INTO users(username,portfolio_no) VALUES(?,?)", (username, portfolio_no))
                user = q(conn, "SELECT * FROM users WHERE username=?", (username,), one=True)
            st.session_state.user = user; st.rerun()
    st.markdown("</div>", unsafe_allow_html=True)
    st.stop()

# ── LOGGED IN ────────────────────────────────────────
user = st.session_state.user; uid = user[0]

# Sidebar
st.sidebar.markdown("<p class='sidebar-logo'>🌿 GreenWallet</p>", unsafe_allow_html=True)
st.sidebar.markdown(f"<p class='sidebar-user'>👤 {user[1]} &nbsp;·&nbsp; 📁 {user[2]}</p>", unsafe_allow_html=True)
st.sidebar.divider()
page = st.sidebar.radio("", ["📊 Dashboard", "💼 Portfolio", "🔍 ESG Explorer", "📈 Analytics", "⚙️ Settings"])
st.sidebar.divider()
if st.sidebar.button("🚪 Logout", use_container_width=True):
    st.session_state.user = None; st.rerun()

# ── HELPER: build ESG bar ────────────────────────────
def esg_bar(label, value, color):
    st.markdown(f"""<div class='esg-label'><span>{label}</span><span style='font-weight:700;color:{color}'>{int(value)}</span></div>
    <div class='esg-bar-bg'><div class='esg-bar-fill' style='width:{value}%;background:{color}'></div></div>""", unsafe_allow_html=True)

# ── DASHBOARD ────────────────────────────────────────
if page == "📊 Dashboard":
    st.markdown(f"## Welcome back, {user[1]}")
    holdings = q(conn, "SELECT * FROM holdings WHERE user_id=?", (uid,), fetch=True)
    total_val, weighted, flagged, sources, stock_count = 0, 0, 0, set(), len(holdings)
    with st.spinner("Fetching live market data..."):
        for h in holdings:
            tid, shares = h[2], h[3]
            price = get_price(tid)
            e, s, g, comp, src = get_cached_esg(conn, tid)
            sources.add(src); val = shares * price; total_val += val; weighted += val * comp
            if comp < 30: flagged += 1
    score = weighted / total_val if total_val > 0 else 0

    if score >= 70: label, color, tag_cls = "Sustainable", "#00b894", "tag-green"
    elif score >= 40: label, color, tag_cls = "Moderate", "#fdcb6e", "tag-yellow"
    else: label, color, tag_cls = "High Risk", "#d63031", "tag-red"

    c1, c2 = st.columns([1, 2])
    with c1:
        card_cls = "card card-green" if score >= 40 else "card card-red"
        st.markdown(f"""<div class='{card_cls}'>
            <p class='score-huge' style='color:{color}'>{int(score)}</p>
            <div style='text-align:center'><span class='score-tag {tag_cls}'>{label}</span></div>
            <p style='text-align:center;color:#636e72;margin-top:12px;font-size:13px'>Portfolio Green Score</p>
        </div>""", unsafe_allow_html=True)
    with c2:
        m1, m2, m3 = st.columns(3)
        m1.markdown(f"<div class='card'><p class='stat-label'>Total Value</p><p class='stat-value'>${total_val:,.2f}</p></div>", unsafe_allow_html=True)
        m2.markdown(f"<div class='card'><p class='stat-label'>Holdings</p><p class='stat-value'>{stock_count}</p></div>", unsafe_allow_html=True)
        flag_color = "#d63031" if flagged > 0 else "#00b894"
        m3.markdown(f"<div class='card'><p class='stat-label'>Flagged</p><p class='stat-value' style='color:{flag_color}'>{flagged}</p></div>", unsafe_allow_html=True)
        st.markdown(f"<span class='source-tag'>Data via: {', '.join(sources)}</span>", unsafe_allow_html=True)
        bc1, bc2 = st.columns(2)
        with bc1:
            if st.button("🔄 Refresh Data", use_container_width=True): st.rerun()
        with bc2:
            if st.button("💾 Save Score to History", use_container_width=True):
                q(conn, "INSERT INTO analytics(user_id,green_score) VALUES(?,?)", (uid, int(score)))
                st.success("Score saved!")

# ── PORTFOLIO ────────────────────────────────────────
elif page == "💼 Portfolio":
    st.markdown("## Portfolio Management")
    with st.form("add_stock", clear_on_submit=True):
        c1, c2, c3 = st.columns([3, 1.5, 1])
        new_tick = c1.text_input("Ticker", placeholder="e.g. AAPL")
        new_shares = c2.number_input("Shares", min_value=0.1, value=1.0)
        c3.markdown("<br>", unsafe_allow_html=True)
        submitted = c3.form_submit_button("➕ Add")
        if submitted and new_tick.strip():
            q(conn, "INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)", (uid, new_tick.upper().strip(), new_shares))
            st.rerun()

    holdings = q(conn, "SELECT * FROM holdings WHERE user_id=?", (uid,), fetch=True)
    if holdings:
        rows = []
        with st.spinner("Loading portfolio data..."):
            for h in holdings:
                tid, shares = h[2], h[3]
                price = get_price(tid)
                e, s, g, comp, src = get_cached_esg(conn, tid)
                flag = "⚠️ RISK" if comp < 30 else "✅ OK"
                rows.append({"Ticker": tid, "Shares": shares, "Price ($)": round(price, 2),
                    "Value ($)": round(shares * price, 2), "ESG Score": comp, "Source": src, "Status": flag, "_id": h[0]})
        df = pd.DataFrame(rows)
        st.dataframe(df.drop(columns=["_id"]), use_container_width=True, hide_index=True)

        st.markdown("### Manage Holdings")
        c1, c2 = st.columns(2)
        with c1:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            del_tick = st.selectbox("Select stock to delete", [r["Ticker"] for r in rows], key="del")
            if st.button("🗑️ Delete Stock", use_container_width=True):
                hid = [r["_id"] for r in rows if r["Ticker"] == del_tick][0]
                q(conn, "DELETE FROM holdings WHERE id=?", (hid,)); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
        with c2:
            st.markdown("<div class='card'>", unsafe_allow_html=True)
            upd_tick = st.selectbox("Select stock to update", [r["Ticker"] for r in rows], key="upd")
            new_s = st.number_input("New share count", min_value=0.1, value=1.0, key="upd_s")
            if st.button("✏️ Update Shares", use_container_width=True):
                hid = [r["_id"] for r in rows if r["Ticker"] == upd_tick][0]
                q(conn, "UPDATE holdings SET shares=? WHERE id=?", (new_s, hid)); st.rerun()
            st.markdown("</div>", unsafe_allow_html=True)
    else:
        st.info("No holdings yet. Add stocks above to build your portfolio.")

# ── ESG EXPLORER ─────────────────────────────────────
elif page == "🔍 ESG Explorer":
    st.markdown("## ESG Explorer")
    st.caption("Search any stock ticker to fetch live ESG data from Alpha Vantage, Yahoo Finance, or Finnhub")
    c1, c2 = st.columns([3, 1])
    search = c1.text_input("Ticker", placeholder="e.g. TSLA", label_visibility="collapsed")
    c2.markdown("<br>", unsafe_allow_html=True)
    fetch_btn = c2.button("🔍 Fetch ESG", use_container_width=True)

    if fetch_btn and search.strip():
        with st.spinner(f"Fetching ESG data for {search.upper()}..."):
            e, s, g, comp, src = fetch_esg(search.upper().strip())
        st.markdown(f"""<div class='card'>
            <h3 style='margin:0'>{search.upper()}</h3>
            <span class='source-tag'>Source: {src}</span>
        </div>""", unsafe_allow_html=True)

        esg_bar("🌍 Environmental", e, "#00b894")
        esg_bar("👥 Social", s, "#00cec9")
        esg_bar("🏛️ Governance", g, "#0984e3")

        comp_color = "#00b894" if comp >= 60 else "#fdcb6e" if comp >= 40 else "#d63031"
        st.markdown(f"""<div class='card' style='text-align:center;margin-top:16px'>
            <p class='stat-label'>Composite ESG Score</p>
            <p class='stat-value' style='font-size:48px;color:{comp_color}'>{comp}</p>
        </div>""", unsafe_allow_html=True)

# ── ANALYTICS ────────────────────────────────────────
elif page == "📈 Analytics":
    st.markdown("## Analytics")
    t1, t2 = st.tabs(["📉 Green Score History", "🥧 Portfolio Allocation"])

    with t1:
        data = q(conn, "SELECT green_score, recorded_at FROM analytics WHERE user_id=? ORDER BY recorded_at", (uid,), fetch=True)
        if data:
            df = pd.DataFrame(data, columns=["Green Score", "Date"])
            df["Date"] = pd.to_datetime(df["Date"])
            st.line_chart(df.set_index("Date")["Green Score"], color="#00b894")
        else:
            st.info("No history yet. Save scores from the Dashboard to track your sustainability trends.")
    with t2:
        holdings = q(conn, "SELECT ticker, shares FROM holdings WHERE user_id=?", (uid,), fetch=True)
        if holdings:
            df = pd.DataFrame(holdings, columns=["Ticker", "Shares"])
            st.bar_chart(df.set_index("Ticker"), color="#00b894")
        else:
            st.info("No holdings to display.")

# ── SETTINGS ─────────────────────────────────────────
elif page == "⚙️ Settings":
    st.markdown("## Settings")
    st.markdown(f"""<div class='card'>
        <p class='stat-label'>Username</p><p class='stat-value' style='font-size:22px'>{user[1]}</p>
        <p class='stat-label' style='margin-top:12px'>Portfolio Number</p><p class='stat-value' style='font-size:22px'>{user[2]}</p>
    </div>""", unsafe_allow_html=True)

    c1, c2 = st.columns(2)
    with c1:
        if st.button("🧹 Clear ESG Cache", use_container_width=True):
            q(conn, "DELETE FROM esg_cache")
            st.success("Cache cleared — fresh API calls on next refresh.")
    with c2:
        holdings = q(conn, "SELECT * FROM holdings WHERE user_id=?", (uid,), fetch=True)
        if holdings:
            df = pd.DataFrame(holdings, columns=["ID","UserID","Ticker","Shares","Date"])
            csv = df.to_csv(index=False)
            st.download_button("📥 Export Portfolio CSV", csv, "portfolio_export.csv", "text/csv", use_container_width=True)
