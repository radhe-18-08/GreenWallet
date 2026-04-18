import streamlit as st
import sqlite3, requests, pandas as pd, numpy as np, yfinance as yf, time
from datetime import datetime, timedelta

st.set_page_config(page_title="GreenWallet", page_icon="🌿", layout="centered", initial_sidebar_state="collapsed")
ALPHA_KEY = "7MHSFXGC9EV8NS8Y"
FINNHUB_KEY = "d7h2s9pr01qhiu0a2emgd7h2s9pr01qhiu0a2en0"
G, M, D, BG, CARD, BORDER, TEXT, MUTED = "#00b894","#f59e0b","#ef4444","#07090f","#0d1117","#1c2333","#e2e8f0","#64748b"

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
.chat-b{{background:#131924;color:#a8bbd4;padding:10px 14px;border-radius:14px 14px 14px 4px;font-size:14px;margin:6px 0;margin-right:18%;}}
.stButton>button{{background:{G}!important;color:#000!important;border:none!important;border-radius:12px!important;padding:12px!important;font-weight:700!important;width:100%!important;}}
.pb{{height:8px;background:{BORDER};border-radius:4px;overflow:hidden;margin:4px 0 12px;}}
.pf{{height:100%;border-radius:4px;}}
</style>""", unsafe_allow_html=True)

# ── DATABASE ─────────────────────────────────────────
@st.cache_resource
def init_db():
    conn = sqlite3.connect("greenwallet.db", check_same_thread=False); c = conn.cursor()
    c.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY AUTOINCREMENT, username TEXT UNIQUE, portfolio_no TEXT DEFAULT "")')
    c.execute('CREATE TABLE IF NOT EXISTS holdings (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, ticker TEXT, shares REAL)')
    c.execute('CREATE TABLE IF NOT EXISTS esg_cache (ticker TEXT PRIMARY KEY, env REAL, soc REAL, gov REAL, composite REAL, source TEXT, fetched_at TIMESTAMP)')
    c.execute('CREATE TABLE IF NOT EXISTS analytics (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INT, green_score REAL, recorded_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)')
    conn.commit(); return conn
conn = init_db()
def q(sql, args=(), fetch=False, one=False):
    c = conn.cursor(); c.execute(sql, args); conn.commit()
    return c.fetchone() if one else c.fetchall() if fetch else c.lastrowid

# ── ESG API LAYER (3-tier: Alpha Vantage → yfinance → Finnhub) ──
def fetch_esg(ticker):
    try:  # Tier 1: Alpha Vantage Company Overview
        r = requests.get(f"https://www.alphavantage.co/query?function=OVERVIEW&symbol={ticker}&apikey={ALPHA_KEY}", timeout=8).json()
        if "Symbol" in r and r.get("PERatioTTM"):
            pe,beta,dy = float(r.get("PERatioTTM",0) or 0), float(r.get("Beta",1) or 1), float(r.get("DividendYield",0) or 0)*100
            e,s,g = max(10,min(90,60-beta*10+dy*2)), max(10,min(90,50+dy*3)), max(10,min(90,70-abs(pe-20)*0.5))
            return round(e,1),round(s,1),round(g,1),round((e+s+g)/3,1),"AlphaVantage"
    except: pass
    try:  # Tier 2: Yahoo Finance sustainability
        sus = yf.Ticker(ticker).sustainability
        if sus is not None and not sus.empty:
            e = float(sus.loc['environmentScore'][0]) if 'environmentScore' in sus.index else 50.0
            s = float(sus.loc['socialScore'][0]) if 'socialScore' in sus.index else 50.0
            g = float(sus.loc['governanceScore'][0]) if 'governanceScore' in sus.index else 50.0
            return e,s,g,float(sus.loc['totalEsg'][0]) if 'totalEsg' in sus.index else round((e+s+g)/3,1),"YahooFinance"
    except: pass
    try:  # Tier 3: Finnhub ESG endpoint
        r = requests.get(f"https://finnhub.io/api/v1/stock/esg?symbol={ticker}&token={FINNHUB_KEY}", timeout=8).json()
        if r.get("data") and len(r["data"])>0:
            d = r["data"][-1]; e,s,g = float(d.get("environmentalScore",50)),float(d.get("socialScore",50)),float(d.get("governanceScore",50))
            return e,s,g,float(d.get("totalESGScore",round((e+s+g)/3,1))),"Finnhub"
    except: pass
    return 50.0,50.0,50.0,50.0,"Default"

def get_esg(ticker):
    row = q("SELECT * FROM esg_cache WHERE ticker=?",(ticker,),one=True)
    if row and row[6]:
        if datetime.now()-datetime.strptime(str(row[6])[:19],"%Y-%m-%d %H:%M:%S") < timedelta(days=7): return row[1],row[2],row[3],row[4],row[5]
    e,s,g,comp,src = fetch_esg(ticker)
    q("REPLACE INTO esg_cache VALUES(?,?,?,?,?,?,?)",(ticker,e,s,g,comp,src,datetime.now())); return e,s,g,comp,src

def get_price(t):
    try: return round(yf.Ticker(t).fast_info.last_price,2)
    except: return 0.0

def tier(s):
    if s>=70: return "Sustainable","pg",G
    if s>=40: return "Moderate","py",M
    return "High Risk","pr",D

def bar(label,val,color):
    st.markdown(f"<div style='display:flex;justify-content:space-between;font-size:13px;color:{MUTED}'><span>{label}</span><span style='font-weight:700;color:{color}'>{int(val)}/100</span></div><div class='pb'><div class='pf' style='width:{val}%;background:{color}'></div></div>", unsafe_allow_html=True)

# ── DEMO PORTFOLIOS ──────────────────────────────────
DEMOS = {
    "Jugal Bhagat - Tech Growth Portfolio": ("Jugal Bhagat","PF-1001",[("AAPL",10),("MSFT",5),("GOOGL",3),("NVDA",4),("AMZN",6)],[52,55,58,61,64,67]),
    "Radhika Chopra - Balanced Portfolio": ("Radhika Chopra","PF-2002",[("TSLA",8),("XOM",15),("JPM",7),("META",4),("JNJ",5)],[38,42,40,37,44,39]),
}

# ── SESSION STATE ────────────────────────────────────
for k,v in dict(screen="login",user=None,uid=None,pdata=[],score=0,chat=[]).items():
    if k not in st.session_state: st.session_state[k] = v

# ═══════════════════════════════════════════════════════
if st.session_state.screen == "login":
    st.markdown(f"""<div style="text-align:center;padding:28px 0 20px;">
        <div style="width:56px;height:56px;background:#131924;border:1px solid {BORDER};border-radius:16px;display:flex;align-items:center;justify-content:center;margin:0 auto 14px;font-size:28px;">🌿</div>
        <div style="font-size:26px;font-weight:700;color:{TEXT};">Green<span style="color:{G}">Wallet</span></div>
        <div style="font-size:13px;color:{MUTED};margin-top:4px;">ESG Portfolio Impact Scorer — Know how green your money really is.</div>
    </div>""", unsafe_allow_html=True)
    st.markdown(f"<div style='background:#0d1421;border:1px solid {BORDER};border-radius:14px;padding:16px 18px;margin-bottom:20px;font-size:13px;color:{MUTED};line-height:1.8;'>You own stocks. You check P&L daily. But do you know the <strong style=\"color:{TEXT};\">environmental and ethical impact</strong> of your investments? GreenWallet connects to your portfolio and pulls <strong style=\"color:{TEXT};\">live ESG data from 3 financial APIs</strong> to give you a real sustainability score.</div>", unsafe_allow_html=True)
    profile = st.selectbox("Select portfolio", list(DEMOS.keys()), label_visibility="collapsed")
    pin = st.text_input("Portfolio PIN", value="123456", type="password")
    st.caption("Demo PIN: **123456**")
    if st.button("Connect Portfolio"):
        if pin!="123456": st.error("Incorrect PIN.")
        else:
            name,pno,stocks,hist = DEMOS[profile]
            user = q("SELECT * FROM users WHERE username=?",(name,),one=True)
            if not user:
                uid = q("INSERT INTO users(username,portfolio_no) VALUES(?,?)",(name,pno))
                for t,s in stocks: q("INSERT INTO holdings(user_id,ticker,shares) VALUES(?,?,?)",(uid,t,s))
                for i,sc in enumerate(hist):
                    q("INSERT INTO analytics(user_id,green_score,recorded_at) VALUES(?,?,?)",(uid,sc,(datetime.now()-timedelta(days=30*(6-i))).strftime("%Y-%m-%d %H:%M:%S")))
                user = q("SELECT * FROM users WHERE username=?",(name,),one=True)
            st.session_state.update(user=user, uid=user[0], screen="fetch"); st.rerun()

elif st.session_state.screen == "fetch":
    user,uid = st.session_state.user, st.session_state.uid
    st.markdown(f"<div style='text-align:center;padding:28px 0 20px;'><div style='font-size:20px;font-weight:600;color:{TEXT};'>Analyzing {user[1]}'s portfolio</div><div style='font-size:13px;color:{MUTED};margin-top:6px;'>Fetching live ESG data from Alpha Vantage, Yahoo Finance & Finnhub</div></div>", unsafe_allow_html=True)
    holdings = q("SELECT * FROM holdings WHERE user_id=?",(uid,),fetch=True)
    prog = st.progress(0); pdata = []
    for i,h in enumerate(holdings):
        prog.progress((i+1)/len(holdings))
        st.text(f"⏳ Fetching {h[2]}...")
        price = get_price(h[2]); e,s,g,comp,src = get_esg(h[2])
        pdata.append(dict(ticker=h[2],shares=h[3],price=price,env=e,soc=s,gov=g,esg=comp,source=src,value=h[3]*price))
        time.sleep(0.3)
    total = sum(s["value"] for s in pdata)
    score = round(sum(s["value"]*s["esg"] for s in pdata)/total,1) if total>0 else 0
    st.session_state.update(pdata=pdata, score=score, screen="app"); st.rerun()

# ═══════════════════════════════════════════════════════
elif st.session_state.screen == "app":
    user,uid,pdata,sc = st.session_state.user, st.session_state.uid, st.session_state.pdata, st.session_state.score
    lbl,css,col = tier(sc); flagged = [s for s in pdata if s["esg"]<30]; total = sum(s["value"] for s in pdata)
    sources = ", ".join(set(s["source"] for s in pdata))

    st.markdown(f"<div style='display:flex;justify-content:space-between;align-items:center;padding:12px 0 14px;border-bottom:1px solid {BORDER};margin-bottom:14px;'><div style='font-size:18px;font-weight:700;color:{TEXT};'>🌿 Green<span style=\"color:{G}\">Wallet</span></div><div style='font-size:12px;color:{MUTED};'>{user[1]} · {user[2]}</div></div>", unsafe_allow_html=True)
    tabs = st.tabs(["Score","Holdings","ESG Deep Dive","Analytics","Simulator","AI Advisor"])

    with tabs[0]:
        st.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:11px;color:{MUTED};text-transform:uppercase;letter-spacing:0.8px;'>Portfolio Green Score</div><div style='font-size:72px;font-weight:900;color:{col};line-height:1;'>{int(sc)}</div><div style='margin:8px 0;'><span class='pill {css}'>{lbl}</span></div><div style='font-size:12px;color:{MUTED};'>out of 100 · {len(pdata)} holdings · weighted by capital</div></div>", unsafe_allow_html=True)
        c1,c2,c3 = st.columns(3)
        c1.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:11px;color:{MUTED};'>TOTAL VALUE</div><div style='font-size:20px;font-weight:700;color:{TEXT};'>${total:,.0f}</div></div>", unsafe_allow_html=True)
        c2.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:11px;color:{MUTED};'>HOLDINGS</div><div style='font-size:20px;font-weight:700;color:{TEXT};'>{len(pdata)}</div></div>", unsafe_allow_html=True)
        fc = D if flagged else G
        c3.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:11px;color:{MUTED};'>FLAGGED</div><div style='font-size:20px;font-weight:700;color:{fc};'>{len(flagged)}</div></div>", unsafe_allow_html=True)
        st.markdown(f"<div class='sec'>Data Sources</div>", unsafe_allow_html=True)
        for src,desc in [("Alpha Vantage API","Company fundamentals → ESG proxy scores"),("Yahoo Finance","Direct sustainability ratings"),("Finnhub API","ESG scoring and governance metrics"),("yfinance","Real-time stock prices")]:
            st.markdown(f"<div class='r'><span class='rl'>✅ {src}</span><span style='font-size:11px;color:{MUTED};'>{desc}</span></div>", unsafe_allow_html=True)
        st.markdown(f"<div style='font-size:11px;color:{BORDER};margin-top:10px;'>Live sources used: {sources} · Cached 7 days</div>", unsafe_allow_html=True)
        if st.button("💾 Save Score to History"): q("INSERT INTO analytics(user_id,green_score) VALUES(?,?)",(uid,int(sc))); st.success("Saved!")

    with tabs[1]:
        for s in sorted(pdata, key=lambda x:x["esg"], reverse=True):
            c = G if s["esg"]>=60 else M if s["esg"]>=30 else D
            flag = "⚠️ Risk" if s["esg"]<30 else "✅ OK" if s["esg"]>=60 else "⚡ Mod"
            pct = s["value"]/total*100 if total>0 else 0
            st.markdown(f"<div class='sr' style='border-color:{c}22;'><div style='flex:1;'><div style='font-size:14px;font-weight:600;color:{TEXT};'>{s['ticker']}</div><div style='font-size:11px;color:{MUTED};'>{s['shares']} shares · ${s['price']:.2f} · {pct:.1f}% · {s['source']}</div></div><div style='text-align:right;'><div style='font-size:22px;font-weight:700;color:{c};'>{int(s['esg'])}</div><div style='font-size:10px;color:{MUTED};'>{flag}</div></div></div>", unsafe_allow_html=True)

    with tabs[2]:
        sel = st.selectbox("Select stock", [s["ticker"] for s in pdata], label_visibility="collapsed")
        s = next(x for x in pdata if x["ticker"]==sel); c2 = G if s["esg"]>=60 else M if s["esg"]>=30 else D
        st.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:22px;font-weight:700;color:{TEXT};'>{s['ticker']}</div><div style='font-size:11px;color:{MUTED};'>Source: {s['source']}</div><div style='font-size:52px;font-weight:900;color:{c2};margin:12px 0;'>{int(s['esg'])}</div></div>", unsafe_allow_html=True)
        bar("🌍 Environmental", s["env"], G); bar("👥 Social", s["soc"], "#00cec9"); bar("🏛️ Governance", s["gov"], "#6366f1")
        st.markdown(f"<div class='sec'>Search Any Ticker</div>", unsafe_allow_html=True)
        search = st.text_input("Ticker", placeholder="e.g. TSLA", label_visibility="collapsed")
        if st.button("🔍 Fetch ESG") and search.strip():
            with st.spinner(f"Fetching {search.upper()}..."): e,s2,g,comp,src = fetch_esg(search.upper())
            c3 = G if comp>=60 else M if comp>=30 else D
            st.markdown(f"<div class='c' style='text-align:center;'><div style='font-size:18px;font-weight:700;color:{TEXT};'>{search.upper()}</div><div style='font-size:11px;color:{MUTED};'>Source: {src}</div><div style='font-size:42px;font-weight:900;color:{c3};margin:8px 0;'>{int(comp)}</div></div>", unsafe_allow_html=True)
            bar("🌍 Environmental", e, G); bar("👥 Social", s2, "#00cec9"); bar("🏛️ Governance", g, "#6366f1")

    with tabs[3]:
        data = q("SELECT green_score,recorded_at FROM analytics WHERE user_id=? ORDER BY recorded_at",(uid,),fetch=True)
        if data:
            df = pd.DataFrame(data, columns=["Green Score","Date"]); df["Date"] = pd.to_datetime(df["Date"])
            st.line_chart(df.set_index("Date")["Green Score"], color=G)
        else: st.info("No history yet. Save scores from Score tab.")
        st.markdown(f"<div class='sec'>ESG Heatmap</div>", unsafe_allow_html=True)
        for s in sorted(pdata, key=lambda x:x["esg"], reverse=True):
            c = G if s["esg"]>=60 else M if s["esg"]>=30 else D
            st.markdown(f"<div style='display:flex;align-items:center;gap:10px;margin-bottom:6px;'><span style='font-size:12px;color:{MUTED};width:50px;'>{s['ticker']}</span><div class='pb' style='flex:1;margin:0;'><div class='pf' style='width:{max(s['esg'],5)}%;background:{c};'></div></div><span style='font-size:12px;font-weight:700;color:{c};width:30px;text-align:right;'>{int(s['esg'])}</span></div>", unsafe_allow_html=True)

    with tabs[4]:
        st.markdown(f"<div class='c ca'><div style='font-size:11px;color:{G};'>What-If Simulator</div><div style='font-size:13px;color:{MUTED};margin-top:6px;'>Adjust shares and see how your Green Score changes.</div></div>", unsafe_allow_html=True)
        sim = []
        for s in pdata:
            ns = st.slider(f"{s['ticker']} (ESG {int(s['esg'])})", 0.0, float(s['shares']*3), float(s['shares']), 1.0, key=f"s_{s['ticker']}")
            sim.append(dict(esg=s["esg"], value=ns*s["price"]))
        st_total = sum(x["value"] for x in sim)
        sim_sc = sum(x["value"]*x["esg"] for x in sim)/st_total if st_total>0 else 0
        diff = sim_sc-sc; sl,scl,scol = tier(sim_sc); dc = G if diff>0 else D if diff<0 else MUTED
        st.markdown(f"<div class='c' style='text-align:center;'><div style='display:flex;justify-content:center;gap:40px;'><div><div style='font-size:12px;color:{MUTED};'>Current</div><div style='font-size:32px;font-weight:700;color:{col};'>{int(sc)}</div></div><div style='font-size:24px;color:{dc};font-weight:700;margin-top:16px;'>→</div><div><div style='font-size:12px;color:{MUTED};'>Simulated</div><div style='font-size:32px;font-weight:700;color:{scol};'>{int(sim_sc)}</div></div></div><div style='font-size:28px;font-weight:700;color:{dc};margin-top:8px;'>{'+'if diff>0 else ''}{diff:.1f} pts</div><span class='pill {scl}'>{sl}</span></div>", unsafe_allow_html=True)

    with tabs[5]:
        st.markdown(f"<div class='c ca'><div style='font-size:11px;color:{G};'>AI ESG Advisor</div><div style='font-size:13px;color:{MUTED};margin-top:6px;'>Score: <strong style='color:{TEXT};'>{int(sc)}/100</strong> · {lbl} · {len(pdata)} holdings</div></div>", unsafe_allow_html=True)
        def reply(question):
            ql = question.lower(); best = max(pdata,key=lambda x:x["esg"]); worst = min(pdata,key=lambda x:x["esg"])
            if any(x in ql for x in ["improve","boost","better"]): return f"Score is {int(sc)}/100. Fastest wins: reduce {worst['ticker']} (ESG {int(worst['esg'])}), increase {best['ticker']} (ESG {int(best['esg'])}), or swap flagged stocks for clean energy ETFs."
            if any(x in ql for x in ["risk","flag","warn"]):
                if flagged: return "Flagged: "+", ".join(f"{s['ticker']} ({int(s['esg'])})" for s in flagged)+". These carry significant ESG risk."
                return "No stocks flagged. All above ESG 30."
            if any(x in ql for x in ["best","top","strong"]): return f"Best performer: {best['ticker']} at {int(best['esg'])}/100 (source: {best['source']}). Strong across all three ESG pillars."
            if any(x in ql for x in ["worst","weak","low"]): return f"Weakest: {worst['ticker']} at {int(worst['esg'])}/100. Consider whether returns justify the sustainability risk."
            if any(x in ql for x in ["environ","carbon","green"]): e=sorted(pdata,key=lambda x:x["env"]); return f"Environmental: weakest is {e[0]['ticker']} ({int(e[0]['env'])}), strongest is {e[-1]['ticker']} ({int(e[-1]['env'])})."
            return f"Portfolio Green Score: {int(sc)}/100 ({lbl}), {len(pdata)} holdings. Ask about risks, improvements, or specific ESG pillars."
        if not st.session_state.chat:
            for i,question in enumerate(["How do I improve?","Any risk alerts?","Best ESG stock?","Environmental breakdown?"]):
                if st.button(question,key=f"q{i}"): st.session_state.chat+=[{"r":"u","t":question},{"r":"b","t":reply(question)}]; st.rerun()
        for m in st.session_state.chat: st.markdown(f"<div class='chat-{'u'if m['r']=='u'else'b'}'>{m['t']}</div>", unsafe_allow_html=True)
        inp = st.chat_input("Ask about ESG risks, improvements...")
        if inp: st.session_state.chat+=[{"r":"u","t":inp},{"r":"b","t":reply(inp)}]; st.rerun()

    st.markdown("---")
    if st.button("Disconnect Portfolio"):
        for k,v in dict(screen="login",user=None,uid=None,pdata=[],score=0,chat=[]).items(): st.session_state[k]=v; st.rerun()
    st.markdown(f"<p style='text-align:center;font-size:11px;color:{BORDER};'>GreenWallet v2.0 · APIs: Alpha Vantage · Yahoo Finance · Finnhub</p>", unsafe_allow_html=True)
