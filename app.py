import os
import io
import json
import sqlite3
import requests
from datetime import datetime
import streamlit as st
import pandas as pd
import plotly.express as px
import yfinance as yf

# PostgreSQL desteği (Neon DB)
try:
    import psycopg2
    PG_AVAILABLE = True
except ImportError:
    PG_AVAILABLE = False

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

# --- 1. VERİTABANI BAĞLANTISI (BULUT NEON VEYA YEREL SQLITE) ---
DATABASE_URL = None
if "DATABASE_URL" in st.secrets:
    DATABASE_URL = st.secrets["DATABASE_URL"]
elif "DATABASE_URL" in os.environ:
    DATABASE_URL = os.environ["DATABASE_URL"]

IS_POSTGRES = DATABASE_URL is not None and DATABASE_URL.startswith("postgres") and PG_AVAILABLE

def get_connection():
    if IS_POSTGRES:
        clean_url = DATABASE_URL.replace("&channel_binding=require", "").replace("?channel_binding=require", "")
        return psycopg2.connect(clean_url)
    return sqlite3.connect("portfolio_data.db", check_same_thread=False)

def init_db():
    conn = get_connection()
    c = conn.cursor()
    if IS_POSTGRES:
        c.execute('''CREATE TABLE IF NOT EXISTS portfolios (
                        id SERIAL PRIMARY KEY,
                        name TEXT NOT NULL,
                        currency TEXT NOT NULL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS lots (
                        lot_id SERIAL PRIMARY KEY,
                        portfolio_id INTEGER,
                        ticker TEXT NOT NULL,
                        buy_date TEXT NOT NULL,
                        buy_price DOUBLE PRECISION NOT NULL,
                        initial_shares DOUBLE PRECISION NOT NULL,
                        remaining_shares DOUBLE PRECISION NOT NULL,
                        currency TEXT NOT NULL,
                        commission DOUBLE PRECISION DEFAULT 0.0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS sales (
                        sale_id SERIAL PRIMARY KEY,
                        portfolio_id INTEGER,
                        ticker TEXT NOT NULL,
                        sale_date TEXT NOT NULL,
                        shares DOUBLE PRECISION NOT NULL,
                        sale_price DOUBLE PRECISION NOT NULL,
                        cost DOUBLE PRECISION NOT NULL,
                        commission DOUBLE PRECISION DEFAULT 0.0,
                        realized_pnl DOUBLE PRECISION NOT NULL,
                        currency TEXT NOT NULL,
                        current_price DOUBLE PRECISION DEFAULT NULL,
                        allocations_json TEXT)''')
        conn.commit()
        c.execute("SELECT COUNT(*) FROM portfolios")
        if c.fetchone()[0] == 0:
            c.executemany("INSERT INTO portfolios (name, currency) VALUES (%s, %s)", [
                ("Amerikan Borsası", "USD"),
                ("Alman Borsası", "EUR"),
                ("BIST / Türkiye", "TRY")
            ])
            conn.commit()
    else:
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
    c.close()
    conn.close()

init_db()

# --- 2. DÖVİZ KURLARI & OPTİMİZE EDİLMİŞ CANLI VERİ ÇEKİMİ ---
@st.cache_data(ttl=3600)
def fetch_live_fx_rates():
    rates = {"USD_TRY": 34.20, "EUR_TRY": 37.80, "EUR_USD": 1.10}
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        res = requests.get(url, timeout=3).json()
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

@st.cache_data(ttl=600)
def get_batch_market_data(tickers_tuple):
    """Tüm hisselerin fiyat ve dönemsel verilerini tek seferde topluca çeker (Çok Hızlıdır)."""
    result = {}
    if not tickers_tuple:
        return result

    ticker_str = " ".join([t.strip().upper() for t in tickers_tuple])
    try:
        # Son 1 yıllık verileri tek seferde indirir
        data = yf.download(ticker_str, period="1y", interval="1d", group_by="ticker", threads=True, progress=False)
        
        for sym in tickers_tuple:
            sym_clean = sym.strip().upper()
            sub_df = data[sym_clean] if len(tickers_tuple) > 1 else data

            if not sub_df.empty and "Close" in sub_df:
                closes = sub_df["Close"].dropna()
                if len(closes) >= 2:
                    current_p = round(float(closes.iloc[-1]), 2)
                    
                    def get_p_ret(offset):
                        if len(closes) > offset:
                            past = float(closes.iloc[-1 - offset])
                            return round(((current_p - past) / past) * 100, 2)
                        return 0.0

                    result[sym_clean] = {
                        "price": current_p,
                        "1D": get_p_ret(1),
                        "1W": get_p_ret(5),
                        "1M": get_p_ret(21),
                        "6M": get_p_ret(126),
                        "1Y": get_p_ret(250),
                        "5Y": 0.0,
                        "sector": "Genel"
                    }
    except Exception:
        pass

    # Eksik kalan hisseler için basit fallback
    for sym in tickers_tuple:
        sym_clean = sym.strip().upper()
        if sym_clean not in result:
            result[sym_clean] = {
                "price": 0.0, "1D": 0.0, "1W": 0.0, "1M": 0.0, "6M": 0.0, "1Y": 0.0, "5Y": 0.0, "sector": "Genel"
            }
    return result

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

# --- 3. VERİ ÇEKME YARDIMCILARI ---
def load_portfolios():
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM portfolios ORDER BY id", conn)
    conn.close()
    return df

def load_open_lots(portfolio_id=None):
    conn = get_connection()
    q = "SELECT * FROM lots WHERE remaining_shares > 0"
    if portfolio_id:
        q += f" AND portfolio_id = {portfolio_id}"
    df = pd.read_sql(q, conn)
    conn.close()
    return df

def load_sales(portfolio_id=None):
    conn = get_connection()
    q = "SELECT * FROM sales ORDER BY sale_id DESC"
    if portfolio_id:
        q += f" AND portfolio_id = {portfolio_id}"
    df = pd.read_sql(q, conn)
    conn.close()
    return df

portfolios_df = load_portfolios()

if "edit_lot_id" not in st.session_state:
    st.session_state.edit_lot_id = None
if "edit_sale_id" not in st.session_state:
    st.session_state.edit_sale_id = None

# --- 4. KENAR ÇUBUĞU ---
with st.sidebar:
    st.title("💼 Portföy Terminali")
    
    if IS_POSTGRES:
        st.success("🟢 Bulut Veritabanı Bağlı (Neon)")
    else:
        st.warning("🟠 Yerel SQLite Veritabanı")

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
            "⚙️ Portföy Ayarları",
            "📥 Excel Raporu"
        ]
    )

# --- 5. DASHBOARD ---
if menu == "📊 Dashboard (Canlı Fiyatlı)":
    lots_df = load_open_lots()
    sales_df = load_sales()

    # Açık olan tüm hisseleri topluca tek ağ isteğiyle çek
    all_open_tickers = tuple(sorted(lots_df["ticker"].unique())) if not lots_df.empty else ()
    market_cache = get_batch_market_data(all_open_tickers)

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
                m_info = market_cache.get(lot["ticker"].strip().upper(), {})
                cur_p = m_info.get("price", 0.0) or lot["buy_price"]
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
            sym = lot["ticker"].strip().upper()
            m_info = market_cache.get(sym, {})
            effective_price = m_info.get("price", 0.0) or lot["buy_price"]
            
            market_val = lot["remaining_shares"] * effective_price
            cost_val = lot["remaining_shares"] * lot["buy_price"]
            pnl_val = market_val - cost_val
            pnl_pct = (pnl_val / cost_val * 100) if cost_val > 0 else 0.0
            total_market_val += market_val

            lot_details.append({
                "Hisse": sym,
                "Sektör": m_info.get("sector", "Genel"),
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
            st.subheader("📊 Açık Hisselerin Dönemsel Getiri Performansı")

            period_rows = []
            for sym in sorted(df_lots_full["Hisse"].unique()):
                m_info = market_cache.get(sym, {})
                period_rows.append({
                    "Hisse": sym,
                    "Şimdiki Fiyat": format_curr(m_info.get("price", 0.0), p_info['currency']),
                    "1 Günlük": m_info.get("1D", 0.0),
                    "1 Haftalık": m_info.get("1W", 0.0),
                    "1 Aylık": m_info.get("1M", 0.0),
                    "6 Aylık": m_info.get("6M", 0.0),
                    "1 Yıllık": m_info.get("1Y", 0.0)
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
                        if col in ["1 Günlük", "1 Haftalık", "1 Aylık", "6 Aylık", "1 Yıllık"]:
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

# --- 6. YENİ İŞLEM / SATIŞ ---
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
                conn = get_connection()
                cursor = conn.cursor()
                p = "%s" if IS_POSTGRES else "?"
                cursor.execute(f'''INSERT INTO lots 
                                  (portfolio_id, ticker, buy_date, buy_price, initial_shares, remaining_shares, currency, commission) 
                                  VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})''',
                               (target_pid, ticker_input, str(buy_date_input), price_input, shares_input, shares_input, target_pcurr, comm_input))
                conn.commit()
                cursor.close()
                conn.close()
                st.cache_data.clear()
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
                    conn = get_connection()
                    cursor = conn.cursor()
                    p = "%s" if IS_POSTGRES else "?"
                    for alloc in allocations:
                        cursor.execute(f"UPDATE lots SET remaining_shares = remaining_shares - {p} WHERE lot_id = {p}",
                                       (alloc["qty"], alloc["lot_id"]))
                    cursor.execute(f'''INSERT INTO sales 
                                      (portfolio_id, ticker, sale_date, shares, sale_price, cost, commission, realized_pnl, currency, current_price, allocations_json) 
                                      VALUES ({p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p}, {p})''',
                                   (target_pid, sel_ticker, datetime.now().strftime("%Y-%m-%d"), total_sold, sale_price, total_cost, sale_comm, realized_pnl, target_pcurr, sale_price, json.dumps(allocations)))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    st.cache_data.clear()
                    st.success("Satış tamamlandı!")
                    st.rerun()

# --- 7. SATIŞ SONRASI PERFORMANS (CANLI) ---
elif menu == "🎯 Satış Sonrası Performans (Canlı)":
    st.title("🎯 Satış Sonrası Canlı Fiyat & Karar Analizi")
    st.caption("Alış, satış ve güncel piyasa fiyatı arasındaki tüm farklar canlı karşılaştırılır.")

    sales_df = load_sales()
    if sales_df.empty:
        st.info("Henüz gerçekleştirilmiş satış işlemi bulunmuyor.")
    else:
        sale_tickers = tuple(sorted(sales_df["ticker"].unique()))
        market_cache = get_batch_market_data(sale_tickers)

        if st.button("🔄 Canlı Fiyatları Güncelle"):
            st.cache_data.clear()
            st.rerun()

        for idx, sale in sales_df.iterrows():
            with st.container():
                st.markdown(f"### 📌 {sale['ticker']} Satışı (#{sale['sale_id']}) - {sale['sale_date']}")
                
                avg_buy_price = (sale["cost"] / sale["shares"]) if sale["shares"] > 0 else 0.0
                sym = sale['ticker'].strip().upper()
                live_price = market_cache.get(sym, {}).get("price", 0.0)
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

# --- 8. GEÇMİŞ İŞLEM YÖNETİMİ & DÜZELTME ---
elif menu == "✏️ Geçmiş İşlem Yönetimi & Düzeltme":
    st.title("✏️ İşlem Düzeltme, Güncelleme ve Silme")
    tab_buys, tab_sales = st.tabs(["🟢 Alış Lotlarını Düzelt / Sil", "🔴 Satış Kayıtlarını Düzelt / Geri Al"])

    p = "%s" if IS_POSTGRES else "?"

    with tab_buys:
        conn = get_connection()
        all_lots = pd.read_sql("SELECT * FROM lots ORDER BY lot_id", conn)
        conn.close()

        if all_lots.empty:
            st.info("Kayıtlı alış bulunmuyor.")
        else:
            if st.session_state.edit_lot_id:
                lot_to_edit = all_lots[all_lots["lot_id"] == st.session_state.edit_lot_id].iloc[0]
                st.warning(f"🛠️ Lot #{lot_to_edit['lot_id']} ({lot_to_edit['ticker']}) Düzenleniyor")
                
                with st.form("edit_lot_form"):
                    e_c1, e_c2, e_c3 = st.columns(3)
                    new_ticker = e_c1.text_input("Ticker", value=lot_to_edit["ticker"]).upper()
                    new_date = e_c2.date_input("Tarih", datetime.strptime(str(lot_to_edit["buy_date"]), "%Y-%m-%d"))
                    new_price = e_c3.number_input("Alış Fiyatı", value=float(lot_to_edit["buy_price"]), min_value=0.01)

                    e_c4, e_c5 = st.columns(2)
                    is_sold = lot_to_edit["remaining_shares"] != lot_to_edit["initial_shares"]
                    new_shares = e_c4.number_input("Lot Adedi", value=float(lot_to_edit["initial_shares"]), disabled=is_sold)
                    new_comm = e_c5.number_input("Komisyon", value=float(lot_to_edit["commission"]), min_value=0.0)

                    f_b1, f_b2 = st.columns([1, 4])
                    save_edit = f_b1.form_submit_button("Kaydet", type="primary")
                    cancel_edit = f_b2.form_submit_button("İptal")

                    if save_edit:
                        conn = get_connection()
                        cursor = conn.cursor()
                        rem_shares = new_shares if not is_sold else lot_to_edit["remaining_shares"]
                        cursor.execute(f'''UPDATE lots SET ticker = {p}, buy_date = {p}, buy_price = {p}, initial_shares = {p}, remaining_shares = {p}, commission = {p} 
                                          WHERE lot_id = {p}''',
                                       (new_ticker, str(new_date), new_price, new_shares, rem_shares, new_comm, int(lot_to_edit["lot_id"])))
                        conn.commit()
                        cursor.close()
                        conn.close()
                        st.session_state.edit_lot_id = None
                        st.cache_data.clear()
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
                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute(f"DELETE FROM lots WHERE lot_id = {p}", (int(lot["lot_id"]),))
                        conn.commit()
                        cursor.close()
                        conn.close()
                        st.cache_data.clear()
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
                    new_s_date = s_c1.date_input("Satış Tarihi", datetime.strptime(str(sale_to_edit["sale_date"]), "%Y-%m-%d"))
                    new_s_price = s_c2.number_input("Satış Fiyatı", value=float(sale_to_edit["sale_price"]), min_value=0.01)
                    new_s_comm = s_c3.number_input("Komisyon", value=float(sale_to_edit["commission"]), min_value=0.0)

                    s_b1, s_b2 = st.columns([1, 4])
                    save_s_edit = s_b1.form_submit_button("Kaydet", type="primary")
                    cancel_s_edit = s_b2.form_submit_button("İptal")

                    if save_s_edit:
                        new_proceeds = sale_to_edit["shares"] * new_s_price
                        new_pnl = (new_proceeds - sale_to_edit["cost"]) - new_s_comm

                        conn = get_connection()
                        cursor = conn.cursor()
                        cursor.execute(f'''UPDATE sales SET sale_date = {p}, sale_price = {p}, commission = {p}, realized_pnl = {p} 
                                           WHERE sale_id = {p}''',
                                        (str(new_s_date), new_s_price, new_s_comm, new_pnl, int(sale_to_edit["sale_id"])))
                        conn.commit()
                        cursor.close()
                        conn.close()
                        st.session_state.edit_sale_id = None
                        st.cache_data.clear()
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
                    conn = get_connection()
                    cursor = conn.cursor()
                    for item in allocs:
                        cursor.execute(f"UPDATE lots SET remaining_shares = remaining_shares + {p} WHERE lot_id = {p}",
                                       (item["qty"], item["lot_id"]))
                    cursor.execute(f"DELETE FROM sales WHERE sale_id = {p}", (int(sale["sale_id"]),))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    st.cache_data.clear()
                    st.success("Satış geri alındı ve lotlar iade edildi.")
                    st.rerun()

# --- 9. PORTFÖY AYARLARI ---
elif menu == "⚙️ Portföy Ayarları":
    st.title("⚙️ Portföy Tanımları ve Yönetimi")
    
    if IS_POSTGRES:
        st.success("☁️ Verileriniz güvenli bulut veritabanında (Neon PostgreSQL) tutulmaktadır. Yedek almaya gerek yoktur.")
    
    p = "%s" if IS_POSTGRES else "?"

    col_add, col_del = st.columns(2)
    with col_add:
        st.subheader("➕ Yeni Portföy Oluştur")
        p_name = st.text_input("Portföy Adı", placeholder="Örn: Temettü Portföyü")
        p_curr = st.selectbox("Para Birimi", ["USD", "EUR", "TRY"])
        if st.button("Portföyü Kaydet", type="primary"):
            if p_name.strip():
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(f"INSERT INTO portfolios (name, currency) VALUES ({p}, {p})", (p_name.strip(), p_curr))
                conn.commit()
                cursor.close()
                conn.close()
                st.success(f"{p_name} portföyü başarıyla oluşturuldu.")
                st.rerun()

    with col_del:
        st.subheader("🗑️ Mevcut Portföyleri Sil")
        if portfolios_df.empty:
            st.info("Kayıtlı portföy bulunmuyor.")
        else:
            for _, p_row in portfolios_df.iterrows():
                p_c1, p_c2 = st.columns([3, 1])
                p_c1.write(f"📁 **{p_row['name']}** ({p_row['currency']})")
                
                if p_c2.button("Sil", key=f"del_port_{p_row['id']}"):
                    conn = get_connection()
                    cursor = conn.cursor()
                    cursor.execute(f"DELETE FROM lots WHERE portfolio_id = {p}", (int(p_row['id']),))
                    cursor.execute(f"DELETE FROM sales WHERE portfolio_id = {p}", (p_row['id'],))
                    cursor.execute(f"DELETE FROM portfolios WHERE id = {p}", (int(p_row['id']),))
                    conn.commit()
                    cursor.close()
                    conn.close()
                    st.success(f"{p_row['name']} portföyü silindi.")
                    st.rerun()

# --- 10. EXCEL RAPORU ---
elif menu == "📥 Excel Raporu":
    st.title("📥 Excel Raporu İndir")
    conn = get_connection()
    df_lots = pd.read_sql("SELECT * FROM lots", conn)
    df_sales = pd.read_sql("SELECT * FROM sales", conn)
    conn.close()
    
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
