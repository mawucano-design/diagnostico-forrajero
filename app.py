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
    page_title="🌱 Analizador Forrajero Unificado",
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
    
    with st.expander("ℹ️ Información de acceso demo"):
        st.markdown("""
        **Usuarios de prueba:**
        - **admin** / password123
        - **user** / user123  
        - **tech** / tech123
        """)

# =============================================================================
# PARÁMETROS FORRAJEROS
# =============================================================================

PARAMETROS_FORRAJEROS = {
    'ALFALFA': {
        'MS_POR_HA_OPTIMO': 4500,
        'CRECIMIENTO_DIARIO': 85,
        'CONSUMO_PORCENTAJE_PESO': 0.032,
        'TASA_UTILIZACION_RECOMENDADA': 0.68,
        'FACTOR_BIOMASA_NDVI': 3200,
        'UMBRAL_NDVI_SUELO': 0.12,
        'UMBRAL_NDVI_PASTURA': 0.42,
        'CONSUMO_DIARIO_EV': 13,
        'EFICIENCIA_PASTOREO': 0.78,
        'EFICIENCIA_COSECHA': 0.72,
    },
    'RAYGRASS': {
        'MS_POR_HA_OPTIMO': 3800,
        'CRECIMIENTO_DIARIO': 75,
        'CONSUMO_PORCENTAJE_PESO': 0.029,
        'TASA_UTILIZACION_RECOMENDADA': 0.62,
        'FACTOR_BIOMASA_NDVI': 2800,
        'UMBRAL_NDVI_SUELO': 0.15,
        'UMBRAL_NDVI_PASTURA': 0.48,
        'CONSUMO_DIARIO_EV': 11,
        'EFICIENCIA_PASTOREO': 0.72,
        'EFICIENCIA_COSECHA': 0.67,
    },
    'FESTUCA': {
        'MS_POR_HA_OPTIMO': 3200,
        'CRECIMIENTO_DIARIO': 55,
        'CONSUMO_PORCENTAJE_PESO': 0.026,
        'TASA_UTILIZACION_RECOMENDADA': 0.58,
        'FACTOR_BIOMASA_NDVI': 2400,
        'UMBRAL_NDVI_SUELO': 0.18,
        'UMBRAL_NDVI_PASTURA': 0.52,
        'CONSUMO_DIARIO_EV': 10,
        'EFICIENCIA_PASTOREO': 0.68,
        'EFICIENCIA_COSECHA': 0.62,
    },
    'PASTIZAL_NATURAL': {
        'MS_POR_HA_OPTIMO': 2800,
        'CRECIMIENTO_DIARIO': 45,
        'CONSUMO_PORCENTAJE_PESO': 0.024,
        'TASA_UTILIZACION_RECOMENDADA': 0.52,
        'FACTOR_BIOMASA_NDVI': 2200,
        'UMBRAL_NDVI_SUELO': 0.20,
        'UMBRAL_NDVI_PASTURA': 0.46,
        'CONSUMO_DIARIO_EV': 9,
        'EFICIENCIA_PASTOREO': 0.65,
        'EFICIENCIA_COSECHA': 0.58,
    }
}

def obtener_parametros(tipo_pastura):
    return PARAMETROS_FORRAJEROS.get(tipo_pastura, PARAMETROS_FORRAJEROS['FESTUCA'])

# =============================================================================
# FUNCIONES DE CÁLCULO
# =============================================================================

def calcular_ev_ha(biomasa_disponible_kg_ms_ha, consumo_diario_ev, eficiencia_pastoreo=0.7):
    if consumo_diario_ev <= 0:
        return 0
    ev_ha = (biomasa_disponible_kg_ms_ha * eficiencia_pastoreo) / consumo_diario_ev
    return max(0, round(ev_ha, 2))

def calcular_carga_animal_total(ev_ha, area_ha):
    return round(ev_ha * area_ha, 1)

def calcular_dias_permanencia(biomasa_total_kg, consumo_total_diario):
    if consumo_total_diario <= 0:
        return 0
    return min(round(biomasa_total_kg / consumo_total_diario, 1), 120)

def calcular_disponibilidad_forrajera(gdf_analizado, tipo_pastura):
    params = obtener_parametros(tipo_pastura)
    
    gdf_analizado['disponibilidad_forrajera_kg_ms_ha'] = (
        gdf_analizado['biomasa_disponible_kg_ms_ha'] * 
        params['EFICIENCIA_PASTOREO'] * 
        params['EFICIENCIA_COSECHA']
    ).round(0)
    
    condiciones = [
        gdf_analizado['disponibilidad_forrajera_kg_ms_ha'] < 800,
        gdf_analizado['disponibilidad_forrajera_kg_ms_ha'] < 2000,
        gdf_analizado['disponibilidad_forrajera_kg_ms_ha'] < 3500,
        gdf_analizado['disponibilidad_forrajera_kg_ms_ha'] >= 3500
    ]
    categorias = ['MUY BAJA', 'BAJA', 'MEDIA', 'ALTA']
    gdf_analizado['categoria_disponibilidad'] = np.select(condiciones, categorias, default='MEDIA')
    
    return gdf_analizado

# =============================================================================
# FUNCIONES DE MAPAS - SIMPLIFICADAS Y CORREGIDAS
# =============================================================================

def crear_mapa_base(center_lat=-34.0, center_lon=-60.0, zoom_start=6):
    """Crea un mapa base simple"""
    try:
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=zoom_start,
            tiles='OpenStreetMap'
        )
        return m
    except Exception as e:
        st.error(f"Error creando mapa base: {e}")
        return None

def crear_mapa_ndvi(gdf_analizado):
    """Crea mapa interactivo de NDVI"""
    if not FOLIUM_AVAILABLE or gdf_analizado is None or len(gdf_analizado) == 0:
        st.warning("No se pueden generar mapas: datos no disponibles")
        return None
        
    try:
        # Calcular centro del mapa
        bounds = gdf_analizado.total_bounds
        center_lat = (bounds[1] + bounds[3]) / 2
        center_lon = (bounds[0] + bounds[2]) / 2
        
        m = crear_mapa_base(center_lat, center_lon, 10)
        if m is None:
            return None
        
        # Asegurarse de que tenemos datos NDVI
        if 'ndvi' not in gdf_analizado.columns:
            st.error("❌ No hay datos NDVI para mostrar")
            return m
            
        # Función de estilo para NDVI
        def estilo_ndvi(feature):
            ndvi = feature['properties']['ndvi']
            if ndvi < 0.2:
                color = '#8B4513'  # Marrón
            elif ndvi < 0.4:
                color = '#FFD700'  # Amarillo
            elif ndvi < 0.6:
                color = '#32CD32'  # Verde claro
            else:
                color = '#006400'  # Verde oscuro
                
            return {
                'fillColor': color,
                'color': 'black',
                'weight': 1,
                'fillOpacity': 0.7
            }
        
        # Agregar datos al mapa
        folium.GeoJson(
            gdf_analizado.__geo_interface__,
            style_function=estilo_ndvi,
            tooltip=folium.GeoJsonTooltip(
                fields=['id_subLote', 'ndvi', 'area_ha'],
                aliases=['Sub-Lote:', 'NDVI:', 'Área (ha):'],
                localize=True
            )
        ).add_to(m)
        
        # Leyenda simple
        legend_html = '''
        <div style="position: fixed; bottom: 20px; left: 20px; width: 200px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px">
            <p><strong>🌿 Índice NDVI</strong></p>
            <p><i style="background:#8B4513; width:20px; height:20px; display:inline-block; margin-right:5px"></i> < 0.2 (Bajo)</p>
            <p><i style="background:#FFD700; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 0.2-0.4 (Medio)</p>
            <p><i style="background:#32CD32; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 0.4-0.6 (Bueno)</p>
            <p><i style="background:#006400; width:20px; height:20px; display:inline-block; margin-right:5px"></i> > 0.6 (Excelente)</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
        
    except Exception as e:
        st.error(f"Error creando mapa NDVI: {e}")
        return None

def crear_mapa_ev_ha(gdf_analizado):
    """Crea mapa interactivo de EV/ha"""
    if not FOLIUM_AVAILABLE or gdf_analizado is None or len(gdf_analizado) == 0:
        return None
        
    try:
        bounds = gdf_analizado.total_bounds
        center_lat = (bounds[1] + bounds[3]) / 2
        center_lon = (bounds[0] + bounds[2]) / 2
        
        m = crear_mapa_base(center_lat, center_lon, 10)
        if m is None:
            return None
            
        if 'ev_ha' not in gdf_analizado.columns:
            st.error("❌ No hay datos EV/ha para mostrar")
            return m
            
        def estilo_ev_ha(feature):
            ev_ha = feature['properties']['ev_ha']
            if ev_ha < 1.0:
                color = '#FF4444'  # Rojo
            elif ev_ha < 2.0:
                color = '#FFA726'  # Naranja
            elif ev_ha < 3.0:
                color = '#FFD54F'  # Amarillo
            else:
                color = '#66BB6A'  # Verde
                
            return {
                'fillColor': color,
                'color': 'black',
                'weight': 1,
                'fillOpacity': 0.7
            }
        
        folium.GeoJson(
            gdf_analizado.__geo_interface__,
            style_function=estilo_ev_ha,
            tooltip=folium.GeoJsonTooltip(
                fields=['id_subLote', 'ev_ha', 'area_ha'],
                aliases=['Sub-Lote:', 'EV/ha:', 'Área (ha):'],
                localize=True
            )
        ).add_to(m)
        
        legend_html = '''
        <div style="position: fixed; bottom: 20px; left: 20px; width: 180px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px">
            <p><strong>🐄 EV/ha</strong></p>
            <p><i style="background:#FF4444; width:20px; height:20px; display:inline-block; margin-right:5px"></i> < 1.0</p>
            <p><i style="background:#FFA726; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 1.0-2.0</p>
            <p><i style="background:#FFD54F; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 2.0-3.0</p>
            <p><i style="background:#66BB6A; width:20px; height:20px; display:inline-block; margin-right:5px"></i> > 3.0</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
        
    except Exception as e:
        st.error(f"Error creando mapa EV/ha: {e}")
        return None

def crear_mapa_disponibilidad(gdf_analizado):
    """Crea mapa interactivo de disponibilidad forrajera"""
    if not FOLIUM_AVAILABLE or gdf_analizado is None or len(gdf_analizado) == 0:
        return None
        
    try:
        bounds = gdf_analizado.total_bounds
        center_lat = (bounds[1] + bounds[3]) / 2
        center_lon = (bounds[0] + bounds[2]) / 2
        
        m = crear_mapa_base(center_lat, center_lon, 10)
        if m is None:
            return None
            
        if 'categoria_disponibilidad' not in gdf_analizado.columns:
            st.error("❌ No hay datos de disponibilidad para mostrar")
            return m
            
        def estilo_disponibilidad(feature):
            categoria = feature['properties']['categoria_disponibilidad']
            if categoria == 'MUY BAJA':
                color = '#D32F2F'  # Rojo
            elif categoria == 'BAJA':
                color = '#FF5252'  # Rojo claro
            elif categoria == 'MEDIA':
                color = '#FFEB3B'  # Amarillo
            else:
                color = '#4CAF50'  # Verde
                
            return {
                'fillColor': color,
                'color': 'black',
                'weight': 1,
                'fillOpacity': 0.7
            }
        
        folium.GeoJson(
            gdf_analizado.__geo_interface__,
            style_function=estilo_disponibilidad,
            tooltip=folium.GeoJsonTooltip(
                fields=['id_subLote', 'categoria_disponibilidad', 'disponibilidad_forrajera_kg_ms_ha'],
                aliases=['Sub-Lote:', 'Categoría:', 'Disponibilidad (kg MS/ha):'],
                localize=True
            )
        ).add_to(m)
        
        legend_html = '''
        <div style="position: fixed; bottom: 20px; left: 20px; width: 220px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px">
            <p><strong>📊 Disponibilidad</strong></p>
            <p><i style="background:#D32F2F; width:20px; height:20px; display:inline-block; margin-right:5px"></i> Muy Baja</p>
            <p><i style="background:#FF5252; width:20px; height:20px; display:inline-block; margin-right:5px"></i> Baja</p>
            <p><i style="background:#FFEB3B; width:20px; height:20px; display:inline-block; margin-right:5px"></i> Media</p>
            <p><i style="background:#4CAF50; width:20px; height:20px; display:inline-block; margin-right:5px"></i> Alta</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
        
    except Exception as e:
        st.error(f"Error creando mapa disponibilidad: {e}")
        return None

# =============================================================================
# SISTEMA DE ANÁLISIS - SIMPLIFICADO Y FUNCIONAL
# =============================================================================

class AnalizadorForrajero:
    def __init__(self):
        self.datos_simulados = None
    
    def simular_datos_ndvi(self, geometry):
        """Simula datos NDVI realistas basados en la geometría"""
        try:
            centroid = geometry.centroid
            # Crear un patrón más realista basado en la posición
            x_norm = (centroid.x * 100) % 1
            y_norm = (centroid.y * 100) % 1
            
            # Patrón de variación más realista
            base_ndvi = 0.3 + (x_norm * 0.4)  # Base entre 0.3-0.7
            variacion = np.random.normal(0, 0.1)  # Variación aleatoria
            
            ndvi = base_ndvi + variacion
            return max(0.1, min(0.9, ndvi))
            
        except:
            return 0.5  # Valor por defecto
    
    def analizar_potrero(self, gdf, config):
        """Análisis completo simplificado pero funcional"""
        try:
            st.info("🔍 Iniciando análisis forrajero...")
            
            # 1. Dividir potrero en sub-lotes
            gdf_dividido = self._dividir_potrero(gdf, config['n_divisiones'])
            if gdf_dividido is None:
                st.error("Error dividiendo potrero")
                return None
            
            # 2. Calcular áreas
            gdf_dividido['area_ha'] = self._calcular_superficie(gdf_dividido)
            
            # 3. Simular datos de vegetación
            st.info("🌿 Simulando datos de vegetación...")
            for idx, row in gdf_dividido.iterrows():
                # Simular NDVI
                ndvi = self.simular_datos_ndvi(row.geometry)
                
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
                
                # Guardar resultados
                gdf_dividido.loc[idx, 'ndvi'] = round(ndvi, 3)
                gdf_dividido.loc[idx, 'tipo_superficie'] = tipo_veg
                gdf_dividido.loc[idx, 'biomasa_total_kg_ms_ha'] = round(biomasa_total, 0)
                gdf_dividido.loc[idx, 'biomasa_disponible_kg_ms_ha'] = round(biomasa_disponible, 0)
            
            # 4. Calcular métricas ganaderas
            st.info("🐄 Calculando métricas ganaderas...")
            gdf_analizado = self._calcular_metricas_ganaderas(gdf_dividido, config)
            
            # 5. Calcular disponibilidad forrajera
            gdf_analizado = calcular_disponibilidad_forrajera(gdf_analizado, config['tipo_pastura'])
            
            st.success("✅ Análisis completado exitosamente!")
            return gdf_analizado
            
        except Exception as e:
            st.error(f"❌ Error en análisis: {str(e)}")
            return None
    
    def _dividir_potrero(self, gdf, n_zonas):
        """Divide el potrero en sub-lotes de forma simple"""
        if len(gdf) == 0:
            return gdf
        
        try:
            # Si ya tiene múltiples polígonos, usarlos directamente
            if len(gdf) > 1:
                gdf_resultado = gdf.copy()
                gdf_resultado['id_subLote'] = range(1, len(gdf_resultado) + 1)
                return gdf_resultado
            
            # Dividir el primer polígono
            potrero = gdf.iloc[0].geometry
            bounds = potrero.bounds
            
            sub_poligonos = []
            n_cols = min(3, n_zonas)  # Máximo 3 columnas para simplificar
            n_rows = math.ceil(n_zonas / n_cols)
            
            width = (bounds[2] - bounds[0]) / n_cols
            height = (bounds[3] - bounds[1]) / n_rows
            
            for i in range(n_rows):
                for j in range(n_cols):
                    if len(sub_poligonos) >= n_zonas:
                        break
                        
                    cell = box(
                        bounds[0] + j * width,
                        bounds[1] + i * height,
                        bounds[0] + (j + 1) * width,
                        bounds[1] + (i + 1) * height
                    )
                    
                    intersection = potrero.intersection(cell)
                    if not intersection.is_empty:
                        sub_poligonos.append(intersection)
            
            if sub_poligonos:
                gdf_resultado = gpd.GeoDataFrame({
                    'id_subLote': range(1, len(sub_poligonos) + 1),
                    'geometry': sub_poligonos
                }, crs=gdf.crs)
                return gdf_resultado
            else:
                return gdf
                
        except Exception as e:
            st.error(f"Error dividiendo potrero: {e}")
            return gdf
    
    def _calcular_superficie(self, gdf):
        """Calcula superficie en hectáreas de forma simplificada"""
        try:
            # Conversión simple de metros cuadrados a hectáreas
            areas_m2 = gdf.geometry.area
            return areas_m2 / 10000.0
        except:
            # Fallback: asignar áreas iguales
            area_total = 100  # 100 ha por defecto
            return [area_total / len(gdf)] * len(gdf)
    
    def _calcular_metricas_ganaderas(self, gdf, config):
        """Calcula métricas ganaderas básicas"""
        params = obtener_parametros(config['tipo_pastura'])
        
        for idx, row in gdf.iterrows():
            area_ha = row['area_ha']
            biomasa_disponible = row['biomasa_disponible_kg_ms_ha']
            
            # EV/ha
            consumo_diario = config.get('consumo_voluntario', params['CONSUMO_DIARIO_EV'])
            eficiencia_pastoreo = config.get('eficiencia_pastoreo', params['EFICIENCIA_PASTOREO'])
            ev_ha = calcular_ev_ha(biomasa_disponible, consumo_diario, eficiencia_pastoreo)
            
            # Carga animal
            carga_animal = calcular_carga_animal_total(ev_ha, area_ha)
            
            # Días de permanencia
            biomasa_total_kg = biomasa_disponible * area_ha
            consumo_individual_kg = config['peso_promedio'] * params['CONSUMO_PORCENTAJE_PESO']
            consumo_total_diario = config['carga_animal'] * consumo_individual_kg
            
            dias_permanencia = calcular_dias_permanencia(biomasa_total_kg, consumo_total_diario)
            
            # Guardar resultados
            gdf.loc[idx, 'ev_ha'] = ev_ha
            gdf.loc[idx, 'carga_animal'] = carga_animal
            gdf.loc[idx, 'dias_permanencia'] = dias_permanencia
            gdf.loc[idx, 'consumo_individual_kg'] = round(consumo_individual_kg, 2)
            gdf.loc[idx, 'biomasa_total_kg'] = round(biomasa_total_kg, 0)
        
        return gdf

# =============================================================================
# INTERFAZ PRINCIPAL - SIMPLIFICADA
# =============================================================================

def main_application():
    """Aplicación principal simplificada"""
    
    # Sidebar de configuración
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
        
        # Parámetros básicos
        st.header("🌿 Configuración Básica")
        tipo_pastura = st.selectbox(
            "Tipo de Pastura:",
            ["ALFALFA", "RAYGRASS", "FESTUCA", "PASTIZAL_NATURAL"]
        )
        
        st.header("🐄 Parámetros Ganaderos")
        peso_promedio = st.slider("Peso promedio (kg):", 300, 600, 450)
        carga_animal = st.slider("Carga animal total:", 50, 500, 100)
        
        st.header("📐 Configuración Espacial")
        n_divisiones = st.slider("Número de sub-lotes:", 4, 16, 9)
        
        st.header("📤 Cargar Datos")
        uploaded_file = st.file_uploader("Shapefile (ZIP):", type=['zip'])
        
        # Botón para datos de ejemplo
        if st.button("🎲 Usar Datos de Ejemplo"):
            # Crear un GeoDataFrame de ejemplo
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
    
    # Contenido principal
    st.title("🌱 Analizador Forrajero - Versión Simplificada")
    st.markdown("---")
    
    # Inicializar analizador
    analizador = AnalizadorForrajero()
    
    # Procesar archivo cargado
    if uploaded_file is not None:
        with st.spinner("Cargando shapefile..."):
            try:
                with tempfile.TemporaryDirectory() as tmp_dir:
                    with zipfile.ZipFile(uploaded_file, 'r') as zip_ref:
                        zip_ref.extractall(tmp_dir)
                    
                    # Buscar archivo .shp
                    shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
                    if shp_files:
                        gdf = gpd.read_file(os.path.join(tmp_dir, shp_files[0]))
                        # Asegurar CRS
                        if gdf.crs is None:
                            gdf = gdf.set_crs('EPSG:4326')
                        elif gdf.crs != 'EPSG:4326':
                            gdf = gdf.to_crs('EPSG:4326')
                            
                        st.session_state.gdf_cargado = gdf
                        st.success(f"✅ Shapefile cargado: {len(gdf)} polígono(s)")
                    else:
                        st.error("❌ No se encontró archivo .shp en el ZIP")
            except Exception as e:
                st.error(f"❌ Error cargando shapefile: {e}")
    
    # Mostrar datos cargados
    if st.session_state.gdf_cargado is not None:
        gdf = st.session_state.gdf_cargado
        
        st.header("📁 Datos Cargados")
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Polígonos", len(gdf))
        with col2:
            area_total = gdf.geometry.area.sum() / 10000
            st.metric("Área Total", f"{area_total:.1f} ha")
        with col3:
            st.metric("Usuario", st.session_state.username)
        
        # Mostrar vista previa simple del shapefile
        st.subheader("🗺️ Vista Previa del Potrero")
        try:
            # Crear mapa simple de vista previa
            bounds = gdf.total_bounds
            center_lat = (bounds[1] + bounds[3]) / 2
            center_lon = (bounds[0] + bounds[2]) / 2
            
            m_preview = crear_mapa_base(center_lat, center_lon, 10)
            if m_preview:
                folium.GeoJson(
                    gdf.__geo_interface__,
                    style_function=lambda x: {
                        'fillColor': '#3388ff', 
                        'color': 'blue', 
                        'weight': 2, 
                        'fillOpacity': 0.3
                    }
                ).add_to(m_preview)
                folium_static(m_preview, width=700, height=400)
        except Exception as e:
            st.warning(f"No se pudo mostrar la vista previa: {e}")
        
        # Botón de análisis
        if st.button("🚀 EJECUTAR ANÁLISIS COMPLETO", type="primary", use_container_width=True):
            config = {
                'tipo_pastura': tipo_pastura,
                'peso_promedio': peso_promedio,
                'carga_animal': carga_animal,
                'n_divisiones': n_divisiones,
                'consumo_voluntario': 10.0,  # Valor por defecto
                'eficiencia_pastoreo': 0.7,   # Valor por defecto
            }
            
            with st.spinner("🔍 Realizando análisis forrajero..."):
                gdf_analizado = analizador.analizar_potrero(gdf, config)
                
                if gdf_analizado is not None:
                    st.session_state.gdf_analizado = gdf_analizado
                    st.session_state.analisis_completado = True
                    st.success("✅ ¡Análisis completado! Mostrando resultados...")
                    mostrar_resultados_completos(gdf_analizado, config)
                else:
                    st.error("❌ El análisis no pudo completarse")
    
    else:
        # Pantalla de bienvenida
        st.info("""
        ### 🌱 Bienvenido al Analizador Forrajero Simplificado
        
        **Para comenzar:**
        1. **Configura** los parámetros básicos en la barra lateral
        2. **Carga** tu shapefile en formato ZIP o usa datos de ejemplo
        3. **Ejecuta** el análisis completo
        4. **Explora** los resultados en mapas interactivos
        
        💡 **Tip:** Si no tienes un shapefile, usa el botón **"Usar Datos de Ejemplo"**
        """)

def mostrar_resultados_completos(gdf_analizado, config):
    """Muestra resultados completos del análisis"""
    st.header("📊 RESULTADOS DEL ANÁLISIS")
    
    # Métricas principales
    st.subheader("📈 Métricas Principales")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        biomasa_prom = gdf_analizado['biomasa_disponible_kg_ms_ha'].mean()
        st.metric("Biomasa Disponible", f"{biomasa_prom:.0f} kg MS/ha")
    
    with col2:
        disponibilidad_prom = gdf_analizado['disponibilidad_forrajera_kg_ms_ha'].mean()
        st.metric("Disponibilidad", f"{disponibilidad_prom:.0f} kg MS/ha")
    
    with col3:
        ev_total = gdf_analizado['carga_animal'].sum()
        st.metric("Capacidad Total", f"{ev_total:.1f} EV")
    
    with col4:
        dias_prom = gdf_analizado['dias_permanencia'].mean()
        st.metric("Días Permanencia", f"{dias_prom:.1f}")
    
    # Distribución de disponibilidad
    st.subheader("📊 Distribución de Disponibilidad")
    if 'categoria_disponibilidad' in gdf_analizado.columns:
        distribucion = gdf_analizado['categoria_disponibilidad'].value_counts()
        col_dist1, col_dist2, col_dist3, col_dist4 = st.columns(4)
        
        with col_dist1:
            st.metric("🔴 Muy Baja", distribucion.get('MUY BAJA', 0))
        with col_dist2:
            st.metric("🟠 Baja", distribucion.get('BAJA', 0))
        with col_dist3:
            st.metric("🟡 Media", distribucion.get('MEDIA', 0))
        with col_dist4:
            st.metric("🟢 Alta", distribucion.get('ALTA', 0))
    
    # MAPAS INTERACTIVOS - AHORA DEBERÍAN FUNCIONAR
    if FOLIUM_AVAILABLE and gdf_analizado is not None and len(gdf_analizado) > 0:
        st.header("🗺️ MAPAS INTERACTIVOS")
        st.info("💡 **Los mapas muestran los resultados del análisis por sub-lote**")
        
        # Pestañas para diferentes mapas
        tab1, tab2, tab3 = st.tabs(["🌿 NDVI", "🐄 EV/ha", "📊 Disponibilidad"])
        
        with tab1:
            st.subheader("Índice NDVI - Estado Vegetativo")
            mapa_ndvi = crear_mapa_ndvi(gdf_analizado)
            if mapa_ndvi:
                folium_static(mapa_ndvi, width=800, height=500)
                st.success("✅ Mapa de NDVI generado correctamente")
            else:
                st.error("❌ No se pudo generar el mapa de NDVI")
        
        with tab2:
            st.subheader("Capacidad de Carga - EV/ha")
            mapa_ev = crear_mapa_ev_ha(gdf_analizado)
            if mapa_ev:
                folium_static(mapa_ev, width=800, height=500)
                st.success("✅ Mapa de EV/ha generado correctamente")
            else:
                st.error("❌ No se pudo generar el mapa de EV/ha")
        
        with tab3:
            st.subheader("Disponibilidad Forrajera")
            mapa_disp = crear_mapa_disponibilidad(gdf_analizado)
            if mapa_disp:
                folium_static(mapa_disp, width=800, height=500)
                st.success("✅ Mapa de disponibilidad generado correctamente")
            else:
                st.error("❌ No se pudo generar el mapa de disponibilidad")
    
    else:
        st.warning("⚠️ No se pueden mostrar mapas interactivos")
    
    # Tabla de resultados
    st.header("📋 RESUMEN POR SUB-LOTE")
    columnas_mostrar = ['id_subLote', 'area_ha', 'ndvi', 'biomasa_disponible_kg_ms_ha', 
                       'disponibilidad_forrajera_kg_ms_ha', 'categoria_disponibilidad', 'ev_ha']
    
    columnas_disponibles = [col for col in columnas_mostrar if col in gdf_analizado.columns]
    
    if columnas_disponibles:
        df_resumen = gdf_analizado[columnas_disponibles].copy()
        # Renombrar columnas para mejor visualización
        nombres_amigables = {
            'id_subLote': 'Sub-Lote',
            'area_ha': 'Área (ha)',
            'ndvi': 'NDVI',
            'biomasa_disponible_kg_ms_ha': 'Biomasa (kg MS/ha)',
            'disponibilidad_forrajera_kg_ms_ha': 'Disponibilidad (kg MS/ha)',
            'categoria_disponibilidad': 'Categoría',
            'ev_ha': 'EV/ha'
        }
        df_resumen.columns = [nombres_amigables.get(col, col) for col in df_resumen.columns]
        st.dataframe(df_resumen, use_container_width=True)
    else:
        st.warning("No hay datos suficientes para mostrar la tabla")
    
    # Exportar datos
    st.header("💾 EXPORTAR RESULTADOS")
    col_exp1, col_exp2 = st.columns(2)
    
    with col_exp1:
        if st.button("📥 Descargar CSV", use_container_width=True):
            csv = gdf_analizado.to_csv(index=False)
            st.download_button(
                "💾 Descargar",
                csv,
                f"resultados_forrajeros_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv",
                key="download_csv"
            )
    
    with col_exp2:
        if st.button("📥 Descargar GeoJSON", use_container_width=True):
            geojson = gdf_analizado.to_json()
            st.download_button(
                "💾 Descargar", 
                geojson,
                f"resultados_forrajeros_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson",
                "application/json",
                key="download_geojson"
            )

# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def main():
    """Función principal de la aplicación"""
    initialize_session_state()
    
    if not st.session_state.authenticated:
        login_section()
    else:
        main_application()

if __name__ == "__main__":
    main()
    
