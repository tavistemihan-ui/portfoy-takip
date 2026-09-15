import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import io


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

# Koyu Finans Teması
st.markdown("""
<style>
    .metric-card { background-color: #161b22; border: 1px solid #30363d; border-radius: 8px; padding: 16px; }
    .stButton>button { border-radius: 6px; }
</style>
""", unsafe_allow_html=True)

# --- VERİTABANI & HAFIZA BAŞLATMA ---
if "portfolios" not in st.session_state:
    st.session_state.portfolios = [
        {"id": 1, "name": "Amerikan Borsası", "currency": "USD"},
        {"id": 2, "name": "Alman Borsası", "currency": "EUR"},
        {"id": 3, "name": "BIST / Türkiye", "currency": "TRY"},
    ]

# Döviz Kurları (Baz para birimi dönüşümleri için)
if "fx_rates" not in st.session_state:
    st.session_state.fx_rates = {
        "USD_TRY": 34.0,
        "EUR_TRY": 37.5,
        "EUR_USD": 1.10
    }

def convert_to_base(amount: float, from_curr: str, to_curr: str) -> float:
    if from_curr == to_curr:
        return amount
    rates = st.session_state.fx_rates
    # Önce TRY'ye çevir
    to_try = 1.0
    if from_curr == "USD":
        to_try = rates["USD_TRY"]
    elif from_curr == "EUR":
        to_try = rates["EUR_TRY"]
    amount_try = amount * to_try

    # TRY'den hedef para birimine çevir
    if to_curr == "TRY":
        return amount_try
    elif to_curr == "USD":
        return amount_try / rates["USD_TRY"]
    elif to_curr == "EUR":
        return amount_try / rates["EUR_TRY"]
    return amount

if "lots" not in st.session_state:
    st.session_state.lots = [
        {"lot_id": 1, "portfolio_id": 1, "ticker": "AAPL", "date": "2026-01-01", "buy_price": 200.0, "initial": 50, "remaining": 50, "currency": "USD"},
        {"lot_id": 2, "portfolio_id": 1, "ticker": "AAPL", "date": "2026-01-10", "buy_price": 210.0, "initial": 120, "remaining": 120, "currency": "USD"},
        {"lot_id": 3, "portfolio_id": 1, "ticker": "AAPL", "date": "2026-01-20", "buy_price": 190.0, "initial": 100, "remaining": 100, "currency": "USD"},
        {"lot_id": 4, "portfolio_id": 2, "ticker": "SAP", "date": "2026-02-01", "buy_price": 180.0, "initial": 40, "remaining": 40, "currency": "EUR"},
        {"lot_id": 5, "portfolio_id": 3, "ticker": "THYAO", "date": "2026-02-15", "buy_price": 290.0, "initial": 500, "remaining": 500, "currency": "TRY"},
    ]

if "sales" not in st.session_state:
    st.session_state.sales = []

# --- SOL MENÜ (SIDEBAR) ---
with st.sidebar:
    st.title("💼 Portföy Terminali")
    
    portfolio_options = ["🌐 Toplu Portföy (Konsolide)"] + [f"{p['name']} ({p['currency']})" for p in st.session_state.portfolios]
    selected_p_label = st.selectbox("Aktif Portföy Görünümü", portfolio_options)
    
    # Seçili portföyü belirle
    is_consolidated = selected_p_label.startswith("🌐")
    current_portfolio = None
    if not is_consolidated:
        current_portfolio = next(p for p in st.session_state.portfolios if f"{p['name']} ({p['currency']})" == selected_p_label)

    # Ortak Konsolide Para Birimi
    base_currency = st.selectbox("Konsolide Baz Para Birimi", ["USD", "EUR", "TRY"], index=0)
    
    st.divider()
    menu = st.radio("Menü", ["📊 Dashboard", "📝 Yeni İşlem / Satış", "🗑️ Geçmiş İşlemleri Yönet / Sil", "⚙️ Portföy Tanımları", "📥 Excel Raporu"])

# --- 1. DASHBOARD EKRANI ---
if menu == "📊 Dashboard":
    if is_consolidated:
        st.title(f"🌐 Toplu Konsolide Portföy ({base_currency})")
        st.caption(f"Tüm bağımsız portföyler güncel kurlar üzerinden **{base_currency}** bazında birleştirilmiştir.")
        
        # Konsolide Hesaplamalar
        total_value_base = 0.0
        total_pnl_base = 0.0
        portfolio_breakdown = []

        for p in st.session_state.portfolios:
            p_lots = [l for l in st.session_state.lots if l["portfolio_id"] == p["id"] and l["remaining"] > 0]
            p_cost = sum(l["remaining"] * l["buy_price"] for l in p_lots)
            p_cost_base = convert_to_base(p_cost, p["currency"], base_currency)
            total_value_base += p_cost_base

            p_sales = [s for s in st.session_state.sales if s["portfolio_id"] == p["id"]]
            p_pnl = sum(s["realized_pnl"] for s in p_sales)
            p_pnl_base = convert_to_base(p_pnl, p["currency"], base_currency)
            total_pnl_base += p_pnl_base

            portfolio_breakdown.append({
                "Portföy": p["name"],
                "Kendi Para Birimi": f"{p_cost:,.2f} {p['currency']}",
                f"Değer ({base_currency})": p_cost_base,
                f"Realize K/Z ({base_currency})": p_pnl_base
            })

        c1, c2, c3 = st.columns(3)
        c1.metric(f"Toplam Varlık Maliyeti ({base_currency})", f"{total_value_base:,.2f} {base_currency}")
        c2.metric(f"Toplam Realize Kâr/Zarar ({base_currency})", f"{total_pnl_base:+,.2f} {base_currency}")
        c3.metric("Tanımlı Portföy Sayısı", f"{len(st.session_state.portfolios)} Adet")

        st.divider()
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("Portföy Büyüklük Dağılımı")
            df_pie = pd.DataFrame(portfolio_breakdown)
            if total_value_base > 0:
                fig = px.pie(df_pie, names="Portföy", values=f"Değer ({base_currency})", hole=0.4, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Henüz açık pozisyon bulunmuyor.")

        with col2:
            st.subheader("Portföy Özet Tablosu")
            st.dataframe(pd.DataFrame(portfolio_breakdown), hide_index=True, use_container_width=True)

    else:
        st.title(f"📊 {current_portfolio['name']} ({current_portfolio['currency']})")
        p_lots = [l for l in st.session_state.lots if l["portfolio_id"] == current_portfolio["id"] and l["remaining"] > 0]
        p_sales = [s for s in st.session_state.sales if s["portfolio_id"] == current_portfolio["id"]]

        total_cost = sum(l["remaining"] * l["buy_price"] for l in p_lots)
        total_pnl = sum(s["realized_pnl"] for s in p_sales)

        c1, c2, c3 = st.columns(3)
        c1.metric("Açık Lot Maliyeti", f"{total_cost:,.2f} {current_portfolio['currency']}")
        c2.metric("Realize Kâr/Zarar", f"{total_pnl:+,.2f} {current_portfolio['currency']}")
        c3.metric("Açık Lot Adedi", f"{len(p_lots)} Kalem")

        st.divider()
        st.subheader("Açık Pozisyonlar")
        if p_lots:
            df_open = pd.DataFrame(p_lots)[["ticker", "date", "buy_price", "remaining", "currency"]]
            df_open.columns = ["Hisse", "Alış Tarihi", "Alış Fiyatı", "Kalan Lot", "Birim"]
            st.dataframe(df_open, hide_index=True, use_container_width=True)
        else:
            st.info("Bu portföyde henüz açık işlem yok.")

# --- 2. YENİ İŞLEM / SATIŞ ---
elif menu == "📝 Yeni İşlem / Satış":
    st.title("📝 İşlem Girişi")
    
    # Portföy seçimi
    target_p = st.selectbox("İşlem Yapılacak Portföy", st.session_state.portfolios, format_func=lambda x: f"{x['name']} ({x['currency']})")
    tx_type = st.radio("İşlem Türü", ["ALIŞ (Yeni Lot)", "SATIŞ (Parçalı Lot Satışı)"], horizontal=True)

    if tx_type.startswith("ALIŞ"):
        st.subheader("Yeni Alış Kaydı")
        c1, c2, c3, c4 = st.columns(4)
        with c1:
            ticker = st.text_input("Hisse Kodu (Ticker)", value="AAPL").upper()
        with c2:
            buy_date = st.date_input("Alış Tarihi", datetime.now())
        with c3:
            shares = st.number_input("Adet (Lot)", min_value=1.0, value=10.0, step=1.0)
        with c4:
            price = st.number_input(f"Alış Fiyatı ({target_p['currency']})", min_value=0.01, value=150.0, step=1.0)

        if st.button("Alış İşlemini Kaydet", type="primary"):
            new_lot_id = max([l["lot_id"] for l in st.session_state.lots], default=0) + 1
            st.session_state.lots.append({
                "lot_id": new_lot_id,
                "portfolio_id": target_p["id"],
                "ticker": ticker,
                "date": str(buy_date),
                "buy_price": price,
                "initial": shares,
                "remaining": shares,
                "currency": target_p["currency"]
            })
            st.success(f"{ticker} alışı {target_p['name']} portföyüne başarıyla kaydedildi!")
            st.rerun()

    else:
        st.subheader("Parçalı Lot Satışı")
        open_lots = [l for l in st.session_state.lots if l["portfolio_id"] == target_p["id"] and l["remaining"] > 0]
        tickers = sorted(list(set(l["ticker"] for l in open_lots)))

        if not tickers:
            st.warning(f"{target_p['name']} portföyünde satılabilecek açık hisse bulunmuyor.")
        else:
            selected_ticker = st.selectbox("Satılacak Hisseyi Seçin", tickers)
            sale_price = st.number_input(f"Satış Fiyatı ({target_p['currency']})", min_value=0.01, value=160.0, step=1.0)
            
            ticker_lots = [l for l in open_lots if l["ticker"] == selected_ticker]
            st.markdown("#### 🎯 Hangi Alıştan Satış Yapmak İstiyorsunuz?")
            
            allocations = []
            total_sell = 0.0
            total_cost = 0.0

            for lot in ticker_lots:
                c1, c2, c3, c4 = st.columns([2, 2, 2, 3])
                c1.write(f"📅 **{lot['date']}**")
                c2.write(f"Alış: **{lot['buy_price']} {lot['currency']}**")
                c3.write(f"Kalan: **{lot['remaining']} lot**")
                qty = c4.number_input(
                    f"Sat (Lot #{lot['lot_id']})",
                    min_value=0.0,
                    max_value=float(lot["remaining"]),
                    value=0.0,
                    step=1.0,
                    key=f"sell_lot_{lot['lot_id']}"
                )
                if qty > 0:
                    allocations.append({"lot_id": lot["lot_id"], "qty": qty, "buy_price": lot["buy_price"]})
                    total_sell += qty
                    total_cost += (qty * lot["buy_price"])

            if total_sell > 0:
                proceeds = total_sell * sale_price
                realized_pnl = proceeds - total_cost
                ret_pct = (realized_pnl / total_cost) * 100 if total_cost > 0 else 0

                st.divider()
                m1, m2, m3, m4 = st.columns(4)
                m1.metric("Satılacak Toplam Lot", f"{total_sell:.0f}")
                m2.metric("Toplam Alış Maliyeti", f"{total_cost:,.2f} {target_p['currency']}")
                m3.metric("Satış Geliri", f"{proceeds:,.2f} {target_p['currency']}")
                m4.metric("Realize Kâr/Zarar", f"{realized_pnl:+,.2f} {target_p['currency']}", delta=f"%{ret_pct:+.2f}")

                if st.button("Satışı Onayla ve Gerçekleştir", type="primary"):
                    new_sale_id = max([s["sale_id"] for s in st.session_state.sales], default=0) + 1
                    
                    # Lotları güncelle
                    for item in allocations:
                        lot = next(l for l in st.session_state.lots if l["lot_id"] == item["lot_id"])
                        lot["remaining"] -= item["qty"]

                    # Satış kaydını ekle (Hangi lottan ne kadar satıldığı hafızada tutulur)
                    st.session_state.sales.append({
                        "sale_id": new_sale_id,
                        "portfolio_id": target_p["id"],
                        "ticker": selected_ticker,
                        "date": datetime.now().strftime("%Y-%m-%d"),
                        "shares": total_sell,
                        "sale_price": sale_price,
                        "cost": total_cost,
                        "realized_pnl": realized_pnl,
                        "currency": target_p["currency"],
                        "allocations": allocations
                    })
                    st.success("Satış tamamlandı!")
                    st.rerun()

# --- 3. İŞLEM SİLME & GERİ ALMA ---
elif menu == "🗑️ Geçmiş İşlemleri Yönet / Sil":
    st.title("🗑️ Geçmiş İşlem Yönetimi ve Silme")
    st.info("💡 **Önemli Kural:** Bir satışı sildiğinizde sistem o satışın aldığı hisseleri ait olduğu alış lotuna eksiksiz geri iade eder.")

    tab_sales, tab_buys = st.tabs(["🔴 Satış İşlemlerini Geri Al / Sil", "🟢 Alış Lotlarını Sil"])

    with tab_sales:
        st.subheader("Geçmiş Satış Kayıtları")
        if not st.session_state.sales:
            st.write("Kayıtlı satış işlemi yok.")
        else:
            for sale in list(st.session_state.sales):
                p_name = next(p["name"] for p in st.session_state.portfolios if p["id"] == sale["portfolio_id"])
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
                c1.write(f"**{sale['ticker']}** ({p_name})")
                c2.write(f"📅 {sale['date']}")
                c3.write(f"{sale['shares']} Lot @ {sale['sale_price']} {sale['currency']}")
                c4.write(f"K/Z: **{sale['realized_pnl']:+,.2f} {sale['currency']}**")
                
                if c5.button("🗑️ Satışı Sil", key=f"del_sale_{sale['sale_id']}"):
                    # Lot iadesi yap
                    for item in sale["allocations"]:
                        lot = next((l for l in st.session_state.lots if l["lot_id"] == item["lot_id"]), None)
                        if lot:
                            lot["remaining"] += item["qty"]
                    # Satışı listeden kaldır
                    st.session_state.sales = [s for s in st.session_state.sales if s["sale_id"] != sale["sale_id"]]
                    st.success(f"{sale['ticker']} satışı silindi ve {sale['shares']} lot ait olduğu alışlara geri yüklendi.")
                    st.rerun()

    with tab_buys:
        st.subheader("Alış Lotları")
        st.caption("Yalnızca henüz üzerinde satış yapılmamış veya tamamı duran lotlar doğrudan silinebilir.")
        
        for lot in list(st.session_state.lots):
            p_name = next(p["name"] for p in st.session_state.portfolios if p["id"] == lot["portfolio_id"])
            c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
            c1.write(f"**{lot['ticker']}** (Lot #{lot['lot_id']})")
            c2.write(f"Portföy: {p_name}")
            c3.write(f"📅 {lot['date']}")
            c4.write(f"Kalan: {lot['remaining']}/{lot['initial']} Lot")
            
            # Eğer lottan satış yapılmışsa silme butonunu kilitle
            if lot["remaining"] == lot["initial"]:
                if c5.button("🗑️ Alışı Sil", key=f"del_lot_{lot['lot_id']}"):
                    st.session_state.lots = [l for l in st.session_state.lots if l["lot_id"] != lot["lot_id"]]
                    st.success(f"Lot #{lot['lot_id']} silindi.")
                    st.rerun()
            else:
                c5.caption("⚠️ Parçalı satıldığı için önce ilgili satışı silmelisiniz.")

# --- 4. PORTFÖY TANIMLARI & KURLAR ---
elif menu == "⚙️ Portföy Tanımları":
    st.title("⚙️ Bağımsız Portföy ve Kur Ayarları")
    
    col1, col2 = st.columns(2)
    with col1:
        st.subheader("Yeni Portföy Oluştur")
        p_name = st.text_input("Portföy Adı", placeholder="Örn: Temettü Portföyü")
        p_curr = st.selectbox("Portföy Para Birimi", ["USD", "EUR", "TRY"], key="new_p_curr")
        if st.button("Portföyü Ekle", type="primary"):
            if p_name:
                new_id = max([p["id"] for p in st.session_state.portfolios], default=0) + 1
                st.session_state.portfolios.append({"id": new_id, "name": p_name, "currency": p_curr})
                st.success(f"{p_name} portföyü oluşturuldu.")
                st.rerun()

    with col2:
        st.subheader("Döviz Kurları (Konsolide Dönüşüm İçin)")
        st.session_state.fx_rates["USD_TRY"] = st.number_input("USD / TRY", value=st.session_state.fx_rates["USD_TRY"], step=0.1)
        st.session_state.fx_rates["EUR_TRY"] = st.number_input("EUR / TRY", value=st.session_state.fx_rates["EUR_TRY"], step=0.1)
        st.session_state.fx_rates["EUR_USD"] = st.number_input("EUR / USD", value=st.session_state.fx_rates["EUR_USD"], step=0.01)

# --- 5. EXCEL RAPORU ---
elif menu == "📥 Excel Raporu":
    st.title("📥 Excel Raporu İndir")
    st.write("Tüm açık lotlarınızı ve gerçekleşen satışlarınızı tek bir Excel dosyasında indirin.")
    
    df_lots = pd.DataFrame(st.session_state.lots)
    df_sales = pd.DataFrame(st.session_state.sales)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_lots.to_excel(writer, sheet_name="Açık_Lotlar", index=False)
        if not df_sales.empty:
            df_sales.drop(columns=["allocations"], errors="ignore").to_excel(writer, sheet_name="Satışlar", index=False)
    output.seek(0)

    st.download_button(
        label="📊 Excel Dosyasını İndir (.xlsx)",
        data=output,
        file_name=f"Portfoy_Konsolide_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
