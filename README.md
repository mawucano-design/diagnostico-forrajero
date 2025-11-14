# 🌱 Analizador Forrajero Unificado

Aplicación web completa para análisis de productividad forrajera que combina datos satelitales de Sentinel Hub con métricas de ganadería regenerativa.

## 🚀 Características Principales

### 🔐 Sistema de Autenticación
- Múltiples roles de usuario
- Seguridad con hash de contraseñas
- Sesiones persistentes

### 🛰️ Análisis Satelital
- Integración con Sentinel Hub
- Datos reales de Sentinel-2
- NDVI, EVI, y otros índices
- Filtrado automático de nubes

### 📊 Métricas Forrajeras
- **EV/ha**: Equivalente Vaca por hectárea
- **Días de permanencia**: Por lote y promedio
- **Biomasa disponible**: kg MS/ha
- **Capacidad de carga**: Total y por sub-lote

### 🗺️ Visualización Avanzada
- Múltiples mapas base (ESRI, OSM, etc.)
- Gradientes de color personalizados
- Mapas interactivos con Folium
- Leyendas automáticas

### 📄 Informes Automáticos
- Generación de DOCX con recomendaciones
- Secciones técnicas y prácticas
- Recomendaciones regenerativas
- Descarga automática

## 🛠️ Instalación

```bash
# Clonar repositorio
git clone https://github.com/tuusuario/analizador-forrajero-unificado.git
cd analizador-forrajero-unificado

# Instalar dependencias
pip install -r requirements.txt

# Configurar credenciales
cp .streamlit/secrets.toml.example .streamlit/secrets.toml
# Editar .streamlit/secrets.toml con tus credenciales

# Ejecutar aplicación
streamlit run app.py
