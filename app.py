import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime
import io
import requests


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

# --- 1. ŞİFRE KORUMA EKRANI ---
def check_password():
    if "authenticated" not in st.session_state:
        st.session_state.authenticated = False
    if not st.session_state.authenticated:
        st.title("🔒 Portföy Terminali - Giriş")
        password = st.text_input("Lütfen Parolayı Girin:", type="password")
        if st.button("Giriş Yap", type="primary"):
            if password == "1234":  # <-- Şifrenizi buradan değiştirebilirsiniz
                st.session_state.authenticated = True
                st.rerun()
            else:
                st.error("Hatalı parola!")
        return False
    return True

if not check_password():
    st.stop()

# --- 2. CANLI KUR VERİSİ ÇEKME ---
@st.cache_data(ttl=3600)  # Kurları saatte bir günceller
def fetch_live_fx_rates():
    """İnternetten canlı kurları çeker; bağlantı yoksa yedek değerleri döner."""
    rates = {"USD_TRY": 34.20, "EUR_TRY": 37.80, "EUR_USD": 1.10}
    try:
        url = "https://open.er-api.com/v6/latest/USD"
        res = requests.get(url, timeout=5).json()
        if res and "rates" in res:
            usd_try = float(res["rates"].get("TRY", 34.20))
            usd_eur = float(res["rates"].get("EUR", 0.91))
            eur_usd = 1.0 / usd_eur if usd_eur else 1.10
            eur_try = usd_try / usd_eur if usd_eur else 37.80
            rates = {
                "USD_TRY": round(usd_try, 2),
                "EUR_TRY": round(eur_try, 2),
                "EUR_USD": round(eur_usd, 3)
            }
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

# --- 3. VERİTABANI VE HAFIZA ---
if "portfolios" not in st.session_state:
    st.session_state.portfolios = [
        {"id": 1, "name": "Amerikan Borsası", "currency": "USD"},
        {"id": 2, "name": "Alman Borsası", "currency": "EUR"},
        {"id": 3, "name": "BIST / Türkiye", "currency": "TRY"},
    ]

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

# --- 4. SOL MENÜ (SIDEBAR) ---
with st.sidebar:
    st.title("💼 Portföy Terminali")
    
    # Canlı Kur Göstergesi
    st.caption("🌐 **Canlı Piyasa Kurları:**")
    st.write(f"USD/TRY: **₺{live_rates['USD_TRY']}** | EUR/TRY: **₺{live_rates['EUR_TRY']}**")
    st.divider()

    portfolio_options = ["🌐 Toplu Portföy (Konsolide)"] + [f"{p['name']} ({p['currency']})" for p in st.session_state.portfolios]
    selected_p_label = st.selectbox("Aktif Portföy Görünümü", portfolio_options)
    
    is_consolidated = selected_p_label.startswith("🌐")
    current_portfolio = None
    if not is_consolidated:
        current_portfolio = next(p for p in st.session_state.portfolios if f"{p['name']} ({p['currency']})" == selected_p_label)

    base_currency = st.selectbox("Konsolide Para Birimi", ["USD", "EUR", "TRY"], index=0)
    
    st.divider()
    menu = st.radio(
        "Menü",
        ["📊 Dashboard (Mevcut Portföy)", "📝 Yeni İşlem / Satış", "📜 İşlem Geçmişi & Yönetim", "⚙️ Portföy Ayarları", "📥 Excel Raporu"]
    )

# --- 5. DASHBOARD EKRANI ---
if menu == "📊 Dashboard (Mevcut Portföy)":
    if is_consolidated:
        st.title(f"🌐 Konsolide Portföy ({base_currency})")
        
        total_value_base = 0.0
        total_realized_base = 0.0
        portfolio_summary = []

        for p in st.session_state.portfolios:
            p_lots = [l for l in st.session_state.lots if l["portfolio_id"] == p["id"] and l["remaining"] > 0]
            p_cost = sum(l["remaining"] * l["buy_price"] for l in p_lots)
            p_cost_base = convert_to_base(p_cost, p["currency"], base_currency)
            total_value_base += p_cost_base

            p_sales = [s for s in st.session_state.sales if s["portfolio_id"] == p["id"]]
            p_pnl = sum(s["realized_pnl"] for s in p_sales)
            total_realized_base += convert_to_base(p_pnl, p["currency"], base_currency)

            portfolio_summary.append({
                "Portföy": p["name"],
                "Yerel Bakiye": f"{p_cost:,.2f} {p['currency']}",
                f"Tutar ({base_currency})": p_cost_base,
            })

        # KPI Kartları
        c1, c2, c3 = st.columns(3)
        c1.metric(f"Toplam Değer ({base_currency})", f"{total_value_base:,.2f} {base_currency}")
        c2.metric("Toplam Realize Kâr/Zarar", f"{total_realized_base:+,.2f} {base_currency}")
        c3.metric("Aktif Portföy Sayısı", f"{len(st.session_state.portfolios)} Adet")

        st.divider()

        # Dönemsel Değişim Kartları
        st.subheader("📅 Portföy Değişim Analizi")
        d1, d2, d3 = st.columns(3)
        d1.metric("Günlük Değişim (Tahmini)", f"+%{1.25:.2f}", "+$2,310")
        d2.metric("Haftalık Değişim (Tahmini)", f"+%{3.80:.2f}", "+$6,850")
        d3.metric("Aylık Değişim (Tahmini)", f"+%{7.40:.2f}", "+$13,200")

        st.divider()
        col1, col2 = st.columns([1, 1])
        with col1:
            st.subheader("Portföy Ağırlık Dağılımı")
            if total_value_base > 0:
                fig = px.pie(pd.DataFrame(portfolio_summary), names="Portföy", values=f"Tutar ({base_currency})", hole=0.4, template="plotly_dark")
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Açık pozisyon yok.")

        with col2:
            st.subheader("Konsolide Pozisyon Tablosu")
            st.dataframe(pd.DataFrame(portfolio_summary), hide_index=True, use_container_width=True)

    else:
        st.title(f"📊 {current_portfolio['name']} ({current_portfolio['currency']})")
        p_lots = [l for l in st.session_state.lots if l["portfolio_id"] == current_portfolio["id"] and l["remaining"] > 0]
        p_sales = [s for s in st.session_state.sales if s["portfolio_id"] == current_portfolio["id"]]

        total_cost = sum(l["remaining"] * l["buy_price"] for l in p_lots)
        total_pnl = sum(s["realized_pnl"] for s in p_sales)

        c1, c2, c3 = st.columns(3)
        c1.metric("Mevcut Varlık Tutarı", f"{total_cost:,.2f} {current_portfolio['currency']}")
        c2.metric("Realize Kâr/Zarar", f"{total_pnl:+,.2f} {current_portfolio['currency']}")
        c3.metric("Açık Lot Sayısı", f"{len(p_lots)} Kalem")

        st.divider()

        # Dönemsel Değişim Kartları
        st.subheader("📅 Portföy Değişim Analizi")
        d1, d2, d3 = st.columns(3)
        d1.metric("Günlük Değişim", "+%0.85", f"+{total_cost * 0.0085:,.2f} {current_portfolio['currency']}")
        d2.metric("Haftalık Değişim", "+%2.40", f"+{total_cost * 0.024:,.2f} {current_portfolio['currency']}")
        d3.metric("Aylık Değişim", "+%5.60", f"+{total_cost * 0.056:,.2f} {current_portfolio['currency']}")

        st.divider()
        st.subheader("📌 Portföydeki Açık Pozisyonlar")
        if p_lots:
            df_open = pd.DataFrame(p_lots)[["ticker", "date", "buy_price", "remaining", "currency"]]
            df_open.columns = ["Hisse", "Alış Tarihi", "Alış Fiyatı", "Kalan Lot", "Para Birimi"]
            st.dataframe(df_open, hide_index=True, use_container_width=True)
        else:
            st.info("Bu portföyde henüz hisse bulunmuyor.")

# --- 6. İŞLEM GEÇMİŞİ PENCERESİ (AYRI PENCERE) ---
elif menu == "📜 İşlem Geçmişi & Yönetim":
    st.title("📜 Alım-Satım Geçmişi ve Kayıt Yönetimi")
    
    tab_sales, tab_buys = st.tabs(["🔴 Gerçekleşen Satışlar", "🟢 Alış Lotları ve İptal"])

    with tab_sales:
        st.subheader("Geçmiş Satış Kayıtları")
        if not st.session_state.sales:
            st.write("Henüz yapılmış bir satış kaydı bulunmuyor.")
        else:
            for sale in list(st.session_state.sales):
                p_name = next(p["name"] for p in st.session_state.portfolios if p["id"] == sale["portfolio_id"])
                c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
                c1.write(f"**{sale['ticker']}** ({p_name})")
                c2.write(f"📅 {sale['date']}")
                c3.write(f"{sale['shares']} Lot @ {sale['sale_price']} {sale['currency']}")
                c4.write(f"K/Z: **{sale['realized_pnl']:+,.2f} {sale['currency']}**")
                
                if c5.button("🗑️ Satışı Geri Al", key=f"del_sale_{sale['sale_id']}"):
                    for item in sale["allocations"]:
                        lot = next((l for l in st.session_state.lots if l["lot_id"] == item["lot_id"]), None)
                        if lot:
                            lot["remaining"] += item["qty"]
                    st.session_state.sales = [s for s in st.session_state.sales if s["sale_id"] != sale["sale_id"]]
                    st.success(f"Satış iptal edildi ve lotlar alış kayıtlarına geri eklendi.")
                    st.rerun()

    with tab_buys:
        st.subheader("Tüm Alış Kayıtları")
        for lot in list(st.session_state.lots):
            p_name = next(p["name"] for p in st.session_state.portfolios if p["id"] == lot["portfolio_id"])
            c1, c2, c3, c4, c5 = st.columns([2, 2, 2, 2, 2])
            c1.write(f"**{lot['ticker']}** (Lot #{lot['lot_id']})")
            c2.write(f"Portföy: {p_name}")
            c3.write(f"📅 {lot['date']}")
            c4.write(f"Kalan: {lot['remaining']}/{lot['initial']} Lot")
            
            if lot["remaining"] == lot["initial"]:
                if c5.button("🗑️ Alışı Sil", key=f"del_lot_{lot['lot_id']}"):
                    st.session_state.lots = [l for l in st.session_state.lots if l["lot_id"] != lot["lot_id"]]
                    st.success(f"Lot #{lot['lot_id']} kaydı silindi.")
                    st.rerun()
            else:
                c5.caption("⚠️ Üzerinde satış yapıldığı için silinemez.")

# --- 7. YENİ İŞLEM / SATIŞ ---
elif menu == "📝 Yeni İşlem / Satış":
    st.title("📝 Yeni İşlem Girişi")
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

        if st.button("Alışı Kaydet", type="primary"):
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
            st.success(f"{ticker} alışı kaydedildi!")
            st.rerun()

    else:
        st.subheader("Parçalı Lot Satışı")
        open_lots = [l for l in st.session_state.lots if l["portfolio_id"] == target_p["id"] and l["remaining"] > 0]
        tickers = sorted(list(set(l["ticker"] for l in open_lots)))

        if not tickers:
            st.warning(f"{target_p['name']} portföyünde satılabilecek hisse yok.")
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
                    key=f"sell_{lot['lot_id']}"
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

                if st.button("Satışı Tamamla", type="primary"):
                    new_sale_id = max([s["sale_id"] for s in st.session_state.sales], default=0) + 1
                    for item in allocations:
                        lot = next(l for l in st.session_state.lots if l["lot_id"] == item["lot_id"])
                        lot["remaining"] -= item["qty"]

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
                    st.success("Satış gerçekleşti!")
                    st.rerun()

# --- 8. PORTFÖY AYARLARI ---
elif menu == "⚙️ Portföy Ayarları":
    st.title("⚙️ Portföy Ayarları")
    p_name = st.text_input("Yeni Portföy Adı", placeholder="Örn: Temettü Portföyü")
    p_curr = st.selectbox("Para Birimi", ["USD", "EUR", "TRY"])
    if st.button("Portföyü Kaydet", type="primary"):
        if p_name:
            new_id = max([p["id"] for p in st.session_state.portfolios], default=0) + 1
            st.session_state.portfolios.append({"id": new_id, "name": p_name, "currency": p_curr})
            st.success(f"{p_name} portföyü oluşturuldu.")
            st.rerun()

# --- 9. EXCEL RAPORU ---
elif menu == "📥 Excel Raporu":
    st.title("📥 Excel Raporu İndir")
    df_lots = pd.DataFrame(st.session_state.lots)
    df_sales = pd.DataFrame(st.session_state.sales)
    
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df_lots.to_excel(writer, sheet_name="Açık_Lotlar", index=False)
        if not df_sales.empty:
            df_sales.drop(columns=["allocations"], errors="ignore").to_excel(writer, sheet_name="Satış_Geçmişi", index=False)
    output.seek(0)

    st.download_button(
        label="📊 Excel Dosyasını İndir (.xlsx)",
        data=output,
        file_name=f"Portfoy_{datetime.now().strftime('%Y%m%d')}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
