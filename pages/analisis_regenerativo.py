import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import zipfile
import os
import folium
from streamlit_folium import st_folium
from sentinelhub import SHConfig, DataCollection, MimeType, CRS, BBox, SentinelHubRequest, bbox_to_dimensions
from docx import Document
import io
import base64
import streamlit.components.v1 as components
from datetime import datetime, timedelta

st.set_page_config(page_title="Análisis Regenerativo", layout="wide")
st.title("Análisis Forrajero Regenerativo")

# --- CREDENCIALES ---
try:
    config = SHConfig()
    config.sh_client_id = st.secrets["SENTINEL_HUB_CLIENT_ID"].strip()
    config.sh_client_secret = st.secrets["SENTINEL_HUB_CLIENT_SECRET"].strip()
    config.instance_id = st.secrets.get("SENTINEL_HUB_INSTANCE_ID", "").strip()
    
    if not config.sh_client_id or not config.sh_client_secret:
        raise ValueError("Faltan credenciales")
    SH_OK = True
except Exception as e:
    SH_OK = False
    st.error(f"Credenciales inválidas: {e}")

# --- SIDEBAR ---
with st.sidebar:
    st.header("Parámetros")
    tipo_pastura = st.selectbox("Pastura", ["Alfalfa", "Raygrass", "Festuca", "Natural"])
    default_date = datetime.now().date()
    fecha = st.date_input("Fecha imagen", value=default_date, max_value=default_date)
    nubes = st.slider("Nubes máx (%)", 0, 100, 20)
    peso_vaca = st.slider("Peso promedio (kg)", 400, 600, 500)
    eficiencia = st.slider("Eficiencia pastoreo (%)", 40, 80, 55) / 100

# --- CARGA SHAPEFILE ---
uploaded = st.file_uploader("Subir ZIP con shapefile (.shp, .shx, .dbf, .prj)", type="zip")

if uploaded and SH_OK:
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(uploaded) as z:
            z.extractall(tmp)
        shp_files = [f for f in os.listdir(tmp) if f.endswith('.shp')]
        if not shp_files:
            st.error("No se encontró .shp en el ZIP")
            st.stop()
        shp = shp_files[0]
        gdf = gpd.read_file(f"{tmp}/{shp}")
        if gdf.crs is None:
            gdf = gdf.set_crs('EPSG:4326')
        gdf = gdf.to_crs('EPSG:4326')
        gdf = gdf[gdf.geometry.notna()]  # Eliminar nulos
        st.success(f"{len(gdf)} lotes válidos cargados")
else:
    gdf = None

# --- ANÁLISIS ---
if gdf is not None and st.button("EJECUTAR ANÁLISIS", type="primary"):
    progress_bar = st.progress(0)
    status_text = st.empty()
    results = []

    for idx, (i, row) in enumerate(gdf.iterrows()):
        status_text.text(f"Procesando lote {i+1}/{len(gdf)}...")
        progress_bar.progress((idx + 1) / len(gdf))

        geom = row.geometry
        if geom is None or geom.is_empty:
            ndvi_mean = 0.1
        else:
            bbox = BBox(geom.bounds, crs=CRS.WGS84)
            size = bbox_to_dimensions(bbox, resolution=10)

            evalscript = """
            //VERSION=3
            function setup() {
                return {
                    input: ["B04", "B08", "dataMask"],
                    output: { bands: 4 }
                };
            }
            function evaluatePixel(samples) {
                let ndvi = (samples.B08 - samples.B04)/(samples.B08 + samples.B04 + 0.0001);
                return [ndvi, ndvi, ndvi, samples.dataMask];
            }
            """

            request = SentinelHubRequest(
                evalscript=evalscript,
                input_data=[SentinelHubRequest.input_data(
                    data_collection=DataCollection.SENTINEL2_L2A,
                    time_interval=(str(fecha), str(fecha + timedelta(days=1))),
                    other_args={"maxcc": nubes / 100}
                )],
                responses=[SentinelHubRequest.output_response('default', MimeType.TIFF)],
                bbox=bbox,
                size=size,
                config=config
            )

            try:
                response = request.get_data()[0]
                mask = response[..., 3] == 1
                ndvi_values = response[..., 0][mask]
                ndvi_mean = np.mean(ndvi_values) if len(ndvi_values) > 0 else 0.1
            except Exception as e:
                st.warning(f"Lote {i+1}: sin datos → {e}")
                ndvi_mean = 0.1

        area_ha = geom.area / 10000 if geom else 0
        biomasa = max(ndvi_mean * 4000, 1000) if ndvi_mean > 0.3 else 1000
        consumo_dia = peso_vaca * 0.025 * eficiencia
        ev_ha = biomasa / (consumo_dia * 30) if consumo_dia > 0 else 0
        dias = biomasa / (consumo_dia * ev_ha) if ev_ha > 0 else 0

        results.append({
            'id': i,
            'area_ha': round(area_ha, 2),
            'ndvi': round(ndvi_mean, 3),
            'biomasa_kg_ha': int(biomasa),
            'ev_ha': round(ev_ha, 2),
            'dias': round(dias, 1)
        })

    progress_bar.empty()
    status_text.empty()

    df = pd.DataFrame(results)
    gdf_result = gdf.copy()
    gdf_result = gdf_result.merge(df, left_index=True, right_on='id').set_index('id')

    st.success("¡Análisis completado!")

    # --- MAPA SEGURO ---
    if not gdf_result.empty:
        center_y = gdf_result.geometry.centroid.y.mean()
        center_x = gdf_result.geometry.centroid.x.mean()
        m = folium.Map(location=[center_y, center_x], zoom_start=14)

        for _, r in gdf_result.iterrows():
            if r.geometry is None or r.geometry.is_empty:
                continue
            coords = []
            if r.geometry.geom_type == 'Polygon':
                coords = list(r.geometry.exterior.coords)
            elif r.geometry.geom_type == 'MultiPolygon':
                for poly in r.geometry.geoms:
                    coords.extend(list(poly.exterior.coords))
            else:
                continue

            color = "green" if r.ev_ha > 1.5 else "orange" if r.ev_ha > 0.8 else "red"
            folium.Polygon(
                locations=[(lat, lon) for lon, lat in coords],
                popup=f"EV/ha: {r.ev_ha}<br>Días: {r.dias}<br>Biomasa: {r.biomasa_kg_ha} kg/ha",
                color=color, fill=True, weight=2
            ).add_to(m)

        st_folium(m, width=700, height=500)
    else:
        st.warning("No hay geometrías válidas para mostrar en el mapa.")

    # --- TABLA ---
    st.subheader("Resultados")
    st.dataframe(df.style.format({"area_ha": "{:.2f}", "ndvi": "{:.3f}", "ev_ha": "{:.2f}"}))

    # --- EXPORTES ---
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("CSV", df.to_csv(index=False), "resultados.csv", "text/csv")
    with col2:
        st.download_button("GeoJSON", gdf_result.to_json(), "lotes.geojson", "application/json")

    # --- RECOMENDACIONES ---
    st.subheader("Recomendaciones Regenerativas")
    prom_ev = df['ev_ha'].mean()
    prom_dias = df['dias'].mean()

    rec = []
    if prom_dias < 30:
        rec.append("**Descanso insuficiente** → Mínimo 30-45 días.")
    if prom_ev > 2.0:
        rec.append("**Carga alta** → Reducir EV/ha.")
    if prom_ev < 0.8:
        rec.append("**Baja productividad** → Leguminosas o compost.")
    rec.append("**Rotación intensiva**: 1-3 días pastoreo + 30-60 descanso.")
    rec.append("**Monitoreo mensual** con esta app.")

    for r in rec:
        st.markdown(f"- {r}")

    # --- INFORME DOCX ---
    if st.button("Generar Informe DOCX"):
        doc = Document()
        doc.add_heading('Informe Forrajero Regenerativo', 0)
        doc.add_paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y')}")
        doc.add_paragraph(f"Lotes: {len(gdf_result)} | Área: {df.area_ha.sum():.1f} ha")
        doc.add_paragraph(f"EV/ha promedio: {prom_ev:.2f} | Días: {prom_dias:.1f}")
        doc.add_paragraph("Recomendaciones:")
        for r in rec:
            doc.add_paragraph(r, style='List Bullet')

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode()
        href = f'<a href="data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{b64}" download="informe_regenerativo.docx">Descargar Informe</a>'
        st.markdown(href, unsafe_allow_html=True)
        st.success("Informe listo.")
