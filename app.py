import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

# Cargar config
with open('config.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days'],
    config.get('preauthorized')
)

# --- FORMULARIO DE REGISTRO (solo para preautorizados) ---
with st.expander("¿No tienes cuenta? Regístrate aquí", expanded=False):
    try:
        email_reg = st.text_input("Email")
        if email_reg in config['preauthorized']['emails']:
            username_reg = email_reg.split('@')[0]
            name_reg = st.text_input("Nombre")
            password_reg = st.text_input("Contraseña", type="password")
            password_reg2 = st.text_input("Repite contraseña", type="password")
            if st.button("Registrarse"):
                if password_reg == password_reg2 and password_reg:
                    authenticator.register_user(username_reg, name_reg, email_reg, password_reg)
                    st.success("¡Cuenta creada! Ahora inicia sesión.")
                else:
                    st.error("Las contraseñas no coinciden.")
        else:
            st.warning("Este email no está preautorizado.")
    except Exception as e:
        st.error("Error en registro. Contacta al administrador.")

# --- LOGIN ---
name, authentication_status, username = authenticator.login('Iniciar Sesión', 'main')

if authentication_status:
    st.sidebar.success(f'¡Bienvenido, {name}!')
    authenticator.logout('Salir', 'sidebar')
    st.title('Analizador Forrajero Regenerativo')
    st.info('Ve al menú lateral → Análisis Regenerativo')

elif authentication_status == False:
    st.error('Email o contraseña incorrectos.')
elif authentication_status is None:
    st.warning('Por favor, inicia sesión.')
