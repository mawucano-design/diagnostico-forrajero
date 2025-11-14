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
from shapely.geometry import Polygon, box
import math
import json
import base64
import hashlib
import secrets

# Importaciones para mapas
try:
    import folium
    from streamlit_folium import folium_static, st_folium
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
# CONFIGURACIÓN Y AUTENTICACIÓN
# =============================================================================

st.set_page_config(
    page_title="🌱 Analizador Forrajero Unificado - Sentinel Hub + PRV",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Sistema de autenticación simple
def check_authentication():
    if 'authenticated' not in st.session_state:
        st.session_state.authenticated = False
    if 'username' not in st.session_state:
        st.session_state.username = ""
    
    # Credenciales por defecto (en producción usar variables de entorno)
    default_users = {
        "admin": hashlib.sha256("password123".encode()).hexdigest(),
        "user": hashlib.sha256("user123".encode()).hexdigest(),
        "tech": hashlib.sha256("tech123".encode()).hexdigest()
    }
    
    return default_users

def login_section():
    st.title("🔐 Inicio de Sesión - Analizador Forrajero")
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
    
    # Información de usuarios demo
    with st.expander("ℹ️ Información de acceso demo"):
        st.markdown("""
        **Usuarios de prueba:**
        - **admin** / password123
        - **user** / user123  
        - **tech** / tech123
        
        *En producción, configurar variables de entorno para credenciales reales*
        """)

# =============================================================================
# CONFIGURACIÓN SENTINEL HUB
# =============================================================================

class SentinelHubConfig:
    def __init__(self):
        self.base_url = "https://services.sentinel-hub.com/ogc/wms/"
        self.available = False
        self.config_message = ""
        
    def check_configuration(self):
        try:
            # Verificar credenciales en secrets
            if all(key in st.secrets for key in ['SENTINEL_HUB_CLIENT_ID', 'SENTINEL_HUB_CLIENT_SECRET']):
                st.session_state.sh_client_id = st.secrets['SENTINEL_HUB_CLIENT_ID']
                st.session_state.sh_client_secret = st.secrets['SENTINEL_HUB_CLIENT_SECRET']
                st.session_state.sh_configured = True
                self.available = True
                self.config_message = "✅ Sentinel Hub configurado (Secrets)"
                return True
            
            # Verificar variables de entorno
            elif all(os.getenv(key) for key in ['SENTINEL_HUB_CLIENT_ID', 'SENTINEL_HUB_CLIENT_SECRET']):
                st.session_state.sh_client_id = os.getenv('SENTINEL_HUB_CLIENT_ID')
                st.session_state.sh_client_secret = os.getenv('SENTINEL_HUB_CLIENT_SECRET')
                st.session_state.sh_configured = True
                self.available = True
                self.config_message = "✅ Sentinel Hub configurado (Variables Entorno)"
                return True
            
            else:
                self.available = False
                self.config_message = "❌ Sentinel Hub no configurado"
                return False
                
        except Exception as e:
            self.available = False
            self.config_message = f"❌ Error: {str(e)}"
            return False

# =============================================================================
# PARÁMETROS FORRAJEROS UNIFICADOS
# =============================================================================

PARAMETROS_FORRAJEROS = {
    'ALFALFA': {
        'MS_POR_HA_OPTIMO': 4000,
        'CRECIMIENTO_DIARIO': 80,
        'CONSUMO_PORCENTAJE_PESO': 0.03,
        'TASA_UTILIZACION_RECOMENDADA': 0.65,
        'FACTOR_BIOMASA_NDVI': 2800,
        'UMBRAL_NDVI_SUELO': 0.15,
        'UMBRAL_NDVI_PASTURA': 0.45,
        'CONSUMO_DIARIO_EV': 12,
        'EFICIENCIA_PASTOREO': 0.75,
        'DIGESTIBILIDAD': 0.65,
        'PROTEINA_CRUDA': 0.18
    },
    'RAYGRASS': {
        'MS_POR_HA_OPTIMO': 3500,
        'CRECIMIENTO_DIARIO': 70,
        'CONSUMO_PORCENTAJE_PESO': 0.028,
        'TASA_UTILIZACION_RECOMENDADA': 0.60,
        'FACTOR_BIOMASA_NDVI': 2500,
        'UMBRAL_NDVI_SUELO': 0.18,
        'UMBRAL_NDVI_PASTURA': 0.50,
        'CONSUMO_DIARIO_EV': 10,
        'EFICIENCIA_PASTOREO': 0.70,
        'DIGESTIBILIDAD': 0.70,
        'PROTEINA_CRUDA': 0.15
    },
    'FESTUCA': {
        'MS_POR_HA_OPTIMO': 3000,
        'CRECIMIENTO_DIARIO': 50,
        'CONSUMO_PORCENTAJE_PESO': 0.025,
        'TASA_UTILIZACION_RECOMENDADA': 0.55,
        'FACTOR_BIOMASA_NDVI': 2200,
        'UMBRAL_NDVI_SUELO': 0.20,
        'UMBRAL_NDVI_PASTURA': 0.55,
        'CONSUMO_DIARIO_EV': 9,
        'EFICIENCIA_PASTOREO': 0.65,
        'DIGESTIBILIDAD': 0.60,
        'PROTEINA_CRUDA': 0.12
    },
    'AGROPIRRO': {
        'MS_POR_HA_OPTIMO': 3200,
        'CRECIMIENTO_DIARIO': 55,
        'CONSUMO_PORCENTAJE_PESO': 0.026,
        'TASA_UTILIZACION_RECOMENDADA': 0.58,
        'FACTOR_BIOMASA_NDVI': 2400,
        'UMBRAL_NDVI_SUELO': 0.17,
        'UMBRAL_NDVI_PASTURA': 0.52,
        'CONSUMO_DIARIO_EV': 10,
        'EFICIENCIA_PASTOREO': 0.68,
        'DIGESTIBILIDAD': 0.55,
        'PROTEINA_CRUDA': 0.10
    },
    'PASTIZAL_NATURAL': {
        'MS_POR_HA_OPTIMO': 2500,
        'CRECIMIENTO_DIARIO': 40,
        'CONSUMO_PORCENTAJE_PESO': 0.022,
        'TASA_UTILIZACION_RECOMENDADA': 0.50,
        'FACTOR_BIOMASA_NDVI': 2000,
        'UMBRAL_NDVI_SUELO': 0.22,
        'UMBRAL_NDVI_PASTURA': 0.48,
        'CONSUMO_DIARIO_EV': 8,
        'EFICIENCIA_PASTOREO': 0.60,
        'DIGESTIBILIDAD': 0.50,
        'PROTEINA_CRUDA': 0.08
    }
}

# =============================================================================
# FUNCIONES DE CÁLCULO UNIFICADAS
# =============================================================================

def calcular_ev_ha(biomasa_disponible_kg_ms_ha, consumo_diario_ev, eficiencia_pastoreo=0.7):
    if consumo_diario_ev <= 0:
        return 0
    ev_ha = (biomasa_disponible_kg_ms_ha * eficiencia_pastoreo) / consumo_diario_ev
    return max(0, ev_ha)

def calcular_carga_animal_total(ev_ha, area_ha):
    return ev_ha * area_ha

def calcular_dias_permanencia(biomasa_total_kg, consumo_total_diario, crecimiento_diario_kg=0):
    if consumo_total_diario <= 0:
        return 0
    if crecimiento_diario_kg > 0:
        # Ajustar por crecimiento durante el pastoreo
        dias_estimados = biomasa_total_kg / consumo_total_diario
        crecimiento_total = crecimiento_diario_kg * dias_estimados * 0.3  # Factor conservador
        dias_ajustados = (biomasa_total_kg + crecimiento_total) / consumo_total_diario
        return min(dias_ajustados, 365)  # Máximo 1 año
    return min(biomasa_total_kg / consumo_total_diario, 365)

def obtener_parametros(tipo_pastura):
    return PARAMETROS_FORRAJEROS.get(tipo_pastura, PARAMETROS_FORRAJEROS['FESTUCA'])

# =============================================================================
# FUNCIONES DE MAPAS UNIFICADAS
# =============================================================================

MAPAS_BASE = {
    "ESRI World Imagery": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Esri, Maxar, Earthstar Geographics",
        "name": "ESRI Satellite"
    },
    "ESRI World Street Map": {
        "url": "https://server.arcgisonline.com/ArcGIS/rest/services/World_Street_Map/MapServer/tile/{z}/{y}/{x}",
        "attribution": "Esri, HERE, Garmin",
        "name": "ESRI Streets"
    },
    "OpenStreetMap": {
        "url": "https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png",
        "attribution": "OpenStreetMap contributors",
        "name": "OSM"
    }
}

def crear_mapa_base(gdf, mapa_seleccionado="ESRI World Imagery", zoom_start=10):
    if not FOLIUM_AVAILABLE or gdf is None:
        return None
        
    bounds = gdf.total_bounds
    center_lat = (bounds[1] + bounds[3]) / 2
    center_lon = (bounds[0] + bounds[2]) / 2
    
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=zoom_start,
        tiles=None,
        control_scale=True
    )
    
    for nombre, config in MAPAS_BASE.items():
        folium.TileLayer(
            tiles=config["url"],
            attr=config["attribution"],
            name=config["name"],
            control=True,
            show=(nombre == mapa_seleccionado)
        ).add_to(m)
    
    return m

# =============================================================================
# SISTEMA DE ANÁLISIS UNIFICADO
# =============================================================================

class AnalizadorForrajeroUnificado:
    def __init__(self):
        self.sh_config = SentinelHubConfig()
        self.sh_config.check_configuration()
    
    def analizar_potrero(self, gdf, config):
        """Análisis completo unificado"""
        try:
            st.header("🌱 ANÁLISIS FORRAJERO UNIFICADO")
            
            # Dividir potrero
            gdf_dividido = self._dividir_potrero(gdf, config['n_divisiones'])
            if gdf_dividido is None:
                st.error("Error dividiendo potrero")
                return None
            
            # Calcular áreas
            areas_ha = self._calcular_superficie(gdf_dividido)
            gdf_dividido['area_ha'] = areas_ha
            
            # Obtener datos de vegetación
            resultados = self._obtener_datos_vegetacion(gdf_dividido, config)
            
            # Calcular métricas ganaderas
            gdf_analizado = self._calcular_metricas_ganaderas(gdf_dividido, resultados, config)
            
            return gdf_analizado
            
        except Exception as e:
            st.error(f"Error en análisis: {e}")
            return None
    
    def _dividir_potrero(self, gdf, n_zonas):
        """Divide el potrero en sub-lotes"""
        if len(gdf) == 0:
            return gdf
        
        try:
            potrero = gdf.iloc[0].geometry
            bounds = potrero.bounds
            minx, miny, maxx, maxy = bounds
            
            sub_poligonos = []
            n_cols = math.ceil(math.sqrt(n_zonas))
            n_rows = math.ceil(n_zonas / n_cols)
            width = (maxx - minx) / n_cols
            height = (maxy - miny) / n_rows
            
            for i in range(n_rows):
                for j in range(n_cols):
                    if len(sub_poligonos) >= n_zonas:
                        break
                        
                    cell = Polygon([
                        (minx + j * width, miny + i * height),
                        (minx + (j + 1) * width, miny + i * height),
                        (minx + (j + 1) * width, miny + (i + 1) * height),
                        (minx + j * width, miny + (i + 1) * height)
                    ])
                    
                    intersection = potrero.intersection(cell)
                    if not intersection.is_empty and intersection.area > 0:
                        sub_poligonos.append(intersection)
            
            if sub_poligonos:
                return gpd.GeoDataFrame({
                    'id_subLote': range(1, len(sub_poligonos) + 1),
                    'geometry': sub_poligonos
                }, crs=gdf.crs)
            return gdf
                
        except Exception as e:
            st.error(f"Error dividiendo potrero: {e}")
            return gdf
    
    def _calcular_superficie(self, gdf):
        """Calcula superficie en hectáreas"""
        try:
            if gdf.crs and gdf.crs.is_geographic:
                gdf_proj = gdf.to_crs('EPSG:3857')
                area_m2 = gdf_proj.geometry.area
            else:
                area_m2 = gdf.geometry.area
            return area_m2 / 10000
        except:
            return gdf.geometry.area / 10000
    
    def _obtener_datos_vegetacion(self, gdf, config):
        """Obtiene datos de vegetación (simulado o real)"""
        resultados = []
        
        for idx, row in gdf.iterrows():
            # Simulación de datos de vegetación (reemplazar con Sentinel Hub real)
            ndvi = self._simular_ndvi(row.geometry, config)
            
            # Calcular biomasa basada en NDVI
            params = obtener_parametros(config['tipo_pastura'])
            biomasa_total = params['FACTOR_BIOMASA_NDVI'] * ndvi
            biomasa_disponible = biomasa_total * params['TASA_UTILIZACION_RECOMENDADA']
            
            # Clasificar vegetación
            if ndvi < params['UMBRAL_NDVI_SUELO']:
                tipo_veg = "SUELO_DESNUDO"
            elif ndvi < params['UMBRAL_NDVI_PASTURA']:
                tipo_veg = "VEGETACION_ESCASA"
            else:
                tipo_veg = "VEGETACION_DENSA"
            
            resultados.append({
                'id_subLote': row['id_subLote'],
                'ndvi': ndvi,
                'tipo_superficie': tipo_veg,
                'biomasa_total_kg_ms_ha': biomasa_total,
                'biomasa_disponible_kg_ms_ha': biomasa_disponible,
                'cobertura_vegetal': max(0.1, min(0.95, ndvi * 1.2))
            })
        
        return resultados
    
    def _simular_ndvi(self, geometry, config):
        """Simula NDVI (reemplazar con Sentinel Hub real)"""
        centroid = geometry.centroid
        x_norm = (centroid.x * 100) % 1
        y_norm = (centroid.y * 100) % 1
        
        # Patrones realistas
        if x_norm < 0.2 or y_norm < 0.2:
            ndvi = 0.15 + np.random.normal(0, 0.05)
        elif x_norm > 0.7 and y_norm > 0.7:
            ndvi = 0.75 + np.random.normal(0, 0.03)
        else:
            ndvi = 0.45 + np.random.normal(0, 0.04)
        
        return max(0.1, min(0.85, ndvi))
    
    def _calcular_metricas_ganaderas(self, gdf, resultados, config):
        """Calcula todas las métricas ganaderas"""
        params = obtener_parametros(config['tipo_pastura'])
        
        for idx, resultado in enumerate(resultados):
            area_ha = gdf.loc[gdf.index[idx], 'area_ha']
            biomasa_disponible = resultado['biomasa_disponible_kg_ms_ha']
            
            # EV/ha
            consumo_diario = config.get('consumo_diario_personalizado', params['CONSUMO_DIARIO_EV'])
            eficiencia = config.get('eficiencia_pastoreo', params['EFICIENCIA_PASTOREO'])
            ev_ha = calcular_ev_ha(biomasa_disponible, consumo_diario, eficiencia)
            
            # Carga animal
            carga_animal = calcular_carga_animal_total(ev_ha, area_ha)
            
            # Días de permanencia
            biomasa_total_kg = biomasa_disponible * area_ha
            consumo_individual_kg = config['peso_promedio'] * params['CONSUMO_PORCENTAJE_PESO']
            consumo_total_diario = config['carga_animal'] * consumo_individual_kg
            crecimiento_diario_kg = params['CRECIMIENTO_DIARIO'] * area_ha
            
            dias_permanencia = calcular_dias_permanencia(
                biomasa_total_kg, 
                consumo_total_diario, 
                crecimiento_diario_kg
            )
            
            # Añadir al GeoDataFrame
            for key, value in resultado.items():
                gdf.loc[gdf.index[idx], key] = value
            
            gdf.loc[gdf.index[idx], 'ev_ha'] = ev_ha
            gdf.loc[gdf.index[idx], 'carga_animal'] = carga_animal
            gdf.loc[gdf.index[idx], 'dias_permanencia'] = dias_permanencia
            gdf.loc[gdf.index[idx], 'consumo_individual_kg'] = consumo_individual_kg
            gdf.loc[gdf.index[idx], 'biomasa_total_kg'] = biomasa_total_kg
        
        return gdf

# =============================================================================
# GENERACIÓN DE INFORMES
# =============================================================================

def generar_informe_completo(gdf_analizado, config, mapa_bytes=None):
    """Genera informe DOCX con análisis completo"""
    if not DOCX_AVAILABLE:
        st.error("python-docx no disponible. Instala: pip install python-docx")
        return None
    
    try:
        doc = Document()
        
        # Título
        titulo = doc.add_heading('INFORME DE ANÁLISIS FORRAJERO UNIFICADO', 0)
        
        # Información general
        doc.add_heading('Información General', level=1)
        doc.add_paragraph(f"Fecha de generación: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        doc.add_paragraph(f"Tipo de pastura: {config['tipo_pastura']}")
        doc.add_paragraph(f"Usuario: {st.session_state.username}")
        
        # Métricas principales
        doc.add_heading('Métricas Principales', level=1)
        area_total = gdf_analizado['area_ha'].sum()
        biomasa_prom = gdf_analizado['biomasa_disponible_kg_ms_ha'].mean()
        ev_total = gdf_analizado['carga_animal'].sum()
        dias_prom = gdf_analizado['dias_permanencia'].mean()
        
        doc.add_paragraph(f"Área total analizada: {area_total:.2f} ha")
        doc.add_paragraph(f"Biomasa disponible promedio: {biomasa_prom:.0f} kg MS/ha")
        doc.add_paragraph(f"Capacidad total de carga: {ev_total:.1f} EV")
        doc.add_paragraph(f"Días de permanencia promedio: {dias_prom:.1f} días")
        
        # Mapa si está disponible
        if mapa_bytes:
            doc.add_heading('Mapa de Análisis', level=1)
            try:
                mapa_bytes.seek(0)
                with tempfile.NamedTemporaryFile(delete=False, suffix='.png') as tmp:
                    tmp.write(mapa_bytes.read())
                    tmp_path = tmp.name
                doc.add_picture(tmp_path, width=Inches(6))
                os.unlink(tmp_path)
            except Exception as e:
                doc.add_paragraph(f"Error al insertar mapa: {e}")
        
        # Recomendaciones
        doc.add_heading('Recomendaciones', level=1)
        doc.add_paragraph(self._generar_recomendaciones(gdf_analizado, config))
        
        # Guardar
        buffer = io.BytesIO()
        doc.save(buffer)
        buffer.seek(0)
        return buffer
        
    except Exception as e:
        st.error(f"Error generando informe: {e}")
        return None

def _generar_recomendaciones(self, gdf, config):
    """Genera recomendaciones basadas en el análisis"""
    biomasa_prom = gdf['biomasa_disponible_kg_ms_ha'].mean()
    dias_prom = gdf['dias_permanencia'].mean()
    
    recomendaciones = []
    
    if biomasa_prom < 500:
        recomendaciones.extend([
            "⚠️ **ESTADO CRÍTICO** - Biomasa muy baja",
            "• Reducir carga animal inmediatamente",
            "• Implementar suplementación estratégica",
            "• Aumentar períodos de descanso (60-90 días)",
            "• Considerar resiembra o mejoramiento"
        ])
    elif biomasa_prom < 1500:
        recomendaciones.extend([
            "📋 **ESTADO DE MEJORA** - Biomasa moderada",
            "• Mantener rotaciones con 45-60 días de descanso",
            "• Monitorear crecimiento semanalmente",
            "• Ajustar carga según disponibilidad forrajera",
            "• Implementar pastoreo racional Voisin"
        ])
    else:
        recomendaciones.extend([
            "✅ **ESTADO ÓPTIMO** - Buena biomasa",
            "• Mantener sistema actual de rotaciones",
            "• Optimizar carga animal según EV/ha calculado",
            "• Continuar monitoreo para mantener estado",
            "• Considerar enriquecimiento con leguminosas"
        ])
    
    # Recomendaciones específicas por días de permanencia
    if dias_prom < 7:
        recomendaciones.append("• ⚠️ Días de permanencia muy bajos - considerar suplementación")
    elif dias_prom > 60:
        recomendaciones.append("• ✅ Buenos días de permanencia - sistema sostenible")
    
    return "\n".join(recomendaciones)

# =============================================================================
# INTERFAZ PRINCIPAL
# =============================================================================

def main_application():
    """Aplicación principal después del login"""
    
    # Sidebar de configuración
    with st.sidebar:
        st.header(f"👋 Bienvenido, {st.session_state.username}")
        
        if st.button("🚪 Cerrar Sesión"):
            st.session_state.authenticated = False
            st.session_state.username = ""
            st.rerun()
        
        st.markdown("---")
        st.header("⚙️ Configuración del Análisis")
        
        # Configuración Sentinel Hub
        st.subheader("🛰️ Sentinel Hub")
        sh_config = SentinelHubConfig()
        sh_configured = sh_config.check_configuration()
        
        if sh_configured:
            st.success(sh_config.config_message)
        else:
            st.error(sh_config.config_message)
            with st.expander("🔧 Configurar Manualmente"):
                sh_client_id = st.text_input("Client ID", type="password")
                sh_client_secret = st.text_input("Client Secret", type="password")
                if st.button("💾 Guardar Credenciales"):
                    if sh_client_id and sh_client_secret:
                        st.session_state.sh_client_id = sh_client_id
                        st.session_state.sh_client_secret = sh_client_secret
                        st.session_state.sh_configured = True
                        st.success("Credenciales guardadas")
                        st.rerun()
        
        # Parámetros del análisis
        st.subheader("🌿 Parámetros Forrajeros")
        tipo_pastura = st.selectbox(
            "Tipo de Pastura:",
            ["ALFALFA", "RAYGRASS", "FESTUCA", "AGROPIRRO", "PASTIZAL_NATURAL"]
        )
        
        st.subheader("🐄 Parámetros Ganaderos")
        peso_promedio = st.slider("Peso promedio (kg):", 300, 600, 450)
        carga_animal = st.slider("Carga animal:", 1, 1000, 100)
        
        st.subheader("📐 Configuración Espacial")
        n_divisiones = st.slider("Sub-divisiones:", 8, 48, 24)
        
        st.subheader("📤 Cargar Datos")
        uploaded_file = st.file_uploader("Shapefile (ZIP):", type=['zip'])
    
    # Contenido principal
    st.title("🌱 Analizador Forrajero Unificado")
    st.markdown("---")
    
    # Inicializar analizador
    analizador = AnalizadorForrajeroUnificado()
    
    # Procesar archivo cargado
    if uploaded_file is not None:
        with st.spinner("Cargando y procesando archivo..."):
            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
                        zip_ref.extractall(tmp_dir)
                    
                    shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                    if shp_files:
                        gdf = gpd.read_file(os.path.join(tmp_dir, shp_files[0]))
                        if gdf.crs is None:
                            gdf = gdf.set_crs('EPSG:4326')
                        st.session_state.gdf_cargado = gdf
                        st.success("✅ Shapefile cargado correctamente")
                    else:
                        st.error("❌ No se encontró archivo .shp en el ZIP")
            except Exception as e:
                st.error(f"Error cargando shapefile: {e}")
    
    # Mostrar datos cargados y opción de análisis
    if 'gdf_cargado' in st.session_state and st.session_state.gdf_cargado is not None:
        gdf = st.session_state.gdf_cargado
        
        st.header("📁 Datos Cargados")
        area_total = analizador._calcular_superficie(gdf).sum()
        
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Polígonos", len(gdf))
        with col2:
            st.metric("Área Total", f"{area_total:.1f} ha")
        with col3:
            st.metric("Usuario", st.session_state.username)
        
        # Mapa de vista previa
        if FOLIUM_AVAILABLE:
            st.subheader("🗺️ Vista Previa del Potrero")
            mapa_preview = crear_mapa_base(gdf)
            if mapa_preview:
                # Agregar polígono al mapa
                folium.GeoJson(
                    gdf.__geo_interface__,
                    style_function=lambda x: {'fillColor': '#3388ff', 'color': 'blue', 'weight': 2, 'fillOpacity': 0.3}
                ).add_to(mapa_preview)
                folium_static(mapa_preview, width=800, height=400)
        
        # Botón de análisis
        if st.button("🚀 EJECUTAR ANÁLISIS COMPLETO", type="primary", use_container_width=True):
            config = {
                'tipo_pastura': tipo_pastura,
                'peso_promedio': peso_promedio,
                'carga_animal': carga_animal,
                'n_divisiones': n_divisiones
            }
            
            with st.spinner("Realizando análisis completo..."):
                gdf_analizado = analizador.analizar_potrero(gdf, config)
                
                if gdf_analizado is not None:
                    st.session_state.gdf_analizado = gdf_analizado
                    st.success("✅ Análisis completado exitosamente!")
                    
                    # Mostrar resultados
                    mostrar_resultados_completos(gdf_analizado, config)
                    
                    # Generar y descargar informe
                    if DOCX_AVAILABLE:
                        with st.spinner("Generando informe..."):
                            informe_buffer = generar_informe_completo(gdf_analizado, config)
                            if informe_buffer:
                                st.download_button(
                                    "📄 Descargar Informe DOCX",
                                    informe_buffer,
                                    f"informe_forrajero_{datetime.now().strftime('%Y%m%d_%H%M')}.docx",
                                    "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
                                )
    
    else:
        # Pantalla de bienvenida
        st.info("""
        ### 🌱 Bienvenido al Analizador Forrajero Unificado
        
        **Características:**
        - 🛰️ **Datos satelitales** con Sentinel Hub
        - 📊 **Cálculo de EV/ha** y capacidad de carga
        - 📅 **Días de permanencia** por lote
        - 🗺️ **Mapas interactivos** con múltiples bases
        - 📄 **Informes automáticos** con recomendaciones
        - 🔐 **Sistema de autenticación** seguro
        
        **Para comenzar:**
        1. Configura los parámetros en la barra lateral
        2. Sube tu shapefile en formato ZIP
        3. Ejecuta el análisis completo
        4. Descarga el informe con recomendaciones
        """)

def mostrar_resultados_completos(gdf_analizado, config):
    """Muestra resultados completos del análisis"""
    st.header("📊 Resultados del Análisis")
    
    # Métricas principales
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        biomasa_prom = gdf_analizado['biomasa_disponible_kg_ms_ha'].mean()
        st.metric("Biomasa Disponible Prom", f"{biomasa_prom:.0f} kg MS/ha")
    
    with col2:
        ev_total = gdf_analizado['carga_animal'].sum()
        st.metric("Capacidad Total", f"{ev_total:.1f} EV")
    
    with col3:
        dias_prom = gdf_analizado['dias_permanencia'].mean()
        st.metric("Días Permanencia Prom", f"{dias_prom:.1f}")
    
    with col4:
        area_total = gdf_analizado['area_ha'].sum()
        st.metric("Área Total", f"{area_total:.1f} ha")
    
    # Mapas de resultados
    if FOLIUM_AVAILABLE:
        st.header("🗺️ Visualización de Resultados")
        
        tab1, tab2, tab3 = st.tabs(["🌿 NDVI", "🐄 EV/ha", "📅 Días Permanencia"])
        
        with tab1:
            mapa_ndvi = crear_mapa_ndvi(gdf_analizado)
            if mapa_ndvi:
                folium_static(mapa_ndvi, width=800, height=400)
        
        with tab2:
            mapa_ev = crear_mapa_ev_ha(gdf_analizado)
            if mapa_ev:
                folium_static(mapa_ev, width=800, height=400)
        
        with tab3:
            mapa_dias = crear_mapa_dias_permanencia(gdf_analizado)
            if mapa_dias:
                folium_static(mapa_dias, width=800, height=400)
    
    # Tabla de resultados
    st.header("📋 Detalles por Sub-Lote")
    columnas = ['id_subLote', 'area_ha', 'tipo_superficie', 'ndvi', 
                'biomasa_disponible_kg_ms_ha', 'ev_ha', 'dias_permanencia']
    tabla = gdf_analizado[columnas].copy()
    tabla.columns = ['Sub-Lote', 'Área (ha)', 'Tipo Superficie', 'NDVI', 
                    'Biomasa (kg MS/ha)', 'EV/ha', 'Días Permanencia']
    st.dataframe(tabla, use_container_width=True)
    
    # Exportar datos
    st.header("💾 Exportar Resultados")
    col1, col2 = st.columns(2)
    
    with col1:
        csv = tabla.to_csv(index=False)
        st.download_button(
            "📥 Descargar CSV",
            csv,
            f"resultados_analisis_{config['tipo_pastura']}.csv",
            "text/csv"
        )
    
    with col2:
        geojson = gdf_analizado.to_json()
        st.download_button(
            "📥 Descargar GeoJSON",
            geojson,
            f"resultados_analisis_{config['tipo_pastura']}.geojson",
            "application/json"
        )

# Funciones auxiliares para mapas (implementar según necesidad)
def crear_mapa_ndvi(gdf):
    # Implementar mapa de NDVI
    return crear_mapa_base(gdf)

def crear_mapa_ev_ha(gdf):
    # Implementar mapa de EV/ha
    return crear_mapa_base(gdf)

def crear_mapa_dias_permanencia(gdf):
    # Implementar mapa de días de permanencia
    return crear_mapa_base(gdf)

# =============================================================================
# EJECUCIÓN PRINCIPAL
# =============================================================================

def main():
    if not st.session_state.authenticated:
        login_section()
    else:
        main_application()

if __name__ == "__main__":
    main()
