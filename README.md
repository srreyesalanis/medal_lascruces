# Medal Play — Las Cruces

App Streamlit para registrar torneos de **Medal Play** en Las Cruces Golf Club.

## Flujo

1. Admin crea torneo (campo, tees, nombre, fecha)
2. Admin crea grupos y agrega jugadores
3. Jugadores capturan scores por hoyo con su código de grupo
4. Los torneos aparecen en la app HDC → "Importar Ronda desde Torneo"

## Setup

1. Clonar repo
2. Configurar `.streamlit/secrets.toml` con `SUPABASE_URL`, `SUPABASE_KEY`, `ADMIN_EMAIL`, `ADMIN_PASSWORD`
3. `pip install -r requirements.txt`
4. `streamlit run streamlit_app.py`

## Stack

- Streamlit Cloud
- Supabase (misma DB que HDC Las Cruces)
