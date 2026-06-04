import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from fpdf import FPDF
import json, math, os, io, base64, secrets
from datetime import datetime, date, timedelta

# Path assoluto della cartella dell'app (necessario per st.image con path relativi)
_APP_DIR = os.path.dirname(os.path.abspath(__file__))
def _img(relative: str) -> str:
    return os.path.join(_APP_DIR, relative)

def _img_b64(relative: str) -> str:
    """Restituisce l'immagine come stringa base64 per uso inline in HTML."""
    path = _img(relative)
    if not os.path.exists(path):
        return ""
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode()

import database as db

try:
    import qrcode
    from PIL import Image
    HAS_QR = True
except ImportError:
    HAS_QR = False

try:
    from PIL import Image as _PIL_Image
    _page_icon = _PIL_Image.open(_img("logos/icon.png"))
except Exception:
    _page_icon = "🥗"

st.set_page_config(
    page_title="NutriNext",
    layout="wide",
    initial_sidebar_state="expanded",
    page_icon=_page_icon
)

# ── Colori brand NutriNext ─────────────────────────────────────────────────────
NN_BLUE  = "#0A2540"   # Blu Notte
NN_GREEN = "#5FA83D"   # Verde Brillante
NN_LIGHT = "#f4f7f4"   # Sfondo chiaro

# CSS globale
st.markdown(f"""
<link rel="manifest" href="/app/static/manifest.json">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="NutriNext">
<meta name="theme-color" content="#0A2540">
<link rel="apple-touch-icon" href="/app/static/icon-192.png">
<script>
if ('serviceWorker' in navigator) {{
  window.addEventListener('load', function() {{
    navigator.serviceWorker.register('/app/static/sw.js')
      .catch(function(e) {{ console.log('SW:', e); }});
  }});
}}
</script>
<style>
[data-testid="stSidebar"] {{ background: {NN_BLUE}; }}
[data-testid="stSidebar"] * {{ color: #e8f5e9 !important; }}
[data-testid="stSidebar"] .stRadio label {{ color: #e8f5e9 !important; }}
[data-testid="stSidebar"] hr {{ border-color: rgba(255,255,255,0.15); }}
.metric-card {{
    background: white; border-radius: 12px; padding: 20px 24px;
    box-shadow: 0 2px 8px rgba(10,37,64,0.10); border-left: 4px solid {NN_BLUE};
}}
.metric-card.green {{ border-left-color: {NN_GREEN}; }}
.appt-card {{
    background: white; border-radius: 10px; padding: 12px 16px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 8px;
    border-left: 4px solid {NN_GREEN};
}}
.appt-card.annullato {{ border-left-color: #e53935; opacity: 0.7; }}
.appt-card.completato {{ border-left-color: #9e9e9e; }}
.patient-card {{
    background: white; border-radius: 10px; padding: 14px 18px;
    box-shadow: 0 1px 4px rgba(0,0,0,0.08); margin-bottom: 8px;
    cursor: pointer; border: 2px solid transparent; transition: border-color 0.2s;
}}
.patient-card:hover {{ border-color: {NN_GREEN}; }}
h1, h2, h3 {{ color: {NN_BLUE}; }}
</style>
""", unsafe_allow_html=True)

# ==============================================================================
# DB INIT
# ==============================================================================
db.init_db()

# ==============================================================================
# PWA STATIC ICONS — genera icone per manifest se mancanti
# ==============================================================================
def _ensure_pwa_icons():
    static_dir = os.path.join(_APP_DIR, "static")
    os.makedirs(static_dir, exist_ok=True)
    for size, fname in [(192, "icon-192.png"), (512, "icon-512.png")]:
        dest = os.path.join(static_dir, fname)
        if not os.path.exists(dest):
            src = _img("logos/icon.png")
            if os.path.exists(src):
                try:
                    from PIL import Image as _Img
                    img = _Img.open(src).convert("RGBA")
                    side = min(img.size)
                    left = (img.width - side) // 2
                    top  = (img.height - side) // 2
                    img  = img.crop((left, top, left + side, top + side))
                    img  = img.resize((size, size), _Img.LANCZOS)
                    img.save(dest, "PNG")
                except Exception:
                    pass

_ensure_pwa_icons()

# ==============================================================================
# SESSION STATE
# ==============================================================================
for k, v in {
    "user": None, "patient_obj": None, "page": "dashboard",
    "sel_patient_id": None, "piano_corrente": [], "note_piano": "",
    "edit_appt_id": None,
}.items():
    if k not in st.session_state:
        st.session_state[k] = v

# ==============================================================================
# DATABASE ALIMENTI
# ==============================================================================
@st.cache_resource
def load_database():
    frames = []
    if os.path.exists("food_db.csv"):
        frames.append(pd.read_csv("food_db.csv"))
    if os.path.exists("crea_food_composition_tables.csv"):
        df_c = pd.read_csv("crea_food_composition_tables.csv")
        df_c.columns = [c.strip() for c in df_c.columns]
        df_c.rename(columns={"name":"Alimento_Nome","energy_kcal":"Kcal_100g",
            "proteins":"Pro_100g","available_carbohydrates":"Cho_100g",
            "lipids":"Fat_100g","category":"Categoria_Alimento"}, inplace=True)
        df_c["Marca"] = ""
        frames.append(df_c)
    if not frames:
        return pd.DataFrame(columns=["Alimento_Nome","Marca","Barcode","Kcal_100g","Pro_100g","Cho_100g","Fat_100g","Categoria_Alimento"])
    df = pd.concat(frames, ignore_index=True)
    for col in ["Kcal_100g","Pro_100g","Cho_100g","Fat_100g"]:
        if col in df.columns:
            df[col] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
    df["Marca"]   = df["Marca"].fillna("")
    df["Barcode"] = df["Barcode"].fillna("") if "Barcode" in df.columns else ""
    return df.drop_duplicates(subset=["Alimento_Nome","Marca"]).sort_values("Alimento_Nome").reset_index(drop=True)

DATABASE = load_database()

# ==============================================================================
# BIA & BMR
# ==============================================================================
def calcola_bia(peso, altezza, eta, sesso, R, Xc):
    H2_R = altezza**2 / R
    sex_m = 1 if sesso == "M" else 0
    PhA = math.degrees(math.atan(Xc / R))
    TBW = 0.593 * H2_R + 0.065 * peso + 0.04
    ecw_ratio = 0.420 if sesso == "M" else 0.435
    ECW = TBW * ecw_ratio
    ICW = TBW - ECW
    if sesso == "M":
        FFM = 0.507 * H2_R + 0.259 * peso + 0.124 * Xc - 7.027
    else:
        FFM = 0.474 * H2_R + 0.173 * peso + 0.130 * Xc - 4.056
    FFM = max(FFM, 0.0)
    FM = max(peso - FFM, 0.0)
    BCM = ICW / 0.67
    SMM = (H2_R * 0.401) + (sex_m * 3.825) + (eta * -0.071) + 5.102
    ASMM = max(-4.211 + 0.267 * H2_R + 0.095 * peso, 0.0)
    return {
        "PhA": round(PhA, 2), "TBW": round(TBW, 1),
        "ECW": round(ECW, 1), "ICW": round(ICW, 1),
        "FFM": round(max(FFM, 0), 1), "FM": round(FM, 1),
        "FM%": round(FM / peso * 100, 1),
        "BCM": round(max(BCM, 0), 1), "SMM": round(max(SMM, 0), 1),
        "ASMM": round(max(ASMM, 0), 1),
    }

def calcola_bmr(peso, altezza, eta, sesso, formula="Cunningham", ffm=None):
    if formula == "Cunningham":
        f = ffm if ffm and ffm > 0 else peso * (0.77 if sesso == "M" else 0.68)
        return round(500 + 22 * f)
    if formula == "Mifflin-St Jeor":
        return round(10*peso + 6.25*altezza - 5*eta + (5 if sesso=="M" else -161))
    return round((88.362 + 13.397*peso + 4.799*altezza - 5.677*eta) if sesso=="M"
                 else (447.593 + 9.247*peso + 3.098*altezza - 4.330*eta))

# ==============================================================================
# BIA HTML TABLE
# ==============================================================================
def render_bia_table(bia, peso, sesso, bmr=None):
    REFS = {
        "M": {
            "PhA":  (4.9,6.5,7.3,8.9,9.6,"°",None),
            "TBW":  (40,50,59,67,76,"L","peso"),
            "ECW":  (16,20,25,29,34,"L","TBW"),
            "ICW":  (22,28,34,39,45,"L","TBW"),
            "FFM":  (55,65,76,85,95,"kg","peso"),
            "FM":   (5,12,20,29,40,"kg","peso"),
            "BCM":  (20,30,42,54,65,"kg","FFM"),
            "SMM":  (28,36,44,52,60,"kg","peso"),
            "ASMM": (22,28,34,40,46,"kg","peso"),
        },
        "F": {
            "PhA":  (3.9,5.5,6.3,7.5,8.5,"°",None),
            "TBW":  (25,33,40,48,57,"L","peso"),
            "ECW":  (11,14,18,22,26,"L","TBW"),
            "ICW":  (14,18,22,26,31,"L","TBW"),
            "FFM":  (35,44,53,61,70,"kg","peso"),
            "FM":   (10,16,23,32,42,"kg","peso"),
            "BCM":  (14,20,28,36,45,"kg","FFM"),
            "SMM":  (18,24,31,38,46,"kg","peso"),
            "ASMM": (14,18,23,29,35,"kg","peso"),
        }
    }
    LABELS = {
        "PhA":"Angolo di Fase (PhA)","TBW":"Acqua Totale (TBW)",
        "ECW":"Acqua Extra Cellulare (ECW)","ICW":"Acqua Intra Cellulare (ICW)",
        "FFM":"Massa Magra (FFM)","FM":"Massa Grassa (FM)",
        "BCM":"Massa Cellulare (BCM)","SMM":"Massa Muscolo-Scheletrica (SMM) Janssen",
        "ASMM":"Massa Muscolare Appendicolare (ASMM)",
    }
    refs = REFS.get(sesso, REFS["M"])
    denoms = {"peso": peso, "TBW": bia["TBW"], "FFM": bia["FFM"]}

    def pct_str(val, pct_key):
        if not pct_key: return ""
        d = denoms.get(pct_key, 1)
        return f"{val/d*100:.1f} %" if d else ""

    def bar(val, vmin, p25, vmean, p75, vmax):
        span = vmax - vmin or 1
        def p(v): return max(1, min(99, (v-vmin)/span*100))
        mid = (p(p25)+p(p75))/2
        return f"""
        <div style="position:relative;padding:16px 0 14px">
          <div style="width:100%;height:10px;border-radius:5px;background:
            linear-gradient(to right,#dc3545 0%,#ffc107 {p(p25):.0f}%,
            #28a745 {mid:.0f}%,#ffc107 {p(p75):.0f}%,#dc3545 100%)"></div>
          <div style="position:absolute;left:{p(vmean):.1f}%;top:2px;transform:translateX(-50%);
            color:#c0392b;font-size:13px">★</div>
          <div style="position:absolute;left:{p(val):.1f}%;top:4px;transform:translateX(-50%);
            width:14px;height:14px;border-radius:50%;background:#111;border:2px solid #fff"></div>
          <div style="position:relative;width:100%;height:13px;margin-top:2px;font-size:9px;color:#888">
            <span style="position:absolute;left:0">{vmin}</span>
            <span style="position:absolute;left:{p(p25):.0f}%;transform:translateX(-50%)">{p25}</span>
            <span style="position:absolute;left:{p(vmean):.0f}%;transform:translateX(-50%);color:#c0392b">{vmean}</span>
            <span style="position:absolute;left:{p(p75):.0f}%;transform:translateX(-50%)">{p75}</span>
            <span style="position:absolute;right:0">{vmax}</span>
          </div>
        </div>"""

    rows = ""
    for key, label in LABELS.items():
        vmin,p25,vmean,p75,vmax,unit,pct_key = refs[key]
        val = bia[key]
        diff = val - vmean
        sign = "+" if diff >= 0 else ""
        dcol = "#28a745" if abs(diff)<(vmax-vmin)*0.15 else ("#e67e22" if abs(diff)<(vmax-vmin)*0.3 else "#dc3545")
        rows += f"""<tr style="border-bottom:1px solid #f0f0f0">
          <td style="padding:2px 10px;font-size:13px">{label}</td>
          <td style="padding:2px 10px;text-align:center;font-weight:bold;font-size:13px">{val} {unit}</td>
          <td style="padding:2px 10px;text-align:center;color:#555;font-size:13px">{pct_str(val,pct_key)}</td>
          <td style="padding:2px 10px;min-width:240px">{bar(val,vmin,p25,vmean,p75,vmax)}</td>
          <td style="padding:2px 10px;text-align:center;color:{dcol};font-weight:600;font-size:13px">{sign}{diff:.1f} {unit}</td>
        </tr>"""

    bmr_row = f"""<tr style="border-top:2px solid #e0e0e0;background:#f9f9f9">
      <td style="padding:6px 10px;font-weight:600;font-size:13px">Metabolismo Basale (BMR)</td>
      <td style="padding:6px 10px;text-align:center;font-weight:bold;font-size:13px">{bmr} kcal</td>
      <td colspan="3"></td></tr>""" if bmr else ""

    return f"""<div style="overflow-x:auto;margin-top:10px">
    <table style="width:100%;border-collapse:collapse;font-family:sans-serif">
      <thead><tr style="background:#0A2540;color:white">
        <th style="padding:9px 10px;text-align:left">Parametro</th>
        <th style="padding:9px 10px;text-align:center">Risultato</th>
        <th style="padding:9px 10px;text-align:center">%</th>
        <th style="padding:9px 10px;text-align:center">Valori di riferimento</th>
        <th style="padding:9px 10px;text-align:center">Diff. media</th>
      </tr></thead>
      <tbody>{rows}{bmr_row}</tbody>
    </table></div>"""

# ==============================================================================
# BIAVECTOR
# ==============================================================================
def plot_biavector(R, Xc, altezza):
    Rz_H = R / (altezza/100)
    Xc_H = Xc / (altezza/100)
    fig = go.Figure()
    for cx,cy,rx,ry,col,lbl in [(205,34,30,9,"rgba(60,180,60,0.15)","50%"),
                                  (205,34,50,15,"rgba(60,180,60,0.10)","75%"),
                                  (205,34,75,22,"rgba(60,180,60,0.06)","95%")]:
        t = [i*math.pi/180 for i in range(361)]
        fig.add_trace(go.Scatter(x=[cx+rx*math.cos(a) for a in t],
            y=[cy+ry*math.sin(a) for a in t], fill="toself",
            fillcolor=col, line=dict(color="green",width=1,dash="dot"),
            mode="lines", showlegend=False))
    for x0,y0,x1,y1,txt in [(100,10,150,25,"Disidratazione"),(280,50,240,38,"Iperidratazione"),
                               (205,60,205,45,"Atrofia"),(205,10,205,25,"Obesità")]:
        fig.add_annotation(x=x1,y=y1,ax=x0,ay=y0,xref="x",yref="y",axref="x",ayref="y",
            showarrow=True,arrowhead=2,arrowcolor="#888",arrowwidth=1.5,
            font=dict(size=9,color="#666"),text=txt)
    fig.add_trace(go.Scatter(x=[Rz_H],y=[Xc_H],mode="markers+text",text=["Paziente"],
        textposition="top center",
        marker=dict(color="crimson",size=14,symbol="diamond",line=dict(width=2,color="white"))))
    fig.update_layout(xaxis=dict(title="Rz/H [Ω/m]",range=[80,380],gridcolor="#f0f0f0"),
        yaxis=dict(title="Xc/H [Ω/m]",range=[0,80],gridcolor="#f0f0f0"),
        height=400,margin=dict(l=0,r=0,t=20,b=0),plot_bgcolor="white")
    return fig

# ==============================================================================
# PDF
# ==============================================================================

def _dt_slice(val, start: int, end: int, fallback: str = "—") -> str:
    """Estrae una slice da una stringa data/datetime in modo sicuro."""
    s = str(val) if val else ""
    return s[start:end] if len(s) >= end else fallback

def _safe(text: str) -> str:
    """Sostituisce caratteri non latin-1 con equivalenti ASCII."""
    return (str(text)
        .replace("—", "-").replace("–", "-")   # em/en dash
        .replace("’", "'").replace("‘", "'")   # smart quotes
        .replace("“", '"').replace("”", '"')
        .replace("•", "-").replace("…", "...")
        .encode("latin-1", errors="replace").decode("latin-1"))

# Colore primario PDF (bordeaux come nel modello)
_PDF_R, _PDF_G, _PDF_B = 123, 30, 43   # #7B1E2B

# Ordine canonico dei pasti nel PDF
_PASTO_ORDER = ["Colazione","Spuntino Mattina","Spuntino","Pranzo",
                "Merenda","Spuntino Pomeriggio","Cena","Pre-Nanna"]

class _NutriPDF(FPDF):
    """FPDF personalizzata con footer NutriNext su ogni pagina."""
    def __init__(self, titolo_nut="", nome_paz=""):
        super().__init__()
        self._titolo_nut = titolo_nut
        self._nome_paz   = nome_paz
        self._skip_footer_page = 1   # salta footer sulla copertina

    def footer(self):
        if self.page_no() == self._skip_footer_page:
            return
        self.set_y(-14)
        # Logo NutriNext piccolo a sinistra
        logo_footer = _img("logos/default_logo.png")
        if os.path.exists(logo_footer):
            try:
                self.image(logo_footer, x=20, y=self.get_y()-1, h=8)
            except Exception:
                pass
        # Testo centrato
        self.set_font("Arial", "I", 7)
        self.set_text_color(160, 160, 160)
        testo = _safe(f"{self._titolo_nut}  |  {self._nome_paz}  |  {datetime.now().strftime('%d/%m/%Y')}")
        self.set_x(30)
        self.cell(150, 5, testo, align="C")
        # "NutriNext" a destra
        self.set_font("Arial", "B", 7)
        self.set_text_color(_PDF_R, _PDF_G, _PDF_B)
        self.set_x(0)
        self.cell(190, 5, "NutriNext Pro", align="R")
        self.set_text_color(0, 0, 0)


def _titolo_sezione(pdf, testo: str):
    """Titolo di sezione in bordeaux grassetto, stile modello."""
    pdf.set_font("Arial", "B", 11)
    pdf.set_text_color(_PDF_R, _PDF_G, _PDF_B)
    pdf.cell(0, 7, _safe(testo), ln=True)
    pdf.set_text_color(0, 0, 0)

def _running_header(pdf, nut: dict):
    """Header in alto a destra su ogni pagina (esclusa copertina)."""
    titolo_nut = _safe(_titolo_nutrizionista(nut))
    spec       = _safe(nut.get("specializzazione",""))
    pdf.set_font("Arial", "", 8)
    pdf.set_text_color(80, 80, 80)
    pdf.set_xy(0, 8)
    pdf.cell(200, 4, titolo_nut, align="R")
    pdf.set_xy(0, 13)
    pdf.cell(200, 4, spec, align="R")
    pdf.set_text_color(0, 0, 0)
    pdf.set_y(22)

def _titolo_nutrizionista(nut: dict) -> str:
    prefisso = "Dott.ssa" if nut.get("sesso_nut","M") == "F" else "Dott."
    return f"{prefisso} {nut.get('nome','')} {nut.get('cognome','')}".strip()

def genera_pdf_dieta(items, note, paziente: dict = None,
                     nutrizionista: dict = None, visita: dict = None,
                     freq_proteiche: str = ""):
    paz  = paziente     or {}
    nut  = nutrizionista or {}
    vis  = visita       or {}
    nome_paz   = _safe(f"{paz.get('cognome','')} {paz.get('nome','')}".strip() or "Paziente")
    titolo_nut = _safe(_titolo_nutrizionista(nut))
    spec_nut   = _safe(nut.get("specializzazione",""))

    pdf = _NutriPDF(titolo_nut=titolo_nut, nome_paz=nome_paz)
    pdf.set_margins(20, 20, 20)

    # ── COPERTINA ──────────────────────────────────────────────────────────────
    pdf.add_page()
    pdf.set_auto_page_break(False)

    # Header piccolo in alto a destra (anche copertina)
    pdf.set_font("Arial", "", 9); pdf.set_text_color(80,80,80)
    pdf.set_xy(0, 10)
    pdf.cell(190, 5, titolo_nut, align="R")
    pdf.set_xy(0, 16)
    pdf.cell(190, 5, spec_nut, align="R")

    # Titolo principale centrato
    pdf.set_y(55)
    pdf.set_font("Arial", "B", 28)
    pdf.set_text_color(_PDF_R, _PDF_G, _PDF_B)
    pdf.cell(0, 14, "PIANO ALIMENTARE", ln=True, align="C")
    pdf.cell(0, 14, "PERSONALIZZATO",   ln=True, align="C")

    # Logo centrato — usa logo nutrizionista, altrimenti NutriNext default
    resolved_logo = _get_logo_path(nut)
    default_logo  = _img("logos/default_logo.png")
    logo_to_use   = resolved_logo if resolved_logo else (default_logo if os.path.exists(default_logo) else None)
    if logo_to_use:
        try:
            logo_w = 72
            pdf.image(logo_to_use, x=(210-logo_w)/2, y=105, w=logo_w)
        except Exception:
            pass

    # Dati nutrizionista in basso
    pdf.set_y(220)
    pdf.set_font("Arial", "B", 13); pdf.set_text_color(20,20,20)
    pdf.cell(0, 8, titolo_nut, ln=True, align="C")
    pdf.set_font("Arial", "", 11); pdf.set_text_color(_PDF_R, _PDF_G, _PDF_B)
    pdf.cell(0, 7, spec_nut, ln=True, align="C")
    pdf.set_text_color(20,20,20)
    if nut.get("email_studio"):
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 6, f"Mail: {_safe(nut['email_studio'])}", ln=True, align="C")
    if nut.get("telefono"):
        pdf.set_font("Arial", "B", 10)
        pdf.cell(0, 6, f"Tel: {_safe(nut['telefono'])}", ln=True, align="C")

    # ── PAGINA 2: SPIEGAZIONI + DATI ANTROPOMETRICI ───────────────────────────
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    _running_header(pdf, nut)

    if note:
        _titolo_sezione(pdf, "SPIEGAZIONE E CONSIGLI:")
        pdf.set_font("Arial", "", 10); pdf.set_text_color(0,0,0)
        for line in _safe(note).split("\n"):
            line = line.strip()
            if not line:
                pdf.ln(2); continue
            prefix = "" if line.startswith("-") else ""
            pdf.multi_cell(0, 6, f"{prefix}{line}", align="L")
        pdf.ln(5)

    if freq_proteiche and freq_proteiche.strip():
        _titolo_sezione(pdf, "FREQUENZA CONSUMO FONTI PROTEICHE:")
        pdf.set_font("Arial", "", 10); pdf.set_text_color(0,0,0)
        for line in _safe(freq_proteiche).split("\n"):
            line = line.strip()
            if not line:
                pdf.ln(2); continue
            prefix = "" if line.startswith("-") else ""
            pdf.multi_cell(0, 6, f"{prefix}{line}", align="L")
        pdf.ln(5)

    # Dati antropometrici
    if vis:
        _titolo_sezione(pdf, "DATI ANTROPOMETRICI")
        pdf.set_font("Arial", "", 10)
        dati_antr = [
            ("Paziente", nome_paz),
            ("Peso", f"{vis.get('peso','')} kg"),
            ("Altezza", f"{vis.get('altezza','')} m" if vis.get('altezza') else ""),
            ("FFM (Massa Magra)", f"{vis.get('FFM','')} kg"),
            ("FM (Massa Grassa)", f"{vis.get('FM','')} kg  ({vis.get('FM_perc','')}%)"),
            ("BMR", f"{vis.get('BMR','')} kcal/giorno"),
        ]
        for label, val in dati_antr:
            if val.strip(" kg%m/giorno") not in ("", "0", "0.0"):
                pdf.set_font("Arial", "B", 10)
                pdf.cell(70, 6, _safe(label + ":"), ln=False)
                pdf.set_font("Arial", "", 10)
                pdf.cell(0,  6, _safe(val), ln=True)
        pdf.ln(4)

    # ── PIANO ALIMENTARE — rileva tipo e adatta layout ────────────────────────
    giorni = {}
    for r in items:
        g = str(r.get("Giorno", r.get("giorno", "Altro")))
        giorni.setdefault(g, []).append(r)

    GIORNI_SETTIMANA = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica",
                        "Lunedi","Martedi","Mercoledi","Giovedi","Venerdi"]
    GIORNI_TIPO      = ["Workout Day","Rest Day"]

    chiavi = list(giorni.keys())
    is_workout_rest = any(g in GIORNI_TIPO for g in chiavi)
    is_giornaliero  = any(g in GIORNI_SETTIMANA for g in chiavi)

    ORDER_FULL = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica",
                  "Lunedi","Martedi","Mercoledi","Giovedi","Venerdi","Workout Day","Rest Day"]
    giorni_sorted = sorted(chiavi,
        key=lambda x: next((i for i,o in enumerate(ORDER_FULL) if o.lower()==x.lower()), 99))

    def _scrivi_giorno_pasti(pdf, giorno, voci_giorno):
        """Scrive un giorno con i suoi pasti e alimenti nell'ordine canonico."""
        if giorno:
            pdf.set_font("Arial", "B", 11)
            pdf.set_text_color(_PDF_R, _PDF_G, _PDF_B)
            pdf.cell(0, 8, _safe(giorno.upper() + ":"), ln=True)
            pdf.set_text_color(0, 0, 0)
        pasti = {}
        for r in voci_giorno:
            p = str(r.get("Pasto", r.get("pasto", "Pasto")))
            pasti.setdefault(p, []).append(r)
        pasti_sorted = sorted(
            pasti.items(),
            key=lambda x: next((i for i, o in enumerate(_PASTO_ORDER)
                                 if o.lower() == x[0].lower()), 99)
        )
        for pasto, voci in pasti_sorted:
            pdf.set_font("Arial", "BI", 9)
            pdf.cell(8, 5, "", ln=False)
            pdf.cell(0, 5, _safe(pasto + ":"), ln=True)
            pdf.set_font("Arial", "", 9)
            for r in voci:
                q    = r.get("Quantità", r.get("quantita", 0))
                alim = _safe(r.get("Alimento", r.get("alimento", "")))
                qtxt = "q.b." if not q or q == 0 else f"{q}g"
                pdf.cell(12, 5, "", ln=False)
                pdf.cell(4,  5, "-", ln=False)
                pdf.multi_cell(0, 5, f"{alim}  ({qtxt})", align="L")
        pdf.ln(3)

    if is_workout_rest:
        # ── LAYOUT WORKOUT / REST DAY ──────────────────────────────────────────
        _titolo_sezione(pdf, "PIANO ALIMENTARE")
        for idx, giorno in enumerate(giorni_sorted, 1):
            pdf.set_font("Arial", "B", 12)
            pdf.set_text_color(26, 35, 126)
            label = f"PROTOCOLLO N.{idx} - {giorno.upper()}"
            pdf.cell(0, 9, _safe(label), ln=True)
            pdf.set_draw_color(_PDF_R, _PDF_G, _PDF_B)
            pdf.set_line_width(0.5)
            pdf.line(20, pdf.get_y(), 190, pdf.get_y())
            pdf.ln(3)
            pdf.set_draw_color(0,0,0); pdf.set_line_width(0.2)
            _scrivi_giorno_pasti(pdf, "", giorni[giorno])

    else:
        # ── LAYOUT GIORNALIERO (Lun-Dom) ───────────────────────────────────────
        _titolo_sezione(pdf, "PIANO ALIMENTARE")

        # Tabella riepilogo settimanale se ci sono più di 2 giorni
        PASTI_PRINCIPALI = ["Pranzo","Cena"]
        giorni_disponibili = [g for g in giorni_sorted if g in GIORNI_SETTIMANA + ["Lunedi","Martedi","Mercoledi","Giovedi","Venerdi"]]

        if len(giorni_disponibili) >= 3:
            pdf.ln(2)
            pdf.set_font("Arial", "B", 10)
            pdf.set_fill_color(240, 240, 248)
            pdf.set_text_color(_PDF_R, _PDF_G, _PDF_B)
            pdf.cell(0, 7, "SCHEMA SETTIMANALE", ln=True)
            pdf.set_text_color(0,0,0)
            pdf.ln(1)

            # Header tabella
            col_g, col_p, col_c = 32, 79, 79
            pdf.set_fill_color(_PDF_R, _PDF_G, _PDF_B)
            pdf.set_text_color(255,255,255)
            pdf.set_font("Arial", "B", 8)
            pdf.cell(col_g, 7, "Giorno", border=1, fill=True, align="C")
            pdf.cell(col_p, 7, "Pranzo", border=1, fill=True, align="C")
            pdf.cell(col_c, 7, "Cena",   border=1, fill=True, align="C")
            pdf.ln(7)

            for giorno in giorni_disponibili:
                voci = giorni[giorno]
                pranzo_items = [r for r in voci if "pranzo" in str(r.get("Pasto",r.get("pasto",""))).lower()]
                cena_items   = [r for r in voci if "cena"   in str(r.get("Pasto",r.get("pasto",""))).lower()]

                def fmt_righe(lst):
                    parts = []
                    for r in lst:
                        q = r.get("Quantità",r.get("quantita",0))
                        a = _safe(r.get("Alimento",r.get("alimento","")))
                        parts.append(f"{a} ({('q.b.' if not q or q==0 else str(q)+'g')})")
                    return ", ".join(parts)[:80] if parts else "-"

                pranzo_txt = fmt_righe(pranzo_items)
                cena_txt   = fmt_righe(cena_items)

                # Altezza riga adattiva
                n = max(1, max(len(pranzo_txt)//38+1, len(cena_txt)//38+1))
                h = max(7, 5*n)
                y0 = pdf.get_y()
                pdf.set_fill_color(252,252,255)
                pdf.set_font("Arial", "B", 8); pdf.set_text_color(_PDF_R,_PDF_G,_PDF_B)
                pdf.cell(col_g, h, _safe(giorno[:3].capitalize()), border=1, fill=True, align="C")
                pdf.set_font("Arial", "", 7); pdf.set_text_color(0,0,0)
                x1 = pdf.get_x()
                pdf.multi_cell(col_p, 5, pranzo_txt, border=0, align="L")
                y_after_p = pdf.get_y()
                pdf.set_xy(x1 + col_p, y0)
                pdf.multi_cell(col_c, 5, cena_txt, border=0, align="L")
                # Bordi manuali
                pdf.set_draw_color(200,200,200)
                pdf.rect(20+col_g,     y0, col_p, h)
                pdf.rect(20+col_g+col_p, y0, col_c, h)
                pdf.set_draw_color(0,0,0)
                pdf.set_y(y0 + h)

            pdf.ln(6)

        # Dettaglio completo per ogni giorno
        _titolo_sezione(pdf, "DETTAGLIO GIORNALIERO")
        for giorno in giorni_sorted:
            _scrivi_giorno_pasti(pdf, giorno, giorni[giorno])

    return pdf.output(dest="S").encode("latin-1")


def genera_pdf_spesa(items, paziente: dict = None, nutrizionista: dict = None, visita: dict = None):
    paz = paziente or {}
    nut = nutrizionista or {}
    vis = visita or {}
    nome_paz   = _safe(f"{paz.get('cognome','')} {paz.get('nome','')}".strip() or "Paziente")
    titolo_nut = _safe(_titolo_nutrizionista(nut))

    # Aggrega quantità per alimento
    agg = {}
    for r in items:
        al = str(r.get("Alimento", r.get("alimento", ""))).strip()
        q  = float(r.get("Quantità", r.get("quantita", 0)) or 0)
        if al:
            agg[al] = agg.get(al, 0) + q

    pdf = FPDF()
    pdf.set_margins(20, 20, 20)
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)
    _running_header(pdf, nut)

    pdf.set_font("Arial", "B", 20); pdf.set_text_color(_PDF_R, _PDF_G, _PDF_B)
    pdf.cell(0, 12, "LISTA DELLA SPESA", ln=True, align="C")
    pdf.set_font("Arial", "", 10); pdf.set_text_color(80,80,80)
    pdf.cell(0, 5, _safe(f"Paziente: {nome_paz}  -  Data: {vis.get('data', datetime.now().strftime('%d/%m/%Y'))}"), ln=True, align="C")
    pdf.ln(6)

    _titolo_sezione(pdf, "PRODOTTI DA ACQUISTARE")
    pdf.set_text_color(0, 0, 0)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(3)

    col_w = 90  # due colonne
    items_list = sorted(agg.items())
    mid = math.ceil(len(items_list) / 2)
    left  = items_list[:mid]
    right = items_list[mid:]

    y_start = pdf.get_y()
    pdf.set_font("Arial", "", 10)

    for i, (alim, qtot) in enumerate(left):
        qtxt = "q.b." if qtot == 0 else f"{int(qtot)}g"
        y = y_start + i * 9
        pdf.set_xy(12, y)
        pdf.set_fill_color(232, 234, 246)
        pdf.cell(5, 7, "", border=1, fill=True)
        pdf.set_x(20)
        pdf.cell(col_w - 12, 7, _safe(alim[:35]), border="B")
        pdf.cell(18, 7, qtxt, border="B", align="R")

    for i, (alim, qtot) in enumerate(right):
        qtxt = "q.b." if qtot == 0 else f"{int(qtot)}g"
        y = y_start + i * 9
        pdf.set_xy(108, y)
        pdf.set_fill_color(232, 234, 246)
        pdf.cell(5, 7, "", border=1, fill=True)
        pdf.set_x(116)
        pdf.cell(col_w - 12, 7, _safe(alim[:35]), border="B")
        pdf.cell(18, 7, qtxt, border="B", align="R")

    max_rows = max(len(left), len(right))
    pdf.set_y(y_start + max_rows * 9 + 8)

    # Note
    pdf.set_font("Arial", "I", 8)
    pdf.set_text_color(120, 120, 120)
    pdf.cell(0, 5, _safe(f"Totale prodotti: {len(agg)}  -  Piano: {vis.get('data','')}"), align="C")

    # Footer
    pdf.set_y(-15)
    pdf.set_font("Arial", "I", 7); pdf.set_text_color(160,160,160)
    pdf.cell(0, 5, _safe(f"{titolo_nut} - {nome_paz} - {datetime.now().strftime('%d/%m/%Y')}"), align="C")

    return pdf.output(dest="S").encode("latin-1")

# ==============================================================================
# HELPERS
# ==============================================================================
# ==============================================================================
# SUPERMERCATI — configurazione catene supportate
# ==============================================================================
SUPERMERCATI = {
    "Carrefour": {
        "emoji": "🔵", "colore": "#004a97",
        "url": "https://www.carrefour.it/search?q={q}",
        "note": "Disponibile online con consegna",
    },
    "Esselunga": {
        "emoji": "🟠", "colore": "#ff6600",
        "url": "https://www.esselunga.it/commerce/ecommerce/search.html?q={q}",
        "note": "Nord e Centro Italia",
    },
    "Coop": {
        "emoji": "🟡", "colore": "#c8a800",
        "url": "https://www.coopshop.it/search?q={q}",
        "note": "Cooperative aderenti",
    },
    "Conad": {
        "emoji": "🔴", "colore": "#e30613",
        "url": "https://spesa.conad.it/search?q={q}",
        "note": "Disponibile in molte regioni",
    },
    "Pam": {
        "emoji": "🟢", "colore": "#007b3e",
        "url": "https://www.pampanorama.it/search?q={q}",
        "note": "Nord Est e Centro Italia",
    },
    "Amazon Fresh": {
        "emoji": "📦", "colore": "#ff9900",
        "url": "https://www.amazon.it/s?k={q}&i=amazonfresh",
        "note": "Grandi città italiane",
    },
    "Google Shopping": {
        "emoji": "🔍", "colore": "#4285f4",
        "url": "https://www.google.it/search?q={q}+acquisto+online&tbm=shop",
        "note": "Confronta prezzi su tutti i supermercati online",
    },
}

def get_barcode(alimento_nome: str) -> str:
    """Cerca il barcode di un alimento nel database."""
    if DATABASE.empty or "Barcode" not in DATABASE.columns:
        return ""
    row = DATABASE[DATABASE["Alimento_Nome"] == alimento_nome]
    if not row.empty:
        return str(row["Barcode"].values[0]).strip()
    return ""

def url_supermercato(supermercato: str, alimento: str, marca: str = "") -> str:
    """Genera l'URL di ricerca per un prodotto su un supermercato."""
    conf = SUPERMERCATI.get(supermercato, {})
    template = conf.get("url", "")
    if not template:
        return ""
    # Query: preferisci "Marca NomeProdotto" per risultati più precisi
    query = f"{marca} {alimento}".strip() if marca else alimento
    import urllib.parse
    return template.format(q=urllib.parse.quote(query))

COLORI_TIPO = {
    "Prima Visita":"#3f51b5","Controllo":"#4caf50",
    "Urgenza":"#f44336","Consulenza":"#ff9800","Altro":"#9e9e9e"
}

# ==============================================================================
# IMPORT DIETA DA PDF
# ==============================================================================
_GIORNO_NUM_MAP = {
    "1":"Lunedì","2":"Martedì","3":"Mercoledì",
    "4":"Giovedì","5":"Venerdì","6":"Sabato","7":"Domenica",
}
_GIORNO_IT_MAP = {
    "lunedi":"Lunedì","lunedì":"Lunedì",
    "martedi":"Martedì","martedì":"Martedì",
    "mercoledi":"Mercoledì","mercoledì":"Mercoledì",
    "giovedi":"Giovedì","giovedì":"Giovedì",
    "venerdi":"Venerdì","venerdì":"Venerdì",
    "sabato":"Sabato","domenica":"Domenica",
}

def _pdf_clean_name(raw: str) -> str:
    """Pulisce un nome alimento: rimuove parentesi, tronca alle parole utili."""
    import re
    s = raw.strip().lstrip('•').lstrip('-').strip()
    s = re.sub(r'\([^)]*\)', '', s)           # rimuovi parentesi
    s = re.split(r'à|→|➔', s)[0]             # stop alle frecce
    s = s.rstrip('.,;:').strip()
    # Ferma a parole "filler" dopo almeno 1 parola significativa
    STOP = {'preferibilmente','integrali','integrale','a','da','conditi','condita',
            'freschi','fresco','fresche','fresca','o','oppure','es.','ecc','ecc.',
            'come','per','se','non','al','alla','del','della'}
    words, out = s.split(), []
    for w in words:
        if w.lower() in STOP and out:
            break
        out.append(w)
        if len(out) >= 4:
            break
    result = ' '.join(out).rstrip(',').strip()
    return result if len(result) >= 3 else ''


def _estrai_da_bullet(line: str) -> list:
    """Estrae coppie (nome, qty_g) da una riga bullet stile dieta italiana."""
    import re
    line = re.sub(r'^[•\-\*]\s*', '', line).strip()
    if not line:
        return []

    results = []
    # Split su "/" per alternative con quantità proprie: "170g jocca / 100g feta"
    parti = re.split(r'\s*/\s*', line)

    for part in parti:
        part = part.strip()

        # Range "NUMg-NUMg nome" → prendi il primo
        m = re.match(r'^(\d+)\s*(?:g|gr|ml)?\s*[-–]\s*\d+\s*(?:g|gr|ml)\s+(.+)', part, re.IGNORECASE)
        if m:
            nome = _pdf_clean_name(m.group(2))
            if nome: results.append((nome, int(m.group(1))))
            continue

        # "NUMg nome" o "NUMml nome"
        m = re.match(r'^(\d+(?:[.,]\d+)?)\s*(?:g|gr|ml)\s+(.+)', part, re.IGNORECASE)
        if m:
            nome = _pdf_clean_name(m.group(2))
            qty  = int(float(m.group(1).replace(',','.')))
            if nome: results.append((nome, qty))
            continue

    # Se niente trovato con slash, prova "+" (righe colazione tipo "50g pane + 30g affettato")
    if not results and '+' in line:
        for sub in line.split('+'):
            sub = sub.strip()
            m = re.match(r'^(\d+(?:[.,]\d+)?)\s*(?:g|gr|ml)\s+(.+)', sub, re.IGNORECASE)
            if m:
                nome = _pdf_clean_name(m.group(2))
                qty  = int(float(m.group(1).replace(',','.')))
                if nome: results.append((nome, qty))

    # Deduplication
    seen, out = set(), []
    for n, q in results:
        if n not in seen and len(n) >= 3:
            seen.add(n); out.append((n, q))
    return out


def _parse_flessibile(lines: list) -> list:
    """
    Parser per diete con PROTOCOLLO N.1 (Workout Day) / PROTOCOLLO N.2 (Rest Day).
    Colazione e Spuntini prima dei protocolli vengono duplicati su entrambi i giorni.
    """
    import re
    SALTA_SEZIONI = {'frequenze di consumo','idee pranzo','esempio schema',
                     'dati antropometrici','spiegazione e consigli'}
    SALTA_RIGHE   = ['fonte di carboidrati','da consumare con','fonte proteica',
                     'oppure:','à ','§','n.b.:','come condimento','le verdure',
                     "l'insalata",'si consiglia','è possibile','è importante',
                     'una volta a','a pranzo e cena','mail:','tel:','dott']

    items, shared = [], []
    current_proto = None
    current_pasto = "Colazione"
    skip = False

    for line in lines:
        ls = line.strip()
        if not ls:
            continue
        ll = ls.lower()

        if any(s in ll for s in SALTA_SEZIONI):
            skip = True; continue

        m = re.search(r'PROTOCOLLO\s+N[\.°]?\s*(\d+)', ls, re.IGNORECASE)
        if m:
            current_proto = "Workout Day" if m.group(1) == "1" else "Rest Day"
            skip = False; continue

        if skip:
            continue
        if any(s in ll for s in SALTA_RIGHE):
            continue

        # Rilevamento pasto
        if re.match(r'^colazione\s*[:\(]?', ll):
            current_pasto = "Colazione"; continue
        if re.match(r'^spuntino\s+met[aà]\s+mattina', ll) or re.match(r'^spuntino\s*\(', ll):
            current_pasto = "Spuntino Mattina"; continue
        if re.match(r'^(alternative\s+)?spuntino\s+met[aà]\s+pomeriggio', ll):
            current_pasto = "Merenda"; continue
        if re.match(r'^pranzo\s*[:\(]', ll):
            current_pasto = "Pranzo"; continue
        if re.match(r'^cena\s*:', ll):
            current_pasto = "Cena"; continue

        # Bullet alimentare
        if ls[0] in ('•', '-') and ls[1:3] != '--':
            for nome, qty in _estrai_da_bullet(ls):
                if current_proto is None:
                    shared.append((current_pasto, nome, qty))
                else:
                    items.append({"Giorno": current_proto, "Pasto": current_pasto,
                                  "Alimento": nome, "Quantità": qty})

    # Espandi condivisi su entrambi i protocolli
    for pasto, nome, qty in shared:
        for g in ("Workout Day", "Rest Day"):
            items.append({"Giorno": g, "Pasto": pasto, "Alimento": nome, "Quantità": qty})

    return items


def _parse_tabella_coordinate(page) -> list:
    """
    Parser per PDF con layout tabellare a colonne (Giorno 1…7 o Lunedì…Domenica).
    Usa le coordinate X/Y delle parole per assegnare ciascuna a cella corretta.
    """
    import re
    words = page.extract_words(keep_blank_chars=False, x_tolerance=3, y_tolerance=3)
    if not words:
        return []

    # 1. Trova header colonne "Giorno N"
    giorno_xs = []   # [(x_center, day_name)]
    i = 0
    while i < len(words):
        w = words[i]
        if w['text'].lower() == 'giorno' and i + 1 < len(words):
            nw = words[i + 1]
            if nw['text'].isdigit() and abs(nw['top'] - w['top']) < 5:
                cx = (w['x0'] + nw['x1']) / 2
                giorno_xs.append((cx, _GIORNO_NUM_MAP.get(nw['text'], f"Giorno {nw['text']}")))
                i += 2; continue
        # Prova anche nomi italiani dei giorni come header
        gn = w['text'].lower().rstrip('iì')
        if gn in ('luned','marted','mercoled','gioved','venerd','sabato','domenic') and w['x0'] > 80:
            full = _GIORNO_IT_MAP.get(w['text'].lower(), w['text'].capitalize())
            giorno_xs.append((w['x0'], full))
        i += 1

    if not giorno_xs:
        return []

    giorno_xs.sort(key=lambda x: x[0])

    # 2. Trova label pasti (colonna sinistra x < 90)
    PASTO_LABEL = {
        'COLAZIONE': 'Colazione', 'PRANZO': 'Pranzo',
        'CENA': 'Cena', 'SPUNTINO': None,  # risolto dopo
    }
    pasto_ys = []   # [(y, pasto_name)]
    spuntino_n = 0
    for w in words:
        if w['x0'] < 90 and w['text'].upper() in PASTO_LABEL:
            if w['text'].upper() == 'SPUNTINO':
                spuntino_n += 1
                name = 'Spuntino Mattina' if spuntino_n == 1 else 'Merenda'
            else:
                name = PASTO_LABEL[w['text'].upper()]
            pasto_ys.append((w['top'], name))

    if not pasto_ys:
        return []
    pasto_ys.sort(key=lambda x: x[0])

    # 3. Calcola boundaries colonne e righe
    col_bounds = []   # (x_left, x_right, day_name)
    for j, (cx, name) in enumerate(giorno_xs):
        x_left  = (giorno_xs[j-1][0] + cx) / 2 if j > 0 else cx - 60
        x_right = (cx + giorno_xs[j+1][0]) / 2 if j < len(giorno_xs)-1 else cx + 130
        col_bounds.append((x_left, x_right, name))

    row_bounds = []   # (y_top, y_bottom, pasto_name)
    for k, (y, name) in enumerate(pasto_ys):
        y_bottom = pasto_ys[k+1][0] if k < len(pasto_ys)-1 else 9999
        row_bounds.append((y - 2, y_bottom, name))

    first_content_y = pasto_ys[0][0] if pasto_ys else 0

    # 4. Assegna ogni parola alla cella
    cells = {}   # (day, pasto) → [text, ...]
    for w in words:
        if w['x0'] < 90 or w['top'] < first_content_y - 5:
            continue
        # Colonna
        day = None
        for x_l, x_r, dname in col_bounds:
            if x_l <= w['x0'] < x_r:
                day = dname; break
        if not day:
            continue
        # Riga
        pasto = None
        for y_t, y_b, pname in row_bounds:
            if y_t <= w['top'] < y_b:
                pasto = pname; break
        if not pasto:
            continue
        cells.setdefault((day, pasto), []).append(w['text'])

    # 5. Costruisci items
    items = []
    for (day, pasto), wlist in cells.items():
        testo = ' '.join(wlist)
        testo = re.sub(r'\*+', '', testo).strip()
        if not testo or testo in ('-', '—'):
            continue
        # Cerca quantità nel testo (se presenti)
        m = re.search(r'(\d+)\s*(?:g|gr|ml)\b', testo, re.IGNORECASE)
        qty = int(m.group(1)) if m else 0
        # Pulisce testo da numeri di quantità per usarlo come nome
        nome = re.sub(r'\d+\s*(?:g|gr|ml)\b\s*', '', testo, flags=re.IGNORECASE).strip()
        nome = nome[:80] if nome else testo[:80]
        items.append({"Giorno": day, "Pasto": pasto, "Alimento": nome, "Quantità": qty})

    return items


def _parse_giornaliero_testo(lines: list) -> list:
    """
    Fallback testuale per PDF giornalieri senza layout tabellare riconoscibile.
    Cerca 'Giorno N' o nomi di giorno + pasto + alimenti con grammatura.
    """
    import re
    items = []
    giorno = "Lunedì"
    pasto  = "Pranzo"
    SALTA  = {'dott','mail:','tel:','tutte','nel caso','ribadiamo','lo schema',
               'esso,','*scegliere','**si suggerisce','in alternativa'}

    for line in lines:
        ls = line.strip()
        if not ls or any(s in ls.lower() for s in SALTA):
            continue
        ll = ls.lower()

        # Giorno numerico
        m = re.search(r'\bGiorno\s+(\d)\b', ls, re.IGNORECASE)
        if m:
            giorno = _GIORNO_NUM_MAP.get(m.group(1), giorno); continue

        # Giorno italiano
        for kw, val in _GIORNO_IT_MAP.items():
            if re.search(r'\b' + re.escape(kw) + r'\b', ll):
                giorno = val; break

        # Pasto
        if re.search(r'\bcolazione\b', ll): pasto = "Colazione"
        elif re.search(r'\bspuntino\b', ll): pasto = "Spuntino Mattina"
        elif re.search(r'\bpranzo\b', ll):   pasto = "Pranzo"
        elif re.search(r'\bmerenda\b', ll):  pasto = "Merenda"
        elif re.search(r'\bcena\b', ll):     pasto = "Cena"

        # Quantità + alimento
        for m in re.finditer(r'(\d+)\s*(?:g|gr|ml)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ\s\-\']{2,})', ls):
            nome = _pdf_clean_name(m.group(2))
            qty  = int(m.group(1))
            if nome and qty > 0:
                items.append({"Giorno": giorno, "Pasto": pasto,
                              "Alimento": nome, "Quantità": qty})

    return items


def parse_diet_pdf(pdf_bytes: bytes, tipo_schema: str = "giornaliero"):
    """
    Analizza un PDF di dieta.
    tipo_schema: "giornaliero" | "flessibile"
    Restituisce (items, errore_str)
    """
    import pdfplumber

    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if tipo_schema == "flessibile":
                # Estrai tutto il testo e usa il parser per protocolli
                lines = []
                for pg in pdf.pages:
                    t = pg.extract_text()
                    if t:
                        lines.extend(t.splitlines())
                items = _parse_flessibile(lines)
            else:
                # Prova prima con coordinate (tabella)
                items = []
                for pg in pdf.pages:
                    pg_items = _parse_tabella_coordinate(pg)
                    items.extend(pg_items)
                # Fallback testuale se la tabella non ha dato risultati
                if not items:
                    lines = []
                    for pg in pdf.pages:
                        t = pg.extract_text()
                        if t:
                            lines.extend(t.splitlines())
                    items = _parse_giornaliero_testo(lines)
    except Exception as e:
        return [], f"Errore durante l'analisi: {e}"

    if not items:
        return [], ("Nessun alimento riconosciuto. "
                    "Assicurati di aver selezionato il tipo di dieta corretto "
                    "e che il PDF contenga testo selezionabile.")
    return items, None


def _match_alimento_db(nome: str) -> str:
    """Cerca il nome più simile nel DATABASE. Ritorna il nome trovato o l'originale."""
    if DATABASE.empty:
        return nome
    nome_low = nome.lower()
    exact = DATABASE[DATABASE["Alimento_Nome"].str.lower() == nome_low]
    if not exact.empty:
        return exact["Alimento_Nome"].values[0]
    partial = DATABASE[DATABASE["Alimento_Nome"].str.lower().str.contains(nome_low, na=False)]
    if not partial.empty:
        return partial["Alimento_Nome"].values[0]
    for _, row in DATABASE.iterrows():
        if row["Alimento_Nome"].lower() in nome_low:
            return row["Alimento_Nome"]
    return nome

def macros_da_items(items):
    if not items: return None
    righe = []
    for r in items:
        alim = r.get("Alimento", r.get("alimento",""))
        q    = float(r.get("Quantità", r.get("quantita",0)) or 0)
        gg   = r.get("Giorno", r.get("giorno",""))
        m = DATABASE[DATABASE["Alimento_Nome"]==alim]
        if not m.empty and q > 0:
            f = q/100
            righe.append({"Giorno":gg,
                "Cal": m["Kcal_100g"].values[0]*f, "Pro": m["Pro_100g"].values[0]*f,
                "Cho": m["Cho_100g"].values[0]*f,  "Fat": m["Fat_100g"].values[0]*f})
    if not righe: return None
    return pd.DataFrame(righe).groupby("Giorno").sum().reset_index()

def eta_da_nascita(data_nascita_str):
    try:
        dn = datetime.strptime(data_nascita_str, "%Y-%m-%d").date()
        return (date.today() - dn).days // 365
    except:
        return 30

# ==============================================================================
# ─────────────────────────── LOGIN / SETUP ───────────────────────────────────
# ==============================================================================
# Coppie (maschile, femminile) per ogni specializzazione
_SPEC_COPPIE = [
    ("Nutrizionista",          "Nutrizionista"),
    ("Biologo Nutrizionista",  "Biologa Nutrizionista"),
    ("Dietologo",              "Dietologa"),
    ("Dietista",               "Dietista"),
    ("Medico Nutrizionista",   "Medico Nutrizionista"),
    ("Altro",                  "Altro"),
]
# Lista piatta di tutti i valori possibili (per compatibilità con valori già salvati)
SPECIALIZZAZIONI = [m for m, f in _SPEC_COPPIE] + [f for m, f in _SPEC_COPPIE if m != f]

def _spec_options(sesso: str) -> list:
    i = 0 if sesso == "M" else 1
    return [pair[i] for pair in _SPEC_COPPIE]

def _spec_index(saved: str, sesso: str) -> int:
    options = _spec_options(sesso)
    if saved in options:
        return options.index(saved)
    # Valore dell'altro genere → trova la coppia e restituisce l'indice
    other = _spec_options("F" if sesso == "M" else "M")
    if saved in other:
        return other.index(saved)
    # Valori legacy con slash (es. "Biologo/a Nutrizionista")
    saved_clean = saved.replace("/a ", " ").replace("/a", "")
    for idx, (m, f) in enumerate(_SPEC_COPPIE):
        if saved_clean in (m, f):
            return idx
    return 0

def _form_profilo_nut(user: dict):
    """Form condiviso tra setup e impostazioni profilo."""
    f1, f2 = st.columns(2)
    nome    = f1.text_input("Nome *", value=user.get("nome",""))
    cognome = f2.text_input("Cognome", value=user.get("cognome",""))
    f3, f4 = st.columns(2)
    sesso_nut = f3.selectbox("Genere", ["M","F"],
        index=0 if user.get("sesso_nut","M")=="M" else 1,
        format_func=lambda x: "Maschile (Dott.)" if x=="M" else "Femminile (Dott.ssa)")
    spec_list = _spec_options(sesso_nut)
    spec_idx  = _spec_index(user.get("specializzazione", "Nutrizionista"), sesso_nut)
    specializzazione = f4.selectbox("Specializzazione", spec_list, index=spec_idx)
    f5, f6 = st.columns(2)
    email_studio = f5.text_input("Email studio", value=user.get("email_studio",""))
    telefono     = f6.text_input("Telefono", value=user.get("telefono",""))
    return nome, cognome, sesso_nut, specializzazione, email_studio, telefono

def _salva_logo(logo_file, user_id: int) -> str:
    """Salva il file logo su disco e nel DB (per persistenza cloud)."""
    os.makedirs("logos", exist_ok=True)
    path = _img(f"logos/logo_{user_id}.png")
    data = logo_file.read()
    with open(path, "wb") as f:
        f.write(data)
    db.save_logo_data(user_id, base64.b64encode(data).decode())
    return path

def _get_logo_path(user: dict) -> str:
    """Restituisce il path del logo, ricostruendolo dal DB se il file non esiste.
    Usa /tmp per compatibilità con filesystem read-only (Railway)."""
    logo_b64 = user.get("logo_data") or db.get_logo_data(user.get("id", 0))
    if logo_b64:
        tmp_dir = "/tmp/nutrigen_logos"
        os.makedirs(tmp_dir, exist_ok=True)
        p = os.path.join(tmp_dir, f"logo_{user.get('id',0)}.png")
        with open(p, "wb") as f:
            f.write(base64.b64decode(logo_b64))
        return p
    # Fallback: logo_path salvato nel profilo
    path = user.get("logo_path", "")
    if path and os.path.exists(path):
        return path
    return ""

def page_setup():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c = st.columns([1,2,1])[1]
    with c:
        st.markdown("## 🥗 NutriNext")
        st.markdown("### Configurazione iniziale")
        st.info("Primo avvio rilevato. Crea il tuo account nutrizionista.")

        nome, cognome, sesso_nut, spec, email_s, tel = _form_profilo_nut({})

        st.divider()
        st.markdown("**Logo studio** *(opzionale — apparirà sulla copertina delle diete)*")
        logo_file = st.file_uploader("Carica logo PNG/JPG", type=["png","jpg","jpeg"],
                                     label_visibility="collapsed")
        if logo_file:
            st.image(logo_file, width=120)

        st.divider()
        username = st.text_input("Username (per il login) *")
        pw       = st.text_input("Password *", type="password")
        pw2      = st.text_input("Conferma password *", type="password")

        if st.button("Crea account", type="primary", use_container_width=True):
            if not all([nome, username, pw]):
                st.error("Compila tutti i campi obbligatori (*).")
            elif pw != pw2:
                st.error("Le password non coincidono.")
            else:
                db.setup_nutritionist(username, pw, nome, cognome,
                                      sesso_nut, spec, email_s, tel)
                # Salva logo se caricato
                if logo_file:
                    nut_row = db.find_user_by_email(email_s) or db.get_nutritionist_by_code(
                        next(iter([u["studio_code"] for u in db.get_all_nutritionists()
                                   if u.get("username") == username]), ""))
                    if not nut_row:
                        # fallback: cerca per username tramite login
                        nut_row = db.login(username, pw) or {}
                    uid = nut_row.get("id")
                    if uid:
                        logo_path = _salva_logo(logo_file, uid)
                        db.update_nutritionist_profile(uid, nome, cognome, sesso_nut,
                                                       spec, email_s, tel, logo_path=logo_path)
                st.success("Account creato! Effettua il login.")
                st.rerun()


def page_profilo():
    """Impostazioni profilo nutrizionista — dati e logo in una pagina."""
    user = st.session_state.user
    st.title("⚙️ Profilo & Impostazioni")

    # ── Dati profilo ────────────────────────────────────────────────────────
    st.subheader("👤 Dati profilo")
    nome, cognome, sesso_nut, spec, email_s, tel = _form_profilo_nut(user)

    # ── Logo studio ─────────────────────────────────────────────────────────
    st.divider()
    st.subheader("🖼️ Logo studio")
    st.caption("Appare sulla copertina del PDF. Se non caricato viene usato il logo NutriNext.")

    logo_path = _get_logo_path(user)
    col_prev, col_up = st.columns([1, 2])
    with col_prev:
        if logo_path:
            st.image(logo_path, width=150, caption="Logo attuale")
        else:
            default = _img("logos/default_logo.png")
            if os.path.exists(default):
                st.image(default, width=150, caption="Logo NutriNext (default)")
            st.caption("Nessun logo personalizzato caricato.")
    with col_up:
        logo_file = st.file_uploader("Carica nuovo logo (PNG/JPG)",
                                     type=["png","jpg","jpeg"])
        if logo_file:
            st.image(logo_file, width=150, caption="Anteprima")

    # ── Salva tutto insieme ──────────────────────────────────────────────────
    st.divider()
    if st.button("💾 Salva profilo", type="primary", use_container_width=True):
        new_logo_path = logo_path  # mantieni quello attuale se non caricato nulla
        if logo_file:
            new_logo_path = _salva_logo(logo_file, user["id"])

        db.update_nutritionist_profile(user["id"], nome, cognome,
                                       sesso_nut, spec, email_s, tel,
                                       logo_path=new_logo_path)
        st.session_state.user.update({
            "nome": nome, "cognome": cognome, "sesso_nut": sesso_nut,
            "specializzazione": spec, "email_studio": email_s,
            "telefono": tel, "logo_path": new_logo_path
        })
        st.success("Profilo salvato.")
        st.rerun()

def _widget_recupero_credenziali():
    """Expander per il recupero credenziali tramite reset manuale della password."""
    with st.expander("🔑 Hai dimenticato username o password?"):
        st.caption("Inserisci l'email associata al tuo account per reimpostare la password.")
        rec_tipo  = st.radio("Tipo account", ["Nutrizionista", "Paziente"], horizontal=True,
                             key="rec_tipo")
        rec_email = st.text_input("Email", placeholder="Es. mario.rossi@studio.it", key="rec_email")

        if st.button("🔍 Trova account", key="btn_trova_account"):
            if not rec_email.strip():
                st.warning("Inserisci un'email.")
            else:
                if rec_tipo == "Nutrizionista":
                    found = db.find_user_by_email(rec_email.strip())
                else:
                    found = db.find_patient_by_email(rec_email.strip())
                if not found:
                    st.error("Nessun account trovato con questa email.")
                else:
                    st.session_state["_rec_id"]   = found["id"]
                    st.session_state["_rec_tipo"]  = rec_tipo.lower()
                    st.session_state["_rec_nome"]  = found.get("nome", "")
                    st.success(
                        f"Account trovato: **{found.get('nome','')} {found.get('cognome','')}** "
                        f"— username: `{found.get('username','')}`"
                    )

        if st.session_state.get("_rec_id"):
            st.divider()
            st.markdown(f"**Imposta nuova password per {st.session_state['_rec_nome']}**")
            np1 = st.text_input("Nuova password", type="password", key="rec_np1")
            np2 = st.text_input("Conferma password", type="password", key="rec_np2")
            if st.button("💾 Salva nuova password", type="primary", key="btn_salva_pw"):
                if not np1:
                    st.warning("Inserisci la nuova password.")
                elif np1 != np2:
                    st.error("Le password non coincidono.")
                elif len(np1) < 6:
                    st.warning("La password deve essere di almeno 6 caratteri.")
                else:
                    db.reset_password(st.session_state["_rec_tipo"],
                                      st.session_state["_rec_id"], np1)
                    st.success("✅ Password aggiornata. Puoi ora effettuare il login.")
                    for k in ["_rec_id","_rec_tipo","_rec_nome"]:
                        st.session_state.pop(k, None)
                    st.rerun()


def page_login():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c = st.columns([1,1.2,1])[1]
    with c:
        st.image(_img("logos/logo_login.png"), use_container_width=True)
        st.markdown("""
        <div style='text-align:center;margin-bottom:20px'>
          <p style='color:#666;margin-top:4px'>Software clinico per nutrizionisti</p>
        </div>""", unsafe_allow_html=True)
        username = st.text_input("Username", placeholder="Inserisci username")
        password = st.text_input("Password", type="password", placeholder="Inserisci password")
        if st.button("Accedi", type="primary", use_container_width=True):
            user = db.login(username, password)
            if user and user.get("_suspended"):
                st.error("⛔ Account sospeso. Contatta l'amministratore NutriNext.")
            elif user:
                if user.get("_patient"):
                    st.session_state.user = user
                    st.session_state.patient_obj = user
                else:
                    st.session_state.user = user
                st.rerun()
            else:
                st.error("Credenziali non valide.")
        st.markdown("<br>", unsafe_allow_html=True)
        _widget_recupero_credenziali()
        st.divider()
        st.markdown("<div style='text-align:center;color:#888;font-size:0.9em'>Sei un nutrizionista?</div>",
                    unsafe_allow_html=True)
        if st.button("📋 Registrati come Nutrizionista", use_container_width=True):
            st.session_state["show_register_nut"] = True
            st.rerun()


def page_registrazione_nutrizionista():
    """Pagina pubblica di registrazione per nutrizionisti."""
    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.image(_img("logos/logo_login.png"), use_container_width=True)
    st.markdown("""
    <div style='text-align:center;padding:6px 0 16px'>
      <p style='color:#666;font-size:1.1em'>Registrazione Nutrizionista</p>
      <p style='color:#999;font-size:0.9em'>La tua richiesta verrà esaminata dall'amministratore NutriNext</p>
    </div>""", unsafe_allow_html=True)

    with st.form("form_reg_nut"):
        f1, f2 = st.columns(2)
        nome    = f1.text_input("Nome *")
        cognome = f2.text_input("Cognome")

        f3, f4 = st.columns(2)
        sesso_nut = f3.selectbox("Sesso", ["M", "F"])
        spec      = f4.text_input("Specializzazione", value="Nutrizionista")

        f5, f6 = st.columns(2)
        email_s = f5.text_input("Email studio *")
        tel     = f6.text_input("Telefono")

        st.subheader("Credenziali di accesso")
        u1, u2, u3 = st.columns(3)
        username = u1.text_input("Username *")
        pw1      = u2.text_input("Password *", type="password")
        pw2      = u3.text_input("Conferma password *", type="password")

        submitted = st.form_submit_button("📨 Invia richiesta", type="primary", use_container_width=True)

    if submitted:
        if not all([nome, email_s, username, pw1]):
            st.error("Compila tutti i campi obbligatori (*).")
        elif " " in username:
            st.error("Lo username non può contenere spazi.")
        elif pw1 != pw2:
            st.error("Le password non coincidono.")
        elif len(pw1) < 6:
            st.error("La password deve essere di almeno 6 caratteri.")
        else:
            ok, msg = db.submit_nutritionist_request(
                nome, cognome, sesso_nut, spec, email_s, tel, username, pw1)
            if ok:
                st.success(f"✅ {msg}")
                st.balloons()
                st.info("Puoi chiudere questa pagina. Ti contatteremo via email.")
            else:
                st.error(msg)

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("← Torna al login"):
        st.session_state["show_register_nut"] = False
        st.rerun()


# ==============================================================================
# ───────────────────────── SIDEBAR NUTRIZIONISTA ──────────────────────────────
# ==============================================================================
def _sidebar_logo():
    """Renderizza il logo NutriNext in un riquadro bianco nella sidebar."""
    b64 = _img_b64("logos/default_logo.png")
    if b64:
        st.sidebar.markdown(f"""
        <div style='background:white;border-radius:12px;padding:12px 16px;margin:12px 4px 4px'>
          <img src='data:image/png;base64,{b64}' style='width:100%;display:block'>
        </div>""", unsafe_allow_html=True)

def sidebar_nutrizionista():
    user = st.session_state.user
    _sidebar_logo()
    st.sidebar.markdown(f"""
    <div style='text-align:center;padding:4px 0 10px'>
      <div style='font-size:0.85em;color:#9fa8da'>Dr. {user['nome']} {user.get('cognome','')}</div>
    </div>""", unsafe_allow_html=True)
    st.sidebar.divider()

    nav = {
        "dashboard": "🏠  Dashboard",
        "agenda":    "📅  Agenda",
        "pazienti":  "👥  Pazienti",
        "inviti":    "🔗  Invita Pazienti",
        "archivio":  "📁  Archivio Template",
        "profilo":   "⚙️  Profilo & Impostazioni",
    }
    for key, label in nav.items():
        active = st.session_state.page == key
        if st.sidebar.button(label, use_container_width=True,
                             type="primary" if active else "secondary"):
            st.session_state.page = key
            st.session_state.sel_patient_id = None
            st.rerun()

    if st.session_state.sel_patient_id:
        st.sidebar.divider()
        p = db.get_patient(st.session_state.sel_patient_id)
        st.sidebar.markdown(f"**Paziente:** {p.get('nome','')} {p.get('cognome','')}")
        sub = {"visita":"🔍 Visita & BIA","piano":"🥗 Piano","messaggi":"💬 Messaggi"}
        for key, label in sub.items():
            badge = ""
            if key == "messaggi":
                n = db.unread_count(st.session_state.sel_patient_id, "Nutrizionista")
                if n: badge = f" 🔴{n}"
            if st.sidebar.button(label+badge, use_container_width=True,
                                type="primary" if st.session_state.page==key else "secondary"):
                st.session_state.page = key
                st.rerun()

    st.sidebar.divider()
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        for k in ["user","patient_obj","page","sel_patient_id","piano_corrente","note_piano","edit_appt_id"]:
            st.session_state[k] = None if k in ["user","patient_obj","sel_patient_id","edit_appt_id"] else ([] if k=="piano_corrente" else ("" if k=="note_piano" else "dashboard"))
        st.rerun()

# ==============================================================================
# ─────────────────────────── DASHBOARD ────────────────────────────────────────
# ==============================================================================
def page_dashboard():
    user = st.session_state.user
    st.title(f"Buongiorno, Dr. {user['nome']} 👋")

    oggi = date.today()
    appts_oggi = [a for a in db.get_appointments(user["id"])
                  if str(a.get("data_ora","")).startswith(str(oggi))]
    pazienti    = db.get_patients(user["id"])
    appts_futuri = [a for a in db.get_appointments(user["id"])
                    if str(a.get("data_ora","")) > str(oggi) and a.get("stato")=="Programmato"]

    c1,c2,c3 = st.columns(3)
    c1.markdown(f"""<div class='metric-card'>
      <div style='color:#666;font-size:0.85em'>APPUNTAMENTI OGGI</div>
      <div style='font-size:2.2em;font-weight:700;color:#0A2540'>{len(appts_oggi)}</div>
    </div>""", unsafe_allow_html=True)
    c2.markdown(f"""<div class='metric-card' style='border-color:#4caf50'>
      <div style='color:#666;font-size:0.85em'>PAZIENTI ATTIVI</div>
      <div style='font-size:2.2em;font-weight:700;color:#2e7d32'>{len(pazienti)}</div>
    </div>""", unsafe_allow_html=True)
    c3.markdown(f"""<div class='metric-card' style='border-color:#ff9800'>
      <div style='color:#666;font-size:0.85em'>PROSSIMI APPUNTAMENTI</div>
      <div style='font-size:2.2em;font-weight:700;color:#e65100'>{len(appts_futuri)}</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    col_a, col_b = st.columns([1.2, 1])

    with col_a:
        st.subheader("📅 Appuntamenti di oggi")
        if not appts_oggi:
            st.info("Nessun appuntamento per oggi.")
        for a in sorted(appts_oggi, key=lambda x: x["data_ora"]):
            ora = _dt_slice(a.get("data_ora"), 11, 16)
            col = COLORI_TIPO.get(a.get("tipo",""),"#9e9e9e")
            stato_css = a.get("stato","").lower()
            st.markdown(f"""<div class='appt-card {stato_css}' style='border-left-color:{col}'>
              <b>{ora}</b> — {a.get('patient_name','N/D')}
              <span style='float:right;font-size:0.8em;color:#888'>{a['tipo']} · {a['durata_min']}min</span>
              {'<br><i style="font-size:0.85em;color:#666">' + a['note'] + '</i>' if a.get('note') else ''}
            </div>""", unsafe_allow_html=True)

    with col_b:
        st.subheader("👥 Ultimi pazienti")
        for p in pazienti[:8]:
            if st.button(f"**{p['cognome']} {p['nome']}**  —  {p.get('email','')}",
                        key=f"dash_p_{p['id']}", use_container_width=True):
                st.session_state.sel_patient_id = p["id"]
                st.session_state.page = "visita"
                st.rerun()

# ==============================================================================
# ─────────────────────────── AGENDA ───────────────────────────────────────────
# ==============================================================================
def page_agenda():
    user = st.session_state.user
    st.title("📅 Agenda")

    # Navigazione settimana
    if "agenda_week" not in st.session_state:
        st.session_state.agenda_week = date.today() - timedelta(days=date.today().weekday())

    wstart = st.session_state.agenda_week
    wend   = wstart + timedelta(days=6)

    nav1, nav2, nav3, nav4 = st.columns([1,1,3,2])
    if nav1.button("◀ Prec"):
        st.session_state.agenda_week -= timedelta(weeks=1); st.rerun()
    if nav2.button("Succ ▶"):
        st.session_state.agenda_week += timedelta(weeks=1); st.rerun()
    if nav3.button("Oggi", type="secondary"):
        st.session_state.agenda_week = date.today() - timedelta(days=date.today().weekday()); st.rerun()
    nav4.markdown(f"**{wstart.strftime('%d %b')} – {wend.strftime('%d %b %Y')}**")

    appts = db.get_appointments(user["id"],
        from_date=str(wstart)+" 00:00", to_date=str(wend)+" 23:59")

    # Vista settimanale HTML
    giorni_it = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"]
    header = "".join(
        f"<th style='text-align:center;padding:8px;background:{'#5FA83D' if (wstart+timedelta(days=i))==date.today() else '#0A2540'};color:white;border-radius:6px 6px 0 0'>"
        f"{giorni_it[i]}<br><small>{(wstart+timedelta(days=i)).strftime('%d/%m')}</small></th>"
        for i in range(7)
    )

    cells = ""
    for i in range(7):
        d = wstart + timedelta(days=i)
        day_appts = [a for a in appts if str(a.get("data_ora","")).startswith(str(d))]
        day_appts.sort(key=lambda x: str(x.get("data_ora","")))
        content = ""
        for a in day_appts:
            ora = _dt_slice(a.get("data_ora"), 11, 16)
            col = COLORI_TIPO.get(a.get("tipo",""),"#9e9e9e")
            op = "0.6" if a.get("stato")=="Annullato" else "1"
            content += f"""<div style='background:{col};color:white;border-radius:6px;
              padding:5px 8px;margin-bottom:5px;font-size:0.8em;opacity:{op}'>
              <b>{ora}</b> {a.get('patient_name','—')}<br>
              <span style='font-size:0.85em'>{a.get('tipo','')}</span>
            </div>"""
        if not content:
            content = "<div style='color:#ccc;font-size:0.8em;text-align:center;padding:10px'>—</div>"
        cells += f"<td style='vertical-align:top;padding:8px;min-width:120px;border:1px solid #f0f0f0;background:white'>{content}</td>"

    st.markdown(f"""<div style='overflow-x:auto'>
    <table style='width:100%;border-collapse:collapse'>
      <thead><tr>{header}</tr></thead>
      <tbody><tr>{cells}</tr></tbody>
    </table></div>""", unsafe_allow_html=True)

    st.divider()

    # Form aggiungi / modifica
    pazienti = db.get_patients(user["id"])
    paz_map  = {f"{p['cognome']} {p['nome']}": p["id"] for p in pazienti}
    paz_nomi = ["(Paziente esterno / nuovo)"] + list(paz_map.keys())

    edit_id = st.session_state.get("edit_appt_id")
    appt_edit = next((a for a in db.get_appointments(user["id"]) if a["id"]==edit_id), {}) if edit_id else {}

    with st.expander("➕ Aggiungi / Modifica appuntamento", expanded=bool(appt_edit)):
        f1, f2 = st.columns(2)
        data_appt = f1.date_input("Data", value=date.today() if not appt_edit else
            datetime.strptime(_dt_slice(appt_edit.get("data_ora"), 0, 10, str(date.today())),"%Y-%m-%d").date())
        ora_appt  = f2.time_input("Ora", value=datetime.strptime(
            _dt_slice(appt_edit.get("data_ora"), 11, 16, "09:00") if appt_edit else "09:00","%H:%M").time())

        f3, f4 = st.columns(2)
        paz_sel   = f3.selectbox("Paziente", paz_nomi,
            index=paz_nomi.index(next((k for k,v in paz_map.items() if v==appt_edit.get("patient_id")),
            paz_nomi[0])) if appt_edit else 0)
        paz_nome_ext = ""
        if paz_sel == paz_nomi[0]:
            paz_nome_ext = f3.text_input("Nome paziente esterno", value=appt_edit.get("patient_name",""))
        durata   = f4.selectbox("Durata", [30,45,60,90,120],
            index=[30,45,60,90,120].index(appt_edit.get("durata_min",60)) if appt_edit else 2)

        f5, f6 = st.columns(2)
        tipo  = f5.selectbox("Tipo", list(COLORI_TIPO.keys()),
            index=list(COLORI_TIPO.keys()).index(appt_edit.get("tipo","Prima Visita")) if appt_edit else 0)
        stato = f6.selectbox("Stato", ["Programmato","Completato","Annullato"],
            index=["Programmato","Completato","Annullato"].index(appt_edit.get("stato","Programmato")) if appt_edit else 0)
        note_a = st.text_input("Note", value=appt_edit.get("note",""))

        ba, bb = st.columns(2)
        if ba.button("💾 Salva appuntamento", type="primary", use_container_width=True):
            patient_id   = paz_map.get(paz_sel)
            patient_name = paz_sel if paz_sel!=paz_nomi[0] else paz_nome_ext
            data_ora_str = f"{data_appt} {ora_appt.strftime('%H:%M')}"
            db.save_appointment(user["id"], patient_id, patient_name,
                data_ora_str, durata, tipo, note_a, stato, appt_id=edit_id)
            st.session_state.edit_appt_id = None
            st.success("Salvato."); st.rerun()
        if edit_id and bb.button("🗑️ Elimina", type="secondary", use_container_width=True):
            db.delete_appointment(edit_id)
            st.session_state.edit_appt_id = None
            st.rerun()

    # Lista appuntamenti settimana
    st.subheader("Appuntamenti della settimana")
    if not appts:
        st.info("Nessun appuntamento questa settimana.")
    for a in appts:
        c1, c2, c3 = st.columns([3,1,1])
        ora    = _dt_slice(a.get("data_ora"), 11, 16)
        d_str  = _dt_slice(a.get("data_ora"), 0, 10, str(date.today()))
        giorno = datetime.strptime(d_str, "%Y-%m-%d").strftime("%a %d/%m")
        col = COLORI_TIPO.get(a.get("tipo",""),"#9e9e9e")
        c1.markdown(f"<span style='color:{col}'>●</span> **{giorno} {ora}** — {a.get('patient_name','—')} · {a.get('tipo','—')} · {a.get('durata_min','—')}min · *{a.get('stato','—')}*", unsafe_allow_html=True)
        if c2.button("✏️", key=f"edit_{a['id']}"):
            st.session_state.edit_appt_id = a["id"]; st.rerun()
        if c3.button("🗑️", key=f"del_{a['id']}"):
            db.delete_appointment(a["id"]); st.rerun()

# ==============================================================================
# ─────────────────────────── LISTA PAZIENTI ───────────────────────────────────
# ==============================================================================
def page_pazienti():
    user = st.session_state.user
    st.title("👥 Pazienti")

    tab_lista, tab_nuovo = st.tabs(["📋 Lista pazienti", "➕ Nuovo paziente"])

    with tab_lista:
        pazienti = db.get_patients(user["id"])
        search   = st.text_input("🔍 Cerca per nome, cognome o email", placeholder="Digita per filtrare...")
        if search:
            q = search.lower()
            pazienti = [p for p in pazienti if q in (p.get("nome","")+" "+p.get("cognome","")+" "+p.get("email","")).lower()]
        st.caption(f"{len(pazienti)} pazienti")
        if not pazienti:
            st.info("Nessun paziente trovato.")
        for p in pazienti:
            c1, c2, c3 = st.columns([4,1,1])
            eta = eta_da_nascita(p.get("data_nascita","")) if p.get("data_nascita") else "—"
            c1.markdown(f"**{p['cognome']} {p['nome']}** — {p.get('email','—')} — {p.get('sesso','—')} — {eta} anni")
            if c2.button("Apri", key=f"apri_{p['id']}", type="primary"):
                st.session_state.sel_patient_id = p["id"]
                st.session_state.page = "visita"
                st.rerun()
            if c3.button("✏️", key=f"mod_{p['id']}"):
                st.session_state["edit_patient"] = p["id"]
                st.rerun()

    with tab_nuovo:
        _form_paziente(user["id"])

def _form_paziente(nutritionist_id, patient_id=None):
    p = db.get_patient(patient_id) if patient_id else {}
    f1, f2 = st.columns(2)
    nome    = f1.text_input("Nome *", value=p.get("nome",""))
    cognome = f2.text_input("Cognome", value=p.get("cognome",""))
    f3, f4, f5 = st.columns(3)
    sesso   = f3.selectbox("Sesso", ["M","F"], index=0 if p.get("sesso","M")=="M" else 1)
    dn_val  = datetime.strptime(p["data_nascita"],"%Y-%m-%d").date() if p.get("data_nascita") else date(1990,1,1)
    data_n  = f4.date_input("Data di nascita", value=dn_val)
    tel     = f5.text_input("Telefono", value=p.get("telefono",""))
    email   = st.text_input("Email", value=p.get("email",""))
    note_a  = st.text_area("Anamnesi / note", value=p.get("note_anamnesi",""), height=100)
    st.divider()
    st.subheader("Accesso portale paziente")
    st.caption("Crea credenziali per permettere al paziente di accedere al portale.")
    pu1, pu2 = st.columns(2)
    uname = pu1.text_input("Username paziente", value=p.get("username",""))
    pw    = pu2.text_input("Password (lascia vuoto per non modificare)", type="password")

    if st.button("💾 Salva paziente", type="primary"):
        if not nome:
            st.error("Il nome è obbligatorio.")
        elif uname and " " in uname:
            st.error("Lo username non può contenere spazi.")
        else:
            db.save_patient(nutritionist_id, nome, cognome, email, sesso,
                str(data_n), tel, note_a, uname, pw, patient_id)
            st.success("Paziente salvato.")
            st.rerun()

# ==============================================================================
# ─────────────────────────── VISITA & BIA ─────────────────────────────────────
# ==============================================================================
def page_visita():
    pid = st.session_state.sel_patient_id
    p   = db.get_patient(pid)
    st.title(f"🔍 Visita — {p.get('cognome','')} {p.get('nome','')}")

    visite = db.get_visits(pid)
    tab_nuova, tab_storico = st.tabs(["➕ Nuova visita", "📋 Storico visite"])

    with tab_nuova:
        c1, c2, c3 = st.columns(3)
        data_v  = c1.date_input("Data visita", value=date.today())
        eta_paz = c2.number_input("Età (anni)", 10, 100,
            value=eta_da_nascita(p.get("data_nascita","")) if p.get("data_nascita") else 30)
        sesso_p = c3.selectbox("Sesso", ["M","F"], index=0 if p.get("sesso","M")=="M" else 1)

        c4, c5 = st.columns(2)
        peso    = c4.number_input("Peso (kg)", 30.0, 300.0, value=70.0, step=0.1)
        altezza = c5.number_input("Altezza (cm)", 100, 230, value=170)

        st.divider()
        st.subheader("⚡ BIA — Akern")
        b1, b2 = st.columns(2)
        R_v  = b1.number_input("Resistenza R (Ω)", 100.0, 1000.0, value=500.0, step=0.1, format="%.1f")
        Xc_v = b2.number_input("Reattanza Xc (Ω)", 10.0, 200.0,  value=60.0,  step=0.1, format="%.1f")

        bia = calcola_bia(peso, altezza, eta_paz, sesso_p, R_v, Xc_v)
        formula_bmr = st.radio("Formula BMR:", ["Cunningham","Mifflin-St Jeor","Harris-Benedict"],
                               horizontal=True)
        bmr = calcola_bmr(peso, altezza, eta_paz, sesso_p, formula_bmr, ffm=bia["FFM"])
        latt = st.selectbox("Livello attività:", [
            ("Sedentario ×1.2",1.2),("Lievemente attivo ×1.375",1.375),
            ("Moderatamente attivo ×1.55",1.55),("Molto attivo ×1.725",1.725),
        ], format_func=lambda x: x[0])
        tdee = round(bmr * latt[1])
        tc1, tc2 = st.columns(2)
        tc1.metric("BMR", f"{bmr} kcal/g"); tc2.metric("TDEE", f"{tdee} kcal/g")

        st.markdown(render_bia_table(bia, peso, sesso_p, bmr=bmr), unsafe_allow_html=True)
        st.plotly_chart(plot_biavector(R_v, Xc_v, altezza), use_container_width=True)

        st.divider()
        usa_pliche = st.checkbox("📏 Aggiungi dati plicometrici (opzionale)")
        pliche = {}
        if usa_pliche:
            st.subheader("📏 Plicometria (7 punti — Protocollo Jackson-Pollock)")
            pc1, pc2, pc3 = st.columns(3)
            pliche = {
                "tricipitale":    pc1.number_input("Tricipitale (mm)", 0.0, format="%.1f"),
                "bicipitale":     pc1.number_input("Bicipitale (mm)",  0.0, format="%.1f"),
                "sottoscapolare": pc1.number_input("Sottoscapolare (mm)", 0.0, format="%.1f"),
                "soprailiaca":    pc2.number_input("Soprailiaca (mm)", 0.0, format="%.1f"),
                "addominale":     pc2.number_input("Addominale (mm)",  0.0, format="%.1f"),
                "coscia":         pc3.number_input("Coscia (mm)",      0.0, format="%.1f"),
                "ascellare":      pc3.number_input("Ascellare (mm)",   0.0, format="%.1f"),
            }
        note_v = st.text_area("Note visita", height=100)

        if st.button("💾 SALVA VISITA", type="primary", use_container_width=True):
            db.save_visit(pid, str(data_v), peso, altezza, eta_paz, sesso_p,
                          R_v, Xc_v, bia, bmr, pliche, note_v)
            st.success("Visita salvata.")
            st.rerun()

    with tab_storico:
        if not visite:
            st.info("Nessuna visita registrata.")
        for v in visite:
            with st.expander(f"📅 {v['data']} — {v.get('peso','')} kg — FFM {v.get('FFM','')} kg"):
                vc1,vc2,vc3,vc4 = st.columns(4)
                vc1.metric("Peso",f"{v['peso']} kg"); vc2.metric("FFM",f"{v.get('FFM',0)} kg")
                vc3.metric("FM", f"{v.get('FM',0)} kg ({v.get('FM_perc',0)}%)")
                vc4.metric("BMR",f"{v.get('BMR',0)} kcal")
                if v.get("note"):
                    st.caption(v["note"])

# ==============================================================================
# ─────────────────────────── PIANO NUTRIZIONALE ───────────────────────────────
# ==============================================================================
def page_piano():
    pid = st.session_state.sel_patient_id
    p   = db.get_patient(pid)
    st.title(f"🥗 Piano — {p.get('cognome','')} {p.get('nome','')}")

    # Carica piano attivo in session_state se non già presente
    plan = db.get_active_plan(pid)
    if plan and not st.session_state.piano_corrente:
        st.session_state.piano_corrente = [
            {"Giorno":i["giorno"],"Pasto":i["pasto"],
             "Alimento":i["alimento"],"Quantità":i["quantita"]}
            for i in db.get_plan_items(plan["id"])
        ]
        st.session_state.note_piano = plan.get("note","")

    tab_build, tab_pdf, tab_macro = st.tabs(["🛠️ Costruzione piano","📄 Importa da PDF","📊 Analisi macro"])

    with tab_build:
        # Inserimento
        scelta = st.radio("Schema:", ["Giorni Fissi","Workout / Rest Day"], horizontal=True)
        lista_giorni = (["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"]
                        if "Fissi" in scelta else ["Workout Day","Rest Day"])

        ci1, ci3, ci4 = st.columns([1,1,0.5])
        pasto_sel = ci1.selectbox("Pasto:", ["Colazione","Spuntino Mattina","Pranzo","Merenda","Cena","Pre-Nanna"])
        is_qb     = ci4.checkbox("Q.B.")
        peso_sel  = 0 if is_qb else ci3.number_input("Peso (g):", 0, step=5)

        # ── RICERCA ALIMENTO ────────────────────────────────────────────────────
        st.markdown("**🔍 Ricerca alimento**")

        fc1, fc2 = st.columns([2, 1])
        query     = fc1.text_input("Cerca per nome o marca:",
            placeholder="es. 'Barilla', 'pollo', 'yogurt greco', 'parmigiano'...",
            label_visibility="collapsed")
        tipo_db   = fc2.radio("Tipo prodotto:", ["Tutti", "Con marca", "Generico"],
            horizontal=True, label_visibility="collapsed")

        if not DATABASE.empty:
            has_m = "Marca" in DATABASE.columns
            df_src = DATABASE.copy()

            # Filtra per tipo
            if has_m and tipo_db == "Con marca":
                df_src = df_src[df_src["Marca"].fillna("").str.strip() != ""]
            elif has_m and tipo_db == "Generico":
                df_src = df_src[df_src["Marca"].fillna("").str.strip() == ""]

            # Filtra per testo
            if query.strip():
                q = query.strip().lower()
                msk = df_src["Alimento_Nome"].str.lower().str.contains(q, na=False)
                if has_m:
                    msk |= df_src["Marca"].fillna("").str.lower().str.contains(q, na=False)
                df_f = df_src[msk].head(200)
            else:
                df_f = df_src.head(100)

            tot = len(df_f)
            if df_f.empty:
                st.warning("Nessun prodotto trovato. Prova con un termine diverso.")
                nomi_f = ["Nessun risultato"]
            else:
                def fmt_riga(r):
                    marca = str(r.get("Marca","")).strip() if has_m else ""
                    nome  = str(r["Alimento_Nome"]).strip()
                    kcal  = r.get("Kcal_100g", 0)
                    kcal_str = f"  [{int(kcal)} kcal]" if kcal else ""
                    return f"{marca} — {nome}{kcal_str}" if marca else f"{nome}{kcal_str}"

                nomi_f = df_f.apply(fmt_riga, axis=1).tolist()
                lim_str = " (primi 200)" if tot == 200 else ""
                st.caption(
                    f"**{tot}** prodotti trovati{lim_str} · "
                    f"{'Con marca' if tipo_db=='Con marca' else 'Generici' if tipo_db=='Generico' else 'Tutti i database'}"
                )
        else:
            nomi_f = ["Database non caricato"]

        alim_label = st.selectbox("Seleziona:", nomi_f, label_visibility="collapsed")

        # Estrai il nome alimento puro (senza marca e senza kcal)
        if " — " in alim_label:
            alim_sel = alim_label.split(" — ")[-1]
        else:
            alim_sel = alim_label
        alim_sel = alim_sel.split("  [")[0].strip()  # rimuovi [kcal]
        giorni_sel = st.multiselect("Giorni:", lista_giorni)

        if st.button("🚀 INSERISCI NEL PIANO", type="primary"):
            if not giorni_sel:
                st.warning("Seleziona almeno un giorno.")
            else:
                for g in giorni_sel:
                    st.session_state.piano_corrente.append(
                        {"Giorno":g,"Pasto":pasto_sel,"Alimento":alim_sel,"Quantità":peso_sel})
                st.rerun()

        st.divider()
        st.subheader("📋 Tabella piano")
        col_sort = st.selectbox("Ordina per:", ["Giorno","Pasto","Alimento"], index=0)
        df_edit  = pd.DataFrame(st.session_state.piano_corrente)
        if not df_edit.empty:
            if col_sort == "Giorno":
                order = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica","Workout Day","Rest Day"]
                df_edit["_o"] = df_edit["Giorno"].apply(lambda x: order.index(x) if x in order else 99)
                df_edit = df_edit.sort_values("_o").drop(columns="_o")
            else:
                df_edit = df_edit.sort_values(col_sort)

        st.session_state.piano_corrente = st.data_editor(
            df_edit, num_rows="dynamic", use_container_width=True,
            column_config={
                "Giorno": st.column_config.SelectboxColumn("Giorno", options=lista_giorni),
                "Pasto":  st.column_config.SelectboxColumn("Pasto",  options=["Colazione","Spuntino Mattina","Pranzo","Merenda","Cena","Pre-Nanna"]),
            }
        ).to_dict("records")

        # Svuota con conferma
        if not st.session_state.get("confirm_svuota"):
            if st.button("🗑️ Svuota piano", type="secondary"):
                st.session_state.confirm_svuota = True; st.rerun()
        else:
            st.warning("Confermi di voler eliminare l'intero piano?")
            cc1, cc2 = st.columns(2)
            if cc1.button("✅ Sì, svuota", type="primary"):
                st.session_state.piano_corrente = []; st.session_state.confirm_svuota = False; st.rerun()
            if cc2.button("❌ Annulla"):
                st.session_state.confirm_svuota = False; st.rerun()

        st.divider()
        st.subheader("📝 Spiegazioni e Consigli")
        st.caption("Questo testo apparirà nella seconda pagina del PDF, prima del piano alimentare.")
        st.session_state.note_piano = st.text_area(
            "Consigli comportamentali, spiegazioni, integrazioni, avvertenze:",
            value=st.session_state.note_piano, height=200,
            placeholder="Es. Gli alimenti devono essere pesati a crudo...\nBere 2L di acqua al giorno..."
        )

        # Frequenza consumo fonti proteiche — solo per dieta flessibile (Workout/Rest Day)
        if "Workout" in scelta:
            st.divider()
            st.subheader("🥩 Frequenza Consumo Fonti Proteiche")
            st.caption("Comparirà nel PDF subito dopo Spiegazioni e Consigli.")
            if "freq_proteiche" not in st.session_state:
                st.session_state.freq_proteiche = ""
            st.session_state.freq_proteiche = st.text_area(
                "Indica la frequenza delle fonti proteiche (carne, pesce, uova, legumi…):",
                value=st.session_state.freq_proteiche, height=150,
                placeholder="Es. Carne rossa: max 2 volte a settimana\nPesce: 3-4 volte a settimana\nUova: 3-4 a settimana..."
            )

        st.divider()

        # Export in cima — disponibili subito prima della tabella
        if st.session_state.piano_corrente:
            ultima_vis = db.get_latest_visit(pid)
            _freq_prot = st.session_state.get("freq_proteiche", "") if "Workout" in scelta else ""
            pdf_d = genera_pdf_dieta(
                st.session_state.piano_corrente, st.session_state.note_piano,
                paziente=p, nutrizionista=st.session_state.user, visita=ultima_vis,
                freq_proteiche=_freq_prot)
            pdf_s = genera_pdf_spesa(
                st.session_state.piano_corrente,
                paziente=p, nutrizionista=st.session_state.user, visita=ultima_vis)
            payload = {"paziente": f"{p.get('cognome','')} {p.get('nome','')}",
                       "data": datetime.now().isoformat(),
                       "dieta": st.session_state.piano_corrente,
                       "note": st.session_state.note_piano}
            ex1, ex2, ex3 = st.columns(3)
            ex1.download_button("📥 PDF Dieta", data=pdf_d,
                file_name=f"dieta_{p.get('cognome','')}.pdf", use_container_width=True)
            ex2.download_button("🛒 PDF Lista Spesa", data=pdf_s,
                file_name=f"spesa_{p.get('cognome','')}.pdf", use_container_width=True)
            ex3.download_button("📋 Export JSON", data=json.dumps(payload, ensure_ascii=False, indent=2),
                file_name="dieta.json", mime="application/json", use_container_width=True)

        st.divider()
        sn1, sn2 = st.columns(2)
        nome_piano = sn1.text_input("Nome piano (es. Fase 1 - Dimagrimento)", value="Piano attivo")
        if sn2.button("💾 SALVA E INVIA PIANO", type="primary", use_container_width=True):
            if not st.session_state.piano_corrente:
                st.error("Il piano è vuoto.")
            else:
                db.save_plan(pid, st.session_state.piano_corrente,
                             st.session_state.note_piano, nome_piano)
                st.success("Piano salvato e reso visibile al paziente.")

    with tab_pdf:
        st.subheader("📄 Importa dieta da PDF")

        # ── Passo 1: tipo di schema ──────────────────────────────────────────
        st.markdown("**1️⃣ Che tipo di dieta contiene il PDF?**")
        tipo_schema_pdf = st.radio(
            "Schema dieta",
            ["📅 Giornaliero (Lunedì → Domenica)", "💪 Flessibile (Workout Day / Rest Day)"],
            horizontal=True,
            label_visibility="collapsed",
            help="Questa scelta guida il parser nella ricerca dei giorni nel testo del PDF."
        )
        is_workout_pdf = "Flessibile" in tipo_schema_pdf

        if is_workout_pdf:
            st.info(
                "Il parser cercherà **Workout Day** e **Rest Day** nel testo. "
                "Se non li trova esplicitamente, puoi assegnarli manualmente nella tabella di anteprima."
            )
            lista_giorni_pdf = ["Workout Day", "Rest Day"]
            giorno_default_pdf = "Workout Day"
        else:
            st.info(
                "Il parser cercherà i **giorni della settimana** (Lunedì, Martedì…). "
                "Se il PDF non li riporta, tutti gli alimenti saranno assegnati a Lunedì — correggili nell'anteprima."
            )
            lista_giorni_pdf = ["Lunedì","Martedì","Mercoledì","Giovedì","Venerdì","Sabato","Domenica"]
            giorno_default_pdf = "Lunedì"

        lista_pasti_pdf = ["Colazione","Spuntino Mattina","Pranzo","Merenda","Cena","Pre-Nanna"]

        st.divider()

        # ── Passo 2: carica il file ──────────────────────────────────────────
        st.markdown("**2️⃣ Carica il file PDF**")
        pdf_file = st.file_uploader("Carica PDF dieta", type=["pdf"],
                                    label_visibility="collapsed")

        if pdf_file:
            pdf_bytes = pdf_file.read()
            with st.spinner("Analisi del PDF in corso..."):
                schema_arg = "flessibile" if is_workout_pdf else "giornaliero"
                estratti, err = parse_diet_pdf(pdf_bytes, tipo_schema=schema_arg)

            if err:
                st.error(err)
            elif not estratti:
                st.warning(
                    "Nessun alimento riconosciuto nel PDF. "
                    "Assicurati che il documento contenga quantità in grammi (es. 'Riso 80g')."
                )
            else:
                # Correggi i giorni in base al tipo di schema scelto
                for item in estratti:
                    item["Alimento"] = _match_alimento_db(item["Alimento"])
                    g = item.get("Giorno", "")
                    if is_workout_pdf:
                        # Se il parser ha trovato giorni della settimana, mappali su Workout/Rest
                        if g not in ("Workout Day", "Rest Day"):
                            item["Giorno"] = giorno_default_pdf
                    else:
                        # Se il parser ha trovato Workout/Rest, mappa su Lunedì
                        if g in ("Workout Day", "Rest Day"):
                            item["Giorno"] = giorno_default_pdf

                n_giorni = len({i["Giorno"] for i in estratti})
                n_pasti  = len({i["Pasto"]  for i in estratti})
                st.success(
                    f"✅ Riconosciuti **{len(estratti)} alimenti** "
                    f"su **{n_giorni} {'giorni' if not is_workout_pdf else 'protocolli'}** "
                    f"e **{n_pasti} tipi di pasto**. Verifica e modifica prima di importare."
                )

                st.markdown("**3️⃣ Verifica e correggi**")
                df_preview = pd.DataFrame(estratti)
                df_editato = st.data_editor(
                    df_preview, num_rows="dynamic", use_container_width=True,
                    column_config={
                        "Giorno":   st.column_config.SelectboxColumn("Giorno",   options=lista_giorni_pdf),
                        "Pasto":    st.column_config.SelectboxColumn("Pasto",    options=lista_pasti_pdf),
                        "Quantità": st.column_config.NumberColumn("Quantità (g)", min_value=0, step=5),
                    },
                    key="pdf_import_editor"
                )

                st.markdown("**4️⃣ Importa nel piano**")
                col_imp, col_agg = st.columns(2)
                if col_imp.button("🔄 Sostituisci piano con questi alimenti", type="primary",
                                  use_container_width=True):
                    st.session_state.piano_corrente = df_editato.to_dict("records")
                    st.success("Piano sostituito con gli alimenti dal PDF.")
                    st.rerun()
                if col_agg.button("➕ Aggiungi al piano esistente", use_container_width=True):
                    st.session_state.piano_corrente.extend(df_editato.to_dict("records"))
                    st.success(f"Aggiunti {len(df_editato)} alimenti al piano.")
                    st.rerun()

    with tab_macro:
        df_m = macros_da_items(st.session_state.piano_corrente)
        if df_m is not None:
            for _, r in df_m.iterrows():
                with st.expander(f"📊 {r['Giorno']}"):
                    m1,m2,m3,m4 = st.columns(4)
                    m1.metric("Energia",f"{int(r['Cal'])} kcal")
                    m2.metric("Proteine",f"{int(r['Pro'])}g")
                    m3.metric("Carboidrati",f"{int(r['Cho'])}g")
                    m4.metric("Grassi",f"{int(r['Fat'])}g")
        else:
            st.info("Aggiungi alimenti al piano per vedere l'analisi dei macronutrienti.")

# ==============================================================================
# ─────────────────────────── MESSAGGI ─────────────────────────────────────────
# ==============================================================================
def page_messaggi_nut():
    pid = st.session_state.sel_patient_id
    p   = db.get_patient(pid)
    st.title(f"💬 Messaggi — {p.get('cognome','')} {p.get('nome','')}")
    db.mark_read(pid, "Nutrizionista")
    msgs = db.get_messages(pid)
    for m in msgs:
        with st.chat_message("assistant" if m["ruolo"]=="Nutrizionista" else "user"):
            st.caption(_dt_slice(m.get("timestamp"), 0, 16)); st.write(f"**{m['ruolo']}**: {m['testo']}")
    st.divider()
    testo = st.text_input("Scrivi al paziente:")
    if st.button("Invia", type="primary"):
        if testo:
            db.send_message(pid, "Nutrizionista", testo); st.rerun()

# ==============================================================================
# ─────────────────────────── ARCHIVIO TEMPLATE ────────────────────────────────
# ==============================================================================
def page_archivio():
    user = st.session_state.user
    st.title("📁 Archivio Template")
    templates = db.get_templates(user["id"])

    tab_salva, tab_carica = st.tabs(["💾 Salva piano corrente","📂 Carica template"])

    with tab_salva:
        st.info("Salva il piano corrente come template riutilizzabile per altri pazienti.")
        if not st.session_state.sel_patient_id:
            st.warning("Seleziona prima un paziente e costruisci un piano.")
        else:
            nome_t = st.text_input("Nome template (es. 'Dimagrimento uomo 30-40')")
            note_t = st.text_area("Descrizione", height=80)
            if st.button("💾 Salva template", type="primary"):
                if nome_t and st.session_state.piano_corrente:
                    db.save_template(user["id"], nome_t, note_t,
                        json.dumps(st.session_state.piano_corrente, ensure_ascii=False))
                    st.success("Template salvato.")
                else:
                    st.error("Inserisci nome e assicurati che il piano non sia vuoto.")

    with tab_carica:
        if not templates:
            st.info("Nessun template salvato.")
        for t in templates:
            c1, c2, c3 = st.columns([4,1,1])
            c1.markdown(f"**{t['nome']}** — {t.get('note','')[:60]}")
            if c2.button("Usa", key=f"use_t_{t['id']}", type="primary"):
                st.session_state.piano_corrente = json.loads(t["items_json"])
                st.session_state.note_piano = t.get("note","")
                st.success(f"Template '{t['nome']}' caricato nel piano corrente.")
                st.rerun()
            if c3.button("🗑️", key=f"del_t_{t['id']}"):
                db.delete_template(t["id"]); st.rerun()

    st.divider()
    st.subheader("📥 Import JSON")
    f_json = st.file_uploader("Carica file .json", type="json")
    if f_json and st.button("🚀 Importa"):
        try:
            raw = json.load(f_json)
            items = raw.get("dieta", raw) if isinstance(raw, dict) else raw
            st.session_state.piano_corrente = items
            st.session_state.note_piano = raw.get("note","") if isinstance(raw,dict) else ""
            st.success("Importato."); st.rerun()
        except Exception as e:
            st.error(f"File non valido: {e}")

# ==============================================================================
# ─────────────────────────── PORTALE PAZIENTE ─────────────────────────────────
# ==============================================================================
def portale_paziente():
    pat   = st.session_state.user
    pid   = pat["id"]
    p_obj = db.get_patient(pid)

    # Sidebar paziente
    _sidebar_logo()
    st.sidebar.markdown(f"""
    <div style='text-align:center;padding:4px 0 10px'>
      <div style='font-size:1em;font-weight:700;color:#fff'>{p_obj.get('nome','')} {p_obj.get('cognome','')}</div>
      <div style='font-size:0.8em;color:#9fa8da'>Portale Paziente</div>
    </div>""", unsafe_allow_html=True)
    st.sidebar.divider()

    nav_p = {"home_p":"🏠 Home","piano_p":"📅 Piano","spesa_p":"🛒 Spesa",
             "carrello_p":"🏪 Carrello Digitale",
             "visita_p":"📊 Dati Visita","msg_p":"💬 Messaggi"}
    for key, label in nav_p.items():
        badge = ""
        if key == "msg_p":
            n = db.unread_count(pid, "Paziente")
            if n: badge = f" 🔴{n}"
        if st.sidebar.button(label+badge, use_container_width=True,
                            type="primary" if st.session_state.page==key else "secondary"):
            st.session_state.page = key; st.rerun()
    st.sidebar.divider()
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        st.session_state.user = None; st.session_state.page = "home_p"; st.rerun()

    page = st.session_state.page
    plan     = db.get_active_plan(pid)
    items    = db.get_plan_items(plan["id"]) if plan else []
    ultima_v = db.get_latest_visit(pid)

    if page in ("home_p", None):
        st.title(f"👋 Ciao, {p_obj.get('nome','')}!")
        c1, c2, c3 = st.columns(3)
        c1.markdown(f"""<div class='metric-card'>
          <div style='color:#666;font-size:0.85em'>PIANO ATTIVO</div>
          <div style='font-size:1.3em;font-weight:700;color:#0A2540'>{'✅ ' + plan.get('nome','') if plan else '—'}</div>
        </div>""", unsafe_allow_html=True)
        c2.markdown(f"""<div class='metric-card' style='border-color:#4caf50'>
          <div style='color:#666;font-size:0.85em'>ULTIMA VISITA</div>
          <div style='font-size:1.3em;font-weight:700;color:#2e7d32'>{ultima_v.get('data','—')}</div>
        </div>""", unsafe_allow_html=True)
        unread = db.unread_count(pid, "Paziente")
        c3.markdown(f"""<div class='metric-card' style='border-color:#ff9800'>
          <div style='color:#666;font-size:0.85em'>MESSAGGI NON LETTI</div>
          <div style='font-size:1.3em;font-weight:700;color:#e65100'>{unread}</div>
        </div>""", unsafe_allow_html=True)

    elif page == "piano_p":
        st.title("📅 Il mio piano alimentare")
        if not items:
            st.info("Il tuo nutrizionista non ha ancora caricato un piano.")
        else:
            vis_paz = db.get_latest_visit(pid)
            nut_paz = db.get_nutritionist(p_obj.get("nutritionist_id", 0))
            pdf_d = genera_pdf_dieta(items, plan.get("note",""),
                paziente=p_obj, nutrizionista=nut_paz, visita=vis_paz)
            st.download_button("📥 Scarica PDF piano alimentare", data=pdf_d,
                               file_name="piano_alimentare.pdf", use_container_width=True,
                               type="primary")
            st.divider()
            if plan.get("note"):
                st.info(f"**Indicazioni del nutrizionista:** {plan['note']}")
            df_p = pd.DataFrame(items)
            df_p["Grammatura"] = df_p["quantita"].apply(lambda q: "Libera" if q==0 else f"{int(q)}g")
            st.table(df_p[["giorno","pasto","alimento","Grammatura"]].rename(
                columns={"giorno":"Giorno","pasto":"Pasto","alimento":"Alimento"}))

    elif page == "spesa_p":
        st.title("🛒 Lista della spesa")
        if not items:
            st.info("Nessun piano attivo.")
        else:
            vis_paz = db.get_latest_visit(pid)
            nut_paz = db.get_nutritionist(p_obj.get("nutritionist_id", 0))
            pdf_s = genera_pdf_spesa(items, paziente=p_obj, nutrizionista=nut_paz, visita=vis_paz)
            st.download_button("📥 Scarica Lista Spesa PDF", data=pdf_s,
                               file_name="lista_spesa.pdf", use_container_width=True,
                               type="primary")
            st.divider()
            agg = {}
            for r in items:
                al = r["alimento"]; q = float(r.get("quantita",0) or 0)
                agg[al] = agg.get(al,0) + q
            for al, qtot in sorted(agg.items()):
                st.write(f"🛒 **{al}**: {'q.b.' if qtot==0 else f'{int(qtot)}g'}")

    elif page == "carrello_p":
        st.title("🏪 Carrello Digitale")
        if not items:
            st.info("Il tuo nutrizionista non ha ancora caricato un piano.")
        else:
            # ── Costruisci lista prodotti aggregata ────────────────────────────
            _VUOTI = {"", "nan", "none", "n/a", "nd"}
            def _str_pulita(val):
                s = str(val).strip() if val is not None else ""
                return "" if s.lower() in _VUOTI else s

            agg = {}
            for r in items:
                al = r["alimento"].strip()
                q  = float(r.get("quantita", 0) or 0)
                if al and al not in ("Nessun risultato", "DB non caricato"):
                    agg[al] = agg.get(al, 0) + q

            prodotti = []
            for al, qtot in sorted(agg.items()):
                row     = DATABASE[DATABASE["Alimento_Nome"] == al] if not DATABASE.empty else pd.DataFrame()
                marca   = _str_pulita(row["Marca"].values[0])   if not row.empty and "Marca"   in DATABASE.columns else ""
                barcode = _str_pulita(row["Barcode"].values[0]) if not row.empty and "Barcode" in DATABASE.columns else ""
                prodotti.append({"nome": al, "marca": marca, "barcode": barcode, "qtot": qtot})

            tot_prodotti = len(prodotti)

            # ── Modalità ───────────────────────────────────────────────────────
            modalita = st.radio("Modalità:", ["🧙 Guidata (uno alla volta)", "📋 Lista completa"],
                                horizontal=True)
            st.divider()

            # Scelta supermercato (comune a entrambe le modalità)
            sup_nomi = list(SUPERMERCATI.keys())
            sup_sel  = st.selectbox(
                "Supermercato:",
                sup_nomi,
                format_func=lambda s: f"{SUPERMERCATI[s]['emoji']} {s}  —  {SUPERMERCATI[s]['note']}"
            )
            sup_conf = SUPERMERCATI[sup_sel]

            # ── Condividi via WhatsApp ─────────────────────────────────────────
            import urllib.parse as _up
            righe_wa = []
            for p in prodotti:
                qtxt = "q.b." if p["qtot"] == 0 else f"{int(p['qtot'])}g"
                nome_wa = f"{p['marca']} {p['nome']}".strip() if p["marca"] else p["nome"]
                righe_wa.append(f"• {nome_wa} — {qtxt}")
            msg_wa = (f"🛒 *Lista della spesa settimanale*\n\n" +
                      "\n".join(righe_wa) +
                      f"\n\n_Generata da NutriNext_")
            wa_url = f"https://wa.me/?text={_up.quote(msg_wa)}"

            st.link_button("💚 Condividi lista su WhatsApp", wa_url, use_container_width=True,
                           help="Apre WhatsApp con tutta la lista pronta da inviare")

            st.divider()

            # ── MODALITÀ GUIDATA ───────────────────────────────────────────────
            if "🧙" in modalita:
                if "wizard_idx" not in st.session_state:
                    st.session_state.wizard_idx = 0
                if "wizard_trovati" not in st.session_state:
                    st.session_state.wizard_trovati = set()

                idx = st.session_state.wizard_idx

                if idx >= tot_prodotti:
                    st.success(f"✅ Spesa completata! Hai cercato tutti i {tot_prodotti} prodotti.")
                    if st.button("🔄 Ricomincia", use_container_width=True):
                        st.session_state.wizard_idx = 0
                        st.session_state.wizard_trovati = set()
                        st.rerun()
                else:
                    p = prodotti[idx]
                    qtxt = "q.b." if p["qtot"] == 0 else f"{int(p['qtot'])}g"
                    nome_display = f"{p['marca']} — {p['nome']}" if p["marca"] else p["nome"]

                    # Barra progresso
                    st.progress(idx / tot_prodotti,
                        text=f"Prodotto {idx+1} di {tot_prodotti}")

                    # Card prodotto corrente
                    st.markdown(f"""
                    <div style='background:#f0f4ff;border-radius:14px;padding:24px 28px;
                         border-left:6px solid #0A2540;margin:12px 0'>
                      <div style='font-size:0.85em;color:#666;margin-bottom:4px'>DA CERCARE</div>
                      <div style='font-size:1.5em;font-weight:700;color:#0A2540'>{nome_display}</div>
                      <div style='font-size:1.1em;color:#555;margin-top:6px'>Quantità: <b>{qtxt}</b></div>
                      {'<div style="font-size:0.8em;color:#888;margin-top:4px">EAN ' + p["barcode"] + '</div>' if p["barcode"] else ''}
                    </div>""", unsafe_allow_html=True)

                    # Bottone cerca
                    url = url_supermercato(sup_sel, p["nome"], p["marca"])
                    st.link_button(
                        f"{sup_conf['emoji']} Cerca su {sup_sel} →",
                        url, use_container_width=True, type="primary"
                    )

                    st.markdown("<br>", unsafe_allow_html=True)
                    c1, c2, c3 = st.columns(3)
                    if c1.button("✅ Trovato, prossimo →", use_container_width=True, type="primary"):
                        st.session_state.wizard_trovati.add(p["nome"])
                        st.session_state.wizard_idx += 1
                        st.rerun()
                    if c2.button("⏭️ Salta", use_container_width=True):
                        st.session_state.wizard_idx += 1
                        st.rerun()
                    if c3.button("⬅️ Torna indietro", use_container_width=True):
                        st.session_state.wizard_idx = max(0, idx - 1)
                        st.rerun()

                    # Prodotti già trovati
                    if st.session_state.wizard_trovati:
                        st.caption(f"✅ Già nel carrello: {', '.join(sorted(st.session_state.wizard_trovati))}")

            # ── MODALITÀ LISTA COMPLETA ────────────────────────────────────────
            else:
                con_marca   = [p for p in prodotti if p["marca"]]
                senza_marca = [p for p in prodotti if not p["marca"]]

                def _riga(p):
                    url  = url_supermercato(sup_sel, p["nome"], p["marca"])
                    qtxt = "q.b." if p["qtot"] == 0 else f"{int(p['qtot'])}g"
                    nome = f"{p['marca']} — {p['nome']}" if p["marca"] else p["nome"]
                    col_info, col_btn = st.columns([3, 1])
                    col_info.markdown(f"**{nome}**  \n`{qtxt}`" +
                                      (f"  ·  EAN `{p['barcode']}`" if p["barcode"] else ""))
                    col_btn.link_button("Cerca →", url, use_container_width=True)

                if con_marca:
                    st.subheader(f"🏷️ Con marca  ({len(con_marca)})")
                    for p in con_marca:
                        _riga(p)
                if senza_marca:
                    st.divider()
                    st.subheader(f"🥬 Generici  ({len(senza_marca)})")
                    for p in senza_marca:
                        _riga(p)

    elif page == "visita_p":
        st.title("📊 I miei dati")
        if not ultima_v:
            st.info("Nessun dato visita disponibile.")
        else:
            dc1,dc2 = st.columns(2)
            dc1.metric("Peso", f"{float(ultima_v.get('peso',0)):.2f} kg")
            dc2.metric("Altezza", f"{ultima_v.get('altezza','—')} cm")
            if ultima_v.get("FFM"):
                bia_p = {k: ultima_v.get(k,0) for k in ["PhA","TBW","ECW","ICW","FFM","FM","FM%","BCM","SMM","ASMM"]}
                st.markdown(render_bia_table(bia_p, float(ultima_v["peso"]),
                    ultima_v.get("sesso","M"), bmr=ultima_v.get("BMR")), unsafe_allow_html=True)
                if ultima_v.get("R") and ultima_v.get("Xc"):
                    st.plotly_chart(plot_biavector(ultima_v["R"],ultima_v["Xc"],ultima_v["altezza"]),
                        use_container_width=True)

    elif page == "msg_p":
        st.title("💬 Messaggi")
        db.mark_read(pid, "Paziente")
        for m in db.get_messages(pid):
            with st.chat_message("user" if m["ruolo"]=="Paziente" else "assistant"):
                st.caption(_dt_slice(m.get("timestamp"), 0, 16)); st.write(f"**{m['ruolo']}**: {m['testo']}")
        st.divider()
        testo = st.text_input("Scrivi al nutrizionista:")
        if st.button("Invia", type="primary"):
            if testo:
                db.send_message(pid, "Paziente", testo); st.rerun()

# ==============================================================================
# ==============================================================================
# ─────────────────────── REGISTRAZIONE PAZIENTE ───────────────────────────────
# ==============================================================================

def _qr_image(url: str):
    """Genera un'immagine PNG del QR code per l'URL dato."""
    qr = qrcode.QRCode(version=1, box_size=8, border=3)
    qr.add_data(url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="#0A2540", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)
    return buf

def _form_registrazione(nutritionist_id: int, token: str = ""):
    """Form di registrazione paziente condiviso dai tre metodi."""
    nut = db.get_nutritionist(nutritionist_id)
    st.success(f"Stai registrandoti con **Dr. {nut.get('nome','')} {nut.get('cognome','')}**")
    st.divider()

    f1, f2 = st.columns(2)
    nome    = f1.text_input("Nome *")
    cognome = f2.text_input("Cognome")
    f3, f4, f5 = st.columns(3)
    sesso   = f3.selectbox("Sesso", ["M", "F"])
    data_n  = f4.date_input("Data di nascita", value=date(1990, 1, 1))
    email   = f5.text_input("Email")

    st.subheader("Credenziali di accesso")
    u1, u2, u3 = st.columns(3)
    username = u1.text_input("Username *")
    pw1      = u2.text_input("Password *", type="password")
    pw2      = u3.text_input("Conferma password *", type="password")

    if st.button("✅ Registrati", type="primary", use_container_width=True):
        if not all([nome, username, pw1]):
            st.error("Compila tutti i campi obbligatori (*).")
        elif " " in username:
            st.error("Lo username non può contenere spazi.")
        elif pw1 != pw2:
            st.error("Le password non coincidono.")
        else:
            ok, msg = db.submit_patient_request(
                nutritionist_id, nome, cognome, email, sesso,
                str(data_n), username, pw1
            )
            if ok:
                if token:
                    db.use_token(token)
                st.success(f"✅ {msg}")
                st.balloons()
                st.info("Potrai accedere non appena il tuo nutrizionista approverà la richiesta.")
            else:
                st.error(msg)

def page_registrazione():
    """Pagina pubblica di registrazione — gestisce i 3 metodi."""
    params = st.query_params

    col_l, col_c, col_r = st.columns([1, 2, 1])
    with col_c:
        st.image(_img("logos/logo_login.png"), use_container_width=True)
    st.markdown("""
    <div style='text-align:center;padding:6px 0 16px'>
      <p style='color:#666;font-size:1.1em'>Registrazione Paziente</p>
    </div>""", unsafe_allow_html=True)

    # Metodo 3 — QR code permanente (?studio=CODE)
    if "studio" in params:
        nut = db.get_nutritionist_by_code(params["studio"])
        if not nut:
            st.error("Codice studio non valido.")
            return
        _form_registrazione(nut["id"])
        return

    # Metodo 2 — link temporaneo (?token=XXX)
    if "token" in params:
        token = params["token"]
        info  = db.get_token_info(token)
        if not info:
            st.error("Link non valido o scaduto. Chiedi un nuovo link al tuo nutrizionista.")
            return
        _form_registrazione(info["nutritionist_id"], token=token)
        return

    # Metodo 1 — ricerca per codice studio
    st.subheader("Inserisci il codice del tuo nutrizionista")
    st.caption("Il codice è fornito direttamente dal tuo nutrizionista (6 caratteri, es. AB12CD)")
    col1, col2 = st.columns([2, 1])
    codice = col1.text_input("Codice studio", placeholder="Es. AB12CD",
                              max_chars=6).upper().strip()
    if col2.button("Cerca", type="primary", use_container_width=True):
        if codice:
            st.session_state["reg_nut_code"] = codice

    if st.session_state.get("reg_nut_code"):
        nut = db.get_nutritionist_by_code(st.session_state["reg_nut_code"])
        if not nut:
            st.error("Nessun nutrizionista trovato con questo codice.")
        else:
            _form_registrazione(nut["id"])

    st.divider()
    if st.button("← Torna al login"):
        st.query_params.clear()
        st.session_state["show_register"] = False
        st.rerun()


# ==============================================================================
# ─────────────── SEZIONE INVITI (nel pannello nutrizionista) ──────────────────
# ==============================================================================

def page_inviti():
    user = st.session_state.user
    st.title("🔗 Invita Pazienti")

    # URL base: prende APP_URL da env (Railway), fallback all'header HTTP
    base_url = os.environ.get("APP_URL", "").rstrip("/")
    if not base_url:
        # Ricava l'URL dall'header della richiesta corrente
        try:
            headers = st.context.headers
            host = headers.get("host", "localhost:8501")
            proto = "https" if "railway.app" in host or "up.railway" in host else "http"
            base_url = f"{proto}://{host}"
        except Exception:
            base_url = "http://localhost:8501"

    st.divider()

    # ── CODICE STUDIO ──────────────────────────────────────────────────────────
    st.subheader("1️⃣ Codice Studio")
    st.caption("Il paziente apre l'app, va su 'Registrati' e inserisce questo codice.")
    code = user.get("studio_code", "—")
    st.markdown(f"""
    <div style='background:#e8eaf6;border-radius:12px;padding:20px 30px;text-align:center;
         display:inline-block;min-width:200px;margin:10px 0'>
      <div style='color:#666;font-size:0.85em;margin-bottom:6px'>CODICE STUDIO</div>
      <div style='font-size:2.8em;font-weight:900;letter-spacing:8px;color:#0A2540'>{code}</div>
    </div>""", unsafe_allow_html=True)

    st.divider()

    # ── QR CODE PERMANENTE ─────────────────────────────────────────────────────
    st.subheader("2️⃣ QR Code da Studio (permanente)")
    st.caption("Collegato al tuo codice studio — non scade mai. Stampalo e mettilo sulla scrivania o in sala d'attesa.")

    qr_url = f"{base_url}/?studio={code}"
    st.text_input("URL di registrazione permanente:", value=qr_url, disabled=True)

    if HAS_QR:
        buf_perm = _qr_image(qr_url)
        col_qr, col_info = st.columns([1, 2])
        col_qr.image(buf_perm, width=200)
        col_info.markdown(f"""
        **Come funziona:**
        1. Il paziente scansiona il QR con il telefono
        2. Si apre la pagina di registrazione
        3. Il tuo studio è già pre-selezionato
        4. Il paziente compila i dati e invia la richiesta
        5. Tu approvi dalla sezione "Richieste in attesa" qui sotto

        ✅ Questo QR non scade mai — puoi stamparlo una volta sola.
        """)
        st.download_button("📥 Scarica QR Code (PNG)", data=buf_perm,
                           file_name=f"qr_studio_{code}.png", mime="image/png")
    else:
        st.warning("Libreria qrcode non disponibile. Installa con: pip3 install 'qrcode[pil]'")

    st.divider()

    # ── LINK TEMPORANEO ────────────────────────────────────────────────────────
    st.subheader("3️⃣ Link temporaneo (via email / WhatsApp)")
    st.caption("Per un accesso diretto usa un link con scadenza. Valido per un solo utilizzo.")

    col_d, col_btn = st.columns([1, 1])
    days = col_d.selectbox("Validità", [1, 3, 7, 14, 30], index=2,
                            format_func=lambda d: f"{d} giorno{'i' if d>1 else ''}")
    if col_btn.button("🔗 Genera link", type="primary", use_container_width=True):
        token = db.create_invite_token(user["id"], days_valid=days)
        st.session_state["last_token"] = token

    if st.session_state.get("last_token"):
        token   = st.session_state["last_token"]
        tmp_url = f"{base_url}/?token={token}"
        st.text_input("Link (copialo e invialo):", value=tmp_url)
        st.caption(f"Scade tra {days} giorni · Un solo utilizzo")

    st.divider()

    # ── RICHIESTE IN ATTESA ────────────────────────────────────────────────────
    st.subheader("📬 Richieste di registrazione in attesa")
    requests = db.get_pending_requests(user["id"])
    if not requests:
        st.info("Nessuna richiesta in attesa.")
    for req in requests:
        with st.container():
            c1, c2, c3 = st.columns([4, 1, 1])
            c1.markdown(
                f"**{req['cognome']} {req['nome']}** — {req.get('email','—')} "
                f"— {req.get('sesso','—')} — Arrivata: {req['created_at'][:10]}"
            )
            if c2.button("✅ Approva", key=f"appr_{req['id']}", type="primary"):
                db.approve_request(req["id"])
                st.success(f"{req['nome']} approvato!")
                st.rerun()
            if c3.button("❌ Rifiuta", key=f"rif_{req['id']}"):
                db.reject_request(req["id"])
                st.rerun()


# ==============================================================================
# ==============================================================================
# ─────────────────────── SEGNALAZIONE BUG (nutrizionista) ────────────────────
# ==============================================================================

def widget_segnala_bug():
    """Widget compatto nel profilo per segnalare un bug."""
    with st.expander("🐛 Segnala un problema al team NutriNext"):
        user = st.session_state.user
        titolo = st.text_input("Titolo breve del problema")
        cat    = st.selectbox("Categoria", ["Generale","BIA / Calcoli","Piano Dieta",
                                             "PDF","Carrello","Pazienti","Agenda","Altro"])
        prio   = st.selectbox("Urgenza", ["Bassa","Media","Alta","Critica"])
        desc   = st.text_area("Descrivi il problema in dettaglio", height=100)
        if st.button("📤 Invia segnalazione", type="primary"):
            if titolo and desc:
                db.submit_bug(user["id"], titolo, desc, cat, prio)
                st.success("✅ Segnalazione inviata. Il team NutriNext la esaminerà presto.")
            else:
                st.warning("Compila titolo e descrizione.")


# ==============================================================================
# ─────────────────────────── ADMIN DASHBOARD ──────────────────────────────────
# ==============================================================================

def page_admin_setup():
    st.markdown("<br><br>", unsafe_allow_html=True)
    c = st.columns([1,2,1])[1]
    with c:
        st.markdown("## 🔐 NutriNext — Admin Setup")
        st.warning("Nessun superadmin configurato. Crea l'account amministratore.")
        nome    = st.text_input("Nome")
        cognome = st.text_input("Cognome")
        uname   = st.text_input("Username admin")
        pw      = st.text_input("Password", type="password")
        pw2     = st.text_input("Conferma password", type="password")
        if st.button("Crea account admin", type="primary", use_container_width=True):
            if not all([nome, uname, pw]):
                st.error("Compila tutti i campi.")
            elif pw != pw2:
                st.error("Le password non coincidono.")
            else:
                db.setup_superadmin(uname, pw, nome, cognome)
                st.success("Admin creato. Accedi con le tue credenziali.")
                st.rerun()

def sidebar_admin():
    user = st.session_state.user
    _sidebar_logo()
    st.sidebar.markdown(f"""
    <div style='text-align:center;padding:4px 0 10px'>
      <div style='font-size:0.8em;color:#9fa8da'>Admin — {user.get('nome','')} {user.get('cognome','')}</div>
    </div>""", unsafe_allow_html=True)
    st.sidebar.divider()
    # Conta richieste in attesa per badge
    pending_nut = len(db.get_pending_nutritionist_requests())
    badge = f" 🔴" if pending_nut > 0 else ""
    nav = {
        "admin_overview":       "📊  Overview piattaforma",
        "admin_nutrizionisti":  "👨‍⚕️  Nutrizionisti",
        "admin_richieste_nut":  f"📋  Richieste Nutrizionisti{badge}",
        "admin_pazienti":       "👥  Cerca Pazienti",
        "admin_bugs":           "🐛  Bug Report",
    }
    for key, label in nav.items():
        active = st.session_state.page == key
        if st.sidebar.button(label, use_container_width=True,
                             type="primary" if active else "secondary"):
            st.session_state.page = key
            st.rerun()
    st.sidebar.divider()
    if st.sidebar.button("🚪 Logout", use_container_width=True):
        st.session_state.user = None
        st.session_state.page = "admin_overview"
        st.rerun()

def page_admin_overview():
    st.title("📊 Overview Piattaforma NutriNext")
    stats = db.get_platform_stats()

    c1,c2,c3 = st.columns(3)
    c1.markdown(f"""<div class='metric-card'>
      <div style='color:#666;font-size:0.85em'>NUTRIZIONISTI</div>
      <div style='font-size:2.5em;font-weight:700;color:#0A2540'>{stats['tot_nutrizionisti']}</div>
    </div>""", unsafe_allow_html=True)
    c2.markdown(f"""<div class='metric-card' style='border-color:#4caf50'>
      <div style='color:#666;font-size:0.85em'>PAZIENTI TOTALI</div>
      <div style='font-size:2.5em;font-weight:700;color:#2e7d32'>{stats['tot_pazienti']}</div>
    </div>""", unsafe_allow_html=True)
    c3.markdown(f"""<div class='metric-card' style='border-color:#f44336'>
      <div style='color:#666;font-size:0.85em'>BUG APERTI</div>
      <div style='font-size:2.5em;font-weight:700;color:#c62828'>{stats['bug_aperti']}</div>
    </div>""", unsafe_allow_html=True)

    st.markdown("<br>", unsafe_allow_html=True)
    c4,c5,c6 = st.columns(3)
    c4.metric("Piani dieta creati", stats["tot_piani"])
    c5.metric("Visite registrate",  stats["tot_visite"])
    c6.metric("Messaggi scambiati", stats["tot_messaggi"])

    st.divider()
    st.subheader("🐛 Ultimi bug aperti")
    bugs = [b for b in db.get_all_bugs() if b.get("stato") == "Aperto"][:5]
    if not bugs:
        st.success("Nessun bug aperto al momento.")
    for b in bugs:
        prio_col = {"Critica":"#f44336","Alta":"#ff9800","Media":"#2196f3","Bassa":"#4caf50"}.get(b.get("priorita","Media"),"#666")
        st.markdown(f"""<div style='border-left:4px solid {prio_col};padding:8px 14px;
            background:#fff;border-radius:6px;margin-bottom:8px'>
            <b>{b.get('titolo','')}</b> · <span style='color:{prio_col}'>{b.get('priorita','')}</span>
            · {b.get('nut_nome','')} {b.get('nut_cognome','')}
            <span style='color:#888;font-size:0.85em'> · {str(b.get('created_at',''))[:16]}</span>
        </div>""", unsafe_allow_html=True)

def page_admin_nutrizionisti():
    st.title("👨‍⚕️ Nutrizionisti Registrati")
    nuts = db.get_all_nutritionists()
    search = st.text_input("🔍 Cerca", placeholder="Nome, cognome, email...")
    if search:
        q = search.lower()
        nuts = [n for n in nuts if q in (str(n.get("nome",""))+str(n.get("cognome",""))+str(n.get("email_studio",""))).lower()]

    st.caption(f"{len(nuts)} nutrizionisti")
    for n in nuts:
        is_active = n.get("is_active", 1)
        stato_label = "✅ Attivo" if is_active else "⛔ Sospeso"
        with st.expander(f"{stato_label} — **{n.get('cognome','')} {n.get('nome','')}** — {n.get('specializzazione','')} — {n.get('email_studio','—')}"):
            c1,c2,c3,c4 = st.columns(4)
            c1.metric("Pazienti",       n.get("n_pazienti",0))
            c2.metric("Piani creati",   n.get("n_piani",0))
            c3.metric("Bug aperti",     n.get("n_bug_aperti",0))
            c4.metric("Codice studio",  n.get("studio_code","—"))
            st.caption(f"Registrato: {str(n.get('created_at',''))[:10]}  ·  "
                       f"Ultimo accesso: {str(n.get('last_login','mai'))[:16]}")
            st.divider()
            ba, bb, bc = st.columns(3)
            if is_active:
                if ba.button("⛔ Sospendi", key=f"sosp_{n['id']}", use_container_width=True):
                    db.set_nutritionist_active(n["id"], False)
                    st.success("Nutrizionista sospeso."); st.rerun()
            else:
                if ba.button("✅ Riattiva", key=f"riatt_{n['id']}", use_container_width=True, type="primary"):
                    db.set_nutritionist_active(n["id"], True)
                    st.success("Nutrizionista riattivato."); st.rerun()
            # Eliminazione con doppia conferma
            if not st.session_state.get(f"confirm_del_nut_{n['id']}"):
                if bb.button("🗑️ Elimina", key=f"del_nut_{n['id']}", use_container_width=True):
                    st.session_state[f"confirm_del_nut_{n['id']}"] = True; st.rerun()
            else:
                bb.warning(f"Eliminare **{n.get('nome','')}** e tutti i suoi dati?")
                cd1, cd2 = st.columns(2)
                if cd1.button("✅ Conferma eliminazione", key=f"confirm_yes_{n['id']}", type="primary"):
                    db.delete_nutritionist_admin(n["id"])
                    st.session_state.pop(f"confirm_del_nut_{n['id']}", None)
                    st.success("Nutrizionista eliminato."); st.rerun()
                if cd2.button("❌ Annulla", key=f"confirm_no_{n['id']}"):
                    st.session_state.pop(f"confirm_del_nut_{n['id']}", None); st.rerun()

def page_admin_pazienti():
    st.title("👥 Cerca Pazienti")
    query = st.text_input("🔍 Cerca per nome, cognome o username", placeholder="es. Mario Rossi")
    if not query:
        st.info("Inserisci almeno un termine per cercare.")
        return
    results = db.search_patients(query)
    st.caption(f"{len(results)} risultati per «{query}»")
    if not results:
        st.warning("Nessun paziente trovato.")
        return
    for p in results:
        nome_completo = f"{p.get('cognome','')} {p.get('nome','')}".strip()
        nut = f"{p.get('nut_cognome','')} {p.get('nut_nome','')}".strip()
        with st.expander(f"**{nome_completo}** — username: `{p.get('username','—')}` — Nutrizionista: {nut}"):
            c1, c2, c3 = st.columns(3)
            c1.markdown(f"**Username:** `{p.get('username','—')}`")
            c1.markdown(f"**Email:** {p.get('email','—')}")
            c1.markdown(f"**Telefono:** {p.get('telefono','—')}")
            c2.markdown(f"**Sesso:** {p.get('sesso','—')}")
            c2.markdown(f"**Data nascita:** {p.get('data_nascita','—')}")
            c2.markdown(f"**Registrato:** {str(p.get('created_at',''))[:10]}")
            c3.markdown(f"**Nutrizionista:** {nut}")
            c3.markdown(f"**Codice studio:** `{p.get('studio_code','—')}`")
            c3.markdown(f"**Email studio:** {p.get('nut_email','—')}")
            st.divider()
            if not st.session_state.get(f"confirm_del_paz_{p['id']}"):
                if st.button("🗑️ Elimina paziente", key=f"del_paz_{p['id']}"):
                    st.session_state[f"confirm_del_paz_{p['id']}"] = True; st.rerun()
            else:
                st.warning(f"Eliminare **{nome_completo}** e tutti i suoi dati (visite, piani, messaggi)?")
                dp1, dp2 = st.columns(2)
                if dp1.button("✅ Conferma eliminazione", key=f"delp_yes_{p['id']}", type="primary"):
                    db.delete_patient_admin(p["id"])
                    st.session_state.pop(f"confirm_del_paz_{p['id']}", None)
                    st.success("Paziente eliminato."); st.rerun()
                if dp2.button("❌ Annulla", key=f"delp_no_{p['id']}"):
                    st.session_state.pop(f"confirm_del_paz_{p['id']}", None); st.rerun()


def page_admin_richieste_nut():
    st.title("📋 Richieste Registrazione Nutrizionisti")

    tab_attesa, tab_storico = st.tabs(["⏳ In attesa", "📁 Storico"])

    with tab_attesa:
        requests = db.get_pending_nutritionist_requests()
        if not requests:
            st.success("✅ Nessuna richiesta in attesa.")
        else:
            st.caption(f"{len(requests)} richieste in attesa di approvazione")
        for req in requests:
            with st.container():
                st.markdown(f"""
                <div style='border:1px solid #e0e0e0;border-radius:10px;padding:16px;margin-bottom:12px;background:#fff'>
                  <b style='font-size:1.1em'>{req.get('cognome','')} {req.get('nome','')}</b>
                  &nbsp;·&nbsp; {req.get('specializzazione','—')}
                  &nbsp;·&nbsp; <span style='color:#666'>@{req.get('username','')}</span><br>
                  <span style='color:#888;font-size:0.9em'>
                    📧 {req.get('email_studio','—')} &nbsp;·&nbsp;
                    📞 {req.get('telefono','—')} &nbsp;·&nbsp;
                    📅 {str(req.get('created_at',''))[:10]}
                  </span>
                </div>""", unsafe_allow_html=True)

                c1, c2, c3 = st.columns([2, 1, 1])
                motivo = c1.text_input("Motivo rifiuto (opzionale)", key=f"note_nut_{req['id']}")
                if c2.button("✅ Approva", key=f"appr_nut_{req['id']}", type="primary", use_container_width=True):
                    db.approve_nutritionist_request(req["id"])
                    st.success(f"✅ {req.get('nome','')} approvato! Account creato.")
                    st.rerun()
                if c3.button("❌ Rifiuta", key=f"rif_nut_{req['id']}", use_container_width=True):
                    db.reject_nutritionist_request(req["id"], motivo)
                    st.warning("Richiesta rifiutata.")
                    st.rerun()

    with tab_storico:
        all_req = db.get_all_nutritionist_requests()
        processed = [r for r in all_req if r.get("stato") != "In attesa"]
        if not processed:
            st.info("Nessuna richiesta elaborata.")
        for req in processed:
            stato = req.get("stato","")
            col = "#4caf50" if stato == "Approvato" else "#f44336"
            st.markdown(f"""
            <div style='border-left:4px solid {col};padding:8px 14px;
                background:#fff;border-radius:6px;margin-bottom:8px'>
              <b>{req.get('cognome','')} {req.get('nome','')}</b>
              · @{req.get('username','')}
              · <span style='color:{col}'>{stato}</span>
              <span style='color:#888;font-size:0.85em'> · {str(req.get('created_at',''))[:10]}</span>
              {f"<br><i style='color:#888;font-size:0.85em'>Nota: {req.get('admin_note','')}</i>" if req.get('admin_note') else ''}
            </div>""", unsafe_allow_html=True)


def page_admin_bugs():
    st.title("🐛 Bug Report")

    filtro = st.radio("Stato:", ["Tutti","Aperto","In lavorazione","Risolto"], horizontal=True)
    stato_q = None if filtro == "Tutti" else filtro
    bugs = db.get_all_bugs(stato=stato_q)

    if not bugs:
        st.success("Nessun bug trovato per il filtro selezionato.")
        return

    st.caption(f"{len(bugs)} segnalazioni")
    PRIO_COL = {"Critica":"#f44336","Alta":"#ff9800","Media":"#2196f3","Bassa":"#4caf50"}
    STATO_COL = {"Aperto":"#f44336","In lavorazione":"#ff9800","Risolto":"#4caf50"}

    for b in bugs:
        p_col = PRIO_COL.get(b.get("priorita","Media"),"#666")
        s_col = STATO_COL.get(b.get("stato","Aperto"),"#666")
        with st.expander(
            f"[{b.get('priorita','')}] {b.get('titolo','')} — "
            f"{b.get('nut_nome','')} {b.get('nut_cognome','')} — {str(b.get('created_at',''))[:10]}"
        ):
            st.markdown(f"""
            <span style='background:{p_col};color:white;padding:2px 8px;border-radius:4px;font-size:0.8em'>{b.get('priorita','')}</span>
            <span style='background:{s_col};color:white;padding:2px 8px;border-radius:4px;font-size:0.8em;margin-left:6px'>{b.get('stato','')}</span>
            <span style='background:#607d8b;color:white;padding:2px 8px;border-radius:4px;font-size:0.8em;margin-left:6px'>{b.get('categoria','')}</span>
            """, unsafe_allow_html=True)
            st.markdown(f"**Descrizione:** {b.get('descrizione','')}")
            if b.get("admin_note"):
                st.info(f"**Nota admin:** {b['admin_note']}")

            st.divider()
            col_s, col_n, col_btn = st.columns([1,2,1])
            nuovo_stato = col_s.selectbox("Stato", ["Aperto","In lavorazione","Risolto"],
                index=["Aperto","In lavorazione","Risolto"].index(b.get("stato","Aperto")),
                key=f"stato_{b['id']}")
            nota = col_n.text_input("Nota per il nutrizionista", value=b.get("admin_note",""),
                key=f"nota_{b['id']}")
            if col_btn.button("💾 Aggiorna", key=f"upd_{b['id']}", type="primary", use_container_width=True):
                db.update_bug(b["id"], nuovo_stato, nota)
                st.success("Aggiornato.")
                st.rerun()


# ==============================================================================
# ─────────────────────────── ROUTING PRINCIPALE ───────────────────────────────
# ==============================================================================

# Gestisci token nell'URL anche se l'utente non è loggato
params = st.query_params
_has_token     = "token" in params or "studio" in params
_show_register = st.session_state.get("show_register", False) or _has_token
_show_reg_nut  = st.session_state.get("show_register_nut", False)

# Primo avvio: nessun nutrizionista E nessun superadmin
if not db.has_nutritionist() and not db.has_superadmin():
    page_setup()

elif _show_reg_nut:
    page_registrazione_nutrizionista()

elif _show_register or "token" in params or "studio" in params:
    if not st.session_state.get("reg_nut_code"):
        st.session_state["reg_nut_code"] = None
    page_registrazione()

elif st.session_state.user is None:
    page_login()
    st.divider()
    if st.button("Non hai un account? **Registrati come Paziente**", use_container_width=True):
        st.session_state["show_register"] = True
        st.rerun()

elif st.session_state.user.get("role") == "superadmin":
    # ── Admin NutriNext ────────────────────────────────────────────────────────
    if not db.has_superadmin():
        page_admin_setup()
    else:
        sidebar_admin()
        page = st.session_state.get("page", "admin_overview")
        if page == "admin_nutrizionisti":
            page_admin_nutrizionisti()
        elif page == "admin_richieste_nut":
            page_admin_richieste_nut()
        elif page == "admin_pazienti":
            page_admin_pazienti()
        elif page == "admin_bugs":
            page_admin_bugs()
        else:
            page_admin_overview()

elif st.session_state.user.get("role") == "patient" or st.session_state.user.get("_patient"):
    portale_paziente()

else:
    # ── Nutrizionista ──────────────────────────────────────────────────────────
    sidebar_nutrizionista()
    page = st.session_state.page

    # Aggiungi widget segnalazione bug nel profilo
    if page == "profilo":
        page_profilo()
        widget_segnala_bug()
    elif page == "dashboard":
        page_dashboard()
    elif page == "agenda":
        page_agenda()
    elif page == "pazienti":
        page_pazienti()
    elif page == "archivio":
        page_archivio()
    elif page == "inviti":
        page_inviti()
    elif page == "visita" and st.session_state.sel_patient_id:
        page_visita()
    elif page == "piano" and st.session_state.sel_patient_id:
        page_piano()
    elif page == "messaggi" and st.session_state.sel_patient_id:
        page_messaggi_nut()
    else:
        page_dashboard()
