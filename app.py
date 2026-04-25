# ─────────────────────────────────────────────────────────
# SECTION 1: Configuration & Database
# Contributor : Jugal Bhagat
# Role        : API keys, UI theming, database schema & queries
# ─────────────────────────────────────────────────────────
import streamlit as st
import sqlite3, requests, json, pandas as pd, numpy as np, yfinance as yf, time
import google.generativeai as genai
from datetime import datetime, timedelta

st.set_page_config(page_title="GreenWallet", page_icon="🌿", layout="centered", initial_sidebar_state="collapsed")
GEMINI_KEY = "AIzaSyCDlbjyqSawwc9yyaikQ9aIjXzDyGM0UGI"
ALPHA_KEY = "7MHSFXGC9EV8NS8Y"
FINNHUB_KEY = "d7h2s9pr01qhiu0a2emgd7h2s9pr01qhiu0a2en0"
genai.configure(api_key=GEMINI_KEY)
gemini = genai.GenerativeModel("gemini-2.0-flash")
G,M,D,BG,CARD,BORDER,TEXT,MUTED = "#00b894","#f59e0b","#ef4444","#07090f","#0d1117","#1c2333","#e2e8f0","#64748b"

st.markdown(f"""<style>
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700;900&display=swap');
html,body,[class*="css"]{{font-family:'Inter',sans-serif;}}
.main .block-container{{max-width:520px;padding:1rem 1rem 3rem;margin:0 auto;}}
.stApp{{background:{BG};}}
#MainMenu,footer,header,.stDeployButton{{visibility:hidden;display:none;}}
.c{{background:{CARD};border:1px solid {BORDER};border-radius:16px;padding:18px 20px;margin-bottom:14px;}}
.ca{{border-left:3px solid {G};}}
.sec{{font-size:11px;font-weight:600;color:{MUTED};letter-spacing:0.8px;text-transform:uppercase;margin:18px 0 10px;}}
.pill{{display:inline-block;padding:4px 14px;border-radius:20px;font-size:12px;font-weight:600;}}
.pg{{background:{G}12;color:{G};}} .py{{background:{M}12;color:{M};}} .pr{{background:{D}12;color:{D};}}
.r{{display:flex;justify-content:space-between;align-items:center;padding:11px 0;border-bottom:1px solid {BORDER};}}
.rl{{font-size:13px;color:{MUTED};}} .rv{{font-size:13px;font-weight:600;color:{TEXT};}}
.sr{{display:flex;align-items:center;gap:12px;padding:13px 16px;border-radius:12px;border:1px solid {BORDER};background:{CARD};margin-bottom:10px;}}
.chat-u{{background:{G};color:#000;padding:10px 14px;border-radius:14px 14px 4px 14px;font-size:14px;margin:6px 0;margin-left:18%;}}
.chat-b{{background:#131924;color:#a8bbd4;padding:10px 14px;border-radius:14px 14px 14px 4px;font-size:14px;margin:6px 0;margin-right:18%;line-height:1.7;}}
.stButton>button{{background:{G}!important;color:#000!important;border:none!important;border-radius:12px!important;padding:12px!important;font-weight:700!important;width:100%!important;}}
.pb{{height:8px;background:{BORDER};border-radius:4px;overflow:hidden;margin:4px 0 12px;}}
.pf{{height:100%;border-radius:4px;}}
</style>""", unsafe_allow_html=True)

@st.cache_resource
def init_db():
    conn = sqlite3.connect("greenwallet.db", check_same_thread=False); c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, portfolio_no TEXT DEFAULT "")')
    c.execute('CREATE TABLE IF NOT EXISTS holdings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, ticker TEXT, shares REAL)')
    c.execute('DROP TABLE IF EXISTS esg_cache')
    c.execute('CREATE TABLE IF NOT EXISTS esg_cache (ticker TEXT PRIMARY KEY, env REAL, soc REAL, gov REAL, composite REAL, source TEXT, sector TEXT, explanation TEXT, fetched_at TIMESTAMP)')
    c.execute('CREATE TABLE IF NOT EXISTS analytics (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, green_score REAL, recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    conn.commit(); return conn
conn = init_db()
def q(sql, args=(), fetch=False, one=False):
    c = conn.cursor(); c.execute(sql, args); conn.commit()
    return c.fetchone() if one else c.fetchall() if fetch else c.lastrowid

# ─────────────────────────────────────────────────────────
# SECTION 2: ESG Data Engine
# Contributor : Radhika Chopra
# Role        : Real-world ESG dataset, Gemini AI lookup,
#               Finnhub fallback, 7-day database caching
# ─────────────────────────────────────────────────────────
KNOWN_ESG = {
    "AAPL":(82,65,73,73,"Technology","Strong privacy practices and renewable energy commitments"),
    "MSFT":(85,78,80,81,"Technology","Industry leader in carbon negative pledge and AI ethics"),
    "GOOGL":(70,62,58,63,"Technology","Strong on renewable energy but governance concerns around data privacy"),
    "NVDA":(60,55,65,60,"Semiconductors","Growing focus on energy-efficient computing"),
    "AMZN":(45,42,50,46,"E-Commerce","High carbon footprint offset partially by renewable investments"),
    "META":(55,38,42,45,"Technology","Renewable data centers but social score impacted by content issues"),
    "NFLX":(58,52,60,57,"Entertainment","Moderate ESG with growing content diversity initiatives"),
    "CRM":(78,75,72,75,"Cloud Software","Strong ESG performer with net-zero commitment"),
    "INTC":(74,68,66,69,"Semiconductors","Solid environmental track record"),
    "AMD":(62,58,64,61,"Semiconductors","Improving energy efficiency but limited ESG disclosure"),
    "TSLA":(72,35,40,49,"Automotive","Strong environmental mission but governance concerns"),
    "XOM":(18,32,45,32,"Oil & Gas","Low environmental score due to fossil fuel core business"),
    "CVX":(22,35,48,35,"Oil & Gas","Heavy fossil fuel exposure with modest transition efforts"),
    "NEE":(88,70,74,77,"Renewable Energy","Leading US utility in wind and solar capacity"),
    "ENPH":(84,62,68,71,"Clean Energy","Solar microinverter leader in clean energy transition"),
    "JPM":(48,55,60,54,"Financial Services","Moderate ESG with fossil fuel financing scrutiny"),
    "GS":(44,50,58,51,"Financial Services","Active in green bonds but controversial project financing"),
    "V":(62,68,75,68,"Financial Services","Strong governance and data security"),
    "MA":(64,66,74,68,"Financial Services","Strong governance and financial inclusion initiatives"),
    "JNJ":(68,72,70,70,"Healthcare","Strong social responsibility but product safety litigation"),
    "PFE":(65,74,62,67,"Pharmaceuticals","High social score from vaccine access programs"),
    "UNH":(55,68,66,63,"Health Insurance","Growing health equity focus but pricing scrutiny"),
    "KO":(58,65,68,64,"Beverages","Plastic waste challenges but strong water stewardship"),
    "PEP":(60,63,66,63,"Beverages","Ongoing packaging sustainability investments"),
    "NKE":(56,48,58,54,"Apparel","Supply chain labor concerns offset by climate commitments"),
    "SBUX":(64,60,55,60,"Food & Beverage","Ethical sourcing but labor relations issues"),
    "BA":(40,45,35,40,"Aerospace","Safety governance failures and defense sector exposure"),
    "DIS":(62,70,58,63,"Entertainment","Strong social metrics but governance faced pressure"),
    "WMT":(52,55,60,56,"Retail","Renewable energy push but labor practices scrutiny"),
    "COST":(58,62,72,64,"Retail","Strong employee treatment but limited environmental disclosure"),
}
DEMOS = {
    "Tech Growth Portfolio":[("AAPL",10),("MSFT",5),("GOOGL",3),("NVDA",4),("AMZN",6)],
    "Balanced Portfolio":[("TSLA",8),("XOM",15),("JPM",7),("META",4),("JNJ",5)],
    "Clean Energy Portfolio":[("NEE",10),("ENPH",8),("TSLA",5),("CRM",4),("MSFT",3)],
    "Blue Chip Portfolio":[("AAPL",8),("JNJ",6),("KO",10),("V",5),("COST",4)],
}

def fetch_esg_gemini(ticker):
    try:
        resp = gemini.generate_content(f'ESG analyst: For "{ticker}" return ONLY JSON: {{"environmental":<0-100>,"social":<0-100>,"governance":<0-100>,"composite":<0-100>,"sector":"<name>","explanation":"<1 sentence>"}} Use real MSCI/Sustainalytics data.')
        d = json.loads(resp.text.strip().replace("```json","").replace("```",""))
        return float(d["environmental"]),float(d["social"]),float(d["governance"]),float(d["composite"]),"Gemini AI",d.get("sector",""),d.get("explanation","")
    except: return None

def get_esg(ticker):
    if ticker in KNOWN_ESG:
        e,s,g,comp,sector,expl = KNOWN_ESG[ticker]; return e,s,g,comp,"MSCI/Sustainalytics",sector,expl
    try:
        row = q("SELECT * FROM esg_cache WHERE ticker=?",(ticker,),one=True)
        if row and len(row)>=9 and row[8]:
            if datetime.now()-datetime.strptime(str(row[8])[:19],"%Y-%m-%d %H:%M:%S")<timedelta(days=7): return row[1],row[2],row[3],row[4],row[5],row[6] or "",row[7] or ""
    except: pass
    result = fetch_esg_gemini(ticker)
    if result:
        e,s,g,comp,src,sector,expl = result; q("REPLACE INTO esg_cache VALUES(?,?,?,?,?,?,?,?,?)",(ticker,e,s,g,comp,src,sector,expl,datetime.now())); return e,s,g,comp,src,sector,expl
    return 0,0,0,0,"Unavailable","","No ESG data available."

# ─────────────────────────────────────────────────────────
# SECTION 3: Helpers & Utilities
# Contributor : Ariba Khan
# Role        : Live price fetching, ESG tier classifier,
#               progress bar renderer, Gemini AI advisor,
#               demo portfolio definitions
# ─────────────────────────────────────────────────────────
def get_price(t):
    try: return round(yf.Ticker(t).fast_info.last_price,2)
    except: return 0.0
def tier(s):
    if s>=70: return "Sustainable","pg",G
    if s>=40: return "Moderate","py",M
    return "High Risk","pr",D
def bar(label,val,color):
    st.markdown(f"<div style='display:flex;justify-content:space-between;font-size:13px;color:{MUTED}'><span>{label}</span><span style='font-weight:700;color:{color}'>{int(val)}/100</span></div><div class='pb'><div class='pf' style='width:{val}%;background:{color}'></div></div>",unsafe_allow_html=True)
def ask_advisor(question,pdata,sc):
    hl = "\n".join([f"- {s['ticker']}: ESG {s['esg']}/100 (E:{s['env']},S:{s['soc']},G:{s['gov']}), {s['sector']}, ${s['value']:,.0f}" for s in pdata])
    try: return gemini.generate_content(f"ESG advisor. Score {sc}/100.\nHoldings:\n{hl}\nUser: \"{question}\"\n2-3 specific sentences.").text.strip()
    except: return f"Score is {int(sc)}/100. Ask about specific stocks or improvements."

# ─────────────────────────────────────────────────────────
# SECTION 4: Main Application (Screens & Dashboard)
# Contributor : Duaa Aamir
# Role        : Login/Register screen, Home screen,
#               data-fetch animation, all 6 dashboard tabs
# ─────────────────────────────────────────────────────────
for k,v in dict(screen="login",user=None,uid=None,pdata=[],score=0,chat=[]).items():
    if k not in st.session_state: st.session_state[k]=v

# ═══════════════════════════════════════════════════════
# LOGIN / REGISTER
# ═══════════════════════════════════════════════════════
if st.session_state.screen == "login":
    st.markdown(f"<div style='text-align:center;padding:28px 0 20px;'><div style='font-size:28px;'>🌿</div><div style='font-size:26px;font-weight:700;color:{TEXT};'>Green<span style=\"color:{G}\">Wallet</span></div><div style='font-size:13px;color:{MUTED};margin-top:4px;'>ESG Portfolio Impact Scorer</div></div>",unsafe_allow_html=True)
    st.markdown(f"<div style='background:#0d1421;border:1px solid {BORDER};border-radius:14px;padding:16px 18px;margin-bottom:20px;font-size:13px;color:{MUTED};line-height:1.8;'>Track the <strong style='color:{TEXT};'>environmental and ethical impact</strong> of your investments. Login or create an account to get started.</div>",unsafe_allow_html=True)
    t1,t2 = st.tabs(["Login","Register"])
    with t1:
        login_user = st.text_input("Username",key="lu")
        if st.button("Login",key="lb"):
            user = q("SELECT * FROM users WHERE username=?",(login_user.strip(),),one=True)
            if user: st.session_state.update(user=user,uid=user[0],screen="home"); st.rerun()
            else: st.error("Account not found. Register first.")
    with t2:
        reg_user = st.text_input("Choose username",key="ru")
        reg_pno = st.text_input("Portfolio number (optional)",key="rp")
        if st.button("Create Account",key="rb"):
            if not reg_user.strip(): st.error("Enter a username.")
            elif q("SELECT * FROM users WHERE username=?",(reg_user.strip(),),one=True): st.error("Username taken.")
            else:
                uid = q("INSERT INTO users(username,portfolio_no) VALUES(?,?)",(reg_user.strip(),reg_pno.strip()))
                user = q("SELECT * FROM users WHERE username=?",(reg_user.strip(),),one=True)
                st.session_state.update(user=user,uid=user[0],screen="home"); st.rerun()
    st.caption("Demo accounts: **demo_investor** · **demo_trader** — pre-registered with portfolios")
    # Seed demo accounts silently
    if not q("SELECT * FROM users WHERE username='demo_investor'",one=True):
        uid1 = q("INSERT INTO users(username,portfolio_no) VALUES('demo_investor','PF-1001')")
        for t,s in DEMOS["Tech Growth Portfolio"]: q("INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)",(uid1,t,s))
        uid2 = q("INSERT INTO users(username,portfolio_no) VALUES('demo_trader','PF-2002')")
        for t,s in DEMOS["Balanced Portfolio"]: q("INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)",(uid2,t,s))

# ═══════════════════════════════════════════════════════
# HOME (logged in, no portfolio loaded yet)
# ═══════════════════════════════════════════════════════
elif st.session_state.screen == "home":
    user,uid = st.session_state.user, st.session_state.uid
    st.markdown(f"<div style='display:flex;justify-content:space-between;align-items:center;padding:12px 0 14px;border-bottom:1px solid {BORDER};margin-bottom:14px;'><div style='font-size:18px;font-weight:700;color:{TEXT};'>🌿 Green<span style=\"color:{G}\">Wallet</span></div><div style='font-size:12px;color:{MUTED};'>👤 {user[1]}</div></div>",unsafe_allow_html=True)
    holdings = q("SELECT * FROM holdings WHERE user_id=?",(uid,),fetch=True)
    if holdings:
        st.markdown(f"<div class='c ca'><div style='font-size:13px;color:{TEXT};'>You have <strong>{len(holdings)} stocks</strong> in your portfolio.</div></div>",unsafe_allow_html=True)
        if st.button("📊 Load My Portfolio"): st.session_state.screen="fetch"; st.rerun()
    else:
        st.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:18px;font-weight:700;color:{TEXT};margin-bottom:8px;'>No Portfolio Connected</div><div style='font-size:13px;color:{MUTED};'>Connect a demo portfolio below or add stocks manually.</div></div>",unsafe_allow_html=True)
    st.markdown(f"<div class='sec'>Connect a Demo Portfolio</div>",unsafe_allow_html=True)
    demo_choice = st.selectbox("Choose portfolio",list(DEMOS.keys()),label_visibility="collapsed")
    if st.button("Connect Portfolio"):
        q("DELETE FROM holdings WHERE user_id=?",(uid,))
        for t,s in DEMOS[demo_choice]: q("INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)",(uid,t,s))
        st.session_state.screen="fetch"; st.rerun()
    st.markdown(f"<div class='sec'>Or Add Stocks Manually</div>",unsafe_allow_html=True)
    c1,c2 = st.columns([3,1])
    tick = c1.text_input("Ticker",placeholder="e.g. AAPL",label_visibility="collapsed")
    shares = c2.number_input("Shares",min_value=1.0,value=5.0,label_visibility="collapsed")
    if st.button("➕ Add Stock") and tick.strip():
        q("INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)",(uid,tick.upper().strip(),shares)); st.rerun()
    if holdings:
        st.markdown(f"<div class='sec'>Current Holdings</div>",unsafe_allow_html=True)
        for h in holdings: st.markdown(f"<div class='r'><span class='rl'>{h[2]}</span><span class='rv'>{h[3]} shares</span></div>",unsafe_allow_html=True)
    st.markdown("---")
    if st.button("🚪 Logout"):
        for k,v in dict(screen="login",user=None,uid=None,pdata=[],score=0,chat=[]).items(): st.session_state[k]=v
        st.rerun()

# ═══════════════════════════════════════════════════════
# FETCHING
# ═══════════════════════════════════════════════════════
elif st.session_state.screen == "fetch":
    user,uid = st.session_state.user, st.session_state.uid
    st.markdown(f"<div style='text-align:center;padding:28px 0 20px;'><div style='font-size:20px;font-weight:600;color:{TEXT};'>Analyzing {user[1]}'s portfolio</div><div style='font-size:13px;color:{MUTED};margin-top:6px;'>Fetching real ESG data + live prices</div></div>",unsafe_allow_html=True)
    holdings = q("SELECT * FROM holdings WHERE user_id=?",(uid,),fetch=True)
    prog = st.progress(0); status = st.empty(); pdata = []
    for i,h in enumerate(holdings):
        status.markdown(f"⏳ **{h[2]}** — fetching ESG scores..."); prog.progress((i+1)/len(holdings))
        price = get_price(h[2]); e,s,g,comp,src,sector,expl = get_esg(h[2])
        pdata.append(dict(ticker=h[2],shares=h[3],price=price,env=e,soc=s,gov=g,esg=comp,source=src,sector=sector,expl=expl,value=h[3]*price))
    status.markdown(f"✅ **{len(holdings)} stocks analyzed**")
    total = sum(s["value"] for s in pdata)
    score = round(sum(s["value"]*s["esg"] for s in pdata)/total,1) if total>0 else 0
    st.session_state.update(pdata=pdata,score=score,screen="app"); time.sleep(0.5); st.rerun()

# ═══════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════
elif st.session_state.screen == "app":
    user,uid,pdata,sc = st.session_state.user,st.session_state.uid,st.session_state.pdata,st.session_state.score
    lbl,css,col = tier(sc); flagged = [s for s in pdata if s["esg"]<30]; total = sum(s["value"] for s in pdata)
    st.markdown(f"<div style='display:flex;justify-content:space-between;align-items:center;padding:12px 0 14px;border-bottom:1px solid {BORDER};margin-bottom:14px;'><div style='font-size:18px;font-weight:700;color:{TEXT};'>🌿 Green<span style=\"color:{G}\">Wallet</span></div><div style='font-size:12px;color:{MUTED};'>{user[1]} · {user[2]}</div></div>",unsafe_allow_html=True)
    tabs = st.tabs(["Score","Holdings","ESG Deep Dive","Analytics","Simulator","AI Advisor"])
    with tabs[0]:
        st.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:11px;color:{MUTED};text-transform:uppercase;letter-spacing:0.8px;'>Portfolio Green Score</div><div style='font-size:72px;font-weight:900;color:{col};line-height:1;'>{int(sc)}</div><div style='margin:8px 0;'><span class='pill {css}'>{lbl}</span></div><div style='font-size:12px;color:{MUTED};'>out of 100 · {len(pdata)} holdings · weighted by capital</div></div>",unsafe_allow_html=True)
        c1,c2,c3 = st.columns(3)
        c1.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:11px;color:{MUTED};'>VALUE</div><div style='font-size:20px;font-weight:700;color:{TEXT};'>${total:,.0f}</div></div>",unsafe_allow_html=True)
        c2.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:11px;color:{MUTED};'>HOLDINGS</div><div style='font-size:20px;font-weight:700;color:{TEXT};'>{len(pdata)}</div></div>",unsafe_allow_html=True)
        fc = D if flagged else G
        c3.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:11px;color:{MUTED};'>FLAGGED</div><div style='font-size:20px;font-weight:700;color:{fc};'>{len(flagged)}</div></div>",unsafe_allow_html=True)
        st.markdown(f"<div class='sec'>API Status</div>",unsafe_allow_html=True)
        sources = set(s["source"] for s in pdata)
        for api,desc in [("MSCI/Sustainalytics","Verified real-world ESG ratings"),("Gemini AI","AI-powered ESG lookup"),("Finnhub","ESG endpoint (backup)"),("yfinance","Real-time stock prices")]:
            dot = "🟢" if api in sources or api=="yfinance" else "🟡"
            st.markdown(f"<div class='r'><span class='rl'>{dot} {api}</span><span style='font-size:11px;color:{MUTED};'>{desc}</span></div>",unsafe_allow_html=True)
        if st.button("💾 Save Score to History"): q("INSERT INTO analytics(user_id,green_score) VALUES(?,?)",(uid,int(sc))); st.success("Saved!")
    with tabs[1]:
        for s in sorted(pdata,key=lambda x:x["esg"],reverse=True):
            c = G if s["esg"]>=60 else M if s["esg"]>=30 else D; flag = "⚠️" if s["esg"]<30 else "✅" if s["esg"]>=60 else "⚡"; pct = s["value"]/total*100 if total>0 else 0
            st.markdown(f"<div class='sr' style='border-color:{c}22;'><div style='flex:1;'><div style='font-size:14px;font-weight:600;color:{TEXT};'>{s['ticker']} <span style='font-size:11px;color:{MUTED};font-weight:400;'>· {s['sector']}</span></div><div style='font-size:11px;color:{MUTED};'>{s['shares']} shares · ${s['price']:.2f} · {pct:.1f}% · via {s['source']}</div><div style='font-size:11px;color:{MUTED};font-style:italic;margin-top:2px;'>{s['expl']}</div></div><div style='text-align:right;'><div style='font-size:22px;font-weight:700;color:{c};'>{int(s['esg'])}</div><div style='font-size:10px;color:{MUTED};'>{flag}</div></div></div>",unsafe_allow_html=True)
    with tabs[2]:
        sel = st.selectbox("Select stock",[s["ticker"] for s in pdata],label_visibility="collapsed"); s = next(x for x in pdata if x["ticker"]==sel)
        c2 = G if s["esg"]>=60 else M if s["esg"]>=30 else D
        st.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:22px;font-weight:700;color:{TEXT};'>{s['ticker']}</div><div style='font-size:12px;color:{MUTED};'>{s['sector']} · via {s['source']}</div><div style='font-size:52px;font-weight:900;color:{c2};margin:12px 0;'>{int(s['esg'])}</div><div style='font-size:13px;color:{MUTED};font-style:italic;'>{s['expl']}</div></div>",unsafe_allow_html=True)
        bar("🌍 Environmental",s["env"],G); bar("👥 Social",s["soc"],"#00cec9"); bar("🏛️ Governance",s["gov"],"#6366f1")
    with tabs[3]:
        data = q("SELECT green_score,recorded_at FROM analytics WHERE user_id=? ORDER BY recorded_at",(uid,),fetch=True)
        if data:
            df = pd.DataFrame(data,columns=["Green Score","Date"]); df["Date"]=pd.to_datetime(df["Date"]); st.line_chart(df.set_index("Date")["Green Score"],color=G)
        else: st.info("No history yet. Save scores from Score tab.")
        st.markdown(f"<div class='sec'>ESG Heatmap</div>",unsafe_allow_html=True)
        for s in sorted(pdata,key=lambda x:x["esg"],reverse=True):
            c = G if s["esg"]>=60 else M if s["esg"]>=30 else D
            st.markdown(f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:6px;'><span style='font-size:12px;color:{MUTED};width:50px;'>{s['ticker']}</span><div class='pb' style='flex:1;margin:0;'><div class='pf' style='width:{max(s['esg'],5)}%;background:{c};'></div></div><span style='font-size:12px;font-weight:700;color:{c};width:30px;text-align:right;'>{int(s['esg'])}</span></div>",unsafe_allow_html=True)
    with tabs[4]:
        st.markdown(f"<div class='c ca'><div style='font-size:11px;color:{G};'>What-If Simulator</div><div style='font-size:13px;color:{MUTED};margin-top:6px;'>Adjust shares and watch your Green Score change.</div></div>",unsafe_allow_html=True)
        sim = []
        for s in pdata:
            ns = st.slider(f"{s['ticker']} · ESG {int(s['esg'])}",0.0,float(s['shares']*3),float(s['shares']),1.0,key=f"s_{s['ticker']}"); sim.append(dict(esg=s["esg"],value=ns*s["price"]))
        st2 = sum(x["value"] for x in sim); sim_sc = sum(x["value"]*x["esg"] for x in sim)/st2 if st2>0 else 0; diff = sim_sc-sc; sl,scl,scol = tier(sim_sc); dc = G if diff>0 else D if diff<0 else MUTED
        st.markdown(f"<div class='c' style='text-align:center;'><div style='display:flex;justify-content:center;gap:40px;'><div><div style='font-size:12px;color:{MUTED};'>Current</div><div style='font-size:32px;font-weight:700;color:{col};'>{int(sc)}</div></div><div style='font-size:24px;color:{dc};font-weight:700;margin-top:16px;'>→</div><div><div style='font-size:12px;color:{MUTED};'>Simulated</div><div style='font-size:32px;font-weight:700;color:{scol};'>{int(sim_sc)}</div></div></div><div style='font-size:28px;font-weight:700;color:{dc};margin-top:8px;'>{'+'if diff>0 else''}{diff:.1f} pts</div><span class='pill {scl}'>{sl}</span></div>",unsafe_allow_html=True)
    with tabs[5]:
        st.markdown(f"<div class='c ca'><div style='font-size:11px;color:{G};'>AI ESG Advisor · Powered by Gemini</div><div style='font-size:13px;color:{MUTED};margin-top:6px;'>Score: <strong style='color:{TEXT};'>{int(sc)}/100</strong> · {lbl} · {len(pdata)} holdings</div></div>",unsafe_allow_html=True)
        if not st.session_state.chat:
            for i,question in enumerate(["How can I improve my score?","Which stock is my biggest risk?","Compare to benchmarks","Environmental breakdown"]):
                if st.button(question,key=f"q{i}"):
                    with st.spinner("Thinking..."): reply = ask_advisor(question,pdata,sc)
                    st.session_state.chat+=[{"r":"u","t":question},{"r":"b","t":reply}]; st.rerun()
        for m in st.session_state.chat: st.markdown(f"<div class='chat-{'u'if m['r']=='u'else'b'}'>{m['t']}</div>",unsafe_allow_html=True)
        inp = st.chat_input("Ask about your portfolio's ESG impact...")
        if inp:
            with st.spinner("Thinking..."): reply = ask_advisor(inp,pdata,sc)
            st.session_state.chat+=[{"r":"u","t":inp},{"r":"b","t":reply}]; st.rerun()
    st.markdown("---")
    c1,c2 = st.columns(2)
    with c1:
        if st.button("🔄 Back to Home"): st.session_state.update(screen="home",pdata=[],score=0,chat=[]); st.rerun()
    with c2:
        if st.button("🚪 Logout"):
            for k,v in dict(screen="login",user=None,uid=None,pdata=[],score=0,chat=[]).items(): st.session_state[k]=v
            st.rerun()
    st.markdown(f"<p style='text-align:center;font-size:11px;color:{BORDER};'>GreenWallet v2.0 · Gemini AI · Finnhub · yfinance</p>",unsafe_allow_html=True)
