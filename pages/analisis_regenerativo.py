import streamlit as st
import geopandas as gpd
import pandas as pd
import tempfile
import zipfile
import os
import folium
from streamlit_folium import st_folium
from docx import Document
import io
import base64
from datetime import datetime, timedelta
import ee
import json

st.set_page_config(page_title="Análisis GEE", layout="wide")
st.title("Análisis Forrajero - GEE")

# --- CONEXIÓN GEE ---
try:
    credentials = ee.ServiceAccountCredentials(
        email=None,
        key_data=st.secrets["GEE_SERVICE_ACCOUNT_JSON"]
    )
    ee.Initialize(credentials)
    st.success("Conectado a Google Earth Engine")
except Exception as e:
    st.error(f"Error: {e}")
    st.stop()

# --- CARGA SHAPEFILE ---
uploaded = st.file_uploader("Subir ZIP con shapefile", type="zip")
if uploaded:
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(uploaded) as z:
            z.extractall(tmp)
        shp = [f for f in os.listdir(tmp) if f.endswith('.shp')][0]
        gdf = gpd.read_file(f"{tmp}/{shp}")
        gdf = gdf.to_crs('EPSG:4326')
        st.success(f"{len(gdf)} lotes")
else:
    gdf = None

# --- ANÁLISIS ---
if gdf is not None and st.button("EJECUTAR"):
    progress = st.progress(0)
    results = []

    for i, row in enumerate(gdf.iterrows()):
        idx, geom = row
        progress.progress((i + 1) / len(gdf))

        region = ee.Geometry.Polygon(list(geom.geometry.exterior.coords))
        s2 = ee.ImageCollection('COPERNICUS/S2_SR') \
            .filterBounds(region) \
            .filterDate('2024-01-01', '2024-12-31') \
            .filter(ee.Filter.lt('CLOUDY_PIXEL_PERCENTAGE', 20)) \
            .first()

        ndvi = 0.1
        if s2:
            ndvi_img = s2.normalizedDifference(['B8', 'B4'])
            mean = ndvi_img.reduceRegion(ee.Reducer.mean(), region, 10).get('nd')
            ndvi = float(mean.getInfo() or 0.1)

        area = geom.geometry.area / 10000
        biomasa = max(ndvi * 4000, 1000)
        ev_ha = biomasa / (500 * 0.025 * 0.55 * 30)
        dias = biomasa / (500 * 0.025 * 0.55 * ev_ha) if ev_ha > 0 else 0

        results.append({
            'lote': i+1,
            'area_ha': round(area, 2),
            'ndvi': round(ndvi, 3),
            'ev_ha': round(ev_ha, 2),
            'dias': round(dias, 1)
        })

    df = pd.DataFrame(results)
    st.success("¡Listo!")
    st.dataframe(df)

    m = folium.Map(location=[gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()], zoom_start=15)
    for i, r in df.iterrows():
        color = "green" if r.ev_ha > 1.5 else "red"
        folium.Polygon(
            locations=[(y, x) for x, y in gdf.iloc[i].geometry.exterior.coords],
            color=color, fill=True
        ).add_to(m)
    st_folium(m, width=700, height=500)
