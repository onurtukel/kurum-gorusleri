import streamlit as st
import google.generativeai as genai
import kml2geojson
import requests  # pyairtable yerine daha güvenli olan requests'e geçtik
import json
import os
import tempfile
import PyPDF2
import folium
from streamlit_folium import st_folium

# --- SAYFA AYARLARI ---
st.set_page_config(page_title="Kurum Görüşü Analiz Sistemi", page_icon="🗺️", layout="wide")
st.title("🗺️ Kurum Görüşü ve Kısıt Analizi Paneli")
st.markdown("Resmi kurum yazılarını (PDF) ve mekansal verileri (KML) yükleyerek yapay zeka destekli analiz gerçekleştirin.")

# --- GÜVENLİ ŞİFRE ÇEKİMİ (Streamlit Secrets) ---
try:
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
    AIRTABLE_TOKEN = st.secrets["AIRTABLE_TOKEN"]
    AIRTABLE_BASE_ID = st.secrets["AIRTABLE_BASE_ID"]
    
    genai.configure(api_key=GEMINI_API_KEY)
    
    # Dinamik model seçimi
    available_models = [m.name for m in genai.list_models() if 'generateContent' in m.supported_generation_methods]
    secilen_model = next((m for m in available_models if 'flash' in m), available_models[0])
    model = genai.GenerativeModel(secilen_model)
except Exception as e:
    st.error("API Anahtarları bulunamadı. Lütfen Streamlit Secrets ayarlarını kontrol edin.")
    st.stop()

# --- YARDIMCI FONKSİYONLAR ---
def pdf_metin_cikar(pdf_dosyasi):
    pdf_okuyucu = PyPDF2.PdfReader(pdf_dosyasi)
    metin = ""
    for sayfa in pdf_okuyucu.pages:
        metin += sayfa.extract_text() + "\n"
    return metin

def metni_analiz_et(metin):
    prompt = """
    Aşağıdaki resmi kurum görüşü metnini bir şehir plancısı titizliğiyle analiz et. 
    Lütfen SADECE aşağıdaki JSON formatında cevap ver.
    {
      "kurum_adi": "Kurum adı",
      "evrak_no": "Sayı veya evrak numarası",
      "gorus_durumu": "'Olumlu', 'Kısıtlı' veya 'Olumsuz'",
      "yapilasma_kisitlari": "Kısıtları özetle veya 'Bulunmamaktadır' yaz."
    }
    Metin: """ + metin
    
    response = model.generate_content(prompt)
    temiz_metin = response.text.replace("```json", "").replace("```", "").strip()
    return json.loads(temiz_metin)

def airtable_kaydet(ai_verisi, kml_var_mi):
    # Tablo adını URL formatına uygun hale getiriyoruz
    url = f"https://api.airtable.com/v0/{AIRTABLE_BASE_ID}/Kurum%20G%C3%B6r%C3%BC%C5%9Fleri"
    headers = {
        "Authorization": f"Bearer {AIRTABLE_TOKEN}",
        "Content-Type": "application/json"
    }
    
    yeni_kayit = {
        "fields": {
            "Kurum Adı": ai_verisi.get("kurum_adi", ""),
            "Evrak No": ai_verisi.get("evrak_no", ""),
            "Görüş Durumu": ai_verisi.get("gorus_durumu", ""),
            "Yapılaşma Kısıtları": ai_verisi.get("yapilasma_kisitlari", ""),
            "Mekansal Veri Durumu": kml_var_mi
        }
    }
    
    response = requests.post(url, headers=headers, json=yeni_kayit)
    
    # Airtable'dan gelen gerçek hatayı yakala ve ekrana yansıt
    if response.status_code != 200:
        hata_mesaji = response.json()
        raise Exception(f"Airtable Hatası: {json.dumps(hata_mesaji, ensure_ascii=False)}")
    
    return response.json()

# --- ARAYÜZ (UI) ---
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📎 Belge Yükleme")
    yuklenen_pdf = st.file_uploader("Kurum Yazısı (PDF)", type=["pdf"])
    yuklenen_kml = st.file_uploader("Mekansal Veri (KML - Opsiyonel)", type=["kml"])
    
    islem_baslat = st.button("🚀 Analiz Et ve Veritabanına İşle", use_container_width=True, type="primary")

with col2:
    st.subheader("📍 Mekansal Görüntüleme")
    m = folium.Map(location=[39.9334, 32.8597], zoom_start=11, tiles="CartoDB positron")
    harita_gosterici = st_folium(m, width=700, height=400, key="bos_harita")

# --- İŞLEM AKIŞI ---
if islem_baslat and yuklenen_pdf:
    with st.spinner("Yapay zeka belgeyi okuyor ve analiz ediyor..."):
        try:
            okunan_metin = pdf_metin_cikar(yuklenen_pdf)
            ai_sonuc = metni_analiz_et(okunan_metin)
            
            geojson_veri = None
            if yuklenen_kml:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".kml") as tmp:
                    tmp.write(yuklenen_kml.getvalue())
                    tmp_yolu = tmp.name
                donusum = kml2geojson.main.convert(tmp_yolu)
                geojson_veri = donusum[0] if isinstance(donusum, list) else donusum
                os.unlink(tmp_yolu)
            
            # Kayıt İşlemi
            airtable_kaydet(ai_sonuc, bool(yuklenen_kml))
            st.success("✅ Veriler başarıyla analiz edildi ve Airtable'a kaydedildi!")
            st.json(ai_sonuc)
            
            if geojson_veri:
                st.subheader("📍 Kısıt Sınırları (GeoJSON)")
                m_dolu = folium.Map(location=[39.9334, 32.8597], zoom_start=11, tiles="CartoDB positron")
                folium.GeoJson(geojson_veri, name="Kurum Kısıt Sınırı").add_to(m_dolu)
                m_dolu.fit_bounds(m_dolu.get_bounds())
                st_folium(m_dolu, width=700, height=400, key="dolu_harita")
                
        except Exception as e:
            st.error(f"Sistem Hatası: {str(e)}")
elif islem_baslat and not yuklenen_pdf:
    st.warning("Lütfen analiz için bir kurum yazısı (PDF) yükleyin.")
