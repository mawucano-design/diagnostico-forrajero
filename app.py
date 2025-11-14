# app.py
"""
App completa actualizada: análisis forrajero + exportes + informe DOCX con recomendaciones
(técnicas + prácticas regenerativas) y descarga automática.
"""

import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime, timedelta
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.colors import LinearSegmentedColormap
import io
from shapely.geometry import Polygon
import math
import base64
import hashlib
import streamlit.components.v1 as components

# Intento importar python-docx
try:
    from docx import Document
    from docx.shared import Inches
    DOCX_AVAILABLE = True
except Exception:
    DOCX_AVAILABLE = False

# Folium (opcional)
try:
    import folium
    from streamlit_folium import st_folium
    FOLIUM_AVAILABLE = True
except Exception:
    FOLIUM_AVAILABLE = False
    folium = None
    st_folium = None

# Streamlit config
st.set_page_config(page_title="🌱 Disponibilidad Forrajera PRV", layout="wide")
st.title("🌱 Disponibilidad Forrajera PRV — Analizador Forrajero")
st.markdown("---")
os.environ['SHAPE_RESTORE_SHX'] = 'YES'

# ---------- AUTENTICACIÓN ----------
def check_authentication():
    """Verifica las credenciales de autenticación"""
    default_users = {
        "admin": hashlib.sha256("password123".encode()).hexdigest(),
        "user": hashlib.sha256("user123".encode()).hexdigest(),
        "tech": hashlib.sha256("tech123".encode()).hexdigest()
    }
    return default_users

def login_section():
    """Sección de login"""
    st.title("🔐 Inicio de Sesión - Analizador Forrajero PRV")
    st.markdown("---")
    
    users_db = check_authentication()
    
    with st.form("login_form"):
        username = st.text_input("Usuario")
        password = st.text_input("Contraseña", type="password")
        submit = st.form_submit_button("Iniciar Sesión")
        
        if submit:
            if username in users_db:
                hashed_password = hashlib.sha256(password.encode()).hexdigest()
                if users_db[username] == hashed_password:
                    st.session_state.authenticated = True
                    st.session_state.username = username
                    st.success(f"✅ Bienvenido, {username}!")
                    st.rerun()
                else:
                    st.error("❌ Contraseña incorrecta")
            else:
                st.error("❌ Usuario no encontrado")
    
    with st.expander("ℹ️ Información de acceso demo"):
        st.markdown("""
        **Usuarios de prueba:**
        - **admin** / password123
        - **user** / user123  
        - **tech** / tech123
        """)

# ---------- Session state ----------
for key in [
    'authenticated', 'username', 'gdf_cargado', 'gdf_analizado', 'mapa_detallado_bytes',
    'docx_buffer', 'analisis_completado', 'html_download_injected'
]:
    if key not in st.session_state:
        if key == 'authenticated':
            st.session_state[key] = False
        elif key == 'username':
            st.session_state[key] = ""
        else:
            st.session_state[key] = None

# Si no está autenticado, mostrar login
if not st.session_state.authenticated:
    login_section()
    st.stop()

# ---------- Parámetros por defecto ----------
ms_optimo = 4000
crecimiento_diario = 80
consumo_porcentaje = 0.025
tasa_utilizacion = 0.55
umbral_ndvi_suelo = 0.15
umbral_ndvi_pastura = 0.6

# -----------------------
# SIDEBAR (CONFIGURACIÓN)
# -----------------------
with st.sidebar:
    st.header(f"👋 Bienvenido, {st.session_state.username}")
    
    if st.button("🚪 Cerrar Sesión"):
        for key in st.session_state.keys():
            del st.session_state[key]
        st.rerun()
    
    st.markdown("---")
    st.header("⚙️ Configuración")
    if FOLIUM_AVAILABLE:
        st.subheader("🗺️ Mapa Base")
        base_map_option = st.selectbox(
            "Seleccionar mapa base:",
            ["ESRI Satélite", "OpenStreetMap", "CartoDB Positron"],
            index=0
        )
    else:
        base_map_option = "ESRI Satélite"

    st.subheader("🛰️ Fuente de Datos Satelitales")
    fuente_satelital = st.selectbox(
        "Seleccionar satélite:",
        ["SENTINEL-2", "LANDSAT-8", "LANDSAT-9", "SIMULADO"],
    )

    tipo_pastura = st.selectbox("Tipo de Pastura:",
                               ["ALFALFA", "RAYGRASS", "FESTUCA", "AGROPIRRO", "PASTIZAL_NATURAL", "PERSONALIZADO"])

    st.subheader("📅 Configuración Temporal")
    fecha_imagen = st.date_input(
        "Fecha de imagen satelital:",
        value=datetime.now() - timedelta(days=30),
        max_value=datetime.now()
    )
    nubes_max = st.slider("Máximo % de nubes permitido:", 0, 100, 20)

    st.subheader("🌿 Parámetros de Detección de Vegetación")
    umbral_ndvi_minimo = st.slider("Umbral NDVI mínimo vegetación:", 0.05, 0.3, 0.15, 0.01)
    umbral_ndvi_optimo = st.slider("Umbral NDVI vegetación óptima:", 0.4, 0.8, 0.6, 0.01)
    sensibilidad_suelo = st.slider("Sensibilidad detección suelo:", 0.1, 1.0, 0.5, 0.1)

    if tipo_pastura == "PERSONALIZADO":
        st.subheader("📊 Parámetros Forrajeros Personalizados")
        ms_optimo = st.number_input("Biomasa Óptima (kg MS/ha):", min_value=1000, max_value=10000, value=4000)
        crecimiento_diario = st.number_input("Crecimiento Diario (kg MS/ha/día):", min_value=10, max_value=300, value=80)
        consumo_porcentaje = st.number_input("Consumo (% peso vivo):", min_value=0.01, max_value=0.05,
                                            value=0.025, step=0.001, format="%.3f")
        tasa_utilizacion = st.number_input("Tasa Utilización:", min_value=0.3, max_value=0.8, value=0.55, step=0.01,
                                          format="%.2f")
        umbral_ndvi_suelo = st.number_input("Umbral NDVI Suelo:", min_value=0.05, max_value=0.3, value=0.15, step=0.01,
                                            format="%.2f")
        umbral_ndvi_pastura = st.number_input("Umbral NDVI Pastura:", min_value=0.3, max_value=0.8, value=0.6, step=0.01,
                                              format="%.2f")

    st.subheader("📊 Parámetros Ganaderos")
    peso_promedio = st.slider("Peso promedio animal (kg):", 300, 600, 450)
    carga_animal = st.slider("Carga animal (cabezas):", 1, 1000, 100)

    st.subheader("🎯 División de Potrero")
    n_divisiones = st.slider("Número de sub-lotes:", min_value=4, max_value=64, value=24)

    st.subheader("📤 Subir Lote")
    tipo_archivo = st.radio(
        "Formato del archivo:",
        ["Shapefile (ZIP)", "KML"],
        horizontal=True
    )
    if tipo_archivo == "Shapefile (ZIP)":
        uploaded_file = st.file_uploader("Subir ZIP con shapefile del potrero", type=['zip'])
    else:
        uploaded_file = st.file_uploader("Subir archivo KML del potrero", type=['kml'])

# -----------------------
# FUNCIONES DE CARGA
# -----------------------
def cargar_shapefile_desde_zip(uploaded_zip):
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            zip_path = os.path.join(tmp_dir, "upload.zip")
            with open(zip_path, "wb") as f:
                f.write(uploaded_zip.getvalue())
            with zipfile.ZipFile(zip_path, 'r') as zip_ref:
                zip_ref.extractall(tmp_dir)
            shp_files = [f for f in os.listdir(tmp_dir) if f.lower().endswith('.shp')]
            if shp_files:
                shp_path = os.path.join(tmp_dir, shp_files[0])
                gdf = gpd.read_file(shp_path)
                if gdf.crs is None:
                    gdf.set_crs(epsg=4326, inplace=True, allow_override=True)
                return gdf
            else:
                st.error("❌ No se encontró archivo .shp en el ZIP")
                return None
    except Exception as e:
        st.error(f"❌ Error cargando shapefile: {e}")
        return None

def cargar_kml(uploaded_kml):
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix='.kml') as tmp_file:
            tmp_file.write(uploaded_kml.getvalue())
            tmp_file.flush()
            tmp_path = tmp_file.name
        gdf = gpd.read_file(tmp_path, driver='KML')
        os.unlink(tmp_path)
        if not gdf.empty and gdf.crs is None:
            gdf.set_crs(epsg=4326, inplace=True, allow_override=True)
        return gdf
    except Exception as e:
        st.error(f"❌ Error cargando KML: {e}")
        return None

# -----------------------
# UTILIDADES FORRAJERAS
# -----------------------
PARAMETROS_FORRAJEROS_BASE = {
    'ALFALFA': {'MS_POR_HA_OPTIMO': 5000, 'CRECIMIENTO_DIARIO': 100, 'CONSUMO_PORCENTAJE_PESO': 0.03,
                'TASA_UTILIZACION_RECOMENDADA': 0.65},
    'RAYGRASS': {'MS_POR_HA_OPTIMO': 4500, 'CRECIMIENTO_DIARIO': 90, 'CONSUMO_PORCENTAJE_PESO': 0.028,
                 'TASA_UTILIZACION_RECOMENDADA': 0.60},
    'FESTUCA': {'MS_POR_HA_OPTIMO': 4000, 'CRECIMIENTO_DIARIO': 70, 'CONSUMO_PORCENTAJE_PESO': 0.025,
                'TASA_UTILIZACION_RECOMENDADA': 0.55},
    'AGROPIRRO': {'MS_POR_HA_OPTIMO': 3500, 'CRECIMIENTO_DIARIO': 60, 'CONSUMO_PORCENTAJE_PESO': 0.022,
                  'TASA_UTILIZACION_RECOMENDADA': 0.50},
    'PASTIZAL_NATURAL': {'MS_POR_HA_OPTIMO': 3000, 'CRECIMIENTO_DIARIO': 40, 'CONSUMO_PORCENTAJE_PESO': 0.020,
                         'TASA_UTILIZACION_RECOMENDADA': 0.45}
}

def obtener_parametros_forrajeros(tipo_pastura):
    if tipo_pastura == "PERSONALIZADO":
        return {
            'MS_POR_HA_OPTIMO': ms_optimo,
            'CRECIMIENTO_DIARIO': crecimiento_diario,
            'CONSUMO_PORCENTAJE_PESO': consumo_porcentaje,
            'TASA_UTILIZACION_RECOMENDADA': tasa_utilizacion
        }
    else:
        return PARAMETROS_FORRAJEROS_BASE.get(tipo_pastura, PARAMETROS_FORRAJEROS_BASE['PASTIZAL_NATURAL'])

def calcular_superficie(gdf):
    try:
        if gdf.crs is None or gdf.crs.is_geographic:
            gdf_m = gdf.to_crs(epsg=3857)
            area_m2 = gdf_m.geometry.area
        else:
            area_m2 = gdf.geometry.area
        return area_m2 / 10000.0
    except Exception:
        try:
            return gdf.geometry.area / 10000.0
        except Exception:
            return pd.Series([0]*len(gdf), index=gdf.index)

def dividir_potrero_en_subLotes(gdf, n_zonas):
    if gdf is None or len(gdf) == 0:
        return gdf
    potrero = gdf.iloc[0].geometry
    minx, miny, maxx, maxy = potrero.bounds
    sub_poligonos = []
    n_cols = math.ceil(math.sqrt(n_zonas))
    n_rows = math.ceil(n_zonas / n_cols)
    width = (maxx - minx) / n_cols
    height = (maxy - miny) / n_rows
    for i in range(n_rows):
        for j in range(n_cols):
            if len(sub_poligonos) >= n_zonas:
                break
            cell_minx = minx + j * width
            cell_maxx = minx + (j + 1) * width
            cell_miny = miny + i * height
            cell_maxy = miny + (i + 1) * height
            cell = Polygon([
                (cell_minx, cell_miny),
                (cell_maxx, cell_miny),
                (cell_maxx, cell_maxy),
                (cell_minx, cell_maxy)
            ])
            inter = potrero.intersection(cell)
            if not inter.is_empty and inter.area > 0:
                sub_poligonos.append(inter)
    if sub_poligonos:
        nuevo = gpd.GeoDataFrame({'id_subLote': range(1, len(sub_poligonos)+1), 'geometry': sub_poligonos})
        nuevo.crs = gdf.crs
        return nuevo
    return gdf

# -----------------------
# DETECCIÓN / SIMULACIÓN
# -----------------------
class DetectorVegetacionRealista:
    def __init__(self, umbral_ndvi_minimo=0.15, umbral_ndvi_optimo=0.6, sensibilidad_suelo=0.5):
        self.umbral_ndvi_minimo = umbral_ndvi_minimo
        self.umbral_ndvi_optimo = umbral_ndvi_optimo
        self.sensibilidad_suelo = sensibilidad_suelo

    def clasificar_vegetacion_realista(self, ndvi, evi, savi, bsi, ndbi, msavi2=None):
        if ndvi < 0.12:
            return "SUELO_DESNUDO", 0.05
        elif ndvi < 0.22:
            return "SUELO_PARCIAL", 0.25
        elif ndvi < 0.4:
            return "VEGETACION_ESCASA", 0.5
        elif ndvi < 0.65:
            return "VEGETACION_MODERADA", 0.75
        else:
            return "VEGETACION_DENSA", 0.9

    def calcular_biomasa_realista(self, ndvi, evi, savi, categoria, cobertura, params):
        base = params['MS_POR_HA_OPTIMO']
        if categoria == "SUELO_DESNUDO":
            return 20, 1, 0.2
        if categoria == "SUELO_PARCIAL":
            return min(base * 0.05, 200), params['CRECIMIENTO_DIARIO'] * 0.2, 0.3
        if categoria == "VEGETACION_ESCASA":
            return min(base * 0.3, 1200), params['CRECIMIENTO_DIARIO'] * 0.4, 0.5
        if categoria == "VEGETACION_MODERADA":
            return min(base * 0.6, 3000), params['CRECIMIENTO_DIARIO'] * 0.7, 0.7
        return min(base * 0.9, 6000), params['CRECIMIENTO_DIARIO'] * 0.9, 0.85

def simular_patrones_reales_con_suelo(id_subLote, x_norm, y_norm, fuente_satelital):
    base = 0.2 + 0.4 * ((id_subLote % 6) / 6)
    ndvi = max(0.05, min(0.85, base + np.random.normal(0, 0.05)))
    if ndvi < 0.15:
        evi = ndvi * 0.8
        savi = ndvi * 0.9
        bsi = 0.6
        ndbi = 0.25
    elif ndvi < 0.3:
        evi = ndvi * 1.1
        savi = ndvi * 1.05
        bsi = 0.4
        ndbi = 0.15
    elif ndvi < 0.5:
        evi = ndvi * 1.3
        savi = ndvi * 1.2
        bsi = 0.1
        ndbi = 0.05
    else:
        evi = ndvi * 1.4
        savi = ndvi * 1.3
        bsi = -0.1
        ndbi = -0.05
    msavi2 = ndvi * 1.0
    return ndvi, evi, savi, bsi, ndbi, msavi2

def calcular_metricas_ganaderas(gdf_analizado, tipo_pastura, peso_promedio, carga_animal):
    params = obtener_parametros_forrajeros(tipo_pastura)
    metricas = []
    for idx, row in gdf_analizado.iterrows():
        biomasa_disponible = row.get('biomasa_disponible_kg_ms_ha', 0)
        area_ha = row.get('area_ha', 0)
        consumo_individual_kg = peso_promedio * params['CONSUMO_PORCENTAJE_PESO']
        biomasa_total_disponible = biomasa_disponible * area_ha
        if biomasa_total_disponible > 0 and consumo_individual_kg > 0:
            ev_por_dia = biomasa_total_disponible * 0.001 / consumo_individual_kg
            ev_soportable = ev_por_dia / params['TASA_UTILIZACION_RECOMENDADA']
            ev_soportable = max(0.01, ev_soportable)
        else:
            ev_soportable = 0.01
        if ev_soportable > 0 and area_ha > 0:
            ev_ha = ev_soportable / area_ha
            ev_ha_display = ev_ha
        else:
            ev_ha_display = 0.01
        if carga_animal > 0:
            consumo_total_diario = carga_animal * consumo_individual_kg
            if consumo_total_diario > 0 and biomasa_total_disponible > 0:
                dias_permanencia = biomasa_total_disponible / consumo_total_diario
                dias_permanencia = min(max(dias_permanencia, 0.1), 365)
            else:
                dias_permanencia = 0.1
        else:
            dias_permanencia = 0.1
        if biomasa_disponible >= 2000:
            estado_forrajero = 4
        elif biomasa_disponible >= 1200:
            estado_forrajero = 3
        elif biomasa_disponible >= 600:
            estado_forrajero = 2
        elif biomasa_disponible >= 200:
            estado_forrajero = 1
        else:
            estado_forrajero = 0
        metricas.append({
            'ev_soportable': round(ev_soportable, 2),
            'dias_permanencia': round(dias_permanencia, 1),
            'tasa_utilizacion': round(min(1.0, (carga_animal * consumo_individual_kg) / max(1, biomasa_total_disponible)), 3) if biomasa_total_disponible>0 else 0,
            'biomasa_total_kg': round(biomasa_total_disponible, 1),
            'consumo_individual_kg': round(consumo_individual_kg, 1),
            'estado_forrajero': estado_forrajero,
            'ev_ha': round(ev_ha_display, 3)
        })
    return metricas

def calcular_indices_forrajeros_realista(gdf, tipo_pastura, fuente_satelital, fecha_imagen, nubes_max,
                                       umbral_ndvi_minimo=0.15, umbral_ndvi_optimo=0.6, sensibilidad_suelo=0.5):
    try:
        resultados = []
        params = obtener_parametros_forrajeros(tipo_pastura)
        detector = DetectorVegetacionRealista(umbral_ndvi_minimo, umbral_ndvi_optimo, sensibilidad_suelo)
        gdf_centroids = gdf.copy()
        gdf_centroids['centroid'] = gdf_centroids.geometry.centroid
        gdf_centroids['x'] = gdf_centroids.centroid.x
        gdf_centroids['y'] = gdf_centroids.centroid.y
        x_coords = gdf_centroids['x'].tolist()
        y_coords = gdf_centroids['y'].tolist()
        x_min, x_max = min(x_coords), max(x_coords)
        y_min, y_max = min(y_coords), max(y_coords)
        st.info("🔍 Aplicando detección REALISTA (simulada) ...")
        for idx, row in gdf_centroids.iterrows():
            id_subLote = row.get('id_subLote', idx+1)
            x_norm = (row['x'] - x_min) / (x_max - x_min) if x_max!=x_min else 0.5
            y_norm = (row['y'] - y_min) / (y_max - y_min) if y_max!=y_min else 0.5
            ndvi, evi, savi, bsi, ndbi, msavi2 = simular_patrones_reales_con_suelo(id_subLote, x_norm, y_norm, fuente_satelital)
            categoria, cobertura = detector.clasificar_vegetacion_realista(ndvi, evi, savi, bsi, ndbi, msavi2)
            biomasa_ms_ha, crecimiento_diario, calidad = detector.calcular_biomasa_realista(ndvi, evi, savi, categoria, cobertura, params)
            if categoria == "SUELO_DESNUDO":
                biomasa_disponible = 20
            elif categoria == "SUELO_PARCIAL":
                biomasa_disponible = 80
            else:
                biomasa_disponible = max(20, min(4000, biomasa_ms_ha * calidad * cobertura))
            resultados.append({
                'id_subLote': id_subLote,
                'ndvi': round(float(ndvi),3),
                'evi': round(float(evi),3),
                'savi': round(float(savi),3),
                'msavi2': round(float(msavi2),3),
                'bsi': round(float(bsi),3),
                'ndbi': round(float(ndbi),3),
                'cobertura_vegetal': round(cobertura,3),
                'tipo_superficie': categoria,
                'biomasa_ms_ha': round(biomasa_ms_ha,1),
                'biomasa_disponible_kg_ms_ha': round(biomasa_disponible,1),
                'crecimiento_diario': round(crecimiento_diario,1),
                'factor_calidad': round(calidad,3),
                'fuente_datos': fuente_satelital,
                'x_norm': round(x_norm,3),
                'y_norm': round(y_norm,3)
            })
        st.success("✅ Cálculo de índices completado.")
        return resultados
    except Exception as e:
        st.error(f"❌ Error en índices: {e}")
        import traceback
        st.error(traceback.format_exc())
        return []

# -----------------------
# MAPAS (MATPLOTLIB y FOLIUM)
# -----------------------
def crear_mapa_detallado_vegetacion(gdf_analizado, tipo_pastura):
    try:
        fig, axes = plt.subplots(2, 2, figsize=(20, 16))
        ax1, ax2, ax3, ax4 = axes[0, 0], axes[0, 1], axes[1, 0], axes[1, 1]
        
        # Mapa 1: Tipos de Superficie
        colores_superficie = {
            'SUELO_DESNUDO': '#d73027',
            'SUELO_PARCIAL': '#fdae61',
            'VEGETACION_ESCASA': '#fee08b',
            'VEGETACION_MODERADA': '#a6d96a',
            'VEGETACION_DENSA': '#1a9850'
        }
        for idx, row in gdf_analizado.iterrows():
            tipo = row.get('tipo_superficie', 'VEGETACION_ESCASA')
            color = colores_superficie.get(tipo, '#cccccc')
            gdf_analizado.iloc[[idx]].plot(ax=ax1, color=color, edgecolor='black', linewidth=0.5)
            c = row.geometry.centroid
            ax1.text(c.x, c.y, f"S{row['id_subLote']}", fontsize=6, ha='center', va='center')
        ax1.set_title(f"Tipos de Superficie - {tipo_pastura}", fontsize=14, fontweight='bold')
        
        # Leyenda para tipos de superficie
        patches = [mpatches.Patch(color=color, label=label) for label, color in colores_superficie.items()]
        ax1.legend(handles=patches, loc='upper right', fontsize=8)

        # Mapa 2: Biomasa Disponible
        cmap_biomasa = LinearSegmentedColormap.from_list('biomasa_cmap', ['#d73027','#fee08b','#a6d96a','#1a9850'])
        for idx, row in gdf_analizado.iterrows():
            biom = row.get('biomasa_disponible_kg_ms_ha', 0)
            val = max(0, min(1, biom/4000))
            color = cmap_biomasa(val)
            gdf_analizado.iloc[[idx]].plot(ax=ax2, color=color, edgecolor='black', linewidth=0.5)
            c = row.geometry.centroid
            ax2.text(c.x, c.y, f"{biom:.0f}", fontsize=6, ha='center', va='center')
        ax2.set_title("Biomasa Disponible (kg MS/ha)", fontsize=14, fontweight='bold')

        # Mapa 3: EV por Hectárea
        cmap_ev = LinearSegmentedColormap.from_list('ev_cmap', ['#d73027','#fee08b','#a6d96a','#1a9850'])
        for idx, row in gdf_analizado.iterrows():
            ev_ha = row.get('ev_ha', 0)
            val = max(0, min(1, ev_ha/2.0))  # Normalizar considerando 2 EV/ha como máximo
            color = cmap_ev(val)
            gdf_analizado.iloc[[idx]].plot(ax=ax3, color=color, edgecolor='black', linewidth=0.5)
            c = row.geometry.centroid
            ax3.text(c.x, c.y, f"{ev_ha:.2f}", fontsize=6, ha='center', va='center')
        ax3.set_title("Equivalente Vaca por Hectárea (EV/ha)", fontsize=14, fontweight='bold')

        # Mapa 4: Días de Permanencia
        cmap_dias = LinearSegmentedColormap.from_list('dias_cmap', ['#d73027','#fee08b','#a6d96a','#1a9850'])
        for idx, row in gdf_analizado.iterrows():
            dias = row.get('dias_permanencia', 0)
            val = max(0, min(1, dias/60.0))  # Normalizar considerando 60 días como máximo
            color = cmap_dias(val)
            gdf_analizado.iloc[[idx]].plot(ax=ax4, color=color, edgecolor='black', linewidth=0.5)
            c = row.geometry.centroid
            ax4.text(c.x, c.y, f"{dias:.0f}", fontsize=6, ha='center', va='center')
        ax4.set_title("Días de Permanencia", fontsize=14, fontweight='bold')

        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        st.error(f"❌ Error creando mapa detallado: {e}")
        return None

def crear_mapa_interactivo(gdf, base_map_name="ESRI Satélite"):
    if not FOLIUM_AVAILABLE or gdf is None or len(gdf)==0:
        return None
    bounds = gdf.total_bounds
    centroid = gdf.geometry.centroid.iloc[0]
    m = folium.Map(location=[centroid.y, centroid.x], tiles=None, control_scale=True, zoom_start=12)
    
    # Definir mapas base CORREGIDOS
    if base_map_name == "ESRI Satélite":
        tiles = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
        attr = 'Esri, Maxar, Earthstar Geographics'
        folium.TileLayer(tiles=tiles, attr=attr, name='ESRI Satellite').add_to(m)
    elif base_map_name == "OpenStreetMap":
        folium.TileLayer(tiles='OpenStreetMap', name='OpenStreetMap').add_to(m)
    else:  # CartoDB Positron
        folium.TileLayer(tiles='CartoDB positron', name='CartoDB Positron').add_to(m)
    
    # Añadir el polígono
    folium.GeoJson(
        gdf.__geo_interface__, 
        name='Potrero',
        style_function=lambda feature: {
            'fillColor': 'blue',
            'color': 'blue',
            'weight': 2,
            'fillOpacity': 0.1
        },
        tooltip=folium.GeoJsonTooltip(fields=[], aliases=[], labels=True)
    ).add_to(m)
    
    m.fit_bounds([[bounds[1], bounds[0]], [bounds[3], bounds[2]]])
    folium.LayerControl().add_to(m)
    return m

# -----------------------
# GENERAR INFORME DOCX (unificado técnico + práctico)
# -----------------------
def generar_informe_forrajero_docx(gdf, tipo_pastura, peso_promedio, carga_animal, fecha_imagen):
    """Genera y devuelve un BytesIO con el DOCX que contiene el análisis y
       las secciones: técnico + orientaciones prácticas (ganadería regenerativa)."""
    if not DOCX_AVAILABLE:
        st.error("La librería python-docx no está instalada. Ejecutá: pip install python-docx")
        return None
    try:
        doc = Document()
        titulo = f"INFORME DE DISPONIBILIDAD FORRAJERA PRV – {fecha_imagen.strftime('%Y/%m')}"
        doc.add_heading(titulo, level=0)
        doc.add_paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        doc.add_paragraph(f"Tipo de pastura: {tipo_pastura}")
        doc.add_paragraph(f"Fuente de datos: {fuente_satelital}")
        doc.add_paragraph(f"Peso promedio animal: {peso_promedio} kg")
        doc.add_paragraph(f"Carga animal: {carga_animal} cabezas")
        doc.add_paragraph("")

        # Estadísticas
        try:
            area_total = gdf['area_ha'].sum()
            biomasa_prom = float(gdf['biomasa_disponible_kg_ms_ha'].mean())
            ndvi_prom = float(gdf['ndvi'].mean())
            dias_prom = float(gdf['dias_permanencia'].mean())
            ev_total = float(gdf['ev_soportable'].sum())
            ev_ha_prom = float(gdf['ev_ha'].mean())
        except Exception:
            area_total = biomasa_prom = ndvi_prom = dias_prom = ev_total = ev_ha_prom = 0.0

        doc.add_heading("Resumen del Análisis", level=1)
        doc.add_paragraph(f"Área total (ha): {area_total:.2f}")
        doc.add_paragraph(f"Biomasa promedio (kg MS/ha): {biomasa_prom:.0f}")
        doc.add_paragraph(f"NDVI promedio: {ndvi_prom:.3f}")
        doc.add_paragraph(f"Días de permanencia promedio: {dias_prom:.1f}")
        doc.add_paragraph(f"Equivalente Vaca (EV) total: {ev_total:.2f}")
        doc.add_paragraph(f"EV por hectárea promedio: {ev_ha_prom:.2f}")
        doc.add_paragraph("")

        # Tabla resumen por sub-lote (primeras 20)
        doc.add_heading("Resultados por Sub-lote (primeras 20 filas)", level=1)
        columnas = ['id_subLote', 'area_ha', 'tipo_superficie', 'ndvi', 'cobertura_vegetal',
                   'biomasa_disponible_kg_ms_ha', 'ev_ha', 'dias_permanencia']
        cols_presentes = [c for c in columnas if c in gdf.columns]
        table = doc.add_table(rows=1, cols=len(cols_presentes))
        hdr = table.rows[0].cells
        for i, c in enumerate(cols_presentes):
            hdr[i].text = c.replace('_',' ').title()
        for _, row in gdf.head(20).iterrows():
            r = table.add_row().cells
            for i, c in enumerate(cols_presentes):
                val = row.get(c, '')
                if pd.isna(val):
                    val = ''
                r[i].text = str(val)
        doc.add_paragraph(f"Mostrando {min(20,len(gdf))} de {len(gdf)} sub-lotes.")
        doc.add_paragraph("")

        # Inserción del mapa (si existe)
        if st.session_state.mapa_detallado_bytes is not None:
            try:
                img_buf = st.session_state.mapa_detallado_bytes
                img_buf.seek(0)
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as tmp_img:
                    tmp_img.write(img_buf.read())
                    tmp_img.flush()
                    tmp_path = tmp_img.name
                doc.add_page_break()
                doc.add_heading("Mapa Detallado de Análisis", level=1)
                try:
                    doc.add_picture(tmp_path, width=Inches(6))
                except Exception:
                    # Si no se puede insertar a tamaño, insertar sin width
                    try:
                        doc.add_picture(tmp_path)
                    except Exception:
                        pass
                try:
                    os.remove(tmp_path)
                except Exception:
                    pass
            except Exception:
                pass

        # Conclusión breve
        doc.add_heading("Conclusión", level=1)
        if biomasa_prom <= 200:
            estado = "Muy degradado / casi sin biomasa"
        elif biomasa_prom < 600:
            estado = "Baja biomasa"
        elif biomasa_prom < 1200:
            estado = "Biomasa moderada"
        elif biomasa_prom < 2000:
            estado = "Buena biomasa"
        else:
            estado = "Biomasa alta"
        doc.add_paragraph(f"Estado general del potrero: {estado} (Biomasa promedio: {biomasa_prom:.0f} kg MS/ha)")

        # ---------------- Recomendaciones regenerativas (TÉCNICAS) ----------------
        doc.add_heading("Recomendaciones técnicas (Ganadería Regenerativa)", level=1)
        # Principios generales
        doc.add_paragraph("Principios aplicados: Descanso suficiente, alta densidad temporal, uso eficiente de la biomasa, continuidad del ciclo biológico.")
        # Adaptación por estado
        if biomasa_prom < 1000:
            doc.add_paragraph("Estado: RECUPERACIÓN / CRÍTICO (biomasa baja). Recomendaciones técnicas:")
            doc.add_paragraph("• Aumentar significativamente los periodos de descanso (60–120 días dependiendo de la estación).")
            doc.add_paragraph("• Reducir la carga animal temporalmente; priorizar suplementación si es necesario.")
            doc.add_paragraph("• Implementar pastoreo diferido en sectores críticos y proteger corredores de agua.")
            doc.add_paragraph("• Aplicar técnicas de regeneración: cobertura orgánica, siembra de especies perennes y abonos orgánicos.")
            doc.add_paragraph("• Evitar tráfico pesado en épocas húmedas para prevenir compactación.")
        elif biomasa_prom < 2000:
            doc.add_paragraph("Estado: MEJORA / INTERMEDIO. Recomendaciones técnicas:")
            doc.add_paragraph("• Implementar rotación con alta densidad temporal por períodos cortos (1–3 días) y descansos moderados (45–75 días).")
            doc.add_paragraph("• Monitorear crecimiento y ajustar la duración del pastoreo según rebrote.")
            doc.add_paragraph("• Introducir o favorecer mezcla de gramíneas y leguminosas para mejorar calidad y fijación de N.")
            doc.add_paragraph("• Promover prácticas que aumenten la retención de humedad y materia orgánica (coberturas, mulch).")
        else:
            doc.add_paragraph("Estado: CONSERVACIÓN / ÓPTIMO. Recomendaciones técnicas:")
            doc.add_paragraph("• Mantener la rotación con descansos de 35–60 días según especie y estación.")
            doc.add_paragraph("• Aprovechar biomasa con pastoreos de alta densidad y corta duración para estimular rebrote.")
            doc.add_paragraph("• Monitorear y conservar hábitats de agua y áreas de protección riparia.")
            doc.add_paragraph("• Evaluar enriquecimiento con leguminosas para mejorar proteína del forraje.")

        # ---------------- Recomendaciones prácticas (PRODUCCIÓN) ----------------
        doc.add_heading("Orientaciones prácticas para productores", level=1)
        if biomasa_prom < 1000:
            doc.add_paragraph("🌾 Acción Prioritaria: Recuperación rápida y reducción de presión.")
            doc.add_paragraph("• Dejá los potreros descansar hasta que la planta recupere altura y color.")
            doc.add_paragraph("• Mové los animales con frecuencia (siempre en diarios o cada 2 días) y evitá dejarlos mucho tiempo en el mismo potrero.")
            doc.add_paragraph("• Si no hay suficiente forraje, reducí la carga y considerá suplementar con conservas.")
            doc.add_paragraph("• Evitá entrar con maquinaria pesada o animales cuando el suelo esté muy húmedo.")
        elif biomasa_prom < 2000:
            doc.add_paragraph("🌿 Acción Prioritaria: Manejo activo y mejora.")
            doc.add_paragraph("• Hacé descansos más largos entre pastoreos (45–75 días) y usá rotaciones cortas para estimular rebrote.")
            doc.add_paragraph("• Introducí mezcla de especies donde sea posible para mejorar calidad del forraje.")
            doc.add_paragraph("• Monitoreá el potrero cada 15–30 días para ajustar la duración del pastoreo.")
        else:
            doc.add_paragraph("🌱 Acción Prioritaria: Mantener y optimizar.")
            doc.add_paragraph("• Rotá con descansos regulares (35–60 días) y aprovechá picos de crecimiento con pastoreos intensos y cortos.")
            doc.add_paragraph("• Conservar cobertura vegetal y usar sombra/aguas para distribuir el ganado según disponibilidad.")
            doc.add_paragraph("• Registrá y monitoreá (fotos, medidas) para detectar cambios tempranos.")

        # Pequeñas prácticas complementarias
        doc.add_paragraph("")
        doc.add_paragraph("Prácticas complementarias sugeridas:")
        doc.add_paragraph("• Mantener franjas de protección alrededor de cursos de agua.")
        doc.add_paragraph("• Fomentar biodiversidad: árboles y arbustos dispersos para sombra y refugio.")
        doc.add_paragraph("• Registrar datos simples: biomasa estimada, altura forrajera, % cubierta y días de descanso.")

        # Pie
        doc.add_paragraph("")
        doc.add_paragraph("Este informe ofrece recomendaciones generales basadas en el análisis automatizado. Para planes de manejo específicos, contactá un técnico/agronomo local.")
        # Guardar en BytesIO
        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf
    except Exception as e:
        st.error(f"❌ Error generando informe DOCX: {e}")
        return None

# -----------------------
# FLUJO PRINCIPAL: carga, análisis, exportes
# -----------------------
st.markdown("### 📁 Cargar / visualizar lote")
gdf_loaded = None
if uploaded_file is not None:
    with st.spinner("Cargando archivo..."):
        try:
            if tipo_archivo == "Shapefile (ZIP)":
                gdf_loaded = cargar_shapefile_desde_zip(uploaded_file)
            else:
                gdf_loaded = cargar_kml(uploaded_file)
            if gdf_loaded is not None and len(gdf_loaded) > 0:
                st.session_state.gdf_cargado = gdf_loaded
                area_total = calcular_superficie(gdf_loaded).sum()
                st.success("✅ Archivo cargado correctamente.")
                col1,col2,col3,col4 = st.columns(4)
                with col1: st.metric("Polígonos", len(gdf_loaded))
                with col2: st.metric("Área total (ha)", f"{area_total:.2f}")
                with col3: st.metric("Tipo pastura", tipo_pastura)
                with col4: st.metric("Fuente datos", fuente_satelital)
                if FOLIUM_AVAILABLE:
                    st.markdown("---")
                    st.markdown("### 🗺️ Visualización del potrero (interactiva)")
                    m = crear_mapa_interactivo(gdf_loaded, base_map_option)
                    if m:
                        st_folium(m, width=1200, height=500)
                else:
                    st.info("Instalá folium y streamlit-folium para ver el mapa interactivo: pip install folium streamlit-folium")
            else:
                st.info("Carga completada pero no se detectaron geometrías válidas.")
        except Exception as e:
            st.error(f"❌ Error al cargar archivo: {e}")

st.markdown("---")
st.markdown("### 🚀 Ejecutar análisis")
if st.session_state.gdf_cargado is not None:
    if st.button("🚀 Ejecutar Análisis Forrajero (Realista)"):
        with st.spinner("Ejecutando análisis..."):
            try:
                gdf_input = st.session_state.gdf_cargado.copy()
                gdf_sub = dividir_potrero_en_subLotes(gdf_input, n_divisiones)
                if gdf_sub is None or len(gdf_sub)==0:
                    st.error("No se pudo dividir el potrero en sub-lotes.")
                else:
                    areas = calcular_superficie(gdf_sub)
                    gdf_sub['area_ha'] = areas.values
                    indices = calcular_indices_forrajeros_realista(gdf_sub, tipo_pastura, fuente_satelital, fecha_imagen, nubes_max,
                                                                  umbral_ndvi_minimo, umbral_ndvi_optimo, sensibilidad_suelo)
                    if not indices:
                        st.error("No se pudieron calcular índices (indices vacío).")
                    else:
                        for idx, rec in enumerate(indices):
                            for k,v in rec.items():
                                if k != 'id_subLote':
                                    try:
                                        gdf_sub.loc[gdf_sub.index[idx], k] = v
                                    except Exception:
                                        pass
                        metricas = calcular_metricas_ganaderas(gdf_sub, tipo_pastura, peso_promedio, carga_animal)
                        for idx, met in enumerate(metricas):
                            for k,v in met.items():
                                try:
                                    gdf_sub.loc[gdf_sub.index[idx], k] = v
                                except Exception:
                                    pass
                        st.session_state.gdf_analizado = gdf_sub
                        mapa_buf = crear_mapa_detallado_vegetacion(gdf_sub, tipo_pastura)
                        if mapa_buf is not None:
                            st.image(mapa_buf, use_column_width=True, caption="Mapas de Análisis: Tipos de Superficie, Biomasa Disponible, EV/ha y Días de Permanencia")
                            st.session_state.mapa_detallado_bytes = mapa_buf
                        # Exportes: GeoJSON y CSV
                        try:
                            geojson_str = gdf_sub.to_json()
                            st.download_button("📤 Exportar GeoJSON", geojson_str,
                                               f"analisis_{tipo_pastura}_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson",
                                               "application/geo+json")
                        except Exception as e:
                            st.error(f"Error exportando GeoJSON: {e}")
                        try:
                            csv_bytes = gdf_sub.drop(columns=['geometry']).to_csv(index=False).encode('utf-8')
                            st.download_button("📊 Exportar CSV", csv_bytes,
                                               f"analisis_{tipo_pastura}_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                                               "text/csv")
                        except Exception as e:
                            st.error(f"Error exportando CSV: {e}")
                        # Mostrar tabla
                        try:
                            columnas_detalle = ['id_subLote', 'area_ha', 'tipo_superficie', 'ndvi', 'cobertura_vegetal',
                                               'biomasa_disponible_kg_ms_ha', 'ev_ha', 'dias_permanencia']
                            cols_presentes = [c for c in columnas_detalle if c in gdf_sub.columns]
                            df_show = gdf_sub[cols_presentes].copy()
                            df_show.columns = [c.replace('_',' ').title() for c in df_show.columns]
                            st.dataframe(df_show, use_container_width=True)
                        except Exception:
                            st.info("No hay datos tabulares para mostrar.")
                        # Generar informe DOCX automáticamente
                        if DOCX_AVAILABLE:
                            docx_buf = generar_informe_forrajero_docx(gdf_sub, tipo_pastura, peso_promedio, carga_animal, fecha_imagen)
                            if docx_buf is not None:
                                st.session_state.docx_buffer = docx_buf
                                b64 = base64.b64encode(docx_buf.getvalue()).decode()
                                filename = f"informe_disponibilidad_forrajera_prv_{tipo_pastura}_{fecha_imagen.strftime('%Y%m')}.docx"
                                html_download = f"""
                                <html>
                                <body>
                                <a id='dlink' href='data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{b64}' download='{filename}'>download</a>
                                <script>
                                    const d = document.getElementById('dlink');
                                    d.click();
                                </script>
                                <p>Si la descarga automática no inició, <a href='data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{b64}' download='{filename}'>hacé clic acá para descargar</a>.</p>
                                </body>
                                </html>
                                """
                                st.success("✅ Informe DOCX generado. Descarga automática iniciada (o hacé clic en el enlace).")
                                components.html(html_download, height=140)
                            else:
                                st.error("❌ No se pudo generar el informe DOCX.")
                        else:
                            st.warning("python-docx no está instalado — no puedo generar DOCX. Ejecutá: pip install python-docx")
                        st.session_state.analisis_completado = True
            except Exception as e:
                st.error(f"❌ Error ejecutando análisis: {e}")
                import traceback
                st.error(traceback.format_exc())
else:
    st.info("Carga un archivo (ZIP con shapefile o KML) en la barra lateral para comenzar.")

# Mensaje final / instrucciones
st.markdown("---")
st.markdown("**Notas:**")
st.markdown("- Si la descarga automática no inicia por políticas del navegador, usá el enlace que aparece debajo del mensaje de éxito para descargar el .docx manualmente.")
st.markdown("- Para convertir a PDF, abrí el .docx y guardá como PDF o usá tu conversor preferido.")
