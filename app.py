import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import os
import zipfile
from datetime import datetime
import matplotlib.pyplot as plt
import folium
from streamlit_folium import st_folium
from shapely.geometry import Polygon
import math

# Configuración DEBE IR PRIMERO
st.set_page_config(
    page_title="🌱 Analizador Forrajero",
    page_icon="🌱",
    layout="wide"
)

st.title("🌱 ANALIZADOR FORRAJERO CON SENTINEL-2")
st.markdown("---")

# Funciones (todo en un archivo para evitar problemas de import)
def calculate_area(gdf):
    """Calculate area in hectares"""
    try:
        if gdf.crs and gdf.crs.is_geographic:
            area_m2 = gdf.geometry.area * 10000000000
        else:
            area_m2 = gdf.geometry.area
        return area_m2 / 10000
    except:
        return gdf.geometry.area / 10000

def divide_pasture(gdf, n_zones):
    """Divide pasture into sub-lots"""
    if len(gdf) == 0:
        return gdf
    
    main_pasture = gdf.iloc[0].geometry
    bounds = main_pasture.bounds
    minx, miny, maxx, maxy = bounds
    
    sub_polygons = []
    n_cols = math.ceil(math.sqrt(n_zones))
    n_rows = math.ceil(n_zones / n_cols)
    width = (maxx - minx) / n_cols
    height = (maxy - miny) / n_rows
    
    for i in range(n_rows):
        for j in range(n_cols):
            if len(sub_polygons) >= n_zones:
                break
                
            cell_minx = minx + (j * width)
            cell_maxx = minx + ((j + 1) * width)
            cell_miny = miny + (i * height)
            cell_maxy = miny + ((i + 1) * height)
            
            cell_poly = Polygon([
                (cell_minx, cell_miny),
                (cell_maxx, cell_miny),
                (cell_maxx, cell_maxy),
                (cell_minx, cell_maxy)
            ])
            
            intersection = main_pasture.intersection(cell_poly)
            if not intersection.is_empty and intersection.area > 0:
                sub_polygons.append(intersection)
    
    if sub_polygons:
        new_gdf = gpd.GeoDataFrame({
            'id_subLote': range(1, len(sub_polygons) + 1),
            'geometry': sub_polygons
        }, crs=gdf.crs)
        return new_gdf
    else:
        return gdf

def simulate_forage_analysis(gdf_divided, pasture_type):
    """Simulate forage analysis with realistic data"""
    results = []
    
    pasture_params = {
        "ALFALFA": {"biomass_min": 800, "biomass_max": 1500, "ndvi_min": 0.5},
        "RAYGRASS": {"biomass_min": 600, "biomass_max": 1200, "ndvi_min": 0.4},
        "FESTUCA": {"biomass_min": 500, "biomass_max": 1000, "ndvi_min": 0.4},
        "AGROPIRRO": {"biomass_min": 400, "biomass_max": 900, "ndvi_min": 0.3},
        "PASTIZAL_NATURAL": {"biomass_min": 300, "biomass_max": 700, "ndvi_min": 0.3},
        "PERSONALIZADO": {"biomass_min": 400, "biomass_max": 1000, "ndvi_min": 0.4}
    }
    
    params = pasture_params.get(pasture_type, pasture_params["PERSONALIZADO"])
    
    for i, row in gdf_divided.iterrows():
        centroid = row.geometry.centroid
        spatial_variation = (centroid.x + centroid.y) % 1
        
        biomass_base = params["biomass_min"] + (params["biomass_max"] - params["biomass_min"]) * spatial_variation
        ndvi_base = params["ndvi_min"] + (0.8 - params["ndvi_min"]) * spatial_variation
        
        biomass = max(100, biomass_base + np.random.normal(0, 100))
        ndvi = max(0.1, min(0.9, ndvi_base + np.random.normal(0, 0.1)))
        
        if ndvi < 0.2:
            surface_type = "SUELO_DESNUDO"
            coverage = np.random.uniform(0.1, 0.3)
        elif ndvi < 0.4:
            surface_type = "VEGETACION_ESCASA"
            coverage = np.random.uniform(0.3, 0.6)
        elif ndvi < 0.6:
            surface_type = "VEGETACION_MODERADA"
            coverage = np.random.uniform(0.6, 0.8)
        else:
            surface_type = "VEGETACION_DENSA"
            coverage = np.random.uniform(0.8, 0.95)
        
        results.append({
            'biomasa_disponible_kg_ms_ha': biomass,
            'ndvi': ndvi,
            'evi': ndvi * 0.9 + np.random.normal(0, 0.05),
            'savi': ndvi * 0.95 + np.random.normal(0, 0.03),
            'cobertura_vegetal': coverage,
            'tipo_superficie': surface_type,
            'crecimiento_diario': biomass * 0.02 + np.random.normal(0, 5),
            'factor_calidad': min(0.95, coverage * 0.8 + np.random.normal(0, 0.1))
        })
    
    return results

def create_interactive_map(gdf, pasture_type, analysis_results):
    """Create interactive map with Google Satellite"""
    try:
        centroid = gdf.geometry.centroid.iloc[0]
        center_lat, center_lon = centroid.y, centroid.x
        
        m = folium.Map(
            location=[center_lat, center_lon],
            zoom_start=12,
            tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',
            attr='Google Satellite'
        )
        
        for idx, row in gdf.iterrows():
            sub_lot_id = row['id_subLote']
            biomass = analysis_results[idx]['biomasa_disponible_kg_ms_ha']
            ndvi = analysis_results[idx]['ndvi']
            surface_type = analysis_results[idx]['tipo_superficie']
            coverage = analysis_results[idx]['cobertura_vegetal']
            
            if ndvi < 0.2:
                color = '#d73027'
                fill_opacity = 0.4
            elif ndvi < 0.4:
                color = '#fc8d59'
                fill_opacity = 0.5
            elif ndvi < 0.6:
                color = '#fee08b'
                fill_opacity = 0.6
            elif ndvi < 0.8:
                color = '#91cf60'
                fill_opacity = 0.7
            else:
                color = '#1a9850'
                fill_opacity = 0.8
            
            geom = row.geometry
            if geom.geom_type == 'Polygon':
                coords = [[point[1], point[0]] for point in geom.exterior.coords]
                
                folium.Polygon(
                    locations=coords,
                    popup=f"""
                    <div style="font-family: Arial; font-size: 12px; min-width: 220px;">
                        <h4>🌿 Sub-Lote S{sub_lot_id}</h4>
                        <b>NDVI:</b> {ndvi:.3f}<br>
                        <b>Biomasa:</b> {biomass:.0f} kg MS/ha<br>
                        <b>Tipo:</b> {surface_type}<br>
                        <b>Cobertura:</b> {coverage:.1%}
                    </div>
                    """,
                    tooltip=f'S{sub_lot_id} - NDVI: {ndvi:.3f}',
                    color=color,
                    fill_color=color,
                    fill_opacity=fill_opacity,
                    weight=2,
                    opacity=0.8
                ).add_to(m)
        
        # Leyenda
        legend_html = '''
        <div style="position: fixed; bottom: 50px; left: 50px; width: 220px; height: 160px; 
                    background-color: white; border:2px solid grey; z-index:9999; 
                    font-size:12px; padding: 10px; border-radius: 5px;">
        <p style="margin:0; font-weight:bold;">🌿 Leyenda NDVI</p>
        <p style="margin:2px 0;"><i style="background:#d73027; width: 15px; height: 15px; display: inline-block; margin-right: 5px; border:1px solid grey;"></i> < 0.2 (Suelo)</p>
        <p style="margin:2px 0;"><i style="background:#fc8d59; width: 15px; height: 15px; display: inline-block; margin-right: 5px; border:1px solid grey;"></i> 0.2-0.4 (Escasa)</p>
        <p style="margin:2px 0;"><i style="background:#fee08b; width: 15px; height: 15px; display: inline-block; margin-right: 5px; border:1px solid grey;"></i> 0.4-0.6 (Moderada)</p>
        <p style="margin:2px 0;"><i style="background:#91cf60; width: 15px; height: 15px; display: inline-block; margin-right: 5px; border:1px solid grey;"></i> 0.6-0.8 (Buena)</p>
        <p style="margin:2px 0;"><i style="background:#1a9850; width: 15px; height: 15px; display: inline-block; margin-right: 5px; border:1px solid grey;"></i> > 0.8 (Densa)</p>
        </div>
        '''
        m.get_root().html.add_child(folium.Element(legend_html))
        
        return m
    except Exception as e:
        return folium.Map(location=[-34.0, -64.0], zoom_start=4)

# INTERFAZ
with st.sidebar:
    st.header("⚙️ Configuración")
    
    tipo_pastura = st.selectbox("Tipo de Pastura:", 
                               ["ALFALFA", "RAYGRASS", "FESTUCA", "AGROPIRRO", "PASTIZAL_NATURAL", "PERSONALIZADO"])
    
    st.subheader("📊 Parámetros Ganaderos")
    peso_promedio = st.slider("Peso promedio animal (kg):", 300, 600, 450)
    carga_animal = st.slider("Carga animal (cabezas):", 50, 1000, 100)
    
    st.subheader("🎯 División de Potrero")
    n_divisiones = st.slider("Número de sub-lotes:", min_value=8, max_value=36, value=16)
    
    st.subheader("📤 Subir Lote")
    uploaded_zip = st.file_uploader("Subir ZIP con shapefile", type=['zip'])

# MAIN APP
if uploaded_zip:
    try:
        with tempfile.TemporaryDirectory() as tmp_dir:
            with zipfile.ZipFile(uploaded_zip, 'r') as zip_ref:
                zip_ref.extractall(tmp_dir)
            
            shp_files = [f for f in os.listdir(tmp_dir) if f.endswith('.shp')]
            if shp_files:
                shp_path = os.path.join(tmp_dir, shp_files[0])
                gdf = gpd.read_file(shp_path)
                
                st.success(f"✅ **Potrero cargado:** {len(gdf)} polígono(s)")
                
                area_total = calculate_area(gdf).sum()
                
                col1, col2 = st.columns(2)
                with col1:
                    st.write("**📊 INFORMACIÓN DEL POTRERO:**")
                    st.write(f"- Polígonos: {len(gdf)}")
                    st.write(f"- Área total: {area_total:.1f} ha")
                    st.write(f"- CRS: {gdf.crs}")
                
                with col2:
                    st.write("**🎯 CONFIGURACIÓN:**")
                    st.write(f"- Pastura: {tipo_pastura}")
                    st.write(f"- Sub-lotes: {n_divisiones}")
                
                if st.button("🚀 EJECUTAR ANÁLISIS FORRAJERO", type="primary"):
                    with st.spinner("Procesando..."):
                        # Dividir potrero
                        gdf_dividido = divide_pasture(gdf, n_divisiones)
                        st.success(f"✅ Potrero dividido en {len(gdf_dividido)} sub-lotes")
                        
                        # Simular análisis
                        resultados = simulate_forage_analysis(gdf_dividido, tipo_pastura)
                        
                        # Mostrar mapa
                        st.subheader("🗺️ MAPA INTERACTIVO - GOOGLE SATELLITE")
                        mapa = create_interactive_map(gdf_dividido, tipo_pastura, resultados)
                        returned_data = st_folium(mapa, width=1200, height=600)
                        
                        # Resultados
                        st.subheader("📊 RESULTADOS")
                        biomasas = [r['biomasa_disponible_kg_ms_ha'] for r in resultados]
                        ndvis = [r['ndvi'] for r in resultados]
                        
                        col1, col2, col3, col4 = st.columns(4)
                        with col1:
                            st.metric("🌿 NDVI Promedio", f"{np.mean(ndvis):.3f}")
                        with col2:
                            st.metric("📈 Biomasa Promedio", f"{np.mean(biomasas):.0f} kg/ha")
                        with col3:
                            st.metric("🟢 Sub-lotes", len(gdf_dividido))
                        with col4:
                            tipos = [r['tipo_superficie'] for r in resultados]
                            st.metric("🎯 Tipo Principal", max(set(tipos), key=tipos.count))
    
    except Exception as e:
        st.error(f"❌ Error: {str(e)}")

else:
    st.info("📁 Sube un shapefile en formato ZIP para comenzar")
    st.markdown("""
    ### 🌟 Analizador Forrajero con Sentinel-2
    
    **Funcionalidades:**
    - 🗺️ Google Satellite como base de mapa
    - 📊 Análisis de biomasa forrajera  
    - 🌿 Cálculo de índices de vegetación
    - 🎯 División automática en sub-lotes
    - 🛰️ Preparado para datos Sentinel-2 reales
    
    **Instrucciones:**
    1. Prepara tu shapefile (.shp, .shx, .dbf, .prj)
    2. Comprime en ZIP y súbelo
    3. Configura los parámetros
    4. Ejecuta el análisis
    5. Explora el mapa satelital interactivo
    """)
