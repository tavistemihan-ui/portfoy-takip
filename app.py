import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import io
import requests
import sqlite3
import json
import yfinance as yf


# --- ŞİFRE KORUMA SİSTEMİ ---
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False

    if not st.session_state.authenticated:
        st.title("🔒 Portföy Terminali - Giriş")
        password = st.text_input("Lütfen Parolayı Girin:", type="password")
        if st.button("Giriş Yap", type="primary"):
            if password == "a4mB3kfYjRJ3sGv":  # <-- BURAYA KENDİ ŞİFRENİZİ YAZIN
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Hatalı parola!")
        return False
    return True

if not check_password():
    st.stop()  # Şifre doğru girilene kadar uygulamanın geri kalanını çalıştırmaz
# ----------------------------


st.set_page_config(
    page_title="Portföy Terminal Pro",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Koyu Finans Teması & Tablo Başlık Alt Satır Desteği
st.markdown("""
<style>
    .metric-card { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
    .stButton>button { border-radius: 6px; }
    th {
        white-space: pre-wrap !important;
        vertical-align: middle !important;
        text-align: center !important;
    }
</style>
""", unsafe_allow_html=True)

# --- 1. VERİTABANI BAĞLANTISI ---
DB_FILE = "portfolio_data.db"

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('''CREATE TABLE IF NOT EXISTS portfolios (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        currency TEXT NOT NULL)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS lots (
                        lot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        portfolio_id INTEGER,
                        ticker TEXT NOT NULL,
                        buy_date TEXT NOT NULL,
                        buy_price REAL NOT NULL,
                        initial_shares REAL NOT NULL,
                        remaining_shares REAL NOT NULL,
                        currency TEXT NOT NULL,
                        commission REAL DEFAULT 0.0)''')
        
        c.execute('''CREATE TABLE IF NOT EXISTS sales (
                        sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        portfolio_id INTEGER,
                        ticker TEXT NOT NULL,
                        sale_date TEXT NOT NULL,
                        shares REAL NOT NULL,
                        sale_price REAL NOT NULL,
                        cost REAL NOT NULL,
                        commission REAL DEFAULT 0.0,
                        realized_pnl REAL NOT NULL,
                        currency TEXT NOT NULL,
                        current_price REAL DEFAULT NULL,
                        allocations_json TEXT)''')
        
        c.execute("SELECT COUNT(*) FROM portfolios")
        if c.fetchone()[0] == 0:
            c.executemany("INSERT INTO portfolios (name, currency) VALUES (?, ?)", [
                ("Amerikan Borsası", "USD"),
                ("Alman Borsası", "EUR"),
                ("BIST / Türkiye", "TRY")
            ])
        conn.commit()

init_db()

# --- 2. ŞİFRE KORUMASI ---
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        st.title("🔒 Portföy Terminali - Giriş")
        password = st.text_input("Lütfen Parolayı Girin:", type="password")
        if st.button("Giriş Yap", type="primary"):
            if password == "1234":
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Hatalı parola!")
        return False
    return True

if not check_password():
    st.stop()

# --- 3. DÖVİZ KURLARI & PİYASA VERİLERİ ---
@st.cache_data(ttl=1800)
def fetch_live_fx_rates():
    rates = {"USD_TRY": 34.20, "EUR_TRY": 37.80, "EUR_USD": 1.10}
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        res = requests.get(url, timeout=5).json()
        if res and "rates" in res:
            usd_try = float(res["rates"].get("TRY", 34.20))
            usd_eur = float(res["rates"].get("EUR", 0.91))
            eur_usd = 1.0 / usd_eur if usd_eur else 1.10
            eur_try = usd_try / usd_eur if usd_eur else 37.80
            rates = {"USD_TRY": round(usd_try, 2), "EUR_TRY": round(eur_try, 2), "EUR_USD": round(eur_usd, 3)}
    except Exception:
        pass
    return rates

live_rates = fetch_live_fx_rates()

@st.cache_data(ttl=300)
def get_live_stock_data(ticker: str):
    try:
        t = yf.Ticker(ticker.strip().upper())
        hist = t.history(period="1d")
        price = 0.0
        if not hist.empty:
            price = round(float(hist["Close"].iloc[-1]), 2)
        else:
            info = t.info
            price = round(float(info.get("regularMarketPrice") or info.get("previousClose") or 0.0), 2)
        sector = t.info.get("sector", "Diğer")
        return price, sector
    except Exception:
        return 0.0, "Diğer"

@st.cache_data(ttl=600)
def get_stock_multi_period_performance(ticker: str):
    perf = {"current_price": 0.0, "1D": 0.0, "1W": 0.0, "1M": 0.0, "6M": 0.0, "1Y": 0.0, "5Y": 0.0}
    try:
        t = yf.Ticker(ticker.strip().upper())
        hist = t.history(period="5y")
        if hist.empty or len(hist) < 2:
            return perf
        
        current_close = float(hist["Close"].iloc[-1])
        perf["current_price"] = round(current_close, 2)

        def calc_ret(idx_offset):
            if len(hist) > idx_offset:
                past_close = float(hist["Close"].iloc[-1 - idx_offset])
                if past_close > 0:
                    return ((current_close - past_close) / past_close) * 100
            return 0.0

        perf["1D"] = calc_ret(1)
        perf["1W"] = calc_ret(5)
        perf["1M"] = calc_ret(21)
        perf["6M"] = calc_ret(126)
        perf["1Y"] = calc_ret(252)
        
        first_close = float(hist["Close"].iloc[0])
        if first_close > 0 and len(hist) >= 500:
            perf["5Y"] = ((current_close - first_close) / first_close) * 100
    except Exception:
        pass
    return perf

def format_curr(amount: float, curr: str) -> str:
    if curr == "USD":
        return f"${amount:,.2f}"
    elif curr == "EUR":
        return f"€{amount:,.2f}"
    elif curr == "TRY":
        return f"₺{amount:,.2f}"
    return f"{amount:,.2f} {curr}"

def convert_to_base(amount: float, from_curr: str, to_curr: str) -> float:
    if from_curr == to_curr:
        return amount
    to_try = 1.0
    if from_curr == "USD":
        to_try = live_rates["USD_TRY"]
    elif from_curr == "EUR":
        to_try = live_rates["EUR_TRY"]
    amount_try = amount * to_try

    if to_curr == "TRY":
        return amount_try
    elif to_curr == "USD":
        return amount_try / live_rates["USD_TRY"]
    elif to_curr == "EUR":
        return amount_try / live_rates["EUR_TRY"]
    return amount

# --- 4. VERİ ÇEKME YARDIMCILARI ---
def load_portfolios():
    with get_connection() as conn:
        return pd.read_sql("SELECT * FROM portfolios", conn)

def load_open_lots(portfolio_id=None):
    with get_connection() as conn:
        q = "SELECT * FROM lots WHERE remaining_shares > 0"
        if portfolio_id:
            q += f" AND portfolio_id = {portfolio_id}"
        return pd.read_sql(q, conn)

def load_sales(portfolio_id=None):
    with get_connection() as conn:
        q = "SELECT * FROM sales"
        if portfolio_id:
            q += f" AND portfolio_id = {portfolio_id}"
        return pd.read_sql(q, conn)

portfolios_df = load_portfolios()

if "edit_lot_id" not in st.session_state:
    st.session_state.edit_lot_id = None
if "edit_sale_id" not in st.session_state:
    st.session_state.edit_sale_id = None

# --- 5. KENAR ÇUBUĞU ---
with st.sidebar:
    st.title("💼 Portföy Terminali")
    st.caption("🌐 **Canlı Kurlar:**")
    st.write(f"USD/TRY: **₺{live_rates['USD_TRY']}** | EUR/TRY: **₺{live_rates['EUR_TRY']}**")
    st.divider()

    p_names = ["🌐 Toplu Portföy (Konsolide)"] + [f"{r['name']} ({r['currency']})" for _, r in portfolios_df.iterrows()]
    selected_p_str = st.selectbox("Aktif Portföy", p_names)
    
    is_consolidated = selected_p_str.startswith("🌐")
    current_p_id = None
    current_p_curr = "USD"
    if not is_consolidated:
        matched = portfolios_df[portfolios_df.apply(lambda r: f"{r['name']} ({r['currency']})" == selected_p_str, axis=1)]
        if not matched.empty:
            current_p_id = int(matched.iloc[0]["id"])
            current_p_curr = matched.iloc[0]["currency"]

    base_currency = st.selectbox("Konsolide Para Birimi", ["USD", "EUR", "TRY"], index=0)
    st.divider()
    menu = st.radio(
        "Menü",
        [
            "📊 Dashboard (Canlı Fiyatlı)",
            "📝 Yeni İşlem / Satış",
            "🎯 Satış Sonrası Performans (Canlı)",
            "✏️ Geçmiş İşlem Yönetimi & Düzeltme",
            "⚙️ Portföy & Yedekleme Ayarları",
            "📥 Excel Raporu"
        ]
    )

# --- 6. DASHBOARD ---
if menu == "📊 Dashboard (Canlı Fiyatlı)":
    lots_df = load_open_lots()
    sales_df = load_sales()

    if is_consolidated:
        st.title(f"🌐 Konsolide Portföy ({base_currency})")
        
        total_cost_base = 0.0
        total_current_val_base = 0.0
        total_realized_base = 0.0
        portfolio_rows = []

        for _, p in portfolios_df.iterrows():
            p_lots = lots_df[lots_df["portfolio_id"] == p["id"]]
            p_sales = sales_df[sales_df["portfolio_id"] == p["id"]]
            
            p_cost = (p_lots["remaining_shares"] * p_lots["buy_price"]).sum()
            p_cost_b = convert_to_base(p_cost, p["currency"], base_currency)
            total_cost_base += p_cost_b

            p_cur_val = 0.0
            for _, lot in p_lots.iterrows():
                lp, _ = get_live_stock_data(lot["ticker"])
                cur_p = lp if lp > 0 else lot["buy_price"]
                p_cur_val += lot["remaining_shares"] * cur_p
            
            p_cur_val_b = convert_to_base(p_cur_val, p["currency"], base_currency)
            total_current_val_base += p_cur_val_b

            p_pnl = p_sales["realized_pnl"].sum() if not p_sales.empty else 0.0
            total_realized_base += convert_to_base(p_pnl, p["currency"], base_currency)

            portfolio_rows.append({
                "Portföy": p["name"],
                "Toplam<br>Maliyet": format_curr(p_cost_b, base_currency),
                "Güncel Piyasa Değeri": format_curr(p_cur_val_b, base_currency),
                "Piyasa Değeri Ham": p_cur_val_b
            })

        unrealized_total_base = total_current_val_base - total_cost_base
        unrealized_pct = (unrealized_total_base / total_cost_base * 100) if total_cost_base > 0 else 0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Güncel Piyasa Değeri", format_curr(total_current_val_base, base_currency))
        c2.metric("Toplam Alış Maliyeti", format_curr(total_cost_base, base_currency))
        c3.metric("Anlık Kâr/Zarar", format_curr(unrealized_total_base, base_currency), delta=f"%{unrealized_pct:+.2f}")
        c4.metric("Realize Edilmiş K/Z", format_curr(total_realized_base, base_currency))

        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Portföy Büyüklük Dağılımı")
            if total_current_val_base > 0:
                fig = px.pie(pd.DataFrame(portfolio_rows), names="Portföy", values="Piyasa Değeri Ham", hole=0.4, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Portföyde açık hisse yok.")
        with col2:
            st.subheader("Konsolide Portföy Dağılım Tablosu")
            df_disp = pd.DataFrame(portfolio_rows).drop(columns=["Piyasa Değeri Ham"])
            st.write(df_disp.to_html(escape=False, index=False), unsafe_allow_html=True)

    else:
        p_info = portfolios_df[portfolios_df["id"] == current_p_id].iloc[0]
        st.title(f"📊 {p_info['name']} ({p_info['currency']})")
        
        p_lots = lots_df[lots_df["portfolio_id"] == current_p_id].copy()
        p_sales = sales_df[sales_df["portfolio_id"] == current_p_id]

        total_cost = (p_lots["remaining_shares"] * p_lots["buy_price"]).sum() if not p_lots.empty else 0.0
        realized_pnl = p_sales["realized_pnl"].sum() if not p_sales.empty else 0.0

        lot_details = []
        total_market_val = 0.0

        for _, lot in p_lots.iterrows():
            live_p, sector = get_live_stock_data(lot["ticker"])
            effective_price = live_p if live_p > 0 else lot["buy_price"]
            market_val = lot["remaining_shares"] * effective_price
            cost_val = lot["remaining_shares"] * lot["buy_price"]
            pnl_val = market_val - cost_val
            pnl_pct = (pnl_val / cost_val * 100) if cost_val > 0 else 0.0
            total_market_val += market_val

            lot_details.append({
                "Hisse": lot["ticker"],
                "Sektör": sector,
                "Alış Tarihi": lot["buy_date"],
                "Kalan Lot": lot["remaining_shares"],
                "Alış Fiyatı": format_curr(lot['buy_price'], p_info['currency']),
                "Şimdiki Fiyat": format_curr(effective_price, p_info['currency']),
                "Toplam<br>Maliyet": format_curr(cost_val, p_info['currency']),
                "Piyasa Değeri": format_curr(market_val, p_info['currency']),
                "Piyasa Değeri Ham": market_val,
                "Anlık K/Z<br>Tutarı": format_curr(pnl_val, p_info['currency']),
                "Anlık K/Z (%)": pnl_pct
            })

        total_unrealized_pnl = total_market_val - total_cost
        total_unrealized_pct = (total_unrealized_pnl / total_cost * 100) if total_cost > 0 else 0.0

        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Güncel Portföy Değeri", format_curr(total_market_val, p_info['currency']))
        c2.metric("Toplam Alış Maliyeti", format_curr(total_cost, p_info['currency']))
        c3.metric("Anlık Kâr/Zarar", format_curr(total_unrealized_pnl, p_info['currency']), delta=f"%{total_unrealized_pct:+.2f}")
        c4.metric("Realize Edilmiş K/Z", format_curr(realized_pnl, p_info['currency']))

        st.divider()

        if lot_details:
            df_lots_full = pd.DataFrame(lot_details)
            g1, g2 = st.columns(2)
            with g1:
                st.subheader("🥧 Portföy Varlık Dağılımı (%)")
                asset_agg = df_lots_full.groupby("Hisse")["Piyasa Değeri Ham"].sum().reset_index()
                fig_asset = px.pie(asset_agg, names="Hisse", values="Piyasa Değeri Ham", hole=0.4, template="plotly_dark")
                st.plotly_chart(fig_asset, use_container_width=True)

            with g2:
                st.subheader("🏭 Sektörel Portföy Dağılımı (%)")
                sector_agg = df_lots_full.groupby("Sektör")["Piyasa Değeri Ham"].sum().reset_index()
                fig_sector = px.pie(sector_agg, names="Sektör", values="Piyasa Değeri Ham", hole=0.4, template="plotly_dark")
                st.plotly_chart(fig_sector, use_container_width=True)

            st.divider()
            st.subheader("📌 Açık Pozisyonlar ve Canlı K/Z Durumu")

            df_table = df_lots_full.drop(columns=["Piyasa Değeri Ham"]).copy()

            def build_custom_html_table(df):
                html = """<table style="width:100%; border-collapse: collapse; text-align:left;"><thead><tr style="border-bottom: 2px solid #30363d; background-color:#161b22;">"""
                for col in df.columns:
                    html += f"""<th style="padding:10px; font-weight:600; color:#c9d1d9;">{col}</th>"""
                html += "</tr></thead><tbody>"

                for _, row in df.iterrows():
                    html += "<tr style='border-bottom: 1px solid #21262d;'>"
                    for col in df.columns:
                        val = row[col]
                        if col == "Anlık K/Z (%)":
                            color = "#2ea043" if val >= 0 else "#f85149"
                            html += f"<td style='padding:10px; font-weight:bold; color:{color};'>%{val:+.2f}</td>"
                        elif col == "Anlık K/Z<br>Tutarı":
                            color = "#f85149" if "-" in str(val) else "#2ea043"
                            html += f"<td style='padding:10px; font-weight:600; color:{color};'>{val}</td>"
                        else:
                            html += f"<td style='padding:10px; color:#e6edf3;'>{val}</td>"
                    html += "</tr>"
                html += "</tbody></table>"
                return html

            st.write(build_custom_html_table(df_table), unsafe_allow_html=True)

            st.divider()
            st.subheader("📊 Açık Hisselerin Dönemsel Getiri Performansı (Canlı Piyasa)")

            unique_tickers = sorted(df_lots_full["Hisse"].unique())
            period_rows = []

            for sym in unique_tickers:
                perf = get_stock_multi_period_performance(sym)
                period_rows.append({
                    "Hisse": sym,
                    "Şimdiki Fiyat": format_curr(perf["current_price"], p_info['currency']),
                    "1 Günlük": perf["1D"],
                    "1 Haftalık": perf["1W"],
                    "1 Aylık": perf["1M"],
                    "6 Aylık": perf["6M"],
                    "1 Yıllık": perf["1Y"],
                    "5 Yıllık": perf["5Y"]
                })

            df_perf = pd.DataFrame(period_rows)

            def build_perf_html_table(df):
                html = """<table style="width:100%; border-collapse: collapse; text-align:left;"><thead><tr style="border-bottom: 2px solid #30363d; background-color:#161b22;">"""
                for col in df.columns:
                    html += f"""<th style="padding:10px; font-weight:600; color:#c9d1d9;">{col}</th>"""
                html += "</tr></thead><tbody>"

                for _, row in df.iterrows():
                    html += "<tr style='border-bottom: 1px solid #21262d;'>"
                    for col in df.columns:
                        val = row[col]
                        if col in ["1 Günlük", "1 Haftalık", "1 Aylık", "6 Aylık", "1 Yıllık", "5 Yıllık"]:
                            color = "#2ea043" if val >= 0 else "#f85149"
                            html += f"<td style='padding:10px; font-weight:bold; color:{color};'>%{val:+.2f}</td>"
                        else:
                            html += f"<td style='padding:10px; color:#e6edf3;'>{val}</td>"
                    html += "</tr>"
                html += "</tbody></table>"
                return html

            st.write(build_perf_html_table(df_perf), unsafe_allow_html=True)
        else:
            st.info("Bu portföyde henüz açık hisse bulunmuyor.")

# --- 7. YENİ İŞLEM / SATIŞ ---
elif menu == "📝 Yeni İşlem / Satış":
    st.title("📝 İşlem Girişi")
    port_dict = {f"{r['name']} ({r['currency']})": (r['id'], r['currency']) for _, r in portfolios_df.iterrows()}
    chosen_label = st.selectbox("İşlem Yapılacak Portföy", list(port_dict.keys()))
    target_pid, target_pcurr = port_dict[chosen_label]

    default_comm = 1.50 if target_pcurr == "USD" else 0.0
    tx_type = st.radio("İşlem Türü", ["ALIŞ (Yeni Lot Ekle)", "SATIŞ (Parçalı Lot Satışı)"], horizontal=True)

    if tx_type.startswith("ALIŞ"):
        st.subheader("Yeni Alış Kaydı")
        c1, c2, c3 = st.columns(3)
        with c1:
            ticker_input = st.text_input("Hisse Kodu (Ticker - örn: AAPL, THYAO.IS)", value="AAPL").strip().upper()
        with c2:
            buy_date_input = st.date_input("Alış Tarihi", datetime.now())
        with c3:
            shares_input = st.number_input("Adet (Lot)", min_value=0.01, value=10.0, step=1.0)

        c4, c5 = st.columns(2)
        with c4:
            price_input = st.number_input(f"Alış Fiyatı ({target_pcurr})", min_value=0.01, value=150.0, step=1.0)
        with c5:
            comm_input = st.number_input(f"Komisyon ({target_pcurr})", min_value=0.0, value=default_comm, step=0.1)

        if st.button("Alışı Kaydet", type="primary"):
            if ticker_input:
                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''INSERT INTO lots 
                                      (portfolio_id, ticker, buy_date, buy_price, initial_shares, remaining_shares, currency, commission) 
                                      VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                                   (target_pid, ticker_input, str(buy_date_input), price_input, shares_input, shares_input, target_pcurr, comm_input))
                    conn.commit()
                st.success(f"{ticker_input} ({shares_input} lot) kaydedildi!")
                st.rerun()

    else:
        st.subheader("Parçalı Lot Satışı")
        open_lots_p = load_open_lots(target_pid)

        if open_lots_p.empty:
            st.warning("Bu portföyde satılabilecek hisse bulunmuyor.")
        else:
            available_tickers = sorted(open_lots_p["ticker"].unique())
            sel_ticker = st.selectbox("Satılacak Hisseyi Seçin", available_tickers)
            
            cs1, cs2 = st.columns(2)
            with cs1:
                sale_price = st.number_input(f"Satış Fiyatı ({target_pcurr})", min_value=0.01, value=160.0, step=1.0)
            with cs2:
                sale_comm = st.number_input(f"Satış Komisyonu ({target_pcurr})", min_value=0.0, value=default_comm, step=0.1)

            ticker_lots = open_lots_p[open_lots_p["ticker"] == sel_ticker]
            st.markdown("#### 🎯 Hangi Alıştan Satış Yapmak İstiyorsunuz?")

            allocations = []
            total_sold = 0.0
            total_cost = 0.0

            for _, lot in ticker_lots.iterrows():
                c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
                c1.write(f"📅 **{lot['buy_date']}**")
                c2.write(f"Alış: **{format_curr(lot['buy_price'], lot['currency'])}**")
                c3.write(f"Kalan: **{lot['remaining_shares']} lot**")
                qty = c4.number_input(
                    f"Sat (Lot #{lot['lot_id']})",
                    min_value=0.0,
                    max_value=float(lot["remaining_shares"]),
                    value=0.0,
                    step=1.0,
                    key=f"sell_{lot['lot_id']}"
                )
                if qty > 0:
                    allocations.append({"lot_id": int(lot["lot_id"]), "qty": qty, "buy_price": lot["buy_price"]})
                    total_sold += qty
                    total_cost += (qty * lot["buy_price"])

            if total_sold > 0:
                proceeds = total_sold * sale_price
                realized_pnl = (proceeds - total_cost) - sale_comm
                ret_pct = (realized_pnl / total_cost) * 100 if total_cost > 0 else 0

                st.divider()
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Satılacak Lot", f"{total_sold:.0f}")
                m2.metric("Alış Maliyeti", format_curr(total_cost, target_pcurr))
                m3.metric("Satış Geliri", format_curr(proceeds, target_pcurr))
                m4.metric("Net Kâr/Zarar", format_curr(realized_pnl, target_pcurr), delta=f"%{ret_pct:+.2f}")

                if st.button("Satışı Onayla ve Tamamla", type="primary"):
                    with get_connection() as conn:
                        cursor = conn.cursor()
                        for alloc in allocations:
                            cursor.execute("UPDATE lots SET remaining_shares = remaining_shares - ? WHERE lot_id = ?",
                                           (alloc["qty"], alloc["lot_id"]))
                        cursor.execute('''INSERT INTO sales 
                                          (portfolio_id, ticker, sale_date, shares, sale_price, cost, commission, realized_pnl, currency, current_price, allocations_json) 
                                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                       (target_pid, sel_ticker, datetime.now().strftime("%Y-%m-%d"), total_sold, sale_price, total_cost, sale_comm, realized_pnl, target_pcurr, sale_price, json.dumps(allocations)))
                        conn.commit()
                    st.success("Satış tamamlandı!")
                    st.rerun()

# --- 8. SATIŞ SONRASI PERFORMANS (CANLI) ---
elif menu == "🎯 Satış Sonrası Performans (Canlı)":
    st.title("🎯 Satış Sonrası Canlı Fiyat & Karar Analizi")
    st.caption("Alış, satış ve güncel piyasa fiyatı arasındaki tüm farklar canlı karşılaştırılır.")

    sales_df = load_sales()
    if sales_df.empty:
        st.info("Henüz gerçekleştirilmiş satış işlemi bulunmuyor.")
    else:
        if st.button("🔄 Canlı Fiyatları Güncelle"):
            st.cache_data.clear()
            st.rerun()

        for idx, sale in sales_df.iterrows():
            with st.container():
                st.markdown(f"### 📌 {sale['ticker']} Satışı (#{sale['sale_id']}) - {sale['sale_date']}")
                
                avg_buy_price = (sale["cost"] / sale["shares"]) if sale["shares"] > 0 else 0.0
                live_price, _ = get_live_stock_data(sale['ticker'])
                current_p = live_price if live_price > 0 else (sale['current_price'] or sale['sale_price'])

                col_m1, col_m2, col_m3, col_m4 = st.columns(4)
                col_m1.metric("Satılan Adet", f"{sale['shares']} Lot")
                col_m1.caption(f"Realize Net K/Z: **{format_curr(sale['realized_pnl'], sale['currency'])}**")
                col_m2.metric("Orijinal Alış Fiyatı", format_curr(avg_buy_price, sale['currency']))
                col_m3.metric("Satış Fiyatı", format_curr(sale['sale_price'], sale['currency']))
                col_m4.metric("Şu Anki Canlı Fiyat", format_curr(current_p, sale['currency']))

                diff_sale = current_p - sale["sale_price"]
                diff_sale_pct = (diff_sale / sale["sale_price"] * 100) if sale["sale_price"] > 0 else 0.0
                potential_diff_total = diff_sale * sale["shares"]

                diff_buy = current_p - avg_buy_price
                diff_buy_pct = (diff_buy / avg_buy_price * 100) if avg_buy_price > 0 else 0.0
                total_gain_if_held = diff_buy * sale["shares"]

                sub1, sub2, sub3 = st.columns(3)
                with sub1:
                    st.markdown("**1. Satışa Göre Karşılaştırma**")
                    color_sale = "#2ea043" if diff_sale >= 0 else "#f85149"
                    st.markdown(f"Fark: <span style='color:{color_sale}; font-weight:bold;'>%{diff_sale_pct:+.2f} ({format_curr(diff_sale, sale['currency'])})</span>", unsafe_allow_html=True)
                    st.caption(f"Potansiyel Fark Tutarı: **{format_curr(potential_diff_total, sale['currency'])}**")

                with sub2:
                    st.markdown("**2. Alışa Göre Toplam Fark (Bugün)**")
                    color_buy = "#2ea043" if diff_buy >= 0 else "#f85149"
                    st.markdown(f"Fark: <span style='color:{color_buy}; font-weight:bold;'>%{diff_buy_pct:+.2f} ({format_curr(diff_buy, sale['currency'])})</span>", unsafe_allow_html=True)
                    st.caption(f"Satılmasaydı Toplam K/Z: **{format_curr(total_gain_if_held, sale['currency'])}**")

                with sub3:
                    st.markdown("**3. Karar Yorumu**")
                    if diff_sale > 0:
                        st.warning("⚠️ Satış sonrası yükseliş devam etti (Erken Çıkış).")
                    elif diff_sale < 0:
                        st.success("✅ Fiyat satış seviyesinin altına indi (Doğru Çıkış).")
                    else:
                        st.info("ℹ️ Fiyat satış seviyesinde seyrediyor.")

                st.divider()

# --- 9. GEÇMİŞ İŞLEM YÖNETİMİ & DÜZELTME ---
elif menu == "✏️ Geçmiş İşlem Yönetimi & Düzeltme":
    st.title("✏️ İşlem Düzeltme, Güncelleme ve Silme")
    tab_buys, tab_sales = st.tabs(["🟢 Alış Lotlarını Düzelt / Sil", "🔴 Satış Kayıtlarını Düzelt / Geri Al"])

    with tab_buys:
        with get_connection() as conn:
            all_lots = pd.read_sql("SELECT * FROM lots", conn)

        if all_lots.empty:
            st.info("Kayıtlı alış bulunmuyor.")
        else:
            if st.session_state.edit_lot_id:
                lot_to_edit = all_lots[all_lots["lot_id"] == st.session_state.edit_lot_id].iloc[0]
                st.warning(f"🛠️ Lot #{lot_to_edit['lot_id']} ({lot_to_edit['ticker']}) Düzenleniyor")
                
                with st.form("edit_lot_form"):
                    e_c1, e_c2, e_c3 = st.columns(3)
                    new_ticker = e_c1.text_input("Ticker", value=lot_to_edit["ticker"]).upper()
                    new_date = e_c2.date_input("Tarih", datetime.strptime(lot_to_edit["buy_date"], "%Y-%m-%d"))
                    new_price = e_c3.number_input("Alış Fiyatı", value=float(lot_to_edit["buy_price"]), min_value=0.01)

                    e_c4, e_c5 = st.columns(2)
                    is_sold = lot_to_edit["remaining_shares"] != lot_to_edit["initial_shares"]
                    new_shares = e_c4.number_input("Lot Adedi", value=float(lot_to_edit["initial_shares"]), disabled=is_sold)
                    new_comm = e_c5.number_input("Komisyon", value=float(lot_to_edit["commission"]), min_value=0.0)

                    f_b1, f_b2 = st.columns([1, 4])
                    save_edit = f_b1.form_submit_button("Kaydet", type="primary")
                    cancel_edit = f_b2.form_submit_button("İptal")

                    if save_edit:
                        with get_connection() as conn:
                            cursor = conn.cursor()
                            rem_shares = new_shares if not is_sold else lot_to_edit["remaining_shares"]
                            cursor.execute('''UPDATE lots SET ticker = ?, buy_date = ?, buy_price = ?, initial_shares = ?, remaining_shares = ?, commission = ? 
                                              WHERE lot_id = ?''',
                                           (new_ticker, str(new_date), new_price, new_shares, rem_shares, new_comm, lot_to_edit["lot_id"]))
                            conn.commit()
                        st.session_state.edit_lot_id = None
                        st.success("Alış kaydı güncellendi!")
                        st.rerun()

                    if cancel_edit:
                        st.session_state.edit_lot_id = None
                        st.rerun()

            for _, lot in all_lots.iterrows():
                p_row = portfolios_df[portfolios_df["id"] == lot["portfolio_id"]]
                p_name = p_row.iloc[0]["name"] if not p_row.empty else ""
                c1, c2, c3, c4, c5, c6 = st.columns([2, 2, 2, 2, 1, 1])
                c1.write(f"**{lot['ticker']}** (Lot #{lot['lot_id']})")
                c2.write(f"Portföy: {p_name}")
                c3.write(f"📅 {lot['buy_date']} | {format_curr(lot['buy_price'], lot['currency'])}")
                c4.write(f"Kalan: {lot['remaining_shares']}/{lot['initial_shares']} Lot")

                if c5.button("✏️ Düzenle", key=f"edit_btn_{lot['lot_id']}"):
                    st.session_state.edit_lot_id = int(lot["lot_id"])
                    st.rerun()

                if lot["remaining_shares"] == lot["initial_shares"]:
                    if c6.button("🗑️ Sil", key=f"del_lot_{lot['lot_id']}"):
                        with get_connection() as conn:
                            conn.cursor().execute("DELETE FROM lots WHERE lot_id = ?", (lot["lot_id"],))
                            conn.commit()
                        st.success("Alış silindi.")
                        st.rerun()
                else:
                    c6.caption("Kısmi Satıldı")

    with tab_sales:
        sales_df = load_sales()
        if sales_df.empty:
            st.info("Kayıtlı satış bulunmuyor.")
        else:
            if st.session_state.edit_sale_id:
                sale_to_edit = sales_df[sales_df["sale_id"] == st.session_state.edit_sale_id].iloc[0]
                st.warning(f"🛠️ Satış #{sale_to_edit['sale_id']} ({sale_to_edit['ticker']}) Düzenleniyor")

                with st.form("edit_sale_form"):
                    s_c1, s_c2, s_c3 = st.columns(3)
                    new_s_date = s_c1.date_input("Satış Tarihi", datetime.strptime(sale_to_edit["sale_date"], "%Y-%m-%d"))
                    new_s_price = s_c2.number_input("Satış Fiyatı", value=float(sale_to_edit["sale_price"]), min_value=0.01)
                    new_s_comm = s_c3.number_input("Komisyon", value=float(sale_to_edit["commission"]), min_value=0.0)

                    s_b1, s_b2 = st.columns([1, 4])
                    save_s_edit = s_b1.form_submit_button("Kaydet", type="primary")
                    cancel_s_edit = s_b2.form_submit_button("İptal")

                    if save_s_edit:
                        new_proceeds = sale_to_edit["shares"] * new_s_price
                        new_pnl = (new_proceeds - sale_to_edit["cost"]) - new_s_comm

                        with get_connection() as conn:
                            conn.cursor().execute('''UPDATE sales SET sale_date = ?, sale_price = ?, commission = ?, realized_pnl = ? 
                                                     WHERE sale_id = ?''',
                                                  (str(new_s_date), new_s_price, new_s_comm, new_pnl, sale_to_edit["sale_id"]))
                            conn.commit()
                        st.session_state.edit_sale_id = None
                        st.success("Satış güncellendi!")
                        st.rerun()

                    if cancel_s_edit:
                        st.session_state.edit_sale_id = None
                        st.rerun()

            for _, sale in sales_df.iterrows():
                p_row = portfolios_df[portfolios_df["id"] == sale["portfolio_id"]]
                p_name = p_row.iloc[0]["name"] if not p_row.empty else ""
                c1, c2, c3, c4, c5, c6 = st.columns([2, 2, 2, 2, 1, 1])
                c1.write(f"**{sale['ticker']}** ({p_name})")
                c2.write(f"📅 {sale['sale_date']}")
                c3.write(f"{sale['shares']} Lot @ {format_curr(sale['sale_price'], sale['currency'])}")
                c4.write(f"Net K/Z: **{format_curr(sale['realized_pnl'], sale['currency'])}**")

                if c5.button("✏️ Düzenle", key=f"edit_sale_btn_{sale['sale_id']}"):
                    st.session_state.edit_sale_id = int(sale["sale_id"])
                    st.rerun()

                if c6.button("🗑️ Geri Al", key=f"del_sale_{sale['sale_id']}"):
                    allocs = json.loads(sale["allocations_json"])
                    with get_connection() as conn:
                        cursor = conn.cursor()
                        for item in allocs:
                            cursor.execute("UPDATE lots SET remaining_shares = remaining_shares + ? WHERE lot_id = ?",
                                           (item["qty"], item["lot_id"]))
                        cursor.execute("DELETE FROM sales WHERE sale_id = ?", (sale["sale_id"],))
                        conn.commit()
                    st.success("Satış geri alındı ve lotlar iade edildi.")
                    st.rerun()

# --- 10. PORTFÖY & YEDEKLEME AYARLARI (YENİ EKLENEN BÖLÜM) ---
elif menu == "⚙️ Portföy & Yedekleme Ayarları":
    st.title("⚙️ Portföy ve Veri Yedekleme Yönetimi")
    
    st.info("💡 **Önemli Bilgi:** Streamlit Cloud uyku moduna geçtiğinde sunucudaki geçici verileri sıfırlar. İşlemlerinizin kalıcı olarak korunması için aşağıdaki **Veritabanı Yedeğini İndir** butonunu kullanarak dosyanızı bilgisayarınızda saklayabilir, site uyandığında **Yedekten Geri Yükle** kısmından saniyeler içinde geri yükleyebilirsiniz.")

    tab1, tab2 = st.tabs(["💾 Veritabanı Yedeği Al / Geri Yükle", "📁 Portföy Yönetimi"])

    with tab1:
        st.subheader("💾 Veritabanı Yedekleme İşlemleri")
        
        c_backup1, c_backup2 = st.columns(2)
        with c_backup1:
            st.markdown("#### 1. Yedeği Bilgisayara İndir")
            st.caption("Tüm portföylerinizi, açık lotlarınızı ve satış geçmişinizi içeren `.db` dosyasını indirin.")
            if os.path.exists(DB_FILE):
                with open(DB_FILE, "rb") as f:
                    db_bytes = f.read()
                st.download_button(
                    label="📥 Veritabanı Yedeğini İndir (portfolio_data.db)",
                    data=db_bytes,
                    file_name=f"portfolio_backup_{datetime.now().strftime('%Y%m%d_%H%M')}.db",
                    mime="application/x-sqlite3"
                )
            else:
                st.warning("Veritabanı dosyası henüz oluşmadı.")

        with c_backup2:
            st.markdown("#### 2. Yedekten Geri Yükle")
            st.caption("Daha önce indirdiğiniz `.db` yedek dosyasını yükleyerek tüm verilerinizi geri getirin.")
            uploaded_db = st.file_uploader("Yedek Dosyasını Seçin (.db)", type=["db", "sqlite"])
            if uploaded_db is not None:
                if st.button("Verileri Geri Yükle", type="primary"):
                    with open(DB_FILE, "wb") as f:
                        f.write(uploaded_db.getbuffer())
                    st.success("✅ Tüm portföy verileriniz başarıyla geri yüklendi!")
                    st.rerun()

    with tab2:
        col_add, col_del = st.columns(2)
        with col_add:
            st.subheader("➕ Yeni Portföy Oluştur")
            p_name = st.text_input("Portföy Adı", placeholder="Örn: Temettü Portföyü")
            p_curr = st.selectbox("Para Birimi", ["USD", "EUR", "TRY"])
            if st.button("Portföyü Kaydet", type="primary"):
                if p_name.strip():
                    with get_connection() as conn:
                        conn.cursor().execute("INSERT INTO portfolios (name, currency) VALUES (?, ?)", (p_name.strip(), p_curr))
                        conn.commit()
                    st.success(f"{p_name} portföyü başarıyla oluşturuldu.")
                    st.rerun()

        with col_del:
            st.subheader("🗑️ Mevcut Portföyleri Sil")
            if portfolios_df.empty:
                st.info("Kayıtlı portföy bulunmuyor.")
            else:
                for _, p in portfolios_df.iterrows():
                    p_c1, p_c2 = st.columns([3, 1])
                    p_c1.write(f"📁 **{p['name']}** ({p['currency']})")
                    
                    if p_c2.button("Sil", key=f"del_port_{p['id']}"):
                        with get_connection() as conn:
                            cursor = conn.cursor()
                            cursor.execute("DELETE FROM lots WHERE portfolio_id = ?", (p['id'],))
                            cursor.execute("DELETE FROM sales WHERE portfolio_id = ?", (p['id'],))
                            cursor.execute("DELETE FROM portfolios WHERE id = ?", (p['id'],))
                            conn.commit()
                        st.success(f"{p['name']} portföyü silindi.")
                        st.rerun()

# --- 11. EXCEL RAPORU ---
elif menu == "📥 Excel Raporu":
    st.title("📥 Excel Raporu İndir")
    with get_connection() as conn:
        df_lots = pd.read_sql("SELECT * FROM lots", conn)
        df_sales = pd.read_sql("SELECT * FROM sales", conn)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_lots.to_excel(writer, sheet_name="Açık_Lotlar", index=False)
        if not df_sales.empty:
            df_sales.drop(columns=["allocations_json"], errors="ignore").to_excel(writer, sheet_name="Satış_Geçmişi", index=False)
    output.seek(0)

    st.download_button(
        label="📊 Excel Dosyasını İndir (.xlsx)",
        data=output,
        file_name=f"Portfoy_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
