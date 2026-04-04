import sys
import sqlite3
import requests
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from datetime import datetime, timedelta
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, 
    QTabWidget, QLabel, QPushButton, QLineEdit, QTableWidget, 
    QTableWidgetItem, QHeaderView, QDoubleSpinBox, QSpinBox, 
    QMessageBox, QProgressBar, QComboBox, QCheckBox, QDialog,
    QStatusBar, QFrame
)
from PyQt5.QtCore import Qt, QThread, pyqtSignal, QSize
from PyQt5.QtGui import QFont, QColor, QIcon, QPalette

# ── CONSTANTS & API KEYS ─────────────────────────────
ALPHA_VANTAGE_KEY = "YOUR_ALPHA_VANTAGE_KEY"
FINNHUB_KEY = "YOUR_FINNHUB_KEY"

# ── DATABASE LAYER ───────────────────────────────────
class DatabaseManager:
    def __init__(self, db_name="greenwallet.db"):
        self.conn = sqlite3.connect(db_name)
        self.create_tables()

    def create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute('''CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            target_esg_score REAL DEFAULT 50.0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS holdings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            ticker TEXT NOT NULL,
            shares REAL NOT NULL,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS esg_cache (
            ticker TEXT PRIMARY KEY,
            environmental_score REAL,
            social_score REAL,
            governance_score REAL,
            composite_score REAL,
            fetched_at TIMESTAMP
        )''')
        cursor.execute('''CREATE TABLE IF NOT EXISTS analytics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            green_score REAL,
            recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY(user_id) REFERENCES users(id)
        )''')
        self.conn.commit()

    def get_user(self, username):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM users WHERE username = ?", (username,))
        return cursor.fetchone()

    def register_user(self, username, target_score):
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO users (username, target_esg_score) VALUES (?, ?)", (username, target_score))
        self.conn.commit()
        return cursor.lastrowid

    def get_holdings(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM holdings WHERE user_id = ?", (user_id,))
        return cursor.fetchall()

    def add_holding(self, user_id, ticker, shares):
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO holdings (user_id, ticker, shares) VALUES (?, ?, ?)", (user_id, ticker, shares))
        self.conn.commit()

    def delete_holding(self, holding_id):
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM holdings WHERE id = ?", (holding_id,))
        self.conn.commit()

    def update_holding(self, holding_id, shares):
        cursor = self.conn.cursor()
        cursor.execute("UPDATE holdings SET shares = ? WHERE id = ?", (shares, holding_id))
        self.conn.commit()

    def get_esg_cache(self, ticker):
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM esg_cache WHERE ticker = ?", (ticker,))
        return cursor.fetchone()

    def update_esg_cache(self, ticker, e, s, g, composite):
        cursor = self.conn.cursor()
        cursor.execute("REPLACE INTO esg_cache VALUES (?, ?, ?, ?, ?, ?)", 
                       (ticker, e, s, g, composite, datetime.now()))
        self.conn.commit()

    def save_analytics(self, user_id, score):
        cursor = self.conn.cursor()
        cursor.execute("INSERT INTO analytics (user_id, green_score) VALUES (?, ?)", (user_id, score))
        self.conn.commit()

    def get_analytics(self, user_id):
        cursor = self.conn.cursor()
        cursor.execute("SELECT green_score, recorded_at FROM analytics WHERE user_id = ? ORDER BY recorded_at", (user_id,))
        return cursor.fetchall()

# ── API & DATA FETCHING LAYER ────────────────────────
class ESGFetcher:
    @staticmethod
    def fetch_data(ticker_symbol):
        # 1. Try Alpha Vantage
        try:
            url = f"https://www.alphavantage.co/query?function=ESG_RATING&symbol={ticker_symbol}&apikey={ALPHA_VANTAGE_KEY}"
            # r = requests.get(url) # Simulated for demo
            # if r.status_code == 200: ...
        except:
            pass

        # 2. Fallback to yfinance
        try:
            stock = yf.Ticker(ticker_symbol)
            sus = stock.sustainability
            if sus is not None:
                e = sus.loc['environmentalScore'][0]
                s = sus.loc['socialScore'][0]
                g = sus.loc['governanceScore'][0]
                total = sus.loc['totalEsg'][0]
                return e, s, g, total
        except:
            pass

        # 3. Default neutral
        return 50.0, 50.0, 50.0, 50.0

# ── UI: LOGIN DIALOG ─────────────────────────────────
class LoginDialog(QDialog):
    def __init__(self, db_manager):
        super().__init__()
        self.db = db_manager
        self.user_data = None
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("GreenWallet Login")
        self.setFixedSize(400, 300)
        layout = QVBoxLayout()
        
        title = QLabel("🌿 GreenWallet")
        title.setAlignment(Qt.AlignCenter)
        title.setStyleSheet("font-size: 28px; font-weight: bold; color: #00b894; margin-bottom: 20px;")
        layout.addWidget(title)

        self.username_input = QLineEdit()
        self.username_input.setPlaceholderText("Username")
        layout.addWidget(self.username_input)

        self.target_input = QDoubleSpinBox()
        self.target_input.setRange(0, 100)
        self.target_input.setValue(70)
        self.target_input.setPrefix("Target ESG: ")
        layout.addWidget(self.target_input)

        login_btn = QPushButton("Login / Register")
        login_btn.clicked.connect(self.handle_login)
        layout.addWidget(login_btn)

        self.setLayout(layout)

    def handle_login(self):
        username = self.username_input.text().strip()
        if not username:
            return
        
        user = self.db.get_user(username)
        if not user:
            user_id = self.db.register_user(username, self.target_input.value())
            user = self.db.get_user(username)
            
            # Demo data for "demo" user
            if username.lower() == "demo":
                self.db.add_holding(user[0], "AAPL", 10)
                self.db.add_holding(user[0], "MSFT", 5)
                self.db.add_holding(user[0], "TSLA", 8)
                self.db.add_holding(user[0], "XOM", 15)
                # Fake analytics
                for i in range(6):
                    date = (datetime.now() - timedelta(days=30*(6-i))).strftime("%Y-%m-%d %H:%M:%S")
                    cursor = self.db.conn.cursor()
                    cursor.execute("INSERT INTO analytics (user_id, green_score, recorded_at) VALUES (?, ?, ?)", 
                                   (user[0], 50 + i*3, date))
                self.db.conn.commit()

        self.user_data = user
        self.accept()

# ── UI: MAIN WINDOW & TABS ───────────────────────────
class GreenWalletApp(QMainWindow):
    def __init__(self, user_data, db_manager):
        super().__init__()
        self.user = user_data
        self.db = db_manager
        self.init_ui()

    def init_ui(self):
        self.setWindowTitle("GreenWallet: ESG Portfolio Impact Scorer")
        self.resize(1100, 800)
        
        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)

        self.tab1 = QWidget()
        self.tab2 = QWidget()
        self.tab3 = QWidget()
        self.tab4 = QWidget()
        self.tab5 = QWidget()

        self.tabs.addTab(self.tab1, "Dashboard")
        self.tabs.addTab(self.tab2, "Portfolio")
        self.tabs.addTab(self.tab3, "ESG Explorer")
        self.tabs.addTab(self.tab4, "Analytics")
        self.tabs.addTab(self.tab5, "Settings")

        self.setup_dashboard()
        self.setup_portfolio()
        self.setup_explorer()
        self.setup_analytics()
        self.setup_settings()

        self.apply_styles()
        self.refresh_all()

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow, QDialog, QWidget { background-color: #1a1a2e; color: #ffffff; }
            QTabWidget::pane { border: 1px solid #2d3436; }
            QTabBar::tab { background: #161625; padding: 15px 30px; border-top-left-radius: 10px; border-top-right-radius: 10px; margin-right: 2px; }
            QTabBar::tab:selected { background: #00b894; color: white; }
            QPushButton { background-color: #00b894; border-radius: 8px; padding: 10px; font-weight: bold; min-width: 100px; }
            QPushButton:hover { background-color: #00d1a0; }
            QLineEdit, QDoubleSpinBox, QSpinBox { background-color: #161625; border: 1px solid #2d3436; border-radius: 5px; padding: 8px; color: white; }
            QTableWidget { background-color: #161625; gridline-color: #2d3436; alternate-background-color: #1a1a2e; }
            QHeaderView::section { background-color: #00b894; color: white; padding: 5px; border: none; }
            QProgressBar { border: 1px solid #2d3436; border-radius: 5px; text-align: center; }
            QProgressBar::chunk { background-color: #00b894; }
        """)

    # --- TAB 1: DASHBOARD ---
    def setup_dashboard(self):
        layout = QVBoxLayout()
        
        welcome = QLabel(f"Welcome back, {self.user[1]}!")
        welcome.setStyleSheet("font-size: 24px; font-weight: bold; margin-bottom: 10px;")
        layout.addWidget(welcome)

        score_frame = QFrame()
        score_frame.setStyleSheet("background-color: #161625; border-radius: 20px; padding: 40px;")
        score_layout = QHBoxLayout(score_frame)
        
        self.score_gauge = QLabel("0")
        self.score_gauge.setStyleSheet("font-size: 72px; font-weight: 900; color: #00b894;")
        self.score_gauge.setAlignment(Qt.AlignCenter)
        score_layout.addWidget(self.score_gauge)

        info_layout = QVBoxLayout()
        self.score_label = QLabel("Sustainable")
        self.score_label.setStyleSheet("font-size: 24px; font-weight: bold; color: #00b894;")
        info_layout.addWidget(self.score_label)
        info_layout.addWidget(QLabel("Portfolio Green Score"))
        
        btn_layout = QHBoxLayout()
        refresh_btn = QPushButton("Refresh Score")
        refresh_btn.clicked.connect(self.refresh_all)
        save_btn = QPushButton("Save to History")
        save_btn.clicked.connect(self.save_score)
        btn_layout.addWidget(refresh_btn)
        btn_layout.addWidget(save_btn)
        info_layout.addLayout(btn_layout)
        
        score_layout.addLayout(info_layout)
        layout.addWidget(score_frame)

        stats_layout = QHBoxLayout()
        self.total_val_lbl = QLabel("Total Value: $0.00")
        self.flagged_lbl = QLabel("Flagged Stocks: 0")
        stats_layout.addWidget(self.total_val_lbl)
        stats_layout.addWidget(self.flagged_lbl)
        layout.addLayout(stats_layout)

        self.tab1.setLayout(layout)

    # --- TAB 2: PORTFOLIO ---
    def setup_portfolio(self):
        layout = QVBoxLayout()
        
        add_layout = QHBoxLayout()
        self.p_ticker = QLineEdit()
        self.p_ticker.setPlaceholderText("Ticker (e.g. AAPL)")
        self.p_shares = QDoubleSpinBox()
        self.p_shares.setRange(0.1, 1000000)
        add_btn = QPushButton("Add Holding")
        add_btn.clicked.connect(self.add_holding)
        add_layout.addWidget(self.p_ticker)
        add_layout.addWidget(self.p_shares)
        add_layout.addWidget(add_btn)
        layout.addLayout(add_layout)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(["Ticker", "Shares", "Price", "Market Value", "ESG Score", "Flag"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        layout.addWidget(self.table)

        btn_row = QHBoxLayout()
        del_btn = QPushButton("Delete Selected")
        del_btn.clicked.connect(self.delete_holding)
        upd_btn = QPushButton("Update Shares")
        upd_btn.clicked.connect(self.update_holding)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(upd_btn)
        layout.addLayout(btn_row)

        self.tab2.setLayout(layout)

    # --- TAB 3: EXPLORER ---
    def setup_explorer(self):
        layout = QVBoxLayout()
        search_row = QHBoxLayout()
        self.e_search = QLineEdit()
        self.e_search.setPlaceholderText("Search Ticker...")
        e_btn = QPushButton("Fetch ESG Data")
        e_btn.clicked.connect(self.explore_esg)
        search_row.addWidget(self.e_search)
        search_row.addWidget(e_btn)
        layout.addLayout(search_row)

        self.e_panel = QFrame()
        self.e_panel.setStyleSheet("background-color: #161625; border-radius: 15px; padding: 20px;")
        e_layout = QVBoxLayout(self.e_panel)
        self.e_name = QLabel("Company Name")
        self.e_name.setStyleSheet("font-size: 20px; font-weight: bold;")
        e_layout.addWidget(self.e_name)

        self.e_prog_env = QProgressBar()
        self.e_prog_soc = QProgressBar()
        self.e_prog_gov = QProgressBar()
        e_layout.addWidget(QLabel("Environmental Score"))
        e_layout.addWidget(self.e_prog_env)
        e_layout.addWidget(QLabel("Social Score"))
        e_layout.addWidget(self.e_prog_soc)
        e_layout.addWidget(QLabel("Governance Score"))
        e_layout.addWidget(self.e_prog_gov)

        self.e_composite = QLabel("Composite: 0")
        self.e_composite.setStyleSheet("font-size: 24px; font-weight: bold; color: #00b894;")
        e_layout.addWidget(self.e_composite)

        layout.addWidget(self.e_panel)
        self.tab3.setLayout(layout)

    # --- TAB 4: ANALYTICS ---
    def setup_analytics(self):
        layout = QVBoxLayout()
        self.chart_selector = QComboBox()
        self.chart_selector.addItems(["Historical Green Score", "Portfolio Allocation"])
        self.chart_selector.currentIndexChanged.connect(self.update_charts)
        layout.addWidget(self.chart_selector)

        self.figure, self.ax = plt.subplots(figsize=(5, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)

        export_btn = QPushButton("Export Chart as PNG")
        export_btn.clicked.connect(lambda: self.figure.savefig("chart_export.png"))
        layout.addWidget(export_btn)

        self.tab4.setLayout(layout)

    # --- TAB 5: SETTINGS ---
    def setup_settings(self):
        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"Username: {self.user[1]}"))
        
        self.s_target = QDoubleSpinBox()
        self.s_target.setRange(0, 100)
        self.s_target.setValue(self.user[2])
        self.s_target.setPrefix("Target ESG Score: ")
        layout.addWidget(self.s_target)

        self.s_alerts = QCheckBox("Enable Risk Alerts")
        self.s_alerts.setChecked(True)
        layout.addWidget(self.s_alerts)

        clear_btn = QPushButton("Clear ESG Cache")
        clear_btn.clicked.connect(self.clear_cache)
        layout.addWidget(clear_btn)

        csv_btn = QPushButton("Export Portfolio as CSV")
        csv_btn.clicked.connect(self.export_csv)
        layout.addWidget(csv_btn)

        logout_btn = QPushButton("Logout")
        logout_btn.clicked.connect(self.close)
        layout.addWidget(logout_btn)

        self.tab5.setLayout(layout)

    # --- LOGIC ---
    def refresh_all(self):
        holdings = self.db.get_holdings(self.user[0])
        self.table.setRowCount(0)
        total_value = 0
        weighted_score_sum = 0
        flagged_count = 0

        for h in holdings:
            ticker = h[2]
            shares = h[3]
            
            # Fetch Price & ESG
            stock = yf.Ticker(ticker)
            price = stock.fast_info.last_price if hasattr(stock, 'fast_info') else 150.0
            
            cache = self.db.get_esg_cache(ticker)
            if not cache:
                e, s, g, comp = ESGFetcher.fetch_data(ticker)
                self.db.update_esg_cache(ticker, e, s, g, comp)
                cache = (ticker, e, s, g, comp)
            
            esg_score = cache[4]
            mkt_val = shares * price
            total_value += mkt_val
            weighted_score_sum += (mkt_val * esg_score)

            row = self.table.rowCount()
            self.table.insertRow(row)
            self.table.setItem(row, 0, QTableWidgetItem(ticker))
            self.table.setItem(row, 1, QTableWidgetItem(str(shares)))
            self.table.setItem(row, 2, QTableWidgetItem(f"${price:.2f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"${mkt_val:.2f}"))
            self.table.setItem(row, 4, QTableWidgetItem(str(esg_score)))
            
            if esg_score < 30:
                flagged_count += 1
                self.table.setItem(row, 5, QTableWidgetItem("⚠️ HIGH RISK"))
                for col in range(6):
                    self.table.item(row, col).setBackground(QColor(255, 200, 200))
                    self.table.item(row, col).setForeground(QColor(0, 0, 0))
            else:
                self.table.setItem(row, 5, QTableWidgetItem("OK"))

        final_score = weighted_score_sum / total_value if total_value > 0 else 0
        self.score_gauge.setText(str(int(final_score)))
        self.total_val_lbl.setText(f"Total Value: ${total_value:,.2f}")
        self.flagged_lbl.setText(f"Flagged Stocks: {flagged_count}")
        
        if final_score >= 70:
            self.score_label.setText("Sustainable")
            self.score_label.setStyleSheet("color: #00b894; font-size: 24px;")
        elif final_score >= 40:
            self.score_label.setText("Moderate")
            self.score_label.setStyleSheet("color: #fdcb6e; font-size: 24px;")
        else:
            self.score_label.setText("High Risk")
            self.score_label.setStyleSheet("color: #d63031; font-size: 24px;")

        self.update_charts()

    def add_holding(self):
        ticker = self.p_ticker.text().upper().strip()
        shares = self.p_shares.value()
        if ticker:
            self.db.add_holding(self.user[0], ticker, shares)
            self.refresh_all()
            self.p_ticker.clear()

    def delete_holding(self):
        row = self.table.currentRow()
        if row >= 0:
            ticker = self.table.item(row, 0).text()
            holdings = self.db.get_holdings(self.user[0])
            h_id = holdings[row][0]
            self.db.delete_holding(h_id)
            self.refresh_all()

    def update_holding(self):
        row = self.table.currentRow()
        if row >= 0:
            holdings = self.db.get_holdings(self.user[0])
            h_id = holdings[row][0]
            self.db.update_holding(h_id, self.p_shares.value())
            self.refresh_all()

    def explore_esg(self):
        ticker = self.e_search.text().upper().strip()
        if ticker:
            e, s, g, comp = ESGFetcher.fetch_data(ticker)
            self.e_name.setText(f"Results for {ticker}")
            self.e_prog_env.setValue(int(e))
            self.e_prog_soc.setValue(int(s))
            self.e_prog_gov.setValue(int(g))
            self.e_composite.setText(f"Composite Score: {comp}")

    def save_score(self):
        score = int(self.score_gauge.text())
        self.db.save_analytics(self.user[0], score)
        QMessageBox.information(self, "Success", "Score saved to history!")
        self.update_charts()

    def update_charts(self):
        self.ax.clear()
        self.figure.patch.set_facecolor('#1a1a2e')
        self.ax.set_facecolor('#161625')
        self.ax.tick_params(colors='white')
        self.ax.xaxis.label.set_color('white')
        self.ax.yaxis.label.set_color('white')

        if self.chart_selector.currentIndex() == 0:
            data = self.db.get_analytics(self.user[0])
            if data:
                scores = [d[0] for d in data]
                dates = [d[1][:10] for d in data]
                self.ax.plot(dates, scores, marker='o', color='#00b894', linewidth=3)
                self.ax.axhline(y=self.user[2], color='#d63031', linestyle='--', label="Target")
                self.ax.set_title("Historical Green Score", color='white')
                self.ax.set_ylim(0, 100)
        else:
            holdings = self.db.get_holdings(self.user[0])
            labels = [h[2] for h in holdings]
            sizes = [h[3] for h in holdings] # Simplified to shares for demo
            if sizes:
                self.ax.pie(sizes, labels=labels, autopct='%1.1f%%', colors=['#00b894', '#00cec9', '#0984e3', '#6c5ce7'], textprops={'color':"w"})
                self.ax.set_title("Portfolio Allocation", color='white')

        self.canvas.draw()

    def clear_cache(self):
        self.db.conn.cursor().execute("DELETE FROM esg_cache")
        self.db.conn.commit()
        QMessageBox.information(self, "Cache Cleared", "ESG cache has been emptied.")

    def export_csv(self):
        holdings = self.db.get_holdings(self.user[0])
        df = pd.DataFrame(holdings, columns=["ID", "UserID", "Ticker", "Shares", "DateAdded"])
        df.to_csv("portfolio_export.csv", index=False)
        QMessageBox.information(self, "Exported", "Portfolio exported to portfolio_export.csv")

# ── ENTRY POINT ──────────────────────────────────────
if __name__ == "__main__":
    app = QApplication(sys.argv)
    db = DatabaseManager()
    
    login = LoginDialog(db)
    if login.exec_() == QDialog.Accepted:
        window = GreenWalletApp(login.user_data, db)
        window.show()
        sys.exit(app.exec_())
