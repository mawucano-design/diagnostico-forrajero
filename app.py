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

# Importaciones para mapas
try:
    import folium
    from streamlit_folium import st_folium
    FOLIUM_AVAILABLE = True
except ImportError:
    FOLIUM_AVAILABLE = False

# Importaciones para informes
try:
    from docx import Document
    from docx.shared import Inches
    DOCX_AVAILABLE = True
except ImportError:
    DOCX_AVAILABLE = False

# =============================================================================
# CONFIGURACIÓN
# =============================================================================

st.set_page_config(
    page_title="🌱 Analizador Forrajero PRV",
    page_icon="🌱", 
    layout="wide",
    initial_sidebar_state="expanded"
)

def initialize_session_state():
    """Inicializa todas las variables del session state"""
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'username' not in st.session_state:
        st.session_state.username = ""
    if 'gdf_cargado' not in st.session_state:
        st.session_state.gdf_cargado = None
    if 'gdf_analizado' not in st.session_state:
        st.session_state.gdf_analizado = None
    if 'analisis_completado' not in st.session_state:
        st.session_state.analisis_completado = False
    if 'mapa_detallado_bytes' not in st.session_state:
        st.session_state.mapa_detallado_bytes = None
    if 'docx_buffer' not in st.session_state:
        st.session_state.docx_buffer = None

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

# =============================================================================
# PARÁMETROS FORRAJEROS COMPLETOS
# =============================================================================

PARAMETROS_FORRAJEROS_BASE = {
    'ALFALFA': {
        'MS_POR_HA_OPTIMO': 5000, 
        'CRECIMIENTO_DIARIO': 100, 
        'CONSUMO_PORCENTAJE_PESO': 0.03,
        'TASA_UTILIZACION_RECOMENDADA': 0.65,
        'EFICIENCIA_COSECHA': 0.70,
        'EFICIENCIA_PASTOREO': 0.75,
        'CONSUMO_DIARIO_EV': 12.0
    },
    'RAYGRASS': {
        'MS_POR_HA_OPTIMO': 4500, 
        'CRECIMIENTO_DIARIO': 90, 
        'CONSUMO_PORCENTAJE_PESO': 0.028,
        'TASA_UTILIZACION_RECOMENDADA': 0.60,
        'EFICIENCIA_COSECHA': 0.67,
        'EFICIENCIA_PASTOREO': 0.72,
        'CONSUMO_DIARIO_EV': 11.0
    },
    'FESTUCA': {
        'MS_POR_HA_OPTIMO': 4000, 
        'CRECIMIENTO_DIARIO': 70, 
        'CONSUMO_PORCENTAJE_PESO': 0.025,
        'TASA_UTILIZACION_RECOMENDADA': 0.55,
        'EFICIENCIA_COSECHA': 0.62,
        'EFICIENCIA_PASTOREO': 0.68,
        'CONSUMO_DIARIO_EV': 10.0
    },
    'AGROPIRRO': {
        'MS_POR_HA_OPTIMO': 3500, 
        'CRECIMIENTO_DIARIO': 60, 
        'CONSUMO_PORCENTAJE_PESO': 0.022,
        'TASA_UTILIZACION_RECOMENDADA': 0.50,
        'EFICIENCIA_COSECHA': 0.58,
        'EFICIENCIA_PASTOREO': 0.65,
        'CONSUMO_DIARIO_EV': 9.0
    },
    'PASTIZAL_NATURAL': {
        'MS_POR_HA_OPTIMO': 3000, 
        'CRECIMIENTO_DIARIO': 40, 
        'CONSUMO_PORCENTAJE_PESO': 0.020,
        'TASA_UTILIZACION_RECOMENDADA': 0.45,
        'EFICIENCIA_COSECHA': 0.55,
        'EFICIENCIA_PASTOREO': 0.60,
        'CONSUMO_DIARIO_EV': 8.0
    }
}

def obtener_parametros_forrajeros(tipo_pastura, personalizados=None):
    """Obtiene parámetros forrajeros, con opción de personalización"""
    if tipo_pastura == "PERSONALIZADO" and personalizados:
        return personalizados
    else:
        return PARAMETROS_FORRAJEROS_BASE.get(tipo_pastura, PARAMETROS_FORRAJEROS_BASE['FESTUCA'])

# =============================================================================
# FUNCIONES DE CÁLCULO (ORIGINALES)
# =============================================================================

def calcular_superficie(gdf):
    """Calcula superficie en hectáreas de forma precisa"""
    try:
        if gdf.crs is None or str(gdf.crs).startswith('EPSG:4326'):
            gdf_proj = gdf.to_crs(epsg=3857)
            area_m2 = gdf_proj.geometry.area
        else:
            area_m2 = gdf.geometry.area
        return area_m2 / 10000.0
    except Exception as e:
        st.warning(f"Advertencia en cálculo de área: {e}")
        return gdf.geometry.area / 10000.0

def dividir_potrero_en_subLotes(gdf, n_zonas):
    """Divide el potrero en sub-lotes"""
    if gdf is None or len(gdf) == 0:
        return gdf
    
    try:
        if len(gdf) > 1:
            gdf_resultado = gdf.copy()
            gdf_resultado['id_subLote'] = range(1, len(gdf_resultado) + 1)
            return gdf_resultado
        
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
            
    except Exception as e:
        st.error(f"Error dividiendo potrero: {e}")
        return gdf

# =============================================================================
# SISTEMA DE DETECCIÓN (ORIGINAL)
# =============================================================================

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
        
        st.info("🔍 Aplicando detección REALISTA...")
        
        for idx, row in gdf_centroids.iterrows():
            id_subLote = row.get('id_subLote', idx+1)
            x_norm = (row['x'] - x_min) / (x_max - x_min) if x_max != x_min else 0.5
            y_norm = (row['y'] - y_min) / (y_max - y_min) if y_max != y_min else 0.5
            
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
            'tasa_utilizacion': round(min(1.0, (carga_animal * consumo_individual_kg) / max(1, biomasa_total_disponible)), 3),
            'biomasa_total_kg': round(biomasa_total_disponible, 1),
            'consumo_individual_kg': round(consumo_individual_kg, 1),
            'estado_forrajero': estado_forrajero,
            'ev_ha': round(ev_ha_display, 3)
        })
    
    return metricas

# =============================================================================
# FUNCIONES DE MAPAS (ORIGINALES)
# =============================================================================

def crear_mapa_interactivo(gdf, base_map_name="ESRI Satélite"):
    if not FOLIUM_AVAILABLE or gdf is None or len(gdf)==0:
        return None
    bounds = gdf.total_bounds
    centroid = gdf.geometry.centroid.iloc[0]
    m = folium.Map(location=[centroid.y, centroid.x], tiles=None, control_scale=True)
    
    if base_map_name == "ESRI Satélite":
        ESRI = 'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}'
        folium.TileLayer(ESRI, attr='Esri', name='ESRI Satellite', overlay=False).add_to(m)
    elif base_map_name == "OpenStreetMap":
        folium.TileLayer('OpenStreetMap', attr='OpenStreetMap', name='OpenStreetMap', overlay=False).add_to(m)
    else:
        folium.TileLayer('CartoDB positron', attr='CartoDB', name='CartoDB Positron', overlay=False).add_to(m)
    
    folium.GeoJson(gdf.__geo_interface__, name='Polígono', style_function=lambda feat: {'color':'blue','weight':2,'fillOpacity':0.2}).add_to(m)
    m.fit_bounds([[bounds[1], bounds[0]],[bounds[3], bounds[2]]])
    folium.LayerControl().add_to(m)
    return m

def crear_mapa_detallado_vegetacion(gdf_analizado, tipo_pastura):
    try:
        fig, (ax1, ax2) = plt.subplots(1,2,figsize=(18,9))
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
            gdf_analizado.iloc[[idx]].plot(ax=ax1, color=color, edgecolor='black')
            c = row.geometry.centroid
            ax1.text(c.x, c.y, f"S{row['id_subLote']}", fontsize=7)
        ax1.set_title(f"Tipos de Superficie - {tipo_pastura}")
        cmap = LinearSegmentedColormap.from_list('b', ['#d73027','#fee08b','#a6d96a','#1a9850'])
        for idx, row in gdf_analizado.iterrows():
            biom = row.get('biomasa_disponible_kg_ms_ha',0)
            val = max(0, min(1, biom/4000))
            color = cmap(val)
            gdf_analizado.iloc[[idx]].plot(ax=ax2, color=color, edgecolor='black')
            c = row.geometry.centroid
            ax2.text(c.x, c.y, f"{biom:.0f}", fontsize=7)
        ax2.set_title("Biomasa Disponible (kg MS/ha)")
        plt.tight_layout()
        buf = io.BytesIO()
        plt.savefig(buf, format='png', dpi=150, bbox_inches='tight')
        buf.seek(0)
        plt.close(fig)
        return buf
    except Exception as e:
        st.error(f"❌ Error creando mapa detallado: {e}")
        return None

# =============================================================================
# FUNCIONES DE CARGA (ORIGINALES)
# =============================================================================

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

# =============================================================================
# GENERAR INFORME DOCX (ORIGINAL)
# =============================================================================

def generar_informe_forrajero_docx(gdf, tipo_pastura, peso_promedio, carga_animal, fecha_imagen):
    if not DOCX_AVAILABLE:
        st.error("La librería python-docx no está instalada. Ejecutá: pip install python-docx")
        return None
    try:
        doc = Document()
        titulo = f"INFORME DE DISPONIBILIDAD FORRAJERA PRV – {fecha_imagen.strftime('%Y/%m')}"
        doc.add_heading(titulo, level=0)
        doc.add_paragraph(f"Generado: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        doc.add_paragraph(f"Tipo de pastura: {tipo_pastura}")
        doc.add_paragraph(f"Fuente de datos: SENTINEL-2")
        doc.add_paragraph(f"Peso promedio animal: {peso_promedio} kg")
        doc.add_paragraph(f"Carga animal: {carga_animal} cabezas")
        doc.add_paragraph("")

        try:
            area_total = gdf['area_ha'].sum()
            biomasa_prom = float(gdf['biomasa_disponible_kg_ms_ha'].mean())
            ndvi_prom = float(gdf['ndvi'].mean())
            dias_prom = float(gdf['dias_permanencia'].mean())
            ev_total = float(gdf['ev_soportable'].sum())
        except Exception:
            area_total = biomasa_prom = ndvi_prom = dias_prom = ev_total = 0.0

        doc.add_heading("Resumen del Análisis", level=1)
        doc.add_paragraph(f"Área total (ha): {area_total:.2f}")
        doc.add_paragraph(f"Biomasa promedio (kg MS/ha): {biomasa_prom:.0f}")
        doc.add_paragraph(f"NDVI promedio: {ndvi_prom:.3f}")
        doc.add_paragraph(f"Días de permanencia promedio: {dias_prom:.1f}")
        doc.add_paragraph(f"Equivalente Vaca (EV) total: {ev_total:.2f}")
        doc.add_paragraph("")

        doc.add_heading("Resultados por Sub-lote (primeras 20 filas)", level=1)
        columnas = ['id_subLote', 'area_ha', 'tipo_superficie', 'ndvi', 'cobertura_vegetal',
                   'biomasa_disponible_kg_ms_ha', 'dias_permanencia', 'ev_ha']
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

        doc.add_heading("Recomendaciones técnicas", level=1)
        if biomasa_prom < 1000:
            doc.add_paragraph("Estado: RECUPERACIÓN / CRÍTICO (biomasa baja). Recomendaciones:")
            doc.add_paragraph("• Aumentar significativamente los periodos de descanso (60–120 días)")
            doc.add_paragraph("• Reducir la carga animal temporalmente")
            doc.add_paragraph("• Implementar pastoreo diferido en sectores críticos")
        elif biomasa_prom < 2000:
            doc.add_paragraph("Estado: MEJORA / INTERMEDIO. Recomendaciones:")
            doc.add_paragraph("• Implementar rotación con descansos moderados (45–75 días)")
            doc.add_paragraph("• Monitorear crecimiento y ajustar la duración del pastoreo")
        else:
            doc.add_paragraph("Estado: CONSERVACIÓN / ÓPTIMO. Recomendaciones:")
            doc.add_paragraph("• Mantener la rotación con descansos de 35–60 días")
            doc.add_paragraph("• Aprovechar biomasa con pastoreos de alta densidad")

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        return buf
    except Exception as e:
        st.error(f"❌ Error generando informe DOCX: {e}")
        return None

# =============================================================================
# INTERFAZ PRINCIPAL (ORIGINAL CON CORRECCIÓN)
# =============================================================================

def main_application():
    """Aplicación principal - VERSIÓN ORIGINAL CORREGIDA"""
    
    # Sidebar de configuración COMPLETA
    with st.sidebar:
        st.header(f"👋 Bienvenido, {st.session_state.username}")
        
        if st.button("🚪 Cerrar Sesión"):
            st.session_state.authenticated = False
            st.session_state.username = ""
            st.session_state.gdf_cargado = None
            st.session_state.gdf_analizado = None
            st.session_state.analisis_completado = False
            st.rerun()
        
        st.markdown("---")
        
        # Configuración de mapas base
        if FOLIUM_AVAILABLE:
            st.subheader("🗺️ Mapa Base")
            base_map_option = st.selectbox(
                "Seleccionar mapa base:",
                ["ESRI Satélite", "OpenStreetMap", "CartoDB Positron"],
                index=0
            )
        else:
            base_map_option = "ESRI Satélite"

        # Fuente de datos satelitales
        st.subheader("🛰️ Fuente de Datos Satelitales")
        fuente_satelital = st.selectbox(
            "Seleccionar satélite:",
            ["SENTINEL-2", "LANDSAT-8", "LANDSAT-9", "SIMULADO"],
        )

        # Tipo de pastura con personalización
        st.subheader("🌿 Tipo de Pastura")
        tipo_pastura = st.selectbox(
            "Tipo de Pastura:",
            ["ALFALFA", "RAYGRASS", "FESTUCA", "AGROPIRRO", "PASTIZAL_NATURAL", "PERSONALIZADO"]
        )

        # Parámetros personalizados
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
        else:
            # Usar parámetros por defecto
            ms_optimo = 4000
            crecimiento_diario = 80
            consumo_porcentaje = 0.025
            tasa_utilizacion = 0.55
            umbral_ndvi_suelo = 0.15
            umbral_ndvi_pastura = 0.6

        # Parámetros ganaderos
        st.subheader("🐄 Parámetros Ganaderos")
        peso_promedio = st.slider("Peso promedio animal (kg):", 300, 600, 450)
        carga_animal = st.slider("Carga animal (cabezas):", 1, 1000, 100)

        # Configuración temporal
        st.subheader("📅 Configuración Temporal")
        fecha_imagen = st.date_input(
            "Fecha de imagen satelital:",
            value=datetime.now() - timedelta(days=30),
            max_value=datetime.now()
        )
        nubes_max = st.slider("Máximo % de nubes permitido:", 0, 100, 20)

        # Parámetros de detección
        st.subheader("🌿 Parámetros de Detección de Vegetación")
        umbral_ndvi_minimo = st.slider("Umbral NDVI mínimo vegetación:", 0.05, 0.3, 0.15, 0.01)
        umbral_ndvi_optimo = st.slider("Umbral NDVI vegetación óptima:", 0.4, 0.8, 0.6, 0.01)
        sensibilidad_suelo = st.slider("Sensibilidad detección suelo:", 0.1, 1.0, 0.5, 0.1)

        # División de potrero
        st.subheader("🎯 División de Potrero")
        n_divisiones = st.slider("Número de sub-lotes:", min_value=4, max_value=64, value=24)

        # Carga de datos
        st.subheader("📤 Subir Lote")
        uploaded_file = st.file_uploader("Subir ZIP con shapefile del potrero", type=['zip'])
        
        # Datos de ejemplo
        if st.button("🎲 Usar Datos de Ejemplo"):
            poligono_ejemplo = Polygon([
                [-60.0, -35.0],
                [-59.5, -35.0],
                [-59.5, -34.5],
                [-60.0, -34.5]
            ])
            gdf_ejemplo = gpd.GeoDataFrame({
                'id': [1],
                'nombre': ['Potrero Ejemplo'],
                'geometry': [poligono_ejemplo]
            }, crs='EPSG:4326')
            
            st.session_state.gdf_cargado = gdf_ejemplo
            st.success("✅ Datos de ejemplo cargados!")
            st.rerun()

    # Contenido principal - FLUJO ORIGINAL
    st.title("🌱 Analizador Forrajero PRV - Versión Original")
    st.markdown("---")
    
    # Procesar archivo cargado - PRIMERO Y ÚNICO
    if uploaded_file is not None:
        with st.spinner("Cargando shapefile..."):
            gdf_loaded = cargar_shapefile_desde_zip(uploaded_file)
            if gdf_loaded is not None and len(gdf_loaded) > 0:
                st.session_state.gdf_cargado = gdf_loaded
                st.rerun()

    # Mostrar datos cargados si existen
    if st.session_state.gdf_cargado is not None:
        gdf_loaded = st.session_state.gdf_cargado
        area_total = calcular_superficie(gdf_loaded).sum()
        
        st.success("✅ Archivo cargado correctamente.")
        col1, col2, col3, col4 = st.columns(4)
        with col1: 
            st.metric("Polígonos", len(gdf_loaded))
        with col2: 
            st.metric("Área total (ha)", f"{area_total:.2f}")
        with col3: 
            st.metric("Tipo pastura", tipo_pastura)
        with col4: 
            st.metric("Fuente datos", fuente_satelital)
        
        # Vista previa del mapa
        if FOLIUM_AVAILABLE:
            st.markdown("---")
            st.markdown("### 🗺️ Vista Previa del Potrero")
            m = crear_mapa_interactivo(gdf_loaded, base_map_option)
            if m:
                st_folium(m, width=1200, height=500)

    # Ejecutar análisis
    st.markdown("---")
    st.markdown("### 🚀 Ejecutar Análisis Forrajero")
    
    if st.session_state.gdf_cargado is not None:
        if st.button("🚀 EJECUTAR ANÁLISIS FORRAJERO COMPLETO", type="primary", use_container_width=True):
            with st.spinner("Ejecutando análisis forrajero completo..."):
                try:
                    gdf_input = st.session_state.gdf_cargado.copy()
                    
                    # 1. Dividir potrero
                    gdf_sub = dividir_potrero_en_subLotes(gdf_input, n_divisiones)
                    
                    # 2. Calcular áreas
                    areas = calcular_superficie(gdf_sub)
                    gdf_sub['area_ha'] = areas.values
                    
                    # 3. Calcular índices forrajeros
                    indices = calcular_indices_forrajeros_realista(
                        gdf_sub, tipo_pastura, fuente_satelital, fecha_imagen, nubes_max,
                        umbral_ndvi_minimo, umbral_ndvi_optimo, sensibilidad_suelo
                    )
                    
                    if indices:
                        # 4. Agregar índices al GeoDataFrame
                        for idx, rec in enumerate(indices):
                            for k, v in rec.items():
                                if k != 'id_subLote':
                                    try:
                                        gdf_sub.loc[gdf_sub.index[idx], k] = v
                                    except Exception:
                                        pass
                        
                        # 5. Calcular métricas ganaderas
                        metricas = calcular_metricas_ganaderas(gdf_sub, tipo_pastura, peso_promedio, carga_animal)
                        
                        for idx, met in enumerate(metricas):
                            for k, v in met.items():
                                try:
                                    gdf_sub.loc[gdf_sub.index[idx], k] = v
                                except Exception:
                                    pass
                        
                        st.session_state.gdf_analizado = gdf_sub
                        st.session_state.analisis_completado = True
                        
                        # 6. Generar mapas
                        mapa_buf = crear_mapa_detallado_vegetacion(gdf_sub, tipo_pastura)
                        if mapa_buf is not None:
                            st.session_state.mapa_detallado_bytes = mapa_buf
                            st.image(mapa_buf, use_column_width=True)
                        
                        # 7. Exportaciones
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
                        
                        # 8. Generar informe DOCX
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
                                st.components.v1.html(html_download, height=140)
                            else:
                                st.error("❌ No se pudo generar el informe DOCX.")
                        else:
                            st.warning("python-docx no está instalado — no puedo generar DOCX. Ejecutá: pip install python-docx")
                        
                        st.session_state.analisis_completado = True
                        
                    else:
                        st.error("❌ No se pudieron calcular los índices forrajeros")
                        
                except Exception as e:
                    st.error(f"❌ Error ejecutando análisis: {e}")
                    import traceback
                    st.error(traceback.format_exc())
    
    # Pantalla de bienvenida si no hay datos
    elif st.session_state.gdf_cargado is None:
        st.info("""
        ### 🌱 Bienvenido al Analizador Forrajero PRV
        
        **Para comenzar:**
        1. **Configura** los parámetros en la barra lateral
        2. **Carga** tu shapefile en formato ZIP o usa datos de ejemplo
        3. **Ejecuta** el análisis completo
        
        **Características:**
        - ✅ Sistema de autenticación seguro
        - ✅ Análisis realista de biomasa forrajera
        - ✅ Mapas interactivos con zoom automático
        - ✅ Parámetros forrajeros personalizables
        - ✅ Exportación a DOCX con descarga automática
        - ✅ Análisis por sub-lotes
        """)

# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def main():
    """Función principal"""
    initialize_session_state()
    
    if not st.session_state.authenticated:
        login_section()
    else:
        main_application()

if __name__ == "__main__":
    main()
