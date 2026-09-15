import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import io
import requests
import sqlite3


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

import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import io
import requests
import sqlite3

st.set_page_config(
    page_title="Portföy Terminal Pro",
    page_icon="💼",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Koyu Finans Teması
st.markdown("""
<style>
    .metric-card { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
    .stButton>button { border-radius: 6px; }
</style>
""", unsafe_allow_html=True)

# --- 1. VERİTABANI BAĞLANTISI (KALICI KAYIT) ---
DB_FILE = "portfolio_data.db"

def get_connection():
    return sqlite3.connect(DB_FILE, check_same_thread=False)

def init_db():
    with get_connection() as conn:
        c = conn.cursor()
        # Portföyler tablosu
        c.execute('''CREATE TABLE IF NOT EXISTS portfolios (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name TEXT NOT NULL,
                        currency TEXT NOT NULL)''')
        
        # Alış Lotları tablosu
        c.execute('''CREATE TABLE IF NOT EXISTS lots (
                        lot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        portfolio_id INTEGER,
                        ticker TEXT NOT NULL,
                        buy_date TEXT NOT NULL,
                        buy_price REAL NOT NULL,
                        initial_shares REAL NOT NULL,
                        remaining_shares REAL NOT NULL,
                        currency TEXT NOT NULL)''')
        
        # Satış Kayıtları tablosu
        c.execute('''CREATE TABLE IF NOT EXISTS sales (
                        sale_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        portfolio_id INTEGER,
                        ticker TEXT NOT NULL,
                        sale_date TEXT NOT NULL,
                        shares REAL NOT NULL,
                        sale_price REAL NOT NULL,
                        cost REAL NOT NULL,
                        realized_pnl REAL NOT NULL,
                        currency TEXT NOT NULL,
                        allocations_json TEXT)''')
        
        # İlk açılışta varsayılan portföyler yoksa ekle
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
            if password == "1234":  # <-- Şifreniz
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Hatalı parola!")
        return False
    return True

if not check_password():
    st.stop()

# --- 3. CANLI DÖVİZ KURLARI ---
@st.cache_data(ttl=3600)
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
        query = "SELECT * FROM lots WHERE remaining_shares > 0"
        if portfolio_id:
            query += f" AND portfolio_id = {portfolio_id}"
        return pd.read_sql(query, conn)

def load_sales(portfolio_id=None):
    with get_connection() as conn:
        query = "SELECT * FROM sales"
        if portfolio_id:
            query += f" AND portfolio_id = {portfolio_id}"
        return pd.read_sql(query, conn)

portfolios_df = load_portfolios()

# --- 5. KENAR ÇUBUĞU (SIDEBAR) ---
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
    menu = st.radio("Menü", ["📊 Dashboard", "📝 Yeni İşlem / Satış", "📜 İşlem Geçmişi & Yönetim", "⚙️ Portföy Ayarları", "📥 Excel Raporu"])

# --- 6. DASHBOARD ---
if menu == "📊 Dashboard":
    lots_df = load_open_lots()
    sales_df = load_sales()

    if is_consolidated:
        st.title(f"🌐 Konsolide Portföy ({base_currency})")
        
        total_val_base = 0.0
        total_pnl_base = 0.0
        summary = []

        for _, p in portfolios_df.iterrows():
            p_lots = lots_df[lots_df["portfolio_id"] == p["id"]]
            p_sales = sales_df[sales_df["portfolio_id"] == p["id"]]
            
            p_cost = (p_lots["remaining_shares"] * p_lots["buy_price"]).sum()
            p_cost_b = convert_to_base(p_cost, p["currency"], base_currency)
            total_val_base += p_cost_b

            p_pnl = p_sales["realized_pnl"].sum() if not p_sales.empty else 0.0
            total_pnl_base += convert_to_base(p_pnl, p["currency"], base_currency)

            summary.append({"Portföy": p["name"], "Bakiye": f"{p_cost:,.2f} {p['currency']}", f"Değer ({base_currency})": p_cost_b})

        c1, c2, c3 = st.columns(3)
        c1.metric(f"Toplam Değer ({base_currency})", f"{total_val_base:,.2f} {base_currency}")
        c2.metric("Toplam Realize K/Z", f"{total_pnl_base:+,.2f} {base_currency}")
        c3.metric("Portföy Sayısı", f"{len(portfolios_df)} Adet")
        
        st.divider()
        col1, col2 = st.columns(2)
        with col1:
            st.subheader("Varlık Dağılımı")
            if total_val_base > 0:
                fig = px.pie(pd.DataFrame(summary), names="Portföy", values=f"Değer ({base_currency})", hole=0.4, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Portföyde açık hisse yok.")
        with col2:
            st.subheader("Portföy Özeti")
            st.dataframe(pd.DataFrame(summary), hide_index=True, use_container_width=True)

    else:
        p_info = portfolios_df[portfolios_df["id"] == current_p_id].iloc[0]
        st.title(f"📊 {p_info['name']} ({p_info['currency']})")
        
        p_lots = lots_df[lots_df["portfolio_id"] == current_p_id]
        p_sales = sales_df[sales_df["portfolio_id"] == current_p_id]

        cost = (p_lots["remaining_shares"] * p_lots["buy_price"]).sum()
        pnl = p_sales["realized_pnl"].sum() if not p_sales.empty else 0.0

        c1, c2, c3 = st.columns(3)
        c1.metric("Açık Varlık Tutarı", f"{cost:,.2f} {p_info['currency']}")
        c2.metric("Realize Kâr/Zarar", f"{pnl:+,.2f} {p_info['currency']}")
        c3.metric("Açık Lot Kalemi", f"{len(p_lots)} Adet")

        st.divider()
        st.subheader("📌 Açık Pozisyonlar")
        if not p_lots.empty:
            out_df = p_lots[["ticker", "buy_date", "buy_price", "remaining_shares", "currency"]].copy()
            out_df.columns = ["Hisse", "Alış Tarihi", "Alış Fiyatı", "Kalan Lot", "Birim"]
            st.dataframe(out_df, hide_index=True, use_container_width=True)
        else:
            st.info("Bu portföyde henüz açık hisse bulunmuyor.")

# --- 7. YENİ İŞLEM / SATIŞ (DÜZELTİLEN BÖLÜM) ---
elif menu == "📝 Yeni İşlem / Satış":
    st.title("📝 İşlem Girişi")
    
    port_dict = {f"{r['name']} ({r['currency']})": (r['id'], r['currency']) for _, r in portfolios_df.iterrows()}
    chosen_label = st.selectbox("İşlem Yapılacak Portföy", list(port_dict.keys()))
    target_pid, target_pcurr = port_dict[chosen_label]

    tx_type = st.radio("İşlem Türü", ["ALIŞ (Yeni Lot Ekle)", "SATIŞ (Parçalı Lot Satışı)"], horizontal=True)

    if tx_type.startswith("ALIŞ"):
        st.subheader("Yeni Alış Kaydı")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            ticker_input = st.text_input("Hisse Kodu (Ticker)", value="AAPL").strip().upper()
        with c2:
            buy_date_input = st.date_input("Alış Tarihi", datetime.now())
        with c3:
            shares_input = st.number_input("Adet (Lot)", min_value=0.01, value=10.0, step=1.0)
        with c4:
            price_input = st.number_input(f"Alış Fiyatı ({target_pcurr})", min_value=0.01, value=150.0, step=1.0)

        if st.button("Alışı Kaydet", type="primary"):
            if ticker_input:
                with get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute('''INSERT INTO lots 
                                      (portfolio_id, ticker, buy_date, buy_price, initial_shares, remaining_shares, currency) 
                                      VALUES (?, ?, ?, ?, ?, ?, ?)''',
                                   (target_pid, ticker_input, str(buy_date_input), price_input, shares_input, shares_input, target_pcurr))
                    conn.commit()
                st.success(f"{ticker_input} ({shares_input} lot) veritabanına başarıyla kaydedildi!")
                st.rerun()
            else:
                st.error("Lütfen bir hisse kodu girin.")

    else:
        st.subheader("Parçalı Lot Satışı")
        open_lots_p = load_open_lots(target_pid)

        if open_lots_p.empty:
            st.warning("Bu portföyde satılabilecek hisse bulunmuyor.")
        else:
            available_tickers = sorted(open_lots_p["ticker"].unique())
            sel_ticker = st.selectbox("Satılacak Hisseyi Seçin", available_tickers)
            sale_price = st.number_input(f"Satış Fiyatı ({target_pcurr})", min_value=0.01, value=160.0, step=1.0)

            ticker_lots = open_lots_p[open_lots_p["ticker"] == sel_ticker]
            st.markdown("#### 🎯 Hangi Alıştan Satış Yapmak İstiyorsunuz?")

            allocations = []
            total_sold = 0.0
            total_cost = 0.0

            for _, lot in ticker_lots.iterrows():
                c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
                c1.write(f"📅 **{lot['buy_date']}**")
                c2.write(f"Alış: **{lot['buy_price']} {lot['currency']}**")
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
                realized_pnl = proceeds - total_cost
                ret_pct = (realized_pnl / total_cost) * 100 if total_cost > 0 else 0

                st.divider()
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Satılacak Toplam Lot", f"{total_sold:.0f}")
                m2.metric("Toplam Alış Maliyeti", f"{total_cost:,.2f} {target_pcurr}")
                m3.metric("Satış Geliri", f"{proceeds:,.2f} {target_pcurr}")
                m4.metric("Realize Kâr/Zarar", f"{realized_pnl:+,.2f} {target_pcurr}", delta=f"%{ret_pct:+.2f}")

                if st.button("Satışı Onayla ve Tamamla", type="primary"):
                    import json
                    with get_connection() as conn:
                        cursor = conn.cursor()
                        # Lot bakiyelerini güncelle
                        for alloc in allocations:
                            cursor.execute("UPDATE lots SET remaining_shares = remaining_shares - ? WHERE lot_id = ?",
                                           (alloc["qty"], alloc["lot_id"]))
                        # Satış kaydını ekle
                        cursor.execute('''INSERT INTO sales 
                                          (portfolio_id, ticker, sale_date, shares, sale_price, cost, realized_pnl, currency, allocations_json) 
                                          VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)''',
                                       (target_pid, sel_ticker, datetime.now().strftime("%Y-%m-%d"), total_sold, sale_price, total_cost, realized_pnl, target_pcurr, json.dumps(allocations)))
                        conn.commit()
                    st.success("Satış veritabanına işlendi!")
                    st.rerun()

# --- 8. İŞLEM GEÇMİŞİ VE SİLME ---
elif menu == "📜 İşlem Geçmişi & Yönetim":
    st.title("📜 İşlem Geçmişi ve Kayıt Yönetimi")
    tab_sales, tab_buys = st.tabs(["🔴 Gerçekleşen Satışlar", "🟢 Tüm Alış Lotları"])

    with tab_sales:
        sales_df = load_sales()
        if sales_df.empty:
            st.info("Kayıtlı satış bulunamadı.")
        else:
            import json
            for _, sale in sales_df.iterrows():
                p_row = portfolios_df[portfolios_df["id"] == sale["portfolio_id"]]
                p_name = p_row.iloc[0]["name"] if not p_row.empty else "Bilinmeyen"
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
                c1.write(f"**{sale['ticker']}** ({p_name})")
                c2.write(f"📅 {sale['sale_date']}")
                c3.write(f"{sale['shares']} Lot @ {sale['sale_price']} {sale['currency']}")
                c4.write(f"K/Z: **{sale['realized_pnl']:+,.2f} {sale['currency']}**")
                
                if c5.button("🗑️ Satışı Geri Al", key=f"del_sale_{sale['sale_id']}"):
                    allocs = json.loads(sale["allocations_json"])
                    with get_connection() as conn:
                        cursor = conn.cursor()
                        # Lotları geri iade et
                        for item in allocs:
                            cursor.execute("UPDATE lots SET remaining_shares = remaining_shares + ? WHERE lot_id = ?",
                                           (item["qty"], item["lot_id"]))
                        cursor.execute("DELETE FROM sales WHERE sale_id = ?", (sale["sale_id"],))
                        conn.commit()
                    st.success("Satış iptal edildi, lotlar iade edildi.")
                    st.rerun()

    with tab_buys:
        with get_connection() as conn:
            all_lots = pd.read_sql("SELECT * FROM lots", conn)
        if all_lots.empty:
            st.info("Kayıtlı alış bulunmuyor.")
        else:
            for _, lot in all_lots.iterrows():
                p_row = portfolios_df[portfolios_df["id"] == lot["portfolio_id"]]
                p_name = p_row.iloc[0]["name"] if not p_row.empty else "Bilinmeyen"
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
                c1.write(f"**{lot['ticker']}** (Lot #{lot['lot_id']})")
                c2.write(f"Portföy: {p_name}")
                c3.write(f"📅 {lot['buy_date']}")
                c4.write(f"Kalan: {lot['remaining_shares']}/{lot['initial_shares']} Lot")
                
                if lot["remaining_shares"] == lot["initial_shares"]:
                    if c5.button("🗑️ Alışı Sil", key=f"del_lot_{lot['lot_id']}"):
                        with get_connection() as conn:
                            conn.cursor().execute("DELETE FROM lots WHERE lot_id = ?", (lot["lot_id"],))
                            conn.commit()
                        st.success("Alış lotu silindi.")
                        st.rerun()
                else:
                    c5.caption("⚠️ Üzerinde satış yapıldığı için silinemez.")

# --- 9. PORTFÖY AYARLARI ---
elif menu == "⚙️ Portföy Ayarları":
    st.title("⚙️ Portföy Tanımları")
    p_name = st.text_input("Portföy Adı", placeholder="Örn: Büyüme Hisseleri")
    p_curr = st.selectbox("Para Birimi", ["USD", "EUR", "TRY"])
    if st.button("Yeni Portföy Oluştur", type="primary"):
        if p_name.strip():
            with get_connection() as conn:
                conn.cursor().execute("INSERT INTO portfolios (name, currency) VALUES (?, ?)", (p_name.strip(), p_curr))
                conn.commit()
            st.success(f"{p_name} portföyü oluşturuldu.")
            st.rerun()

# --- 10. EXCEL RAPORU ---
elif menu == "📥 Excel Raporu":
    st.title("📥 Excel Raporu İndir")
    with get_connection() as conn:
        df_lots = pd.read_sql("SELECT * FROM lots", conn)
        df_sales = pd.read_sql("SELECT * FROM sales", conn)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_lots.to_excel(writer, sheet_name="Lotlar", index=False)
        if not df_sales.empty:
            df_sales.drop(columns=["allocations_json"], errors="ignore").to_excel(writer, sheet_name="Satışlar", index=False)
    output.seek(0)

    st.download_button(
        label="📊 Excel Dosyasını İndir (.xlsx)",
        data=output,
        file_name=f"Portfoy_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
