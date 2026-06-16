import streamlit as st
import google.generativeai as genai
import kml2geojson
from pyairtable import Api
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
    AIRTABLE_TABLE_NAME = "Kurum Görüşleri"
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel('gemini-1.5-flash')
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
    SADECE aşağıdaki JSON formatında cevap ver:
    {
      "kurum_adi": "Kurum adı",
      "evrak_no": "Sayı veya evrak numarası",
      "gorus_durumu": "'Olumlu', 'Kısıtlı' veya 'Olumsuz'",
      "yapilasma_kisitlari": "Kısıtları özetle veya 'Bulunmamaktadır' yaz.",
      "etkilenen_parseller": ["101/1", "102/5"] 
    }
    Metin: """ + metin
    
    response = model.generate_content(prompt, generation_config=genai.GenerationConfig(response_mime_type="application/json"))
    return json.loads(response.text)

def airtable_kaydet(ai_verisi, kml_var_mi):
    api = Api(AIRTABLE_TOKEN)
    tablo = api.table(AIRTABLE_BASE_ID, AIRTABLE_TABLE_NAME)
    yeni_kayit = {
        "Kurum Adı": ai_verisi.get("kurum_adi"),
        "Evrak No": ai_verisi.get("evrak_no"),
        "Görüş Durumu": ai_verisi.get("gorus_durumu"),
        "Yapılaşma Kısıtları": ai_verisi.get("yapilasma_kisitlari"),
        "Etkilenen Parseller (Metin)": ", ".join(ai_verisi.get("etkilenen_parseller", [])),
        "Mekansal Veri Durumu": kml_var_mi
    }
    return tablo.create(yeni_kayit)

# --- ARAYÜZ (UI) ---
col1, col2 = st.columns([1, 1])

with col1:
    st.subheader("📎 Belge Yükleme")
    yuklenen_pdf = st.file_uploader("Kurum Yazısı (PDF)", type=["pdf"])
    yuklenen_kml = st.file_uploader("Mekansal Veri (KML - Opsiyonel)", type=["kml"])
    
    islem_baslat = st.button("🚀 Analiz Et ve Veritabanına İşle", use_container_width=True, type="primary")

with col2:
    st.subheader("📍 Mekansal Görüntüleme")
    # Haritayı varsayılan olarak Ankara koordinatlarında başlatıyoruz
    m = folium.Map(location=[39.9334, 32.8597], zoom_start=11, tiles="CartoDB positron")
    harita_gosterici = st_folium(m, width=700, height=400, key="bos_harita")

# --- İŞLEM AKIŞI ---
if islem_baslat and yuklenen_pdf:
    with st.spinner("Yapay zeka belgeyi okuyor ve analiz ediyor..."):
        try:
            # 1. Metin İşleme
            okunan_metin = pdf_metin_cikar(yuklenen_pdf)
            ai_sonuc = metni_analiz_et(okunan_metin)
            
            # 2. KML İşleme (Varsa)
            geojson_veri = None
            if yuklenen_kml:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".kml") as tmp:
                    tmp.write(yuklenen_kml.getvalue())
                    tmp_yolu = tmp.name
                geojson_veri = kml2geojson.main.convert(tmp_yolu)[0]
                os.unlink(tmp_yolu)
            
            # 3. Airtable'a Kayıt
            airtable_kaydet(ai_sonuc, bool(yuklenen_kml))
            
            # --- BAŞARI EKRANI VE SONUÇLAR ---
            st.success("✅ Veriler başarıyla analiz edildi ve Airtable'a kaydedildi!")
            
            # Çıktıları Göster
            st.json(ai_sonuc)
            
            # Haritayı Güncelle (KML varsa)
            if geojson_veri:
                st.subheader("📍 Kısıt Sınırları (GeoJSON)")
                m_dolu = folium.Map(location=[39.9334, 32.8597], zoom_start=11, tiles="CartoDB positron")
                folium.GeoJson(geojson_veri, name="Kurum Kısıt Sınırı").add_to(m_dolu)
                # Haritayı GeoJSON sınırlarına otomatik odakla
                m_dolu.fit_bounds(m_dolu.get_bounds())
                st_folium(m_dolu, width=700, height=400, key="dolu_harita")
                
        except Exception as e:
            st.error(f"Bir hata oluştu: {str(e)}")
elif islem_baslat and not yuklenen_pdf:
    st.warning("Lütfen analiz için bir kurum yazısı (PDF) yükleyin.")