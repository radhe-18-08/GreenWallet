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
        st.download_button("Download CSV", csv, "portfolio_export.csv", "text/csv")        """Creates 2 demo accounts with pre-loaded stock holdings on first run.
        Prices and ESG scores are fetched LIVE from APIs (Alpha Vantage, yfinance, Finnhub)."""
        if self.get_user("demo_investor"): return  # Already seeded
        # Demo Account 1: Tech-heavy sustainable portfolio
        uid1 = self.q("INSERT INTO users(username,portfolio_no) VALUES(?,?)", ("demo_investor","PF-1001"))
        for ticker, shares in [("AAPL",10),("MSFT",5),("GOOGL",3),("AMZN",6),("NVDA",4)]:
            self.q("INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)", (uid1, ticker, shares))
        for i, score in enumerate([52,55,58,61,64,67]):
            dt = (datetime.now() - timedelta(days=30*(6-i))).strftime("%Y-%m-%d %H:%M:%S")
            self.q("INSERT INTO analytics(user_id,green_score,recorded_at) VALUES(?,?,?)", (uid1, score, dt))
        # Demo Account 2: Mixed portfolio with risky energy stocks
        uid2 = self.q("INSERT INTO users(username,portfolio_no) VALUES(?,?)", ("demo_trader","PF-2002"))
        for ticker, shares in [("TSLA",8),("XOM",15),("JPM",7),("META",4),("BA",5)]:
            self.q("INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)", (uid2, ticker, shares))
        for i, score in enumerate([38,35,40,37,42,39]):
            dt = (datetime.now() - timedelta(days=30*(6-i))).strftime("%Y-%m-%d %H:%M:%S")
            self.q("INSERT INTO analytics(user_id,green_score,recorded_at) VALUES(?,?,?)", (uid2, score, dt))

    def q(self, sql, args=(), fetch=False, one=False):
        c = self.conn.cursor(); c.execute(sql, args); self.conn.commit()
        return c.fetchone() if one else c.fetchall() if fetch else c.lastrowid

    def get_user(self, u): return self.q("SELECT * FROM users WHERE username=?", (u,), one=True)
    def add_user(self, u, pno): return self.q("INSERT INTO users(username,portfolio_no) VALUES(?,?)", (u, pno))
    def get_holdings(self, uid): return self.q("SELECT * FROM holdings WHERE user_id=?", (uid,), fetch=True)
    def add_holding(self, uid, t, s): self.q("INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)", (uid, t, s))
    def delete_holding(self, hid): self.q("DELETE FROM holdings WHERE id=?", (hid,))
    def update_holding(self, hid, s): self.q("UPDATE holdings SET shares=? WHERE id=?", (s, hid))
    def save_score(self, uid, sc): self.q("INSERT INTO analytics(user_id,green_score) VALUES(?,?)", (uid, sc))
    def get_scores(self, uid): return self.q("SELECT green_score,recorded_at FROM analytics WHERE user_id=? ORDER BY recorded_at", (uid,), fetch=True)
    def clear_cache(self): self.q("DELETE FROM esg_cache")

    def get_cache(self, ticker):
        """Returns cached ESG data only if it is less than 7 days old."""
        row = self.q("SELECT * FROM esg_cache WHERE ticker=?", (ticker,), one=True)
        if row and row[6]:
            cached_time = datetime.strptime(str(row[6])[:19], "%Y-%m-%d %H:%M:%S")
            if datetime.now() - cached_time < timedelta(days=CACHE_EXPIRY_DAYS):
                return row
        return None

    def set_cache(self, t, e, s, g, comp, source):
        self.q("REPLACE INTO esg_cache VALUES(?,?,?,?,?,?,?)", (t, e, s, g, comp, source, datetime.now()))

# ── API INTEGRATION LAYER ────────────────────────────
# Fetches ESG data using a 3-tier fallback: Alpha Vantage -> yfinance -> Finnhub
class ESGFetcher:
    @staticmethod
    def from_alpha_vantage(ticker):
        """Primary source: Alpha Vantage Company Overview (free tier: 25 calls/day).
        Derives a proxy ESG score from fundamentals since the dedicated ESG endpoint
        requires a premium key. Uses PERatio, Beta, and DividendYield as signals."""
        url = f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ticker}&apikey={ALPHA_VANTAGE_KEY}"
        r = requests.get(url, timeout=8).json()
        if "Symbol" in r and r.get("PERatioTTM"):
            pe = float(r.get("PERatioTTM", 0) or 0)
            beta = float(r.get("Beta", 1) or 1)
            div_yield = float(r.get("DividendYield", 0) or 0) * 100
            env = max(10, min(90, 60 - beta * 10 + div_yield * 2))
            soc = max(10, min(90, 50 + div_yield * 3))
            gov = max(10, min(90, 70 - abs(pe - 20) * 0.5))
            composite = round((env + soc + gov) / 3, 1)
            return env, soc, gov, composite, "AlphaVantage"
        return None

    @staticmethod
    def from_yfinance(ticker):
        """Secondary source: Yahoo Finance sustainability data via yfinance library."""
        stock = yf.Ticker(ticker)
        sus = stock.sustainability
        if sus is not None and not sus.empty:
            e = float(sus.loc['environmentScore'][0]) if 'environmentScore' in sus.index else 50.0
            s = float(sus.loc['socialScore'][0]) if 'socialScore' in sus.index else 50.0
            g = float(sus.loc['governanceScore'][0]) if 'governanceScore' in sus.index else 50.0
            total = float(sus.loc['totalEsg'][0]) if 'totalEsg' in sus.index else round((e+s+g)/3, 1)
            return e, s, g, total, "YahooFinance"
        return None

    @staticmethod
    def from_finnhub(ticker):
        """Tertiary source: Finnhub ESG endpoint (free tier: 60 calls/min)."""
        url = f"https://finnhub.io/api/v1/stock/esg?symbol={ticker}&token={FINNHUB_KEY}"
        r = requests.get(url, timeout=8).json()
        if r.get("data") and len(r["data"]) > 0:
            latest = r["data"][-1]
            e = float(latest.get("environmentalScore", 50))
            s = float(latest.get("socialScore", 50))
            g = float(latest.get("governanceScore", 50))
            composite = float(latest.get("totalESGScore", round((e+s+g)/3, 1)))
            return e, s, g, composite, "Finnhub"
        return None

    @staticmethod
    def fetch(ticker):
        """Tries all three APIs in order; returns (env, soc, gov, composite, source)."""
        for method in [ESGFetcher.from_alpha_vantage, ESGFetcher.from_yfinance, ESGFetcher.from_finnhub]:
            try:
                result = method(ticker)
                if result: return result
            except Exception:
                continue
        return 50.0, 50.0, 50.0, 50.0, "Default"

# ── LOGIN DIALOG ─────────────────────────────────────
class LoginDialog(QDialog):
    def __init__(self, db):
        super().__init__(); self.db = db; self.user_data = None
        self.setWindowTitle("GreenWallet Login"); self.setFixedSize(400, 250)
        layout = QVBoxLayout()
        title = QLabel("🌿 GreenWallet"); title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size:28px;font-weight:bold;color:#00b894;"); layout.addWidget(title)
        self.uname = QLineEdit(); self.uname.setPlaceholderText("Username"); layout.addWidget(self.uname)
        self.portfolio_no = QLineEdit(); self.portfolio_no.setPlaceholderText("Portfolio Number"); layout.addWidget(self.portfolio_no)
        btn = QPushButton("Login / Register"); btn.clicked.connect(self.login); layout.addWidget(btn)
        self.setLayout(layout)

    def login(self):
        u = self.uname.text().strip()
        if not u: return
        user = self.db.get_user(u)
        if not user: self.db.add_user(u, self.portfolio_no.text().strip()); user = self.db.get_user(u)
        self.user_data = user; self.accept()

# ── MAIN APPLICATION ─────────────────────────────────
class GreenWalletApp(QMainWindow):
    def __init__(self, user, db):
        super().__init__(); self.user = user; self.db = db; self.init_ui()

    def init_ui(self):
        self.setWindowTitle("GreenWallet: ESG Portfolio Impact Scorer"); self.resize(1000, 700)
        self.tabs = QTabWidget(); self.setCentralWidget(self.tabs)
        self.tab1, self.tab2, self.tab3, self.tab4, self.tab5 = [QWidget() for _ in range(5)]
        for t, n in [(self.tab1,"Dashboard"),(self.tab2,"Portfolio"),(self.tab3,"ESG Explorer"),
                      (self.tab4,"Analytics"),(self.tab5,"Settings")]:
            self.tabs.addTab(t, n)
        self.setup_dashboard(); self.setup_portfolio(); self.setup_explorer()
        self.setup_analytics(); self.setup_settings(); self.apply_styles(); self.refresh_all()

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow,QWidget{background:#1a1a2e;color:#fff}
            QTabBar::tab{background:#161625;padding:12px 25px;border-top-left-radius:8px;border-top-right-radius:8px}
            QTabBar::tab:selected{background:#00b894;color:#fff}
            QPushButton{background:#00b894;border-radius:6px;padding:8px;font-weight:bold}
            QPushButton:hover{background:#00d1a0}
            QLineEdit,QDoubleSpinBox{background:#161625;border:1px solid #2d3436;border-radius:5px;padding:6px;color:#fff}
            QTableWidget{background:#161625;gridline-color:#2d3436}
            QHeaderView::section{background:#00b894;color:#fff;padding:5px;border:none}
            QProgressBar{border:1px solid #2d3436;border-radius:5px;text-align:center}
            QProgressBar::chunk{background:#00b894}""")

    def setup_dashboard(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"Welcome, {self.user[1]}!", styleSheet="font-size:22px;font-weight:bold"))
        frame = QFrame(); frame.setStyleSheet("background:#161625;border-radius:15px;padding:30px")
        fl = QHBoxLayout(frame)
        self.score_gauge = QLabel("0"); self.score_gauge.setStyleSheet("font-size:64px;font-weight:900;color:#00b894")
        self.score_gauge.setAlignment(Qt.AlignCenter); fl.addWidget(self.score_gauge)
        info = QVBoxLayout()
        self.score_label = QLabel("--"); self.score_label.setStyleSheet("font-size:22px;color:#00b894"); info.addWidget(self.score_label)
        self.source_lbl = QLabel("Data: --"); self.source_lbl.setStyleSheet("font-size:11px;color:#636e72"); info.addWidget(self.source_lbl)
        r = QPushButton("Refresh"); r.clicked.connect(self.refresh_all); info.addWidget(r)
        s = QPushButton("Save to History"); s.clicked.connect(self.save_score_click); info.addWidget(s)
        fl.addLayout(info); layout.addWidget(frame)
        row = QHBoxLayout()
        self.val_lbl = QLabel("Total: $0"); self.flag_lbl = QLabel("Flagged: 0")
        row.addWidget(self.val_lbl); row.addWidget(self.flag_lbl); layout.addLayout(row)
        self.tab1.setLayout(layout)

    def setup_portfolio(self):
        layout = QVBoxLayout(); row = QHBoxLayout()
        self.p_tick = QLineEdit(); self.p_tick.setPlaceholderText("Ticker (e.g. AAPL)")
        self.p_shares = QDoubleSpinBox(); self.p_shares.setRange(0.1, 1000000)
        add = QPushButton("Add"); add.clicked.connect(self.add_holding)
        row.addWidget(self.p_tick); row.addWidget(self.p_shares); row.addWidget(add); layout.addLayout(row)
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["Ticker","Shares","Price","Value","ESG","Source","Flag"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch); layout.addWidget(self.table)
        br = QHBoxLayout()
        d = QPushButton("Delete"); d.clicked.connect(self.del_holding)
        u = QPushButton("Update Shares"); u.clicked.connect(self.upd_holding)
        br.addWidget(d); br.addWidget(u); layout.addLayout(br); self.tab2.setLayout(layout)

    def setup_explorer(self):
        layout = QVBoxLayout(); sr = QHBoxLayout()
        self.e_search = QLineEdit(); self.e_search.setPlaceholderText("Search Ticker...")
        eb = QPushButton("Fetch ESG"); eb.clicked.connect(self.explore_esg)
        sr.addWidget(self.e_search); sr.addWidget(eb); layout.addLayout(sr)
        panel = QFrame(); panel.setStyleSheet("background:#161625;border-radius:12px;padding:15px")
        pl = QVBoxLayout(panel)
        self.e_name = QLabel("Company"); self.e_name.setStyleSheet("font-size:18px;font-weight:bold"); pl.addWidget(self.e_name)
        self.e_src = QLabel("Source: --"); self.e_src.setStyleSheet("color:#636e72"); pl.addWidget(self.e_src)
        self.e_env, self.e_soc, self.e_gov = QProgressBar(), QProgressBar(), QProgressBar()
        for lbl, bar in [("Environmental",self.e_env),("Social",self.e_soc),("Governance",self.e_gov)]:
            pl.addWidget(QLabel(lbl)); pl.addWidget(bar)
        self.e_comp = QLabel("Composite: 0"); self.e_comp.setStyleSheet("font-size:20px;font-weight:bold;color:#00b894")
        pl.addWidget(self.e_comp); layout.addWidget(panel); self.tab3.setLayout(layout)

    def setup_analytics(self):
        layout = QVBoxLayout()
        self.chart_sel = QComboBox(); self.chart_sel.addItems(["Green Score History","Portfolio Allocation"])
        self.chart_sel.currentIndexChanged.connect(self.update_charts); layout.addWidget(self.chart_sel)
        self.fig, self.ax = plt.subplots(figsize=(5,3), dpi=100)
        self.canvas = FigureCanvas(self.fig); layout.addWidget(self.canvas); self.tab4.setLayout(layout)

    def setup_settings(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"User: {self.user[1]}  |  Portfolio: {self.user[2]}"))
        self.alerts_chk = QCheckBox("Enable Risk Alerts (flag stocks below ESG 30)")
        self.alerts_chk.setChecked(True); layout.addWidget(self.alerts_chk)
        cc = QPushButton("Clear ESG Cache"); cc.clicked.connect(self.clear_cache); layout.addWidget(cc)
        ex = QPushButton("Export Portfolio CSV"); ex.clicked.connect(self.export_csv); layout.addWidget(ex)
        layout.addStretch(); self.tab5.setLayout(layout)

    # ── CORE LOGIC ───────────────────────────────────
    def refresh_all(self):
        holdings = self.db.get_holdings(self.user[0]); self.table.setRowCount(0)
        total_val, weighted, flagged, sources = 0, 0, 0, set()
        for h in holdings:
            tid, shares = h[2], h[3]
            # Fetch real-time price from Yahoo Finance API
            try: price = yf.Ticker(tid).fast_info.last_price
            except: price = 0.0
            cache = self.db.get_cache(tid)
            if cache:
                e, s, g, comp, src = cache[1], cache[2], cache[3], cache[4], cache[5]
            else:
                e, s, g, comp, src = ESGFetcher.fetch(tid)
                self.db.set_cache(tid, e, s, g, comp, src)
            sources.add(src); val = shares * price; total_val += val; weighted += val * comp
            row = self.table.rowCount(); self.table.insertRow(row)
            for c, v in enumerate([tid, str(shares), f"${price:.2f}", f"${val:.2f}", str(comp), src]):
                self.table.setItem(row, c, QTableWidgetItem(v))
            if comp < 30 and self.alerts_chk.isChecked():
                flagged += 1; self.table.setItem(row, 6, QTableWidgetItem("⚠️ RISK"))
                for c in range(7):
                    if self.table.item(row,c): self.table.item(row,c).setBackground(QColor(255,200,200))
            else: self.table.setItem(row, 6, QTableWidgetItem("OK"))
        score = weighted / total_val if total_val > 0 else 0
        self.score_gauge.setText(str(int(score))); self.val_lbl.setText(f"Total: ${total_val:,.2f}")
        self.flag_lbl.setText(f"Flagged: {flagged}")
        self.source_lbl.setText(f"Data via: {', '.join(sources) if sources else '--'}")
        lbl, clr = ("Sustainable","#00b894") if score>=70 else ("Moderate","#fdcb6e") if score>=40 else ("High Risk","#d63031")
        self.score_label.setText(lbl); self.score_label.setStyleSheet(f"font-size:22px;color:{clr}")
        self.update_charts()

    def add_holding(self):
        t = self.p_tick.text().upper().strip()
        if t: self.db.add_holding(self.user[0], t, self.p_shares.value()); self.refresh_all(); self.p_tick.clear()

    def del_holding(self):
        r = self.table.currentRow()
        if r >= 0: self.db.delete_holding(self.db.get_holdings(self.user[0])[r][0]); self.refresh_all()

    def upd_holding(self):
        r = self.table.currentRow()
        if r >= 0: self.db.update_holding(self.db.get_holdings(self.user[0])[r][0], self.p_shares.value()); self.refresh_all()

    def explore_esg(self):
        t = self.e_search.text().upper().strip()
        if not t: return
        e, s, g, comp, src = ESGFetcher.fetch(t); self.e_name.setText(f"Results: {t}")
        self.e_src.setText(f"Source: {src}")
        self.e_env.setValue(int(e)); self.e_soc.setValue(int(s)); self.e_gov.setValue(int(g))
        self.e_comp.setText(f"Composite: {comp}")

    def save_score_click(self):
        self.db.save_score(self.user[0], int(self.score_gauge.text()))
        QMessageBox.information(self, "Saved", "Score saved!"); self.update_charts()

    def clear_cache(self):
        self.db.clear_cache()
        QMessageBox.information(self, "Done", "ESG cache cleared. Fresh API calls on next refresh.")

    def export_csv(self):
        h = self.db.get_holdings(self.user[0])
        pd.DataFrame(h, columns=["ID","UserID","Ticker","Shares","Date"]).to_csv("portfolio_export.csv", index=False)
        QMessageBox.information(self, "Exported", "Saved to portfolio_export.csv")

    def update_charts(self):
        self.ax.clear(); self.fig.patch.set_facecolor('#1a1a2e'); self.ax.set_facecolor('#161625')
        self.ax.tick_params(colors='white')
        if self.chart_sel.currentIndex() == 0:
            data = self.db.get_scores(self.user[0])
            if data:
                self.ax.plot([d[1][:10] for d in data],[d[0] for d in data],marker='o',color='#00b894',lw=2)
                self.ax.set_ylim(0,100)
                self.ax.set_title("Green Score History",color='white')
        else:
            h = self.db.get_holdings(self.user[0])
            if h:
                self.ax.pie([x[3] for x in h],labels=[x[2] for x in h],autopct='%1.1f%%',
                    colors=['#00b894','#00cec9','#0984e3','#6c5ce7','#fdcb6e'],textprops={'color':'w'})
                self.ax.set_title("Portfolio Allocation",color='white')
        self.canvas.draw()

# ── ENTRY POINT ──────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv); db = DatabaseManager()
    login = LoginDialog(db)
    if login.exec_() == QDialog.Accepted:
        w = GreenWalletApp(login.user_data, db); w.show(); sys.exit(app.exec_())
