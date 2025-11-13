import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

st.set_page_config(page_title="Forrajero Regenerativo", layout="wide")

with open('config.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days']
)

name, authentication_status, username = authenticator.login('Iniciar Sesión', 'main')

if authentication_status:
    st.sidebar.success(f'¡Bienvenido, {name}!')
    authenticator.logout('Salir', 'sidebar')
    st.title('Analizador Forrajero Regenerativo')
    st.markdown('**Análisis satelital + recomendaciones de ganadería regenerativa.**')

elif authentication_status == False:
    st.error('Email o contraseña incorrectos.')
else:
    st.warning('Por favor, inicia sesión.')
