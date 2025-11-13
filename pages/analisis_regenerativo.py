import streamlit as st
import geopandas as gpd
import pandas as pd
import numpy as np
import tempfile
import zipfile
import os
import folium
from streamlit_folium import st_folium
from sentinelhub import SHConfig, DataCollection, MimeType, CRS, BBox, Geometry, SentinelHubRequest, bbox_to_dimensions
from docx import Document
from docx.shared import Inches
import io
import base64
import streamlit.components.v1 as components
from datetime import datetime, timedelta  # ← IMPORT FALTANTE

st.title("Análisis Forrajero Regenerativo")

# --- CREDENCIALES ---
try:
    config = SHConfig()
    config.sh_client_id = st.secrets["SENTINEL_HUB_CLIENT_ID"]
    config.sh_client_secret = st.secrets["SENTINEL_HUB_CLIENT_SECRET"]
    config.instance_id = st.secrets.get("SENTINEL_HUB_INSTANCE_ID", "")
    SH_OK = True
except:
    SH_OK = False
    st.error("Configura credenciales en Secrets.")

# --- SIDEBAR ---
with st.sidebar:
    st.header("Parámetros")
    tipo_pastura = st.selectbox("Pastura", ["Alfalfa", "Raygrass", "Festuca", "Natural"])
    fecha = st.date_input("Fecha imagen", max_value=datetime.now())
    nubes = st.slider("Nubes máx (%)", 0, 100, 20)
    peso_vaca = st.slider("Peso promedio (kg)", 400, 600, 500)
    eficiencia = st.slider("Eficiencia pastoreo (%)", 40, 80, 55) / 100

# --- CARGA SHAPEFILE ---
uploaded = st.file_uploader("Subir ZIP con shapefile", type="zip")
if uploaded and SH_OK:
    with tempfile.TemporaryDirectory() as tmp:
        with zipfile.ZipFile(uploaded) as z:
            z.extractall(tmp)
        shp = [f for f in os.listdir(tmp) if f.endswith('.shp')][0]
        gdf = gpd.read_file(f"{tmp}/{shp}")
        if gdf.crs is None:
            gdf = gdf.set_crs('EPSG:4326')
        gdf = gdf.to_crs('EPSG:4326')
        st.success(f"{len(gdf)} lotes cargados")
else:
    gdf = None

# --- ANÁLISIS ---
if gdf is not None and st.button("EJECUTAR ANÁLISIS", type="primary"):
    with st.spinner("Procesando Sentinel-2..."):
        results = []
        for idx, row in gdf.iterrows():
            geom = row.geometry
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
                let ndvi = (samples.B08 - samples.B04)/(samples.B08 + samples.B04);
                return [ndvi, ndvi, ndvi, samples.dataMask];
            }
            """

            request = SentinelHubRequest(
                evalscript=evalscript,
                input_data=[SentinelHubRequest.input_data(
                    data_collection=DataCollection.SENTINEL2_L2A,
                    time_interval=(str(fecha), str(fecha + timedelta(days=1))),
                    other_args={"cloudCoverage": nubes}
                )],
                responses=[SentinelHubRequest.output_response('default', MimeType.TIFF)],
                bbox=bbox,
                size=size,
                config=config
            )

            try:
                response = request.get_data()[0]
                ndvi_mean = np.mean(response[response != 0]) if np.any(response != 0) else 0.1
            except:
                ndvi_mean = 0.1

            area_ha = geom.area / 10000
            biomasa = ndvi_mean * 4000 if ndvi_mean > 0.3 else 1000
            consumo_dia = peso_vaca * 0.025 * eficiencia
            ev_ha = biomasa / (consumo_dia * 30)
            dias = biomasa / (ev_ha * consumo_dia) if ev_ha > 0 else 0

            results.append({
                'id': idx,
                'area_ha': round(area_ha, 2),
                'ndvi': round(ndvi_mean, 3),
                'biomasa_kg_ha': int(biomasa),
                'ev_ha': round(ev_ha, 2),
                'dias': round(dias, 1)
            })

        df = pd.DataFrame(results)
        gdf = gdf.merge(df, left_index=True, right_on='id')

    st.success("¡Análisis completado!")

    # --- MAPA ---
    m = folium.Map(location=[gdf.geometry.centroid.y.mean(), gdf.geometry.centroid.x.mean()], zoom_start=14)
    for _, r in gdf.iterrows():
        color = "green" if r.ev_ha > 1.5 else "orange" if r.ev_ha > 0.8 else "red"
        folium.Polygon(
            locations=[(lat, lon) for lon, lat in r.geometry.exterior.coords],
            popup=f"EV/ha: {r.ev_ha}<br>Días: {r.dias}<br>Biomasa: {r.biomasa_kg_ha} kg/ha",
            color=color, fill=True, weight=2
        ).add_to(m)
    st_folium(m, width=700, height=500)

    # --- TABLA ---
    st.subheader("Resultados")
    st.dataframe(df.style.format({"area_ha": "{:.2f}", "ndvi": "{:.3f}", "ev_ha": "{:.2f}"}))

    # --- EXPORTES ---
    col1, col2 = st.columns(2)
    with col1:
        st.download_button("CSV", df.to_csv(index=False), "resultados.csv", "text/csv")
    with col2:
        st.download_button("GeoJSON", gdf.to_json(), "lotes.geojson", "application/json")

    # --- RECOMENDACIONES REGENERATIVAS ---
    st.subheader("Recomendaciones de Ganadería Regenerativa")
    prom_ev = df['ev_ha'].mean()
    prom_dias = df['dias'].mean()

    rec = []
    if prom_dias < 30:
        rec.append("**Descanso insuficiente** → Extender a **mínimo 30-45 días** por lote.")
    if prom_ev > 2.0:
        rec.append("**Carga alta** → Reducir EV/ha para evitar sobrepastoreo.")
    if prom_ev < 0.8:
        rec.append("**Baja productividad** → Considerar siembra de leguminosas o fertilización orgánica.")
    rec.append("**Rotación intensiva**: 1-3 días de pastoreo + 30-60 días de descanso.")
    rec.append("**Biodiversidad**: Incluir especies forrajeras mixtas.")
    rec.append("**Monitoreo continuo**: Usar esta app mensualmente.")

    for r in rec:
        st.markdown(f"- {r}")

    # --- INFORME DOCX ---
    if st.button("Generar Informe DOCX"):
        doc = Document()
        doc.add_heading('Informe Forrajero Regenerativo', 0)
        doc.add_paragraph(f"Fecha: {datetime.now().strftime('%d/%m/%Y')}")
        doc.add_paragraph(f"Lotes: {len(gdf)} | Área total: {df.area_ha.sum():.1f} ha")
        doc.add_paragraph(f"EV/ha promedio: {prom_ev:.2f} | Días promedio: {prom_dias:.1f}")
        doc.add_paragraph("Recomendaciones:")
        for r in rec:
            doc.add_paragraph(r, style='List Bullet')

        buf = io.BytesIO()
        doc.save(buf)
        buf.seek(0)
        b64 = base64.b64encode(buf.read()).decode()
        html = f'<a href="data:application/vnd.openxmlformats-officedocument.wordprocessingml.document;base64,{b64}" download="informe_regenerativo.docx" id="dl">Descargar</a><script>document.getElementById("dl").click();</script>'
        components.html(html, height=0)
        st.success("Informe descargado.")
