import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader
import os

# --- CARGA CONFIG ---
with open('config.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

# --- AUTENTICADOR ---
authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days'],
    config.get('pre_authorized', [])
)

# --- LOGIN EN SIDEBAR ---
authenticator.login('Iniciar Sesión', 'sidebar')

if st.session_state["authentication_status"]:
    st.sidebar.success(f"¡Bienvenido, {st.session_state['name']}!")

    # --- PÁGINAS ---
    st.title("Analizador Forrajero Regenerativo")
    st.markdown("Navega por las opciones del menú lateral.")

    # --- LOGOUT ---
    authenticator.logout('Cerrar Sesión', 'sidebar')

elif st.session_state["authentication_status"] is False:
    st.error('Usuario o contraseña incorrectos')
elif st.session_state["authentication_status"] is None:
    st.warning('Por favor ingresa tus credenciales')
