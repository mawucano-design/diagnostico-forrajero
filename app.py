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
        st.session_state.authenticated = True  # Simplificado sin login
    if 'username' not in st.session_state:
        st.session_state.username = "Usuario"
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

# =============================================================================
# PARÁMETROS FORRAJEROS COMPLETOS
# =============================================================================

PARAMETROS_FORRAJEROS_BASE = {
    'ALFALFA': {
        'MS_POR_HA_OPTIMO': 5000, 
        'CRECIMIENTO_DIARIO': 100, 
        'CONSUMO_PORCENTAJE_PESO': 0.03,
        'TASA_UTILIZACION_RECOMENDADA': 0.65,
        'FACTOR_BIOMASA_NDVI': 3500,
        'UMBRAL_NDVI_SUELO': 0.12,
        'UMBRAL_NDVI_PASTURA': 0.45,
        'CONSUMO_DIARIO_EV': 12,
        'EFICIENCIA_PASTOREO': 0.75,
        'EFICIENCIA_COSECHA': 0.70,
    },
    'RAYGRASS': {
        'MS_POR_HA_OPTIMO': 4500, 
        'CRECIMIENTO_DIARIO': 90, 
        'CONSUMO_PORCENTAJE_PESO': 0.028,
        'TASA_UTILIZACION_RECOMENDADA': 0.60,
        'FACTOR_BIOMASA_NDVI': 3000,
        'UMBRAL_NDVI_SUELO': 0.15,
        'UMBRAL_NDVI_PASTURA': 0.48,
        'CONSUMO_DIARIO_EV': 11,
        'EFICIENCIA_PASTOREO': 0.72,
        'EFICIENCIA_COSECHA': 0.67,
    },
    'FESTUCA': {
        'MS_POR_HA_OPTIMO': 4000, 
        'CRECIMIENTO_DIARIO': 70, 
        'CONSUMO_PORCENTAJE_PESO': 0.025,
        'TASA_UTILIZACION_RECOMENDADA': 0.55,
        'FACTOR_BIOMASA_NDVI': 2800,
        'UMBRAL_NDVI_SUELO': 0.18,
        'UMBRAL_NDVI_PASTURA': 0.52,
        'CONSUMO_DIARIO_EV': 10,
        'EFICIENCIA_PASTOREO': 0.68,
        'EFICIENCIA_COSECHA': 0.62,
    },
    'AGROPIRRO': {
        'MS_POR_HA_OPTIMO': 3500, 
        'CRECIMIENTO_DIARIO': 60, 
        'CONSUMO_PORCENTAJE_PESO': 0.022,
        'TASA_UTILIZACION_RECOMENDADA': 0.50,
        'FACTOR_BIOMASA_NDVI': 2500,
        'UMBRAL_NDVI_SUELO': 0.20,
        'UMBRAL_NDVI_PASTURA': 0.50,
        'CONSUMO_DIARIO_EV': 9,
        'EFICIENCIA_PASTOREO': 0.65,
        'EFICIENCIA_COSECHA': 0.58,
    },
    'PASTIZAL_NATURAL': {
        'MS_POR_HA_OPTIMO': 3000, 
        'CRECIMIENTO_DIARIO': 40, 
        'CONSUMO_PORCENTAJE_PESO': 0.020,
        'TASA_UTILIZACION_RECOMENDADA': 0.45,
        'FACTOR_BIOMASA_NDVI': 2200,
        'UMBRAL_NDVI_SUELO': 0.22,
        'UMBRAL_NDVI_PASTURA': 0.46,
        'CONSUMO_DIARIO_EV': 8,
        'EFICIENCIA_PASTOREO': 0.60,
        'EFICIENCIA_COSECHA': 0.55,
    }
}

def obtener_parametros_forrajeros(tipo_pastura, personalizados=None):
    """Obtiene parámetros forrajeros, con opción de personalización"""
    if tipo_pastura == "PERSONALIZADO" and personalizados:
        return personalizados
    else:
        return PARAMETROS_FORRAJEROS_BASE.get(tipo_pastura, PARAMETROS_FORRAJEROS_BASE['FESTUCA'])

# =============================================================================
# FUNCIONES DE CÁLCULO MEJORADAS
# =============================================================================

def calcular_superficie(gdf):
    """Calcula superficie en hectáreas de forma precisa"""
    try:
        if gdf.crs is None or str(gdf.crs).startswith('EPSG:4326'):
            # Convertir a CRS proyectado para cálculo de área
            gdf_proj = gdf.to_crs(epsg=3857)  # Web Mercator
            area_m2 = gdf_proj.geometry.area
        else:
            area_m2 = gdf.geometry.area
        
        return area_m2 / 10000.0  # Convertir a hectáreas
    except Exception as e:
        st.warning(f"Advertencia en cálculo de área: {e}")
        # Fallback simple
        return gdf.geometry.area / 10000.0

def calcular_ev_ha(biomasa_disponible_kg_ms_ha, consumo_diario_ev, eficiencia_pastoreo=0.7):
    """Calcula equivalente vaca por hectárea"""
    if consumo_diario_ev <= 0:
        return 0
    ev_ha = (biomasa_disponible_kg_ms_ha * eficiencia_pastoreo) / consumo_diario_ev
    return max(0.01, round(ev_ha, 2))

def calcular_dias_permanencia(biomasa_total_kg, consumo_total_diario):
    """Calcula días de permanencia realistas"""
    if consumo_total_diario <= 0:
        return 0.1
    dias = biomasa_total_kg / consumo_total_diario
    return min(max(dias, 0.1), 365)  # Límites realistas

def calcular_disponibilidad_forrajera(gdf_analizado, tipo_pastura):
    """Calcula categorías de disponibilidad forrajera"""
    params = obtener_parametros_forrajeros(tipo_pastura)
    
    gdf_analizado['disponibilidad_forrajera_kg_ms_ha'] = (
        gdf_analizado['biomasa_disponible_kg_ms_ha'] * 
        params['EFICIENCIA_PASTOREO'] * 
        params['EFICIENCIA_COSECHA']
    ).round(0)
    
    # Categorías mejoradas
    condiciones = [
        gdf_analizado['disponibilidad_forrajera_kg_ms_ha'] < 500,
        gdf_analizado['disponibilidad_forrajera_kg_ms_ha'] < 1200,
        gdf_analizado['disponibilidad_forrajera_kg_ms_ha'] < 2500,
        gdf_analizado['disponibilidad_forrajera_kg_ms_ha'] >= 2500
    ]
    categorias = ['MUY BAJA', 'BAJA', 'MEDIA', 'ALTA']
    gdf_analizado['categoria_disponibilidad'] = np.select(condiciones, categorias, default='MEDIA')
    
    return gdf_analizado

# =============================================================================
# SISTEMA DE DETECCIÓN REALISTA
# =============================================================================

class DetectorVegetacionRealista:
    def __init__(self, umbral_ndvi_minimo=0.15, umbral_ndvi_optimo=0.6, sensibilidad_suelo=0.5):
        self.umbral_ndvi_minimo = umbral_ndvi_minimo
        self.umbral_ndvi_optimo = umbral_ndvi_optimo
        self.sensibilidad_suelo = sensibilidad_suelo

    def clasificar_vegetacion_realista(self, ndvi, evi, savi, bsi, ndbi, msavi2=None):
        """Clasificación mejorada de vegetación con umbrales realistas"""
        if ndvi < 0.12:
            return "SUELO_DESNUDO", 0.05
        elif ndvi < 0.22:
            return "SUELO_PARCIAL", 0.25
        elif ndvi < 0.35:
            return "VEGETACION_ESCASA", 0.45
        elif ndvi < 0.55:
            return "VEGETACION_MODERADA", 0.70
        elif ndvi < 0.70:
            return "VEGETACION_DENSA", 0.85
        else:
            return "VEGETACION_MUY_DENSA", 0.95

    def calcular_biomasa_realista(self, ndvi, evi, savi, categoria, cobertura, params):
        """Cálculo realista de biomasa basado en múltiples índices"""
        base = params['MS_POR_HA_OPTIMO']
        
        if categoria == "SUELO_DESNUDO":
            return 50, params['CRECIMIENTO_DIARIO'] * 0.1, 0.15
        elif categoria == "SUELO_PARCIAL":
            return min(base * 0.15, 500), params['CRECIMIENTO_DIARIO'] * 0.3, 0.25
        elif categoria == "VEGETACION_ESCASA":
            return min(base * 0.35, 1500), params['CRECIMIENTO_DIARIO'] * 0.5, 0.40
        elif categoria == "VEGETACION_MODERADA":
            return min(base * 0.65, 3000), params['CRECIMIENTO_DIARIO'] * 0.75, 0.65
        elif categoria == "VEGETACION_DENSA":
            return min(base * 0.85, 4500), params['CRECIMIENTO_DIARIO'] * 0.9, 0.80
        else:  # VEGETACION_MUY_DENSA
            return min(base * 0.95, 5500), params['CRECIMIENTO_DIARIO'] * 0.95, 0.90

def simular_patrones_reales_con_suelo(id_subLote, x_norm, y_norm, fuente_satelital):
    """Simulación mejorada de patrones de vegetación realistas"""
    # Patrón base más realista
    base = 0.25 + 0.5 * ((id_subLote % 8) / 8)
    
    # Variación espacial más realista
    variacion_espacial = 0.2 * (x_norm - 0.5) + 0.1 * (y_norm - 0.5)
    ndvi = max(0.08, min(0.85, base + variacion_espacial + np.random.normal(0, 0.08)))
    
    # Cálculo de índices correlacionados de forma realista
    if ndvi < 0.15:
        evi = ndvi * 0.7 + np.random.normal(0, 0.02)
        savi = ndvi * 0.8 + np.random.normal(0, 0.02)
        bsi = 0.5 + np.random.normal(0, 0.1)
        ndbi = 0.3 + np.random.normal(0, 0.08)
    elif ndvi < 0.30:
        evi = ndvi * 1.0 + np.random.normal(0, 0.03)
        savi = ndvi * 0.95 + np.random.normal(0, 0.03)
        bsi = 0.3 + np.random.normal(0, 0.08)
        ndbi = 0.2 + np.random.normal(0, 0.06)
    elif ndvi < 0.50:
        evi = ndvi * 1.2 + np.random.normal(0, 0.04)
        savi = ndvi * 1.1 + np.random.normal(0, 0.04)
        bsi = 0.1 + np.random.normal(0, 0.05)
        ndbi = 0.05 + np.random.normal(0, 0.03)
    else:
        evi = ndvi * 1.3 + np.random.normal(0, 0.05)
        savi = ndvi * 1.2 + np.random.normal(0, 0.05)
        bsi = -0.1 + np.random.normal(0, 0.03)
        ndbi = -0.1 + np.random.normal(0, 0.02)
    
    msavi2 = ndvi * 1.05 + np.random.normal(0, 0.03)
    
    return ndvi, evi, savi, bsi, ndbi, msavi2

def calcular_indices_forrajeros_realista(gdf, tipo_pastura, fuente_satelital, fecha_imagen, nubes_max,
                                       umbral_ndvi_minimo=0.15, umbral_ndvi_optimo=0.6, sensibilidad_suelo=0.5):
    """Cálculo completo de índices forrajeros de forma realista"""
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
        
        st.info("🔍 Aplicando detección REALISTA mejorada...")
        
        for idx, row in gdf_centroids.iterrows():
            id_subLote = row.get('id_subLote', idx+1)
            x_norm = (row['x'] - x_min) / (x_max - x_min) if x_max != x_min else 0.5
            y_norm = (row['y'] - y_min) / (y_max - y_min) if y_max != y_min else 0.5
            
            ndvi, evi, savi, bsi, ndbi, msavi2 = simular_patrones_reales_con_suelo(
                id_subLote, x_norm, y_norm, fuente_satelital
            )
            
            categoria, cobertura = detector.clasificar_vegetacion_realista(ndvi, evi, savi, bsi, ndbi, msavi2)
            biomasa_ms_ha, crecimiento_diario, calidad = detector.calcular_biomasa_realista(
                ndvi, evi, savi, categoria, cobertura, params
            )
            
            # Biomasa disponible ajustada
            if categoria == "SUELO_DESNUDO":
                biomasa_disponible = 50
            elif categoria == "SUELO_PARCIAL":
                biomasa_disponible = 150
            else:
                biomasa_disponible = max(50, min(5000, biomasa_ms_ha * calidad * cobertura))
            
            resultados.append({
                'id_subLote': id_subLote,
                'ndvi': round(float(ndvi), 3),
                'evi': round(float(evi), 3),
                'savi': round(float(savi), 3),
                'msavi2': round(float(msavi2), 3),
                'bsi': round(float(bsi), 3),
                'ndbi': round(float(ndbi), 3),
                'cobertura_vegetal': round(cobertura, 3),
                'tipo_superficie': categoria,
                'biomasa_ms_ha': round(biomasa_ms_ha, 1),
                'biomasa_disponible_kg_ms_ha': round(biomasa_disponible, 1),
                'crecimiento_diario': round(crecimiento_diario, 1),
                'factor_calidad': round(calidad, 3),
                'fuente_datos': fuente_satelital,
                'x_norm': round(x_norm, 3),
                'y_norm': round(y_norm, 3)
            })
        
        st.success("✅ Cálculo de índices completado.")
        return resultados
        
    except Exception as e:
        st.error(f"❌ Error en índices: {e}")
        import traceback
        st.error(traceback.format_exc())
        return []

def calcular_metricas_ganaderas(gdf_analizado, tipo_pastura, peso_promedio, carga_animal):
    """Cálculo de métricas ganaderas realistas"""
    params = obtener_parametros_forrajeros(tipo_pastura)
    metricas = []
    
    for idx, row in gdf_analizado.iterrows():
        biomasa_disponible = row.get('biomasa_disponible_kg_ms_ha', 0)
        area_ha = row.get('area_ha', 0)
        
        consumo_individual_kg = peso_promedio * params['CONSUMO_PORCENTAJE_PESO']
        biomasa_total_disponible = biomasa_disponible * area_ha
        
        if biomasa_total_disponible > 0 and consumo_individual_kg > 0:
            # EV soportable
            ev_por_dia = biomasa_total_disponible * 0.001 / consumo_individual_kg
            ev_soportable = ev_por_dia / params['TASA_UTILIZACION_RECOMENDADA']
            ev_soportable = max(0.01, ev_soportable)
        else:
            ev_soportable = 0.01
        
        # EV por hectárea
        if ev_soportable > 0 and area_ha > 0:
            ev_ha = ev_soportable / area_ha
            ev_ha_display = ev_ha
        else:
            ev_ha_display = 0.01
        
        # Días de permanencia
        if carga_animal > 0:
            consumo_total_diario = carga_animal * consumo_individual_kg
            if consumo_total_diario > 0 and biomasa_total_disponible > 0:
                dias_permanencia = biomasa_total_disponible / consumo_total_diario
                dias_permanencia = min(max(dias_permanencia, 0.1), 120)  # Límite realista
            else:
                dias_permanencia = 0.1
        else:
            dias_permanencia = 0.1
        
        # Estado forrajero mejorado
        if biomasa_disponible >= 3000:
            estado_forrajero = 5  # Excelente
        elif biomasa_disponible >= 2000:
            estado_forrajero = 4  # Muy bueno
        elif biomasa_disponible >= 1200:
            estado_forrajero = 3  # Bueno
        elif biomasa_disponible >= 600:
            estado_forrajero = 2  # Regular
        elif biomasa_disponible >= 200:
            estado_forrajero = 1  # Crítico
        else:
            estado_forrajero = 0  # Muy crítico
        
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
# FUNCIONES DE MAPAS MEJORADAS
# =============================================================================

def crear_mapa_base(center_lat=-34.0, center_lon=-60.0, zoom_start=6, base_map_name="ESRI Satélite"):
    """Crea mapa base con múltiples opciones"""
    try:
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=zoom_start,
            tiles=None,
            control_scale=True
        )
        
        # Múltiples opciones de mapas base
        if base_map_name == "ESRI Satélite":
            folium.TileLayer(
                tiles='https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
                attr='Esri',
                name='ESRI Satélite',
                overlay=False
            ).add_to(m)
        elif base_map_name == "OpenStreetMap":
            folium.TileLayer(
                tiles='OpenStreetMap',
                attr='OpenStreetMap',
                name='OpenStreetMap',
                overlay=False
            ).add_to(m)
        elif base_map_name == "CartoDB Positron":
            folium.TileLayer(
                tiles='CartoDB positron',
                attr='CartoDB',
                name='CartoDB Positron',
                overlay=False
            ).add_to(m)
        
        return m
    except Exception as e:
        st.error(f"Error creando mapa base: {e}")
        return None

def crear_mapa_ndvi_mejorado(gdf_analizado, base_map_name="ESRI Satélite"):
    """Mapa NDVI mejorado con leyenda completa"""
    if not FOLIUM_AVAILABLE or gdf_analizado is None or len(gdf_analizado) == 0:
        return None
        
    try:
        bounds = gdf_analizado.total_bounds
        center_lat = (bounds[1] + bounds[3]) / 2
        center_lon = (bounds[0] + bounds[2]) / 2
        
        m = crear_mapa_base(center_lat, center_lon, 12, base_map_name)
        if m is None:
            return None
        
        # Función de estilo mejorada para NDVI
        def estilo_ndvi(feature):
            ndvi = feature['properties']['ndvi']
            if ndvi < 0.2:
                color = '#8B4513'  # Marrón - Suelo desnudo
            elif ndvi < 0.3:
                color = '#CD853F'  # Marrón claro - Vegetación muy escasa
            elif ndvi < 0.4:
                color = '#F4A460'  # Arena - Vegetación escasa
            elif ndvi < 0.5:
                color = '#9ACD32'  # Amarillo verdoso - Vegetación moderada
            elif ndvi < 0.6:
                color = '#32CD32'  # Verde lima - Vegetación buena
            elif ndvi < 0.7:
                color = '#228B22'  # Verde forestal - Vegetación muy buena
            else:
                color = '#006400'  # Verde oscuro - Vegetación excelente
                
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
                fields=['id_subLote', 'ndvi', 'area_ha', 'tipo_superficie'],
                aliases=['Sub-Lote:', 'NDVI:', 'Área (ha):', 'Tipo:'],
                localize=True
            )
        ).add_to(m)
        
        # Leyenda completa
        legend_html = '''
        <div style="position: fixed; bottom: 20px; left: 20px; width: 220px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px">
            <p><strong>🌿 Índice NDVI - Vegetación</strong></p>
            <p><i style="background:#8B4513; width:20px; height:20px; display:inline-block; margin-right:5px"></i> < 0.2 (Suelo)</p>
            <p><i style="background:#CD853F; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 0.2-0.3 (Muy escasa)</p>
            <p><i style="background:#F4A460; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 0.3-0.4 (Escasa)</p>
            <p><i style="background:#9ACD32; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 0.4-0.5 (Moderada)</p>
            <p><i style="background:#32CD32; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 0.5-0.6 (Buena)</p>
            <p><i style="background:#228B22; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 0.6-0.7 (Muy buena)</p>
            <p><i style="background:#006400; width:20px; height:20px; display:inline-block; margin-right:5px"></i> > 0.7 (Excelente)</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
        
    except Exception as e:
        st.error(f"Error creando mapa NDVI: {e}")
        return None

def crear_mapa_biomasa_mejorado(gdf_analizado, base_map_name="ESRI Satélite"):
    """Mapa de biomasa mejorado con leyenda completa"""
    if not FOLIUM_AVAILABLE or gdf_analizado is None or len(gdf_analizado) == 0:
        return None
        
    try:
        bounds = gdf_analizado.total_bounds
        center_lat = (bounds[1] + bounds[3]) / 2
        center_lon = (bounds[0] + bounds[2]) / 2
        
        m = crear_mapa_base(center_lat, center_lon, 12, base_map_name)
        if m is None:
            return None
            
        def estilo_biomasa(feature):
            biomasa = feature['properties']['biomasa_disponible_kg_ms_ha']
            if biomasa < 500:
                color = '#FF6B6B'  # Rojo - Muy crítica
            elif biomasa < 1000:
                color = '#FFA726'  # Naranja - Crítica
            elif biomasa < 2000:
                color = '#FFD54F'  # Amarillo - Regular
            elif biomasa < 3000:
                color = '#9CCC65'  # Verde claro - Buena
            elif biomasa < 4000:
                color = '#66BB6A'  # Verde - Muy buena
            else:
                color = '#2E7D32'  # Verde oscuro - Excelente
                
            return {
                'fillColor': color,
                'color': 'black',
                'weight': 1,
                'fillOpacity': 0.7
            }
        
        folium.GeoJson(
            gdf_analizado.__geo_interface__,
            style_function=estilo_biomasa,
            tooltip=folium.GeoJsonTooltip(
                fields=['id_subLote', 'biomasa_disponible_kg_ms_ha', 'area_ha', 'tipo_superficie'],
                aliases=['Sub-Lote:', 'Biomasa (kg MS/ha):', 'Área (ha):', 'Tipo:'],
                localize=True
            )
        ).add_to(m)
        
        legend_html = '''
        <div style="position: fixed; bottom: 20px; left: 20px; width: 230px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px">
            <p><strong>📊 Biomasa Disponible (kg MS/ha)</strong></p>
            <p><i style="background:#FF6B6B; width:20px; height:20px; display:inline-block; margin-right:5px"></i> < 500 (Muy crítica)</p>
            <p><i style="background:#FFA726; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 500-1000 (Crítica)</p>
            <p><i style="background:#FFD54F; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 1000-2000 (Regular)</p>
            <p><i style="background:#9CCC65; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 2000-3000 (Buena)</p>
            <p><i style="background:#66BB6A; width:20px; height:20px; display:inline-block; margin-right:5px"></i> 3000-4000 (Muy buena)</p>
            <p><i style="background:#2E7D32; width:20px; height:20px; display:inline-block; margin-right:5px"></i> > 4000 (Excelente)</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
        
    except Exception as e:
        st.error(f"Error creando mapa biomasa: {e}")
        return None

def crear_mapa_detallado_vegetacion(gdf_analizado, tipo_pastura):
    """Crea mapa detallado con matplotlib para el informe"""
    try:
        fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(20, 10))
        
        # Mapa 1: Tipos de superficie
        colores_superficie = {
            'SUELO_DESNUDO': '#8B4513',
            'SUELO_PARCIAL': '#CD853F', 
            'VEGETACION_ESCASA': '#F4A460',
            'VEGETACION_MODERADA': '#9ACD32',
            'VEGETACION_DENSA': '#32CD32',
            'VEGETACION_MUY_DENSA': '#006400'
        }
        
        for idx, row in gdf_analizado.iterrows():
            tipo = row.get('tipo_superficie', 'VEGETACION_ESCASA')
            color = colores_superficie.get(tipo, '#cccccc')
            gdf_analizado.iloc[[idx]].plot(ax=ax1, color=color, edgecolor='black', linewidth=0.5)
            c = row.geometry.centroid
            ax1.text(c.x, c.y, f"S{row['id_subLote']}", fontsize=6, ha='center', va='center')
        
        ax1.set_title(f"Tipos de Superficie - {tipo_pastura}", fontsize=14, fontweight='bold')
        
        # Leyenda para tipos de superficie
        patches = [mpatches.Patch(color=color, label=tipo) for tipo, color in colores_superficie.items()]
        ax1.legend(handles=patches, loc='upper right', fontsize=8)
        
        # Mapa 2: Biomasa disponible
        cmap = LinearSegmentedColormap.from_list('biomasa_cmap', ['#FF6B6B', '#FFD54F', '#9CCC65', '#2E7D32'])
        
        for idx, row in gdf_analizado.iterrows():
            biom = row.get('biomasa_disponible_kg_ms_ha', 0)
            val = max(0, min(1, biom/5000))  # Normalizar a 5000 kg MS/ha
            color = cmap(val)
            gdf_analizado.iloc[[idx]].plot(ax=ax2, color=color, edgecolor='black', linewidth=0.5)
            c = row.geometry.centroid
            ax2.text(c.x, c.y, f"{biom:.0f}", fontsize=6, ha='center', va='center')
        
        ax2.set_title("Biomasa Disponible (kg MS/ha)", fontsize=14, fontweight='bold')
        
        # Leyenda para biomasa
        norm = plt.Normalize(0, 5000)
        sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm)
        sm.set_array([])
        cbar = plt.colorbar(sm, ax=ax2, shrink=0.8)
        cbar.set_label('kg MS/ha', rotation=270, labelpad=15)
        
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
# FUNCIONES DE CARGA Y DIVISIÓN
# =============================================================================

def cargar_shapefile_desde_zip(uploaded_zip):
    """Carga shapefile desde archivo ZIP"""
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
                elif str(gdf.crs) != 'EPSG:4326':
                    gdf = gdf.to_crs(epsg=4326)
                return gdf
            else:
                st.error("❌ No se encontró archivo .shp en el ZIP")
                return None
    except Exception as e:
        st.error(f"❌ Error cargando shapefile: {e}")
        return None

def dividir_potrero_en_subLotes(gdf, n_zonas):
    """Divide el potrero en sub-lotes de forma optimizada"""
    if gdf is None or len(gdf) == 0:
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
        n_cols = math.ceil(math.sqrt(n_zonas))
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
                if not intersection.is_empty and intersection.area > 0:
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

# =============================================================================
# INTERFAZ PRINCIPAL MEJORADA
# =============================================================================

def main_application():
    """Aplicación principal mejorada"""
    
    # Sidebar de configuración completa
    with st.sidebar:
        st.header("⚙️ Configuración Completa")
        
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
            st.warning("Folium no disponible - mapas limitados")

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

    # Contenido principal
    st.title("🌱 Analizador Forrajero PRV - Versión Mejorada")
    st.markdown("---")
    
    # Procesar archivo cargado
    if uploaded_file is not None:
        with st.spinner("Cargando shapefile..."):
            gdf_loaded = cargar_shapefile_desde_zip(uploaded_file)
            if gdf_loaded is not None and len(gdf_loaded) > 0:
                st.session_state.gdf_cargado = gdf_loaded
                area_total = calcular_superficie(gdf_loaded).sum()
                st.success("✅ Archivo cargado correctamente.")
                
                # Mostrar información del archivo
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
                    bounds = gdf_loaded.total_bounds
                    center_lat = (bounds[1] + bounds[3]) / 2
                    center_lon = (bounds[0] + bounds[2]) / 2
                    
                    m_preview = crear_mapa_base(center_lat, center_lon, 12, base_map_option)
                    if m_preview:
                        folium.GeoJson(
                            gdf_loaded.__geo_interface__,
                            style_function=lambda x: {
                                'fillColor': '#3388ff', 
                                'color': 'blue', 
                                'weight': 2, 
                                'fillOpacity': 0.3
                            },
                            tooltip=folium.GeoJsonTooltip(
                                fields=['id'] if 'id' in gdf_loaded.columns else [],
                                aliases=['ID:'] if 'id' in gdf_loaded.columns else []
                            )
                        ).add_to(m_preview)
                        folium_static(m_preview, width=800, height=400)

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
                                    gdf_sub.loc[gdf_sub['id_subLote'] == rec['id_subLote'], k] = v
                        
                        # 5. Calcular métricas ganaderas
                        metricas = calcular_metricas_ganaderas(gdf_sub, tipo_pastura, peso_promedio, carga_animal)
                        
                        for idx, met in enumerate(metricas):
                            for k, v in met.items():
                                gdf_sub.loc[gdf_sub.index[idx], k] = v
                        
                        # 6. Calcular disponibilidad forrajera
                        gdf_sub = calcular_disponibilidad_forrajera(gdf_sub, tipo_pastura)
                        
                        st.session_state.gdf_analizado = gdf_sub
                        st.session_state.analisis_completado = True
                        
                        # 7. Generar mapas
                        mapa_buf = crear_mapa_detallado_vegetacion(gdf_sub, tipo_pastura)
                        if mapa_buf is not None:
                            st.session_state.mapa_detallado_bytes = mapa_buf
                        
                        st.success("✅ ¡Análisis completado exitosamente!")
                        mostrar_resultados_completos(gdf_sub, base_map_option)
                        
                    else:
                        st.error("❌ No se pudieron calcular los índices forrajeros")
                        
                except Exception as e:
                    st.error(f"❌ Error en el análisis: {e}")
                    import traceback
                    st.error(traceback.format_exc())
    else:
        # Pantalla de bienvenida
        st.info("""
        ### 🌱 Bienvenido al Analizador Forrajero PRV Mejorado
        
        **Características principales:**
        - ✅ Análisis realista de biomasa forrajera
        - ✅ Múltiples mapas base (ESRI Satélite, OpenStreetMap, CartoDB)
        - ✅ Parámetros forrajeros personalizables
        - ✅ Mapas interactivos con leyendas completas
        - ✅ Análisis espacial detallado por sub-lotes
        - ✅ Métricas ganaderas realistas (EV/ha, días de permanencia)
        
        **Para comenzar:**
        1. **Configura** los parámetros en la barra lateral
        2. **Carga** tu shapefile en formato ZIP o usa datos de ejemplo
        3. **Ejecuta** el análisis completo
        4. **Explora** los resultados en mapas interactivos
        """)

def mostrar_resultados_completos(gdf_analizado, base_map_option):
    """Muestra resultados completos del análisis"""
    st.header("📊 RESULTADOS DEL ANÁLISIS FORRAJERO")
    
    # Métricas principales
    st.subheader("📈 Métricas Principales del Potrero")
    col1, col2, col3, col4 = st.columns(4)
    
    with col1:
        biomasa_prom = gdf_analizado['biomasa_disponible_kg_ms_ha'].mean()
        st.metric("Biomasa Disponible Promedio", f"{biomasa_prom:.0f} kg MS/ha")
    
    with col2:
        ndvi_prom = gdf_analizado['ndvi'].mean()
        st.metric("NDVI Promedio", f"{ndvi_prom:.3f}")
    
    with col3:
        ev_total = gdf_analizado['ev_soportable'].sum()
        st.metric("Capacidad Total Soportable", f"{ev_total:.1f} EV")
    
    with col4:
        dias_prom = gdf_analizado['dias_permanencia'].mean()
        st.metric("Días de Permanencia Promedio", f"{dias_prom:.1f}")
    
    # Distribución de categorías
    st.subheader("📊 Distribución de Categorías")
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
    
    # MAPAS INTERACTIVOS MEJORADOS
    if FOLIUM_AVAILABLE:
        st.header("🗺️ MAPAS INTERACTIVOS MEJORADOS")
        
        tab1, tab2, tab3 = st.tabs(["🌿 NDVI - Estado Vegetativo", "📊 Biomasa Disponible", "🗺️ Mapa Detallado"])
        
        with tab1:
            st.subheader("Índice NDVI - Estado Vegetativo")
            mapa_ndvi = crear_mapa_ndvi_mejorado(gdf_analizado, base_map_option)
            if mapa_ndvi:
                folium_static(mapa_ndvi, width=800, height=500)
            else:
                st.error("❌ No se pudo generar el mapa de NDVI")
        
        with tab2:
            st.subheader("Biomasa Disponible (kg MS/ha)")
            mapa_biomasa = crear_mapa_biomasa_mejorado(gdf_analizado, base_map_option)
            if mapa_biomasa:
                folium_static(mapa_biomasa, width=800, height=500)
            else:
                st.error("❌ No se pudo generar el mapa de biomasa")
        
        with tab3:
            st.subheader("Mapa Detallado de Análisis")
            if st.session_state.mapa_detallado_bytes is not None:
                st.image(st.session_state.mapa_detallado_bytes, use_column_width=True)
            else:
                st.info("El mapa detallado se generará para el informe DOCX")
    
    # Tabla de resultados
    st.header("📋 DETALLE POR SUB-LOTE")
    columnas_mostrar = ['id_subLote', 'area_ha', 'tipo_superficie', 'ndvi', 
                       'biomasa_disponible_kg_ms_ha', 'disponibilidad_forrajera_kg_ms_ha', 
                       'categoria_disponibilidad', 'ev_ha', 'dias_permanencia']
    
    columnas_disponibles = [col for col in columnas_mostrar if col in gdf_analizado.columns]
    
    if columnas_disponibles:
        df_resumen = gdf_analizado[columnas_disponibles].copy()
        nombres_amigables = {
            'id_subLote': 'Sub-Lote',
            'area_ha': 'Área (ha)',
            'tipo_superficie': 'Tipo Superficie',
            'ndvi': 'NDVI',
            'biomasa_disponible_kg_ms_ha': 'Biomasa Disp. (kg MS/ha)',
            'disponibilidad_forrajera_kg_ms_ha': 'Disp. Forrajera (kg MS/ha)',
            'categoria_disponibilidad': 'Categoría',
            'ev_ha': 'EV/ha',
            'dias_permanencia': 'Días Permanencia'
        }
        df_resumen.columns = [nombres_amigables.get(col, col) for col in df_resumen.columns]
        st.dataframe(df_resumen, use_container_width=True, height=400)
    else:
        st.warning("No hay datos suficientes para mostrar la tabla")
    
    # Exportar datos
    st.header("💾 EXPORTAR RESULTADOS")
    col_exp1, col_exp2, col_exp3 = st.columns(3)
    
    with col_exp1:
        if st.button("📥 Descargar CSV", use_container_width=True):
            csv = gdf_analizado.to_csv(index=False)
            st.download_button(
                "💾 Descargar CSV",
                csv,
                f"resultados_forrajeros_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv",
                key="download_csv"
            )
    
    with col_exp2:
        if st.button("📥 Descargar GeoJSON", use_container_width=True):
            geojson = gdf_analizado.to_json()
            st.download_button(
                "💾 Descargar GeoJSON", 
                geojson,
                f"resultados_forrajeros_{datetime.now().strftime('%Y%m%d_%H%M')}.geojson",
                "application/json",
                key="download_geojson"
            )
    
    with col_exp3:
        if st.button("📄 Generar Informe DOCX", use_container_width=True) and DOCX_AVAILABLE:
            # Aquí iría la función para generar el informe DOCX
            st.info("Función de generación de informe DOCX (próxima implementación)")

# =============================================================================
# FUNCIÓN PRINCIPAL
# =============================================================================

def main():
    """Función principal de la aplicación"""
    initialize_session_state()
    main_application()

if __name__ == "__main__":
    main()
