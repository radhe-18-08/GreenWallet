import sys, sqlite3, requests, yfinance as yf, pandas as pd, numpy as np, matplotlib.pyplot as plt
from datetime import datetime, timedelta
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from PyQt5.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QPushButton, QLineEdit, QTableWidget, QTableWidgetItem, QHeaderView,
    QDoubleSpinBox, QMessageBox, QProgressBar, QComboBox, QDialog, QFrame, QCheckBox)
from PyQt5.QtCore import Qt
from PyQt5.QtGui import QColor

import os
from dotenv import load_dotenv
load_dotenv()

# ── API KEYS (loaded from .env file) ─────────────────
ALPHA_VANTAGE_KEY = os.getenv("ALPHA_VANTAGE_KEY", "YOUR_ALPHA_VANTAGE_KEY")
FINNHUB_KEY = os.getenv("FINNHUB_KEY", "YOUR_FINNHUB_KEY")
CACHE_EXPIRY_DAYS = 7

# ── DATABASE LAYER ───────────────────────────────────
class DatabaseManager:
    def __init__(self, db="greenwallet.db"):
        self.conn = sqlite3.connect(db)
        c = self.conn.cursor()
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
        self.conn.commit()

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
            try: price = yf.Ticker(tid).fast_info.last_price
            except: price = 100.0
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
