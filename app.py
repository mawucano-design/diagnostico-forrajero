import streamlit as st
import streamlit_authenticator as stauth
import yaml
from yaml.loader import SafeLoader

st.set_page_config(page_title="Forrajero Regenerativo", layout="wide")

# Cargar config
with open('config.yaml') as file:
    config = yaml.load(file, Loader=SafeLoader)

# Autenticador
authenticator = stauth.Authenticate(
    config['credentials'],
    config['cookie']['name'],
    config['cookie']['key'],
    config['cookie']['expiry_days'],
    config.get('preauthorized', [])
)

# --- REGISTRO AUTOMÁTICO ---
with st.expander("¿No tienes cuenta? Regístrate aquí", expanded=False):
    try:
        email = st.text_input("Email", key="reg_email")
        if email and email in config['preauthorized']['emails']:
            username = email.split('@')[0]
            name = st.text_input("Nombre completo", key="reg_name")
            password1 = st.text_input("Contraseña", type="password", key="reg_pass1")
            password2 = st.text_input("Repetir contraseña", type="password", key="reg_pass2")
            
            if st.button("Crear cuenta"):
                if password1 == password2 and len(password1) >= 6:
                    if authenticator.register_user(username, name, email, password1):
                        st.success("Cuenta creada. Ahora inicia sesión.")
                        st.rerun()
                    else:
                        st.error("Error al crear usuario.")
                else:
                    st.error("Las contraseñas no coinciden o son muy cortas.")
        else:
            if email:
                st.warning("Este email no está preautorizado.")
    except Exception as e:
        st.error(f"Error: {e}")

# --- LOGIN SIMPLE (SIN FIELDS - NUEVO FORMATO) ---
authenticator.login('Iniciar Sesión')

# Leer estado del login
name = st.session_state.get('name')
authentication_status = st.session_state.get('authentication_status')
username = st.session_state.get('username')

# --- INTERFAZ ---
if authentication_status:
    st.sidebar.success(f'¡Bienvenido, {name}!')
    authenticator.logout('Salir', 'sidebar')
    st.title('Analizador Forrajero Regenerativo')
    st.markdown('**Análisis satelital + ganadería regenerativa.**')
    st.info('Ve al menú → **Análisis Regenerativo**')

elif authentication_status == False:
    st.error('Email o contraseña incorrectos.')
elif authentication_status is None:
    st.warning('Por favor, inicia sesión o regístrate.')
