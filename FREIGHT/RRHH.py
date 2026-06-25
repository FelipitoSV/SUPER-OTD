# ==============================================================================
# SISTEMA: OTD RH (RECURSOS HUMANOS Y NÓMINA)
# VERSION: V9.90 (STABLE - QA MEMORY & ANTI-CRASH FIX)
# ==============================================================================
import streamlit as st
import pandas as pd
import sqlite3
import psycopg2
from datetime import datetime, timedelta
import io
import time
import os
import shutil
import warnings
import math
import numpy as np
import zipfile
import difflib
import subprocess
import sys
import unicodedata
import random
import signal
import gc

# --- 1. CONFIGURACIÓN DE PÁGINA (PRIMERA INSTRUCCIÓN) ---
st.set_page_config(page_title="OTD Recursos Humanos", page_icon="👔", layout="wide", initial_sidebar_state="expanded")

# --- 2. SILENCIAR ADVERTENCIAS ---
warnings.simplefilter(action='ignore', category=FutureWarning)
warnings.simplefilter(action='ignore', category=UserWarning)
pd.set_option('future.no_silent_downcasting', True)

# --- 3. CONFIGURACIÓN Y DETECCIÓN DE ENTORNO ---
LOGO_FILE = "OTD Logo.png"
SANDBOX_PORT = 8599
SERVER_IP = "100.75.64.13"
SANDBOX_DB = "sandbox_otd_rh.db"
SANDBOX_FILE = "sandbox_app.py"
PID_FILE = "sandbox_pid.txt"

CURRENT_FILE_NAME = os.path.basename(__file__)
IS_SANDBOX = "sandbox" in CURRENT_FILE_NAME.lower()

PAGE_TITLE = "🔴 SANDBOX RH" if IS_SANDBOX else "OTD Recursos Humanos"
PAGE_ICON = "🧪" if IS_SANDBOX else LOGO_FILE

# --- 4. AUTO-CONFIGURACIÓN DEL SERVER ---
def setup_streamlit_config():
    config_dir = ".streamlit"
    config_file = os.path.join(config_dir, "config.toml")
    if not os.path.exists(config_dir): 
        try: os.makedirs(config_dir)
        except: pass
    config_content = f"""[server]\nmaxUploadSize = 500\nenableCORS = false\nenableXsrfProtection = false\nheadless = true\n[browser]\ngatherUsageStats = false"""
    try:
        with open(config_file, "w") as f: f.write(config_content.strip())
    except: pass

setup_streamlit_config()

DB_NAME = SANDBOX_DB if IS_SANDBOX else "otd_rh.db"
NOMBRE_EMPRESA = "OTD FREIGHT" 

# --- 5. CSS PROFESIONAL ---
if IS_SANDBOX:
    st.markdown(f"""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
        html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
        .stApp {{ border-top: 10px solid #f59e0b; }}
        section[data-testid="stSidebar"] {{ background-color: #2a1e00; border-right: 1px solid #f59e0b; }}
        section[data-testid="stSidebar"] * {{ color: #fcd34d !important; }}
        .sandbox-banner {{
            width: 100%; background-color: #f59e0b; color: black; text-align: center;
            font-weight: bold; padding: 10px; font-size: 1.2rem; border-radius: 0 0 8px 8px;
            margin-bottom: 20px; text-transform: uppercase; letter-spacing: 2px;
        }}
        </style>
        <div class="sandbox-banner">🧪 MODO SANDBOX - {SERVER_IP}:{SANDBOX_PORT} 🧪</div>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
        <style>
        @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;700&display=swap');
        html, body, [class*="css"] { font-family: 'Inter', sans-serif; }
        section[data-testid="stSidebar"] { background-color: #0f172a; border-right: 1px solid #334155; }
        section[data-testid="stSidebar"] * { color: #e2e8f0 !important; }
        section[data-testid="stSidebar"] .stButton button {
            background-color: #1e293b !important; color: #cbd5e1 !important;
            border: 1px solid #475569 !important; transition: all 0.3s ease;
            box-shadow: 0 4px 6px rgba(0,0,0,0.3);
        }
        section[data-testid="stSidebar"] .stButton button:hover {
            background-color: #002B5B !important; color: white !important;
            border-color: #3b82f6 !important; transform: translateY(-2px);
        }
        </style>
    """, unsafe_allow_html=True)

st.markdown("""
    <style>
    .header-box { padding: 20px; background: white; border-radius: 12px; border-bottom: 2px solid #e2e8f0; margin-bottom: 20px; }
    .stButton > button { border-radius: 8px; height: 45px; font-weight: 600; border: none; box-shadow: 0 2px 4px rgba(0,0,0,0.05); }
    div[data-testid="stMetric"] { background-color: white; padding: 15px; border-radius: 12px; box-shadow: 0 2px 4px rgba(0,0,0,0.05); border: 1px solid #e2e8f0; }
    </style>
""", unsafe_allow_html=True)

# --- 6. FUNCIONES BACKEND (ROBUSTAS) ---
def get_db_connection(db_file=DB_NAME):
    conn = sqlite3.connect(db_file, timeout=15) 
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
    except: pass
    return conn

def get_table_columns(table_name, conn, is_postgres):
    cur = conn.cursor()
    if is_postgres:
        cur.execute("SELECT column_name FROM information_schema.columns WHERE table_name = %s", (table_name.lower(),))
        cols = [r[0] for r in cur.fetchall()]
    else:
        cur.execute(f"PRAGMA table_info({table_name})")
        cols = [r[1] for r in cur.fetchall()]
    return cols

def translate_sqlite_to_postgres(query):
    query = query.replace("?", "%s")
    ql = query.lower().strip()
    
    if ql.startswith("insert or ignore into"):
        if "usuarios" in ql:
            query = "INSERT INTO usuarios (username, password, role) VALUES (%s, %s, %s) ON CONFLICT (username) DO NOTHING"
        elif "configuracion" in ql:
            query = "INSERT INTO configuracion (clave, valor) VALUES (%s, %s) ON CONFLICT (clave) DO NOTHING"
            
    elif ql.startswith("insert or replace into"):
        if "configuracion" in ql:
            query = "INSERT INTO configuracion (clave, valor) VALUES (%s, %s) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"
        elif "asistencia_live" in ql:
            query = """INSERT INTO asistencia_live VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s) 
                       ON CONFLICT (uid) DO UPDATE SET 
                       semana_id = EXCLUDED.semana_id, nombre = EXCLUDED.nombre, 
                       lun = EXCLUDED.lun, mar = EXCLUDED.mar, mie = EXCLUDED.mie, 
                       jue = EXCLUDED.jue, vie = EXCLUDED.vie, sab = EXCLUDED.sab"""
        elif "he_live" in ql:
            query = """INSERT INTO he_live VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s) 
                       ON CONFLICT (uid) DO UPDATE SET 
                       semana_id = EXCLUDED.semana_id, nombre = EXCLUDED.nombre, 
                       lun = EXCLUDED.lun, mar = EXCLUDED.mar, mie = EXCLUDED.mie, 
                       jue = EXCLUDED.jue, vie = EXCLUDED.vie, sab = EXCLUDED.sab, dom = EXCLUDED.dom"""
                       
    return query



def get_local_now():
    from datetime import timezone
    offset_hours = -5
    try:
        # Try loading offset from configuracion table in Supabase
        res = run_query("SELECT valor FROM configuracion WHERE clave='timezone_offset'")
        if res:
            offset_hours = float(res[0][0])
    except:
        pass
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=offset_hours)

def run_query(q, p=()):
    is_postgres = "postgres_url" in st.secrets and st.secrets["postgres_url"] and "[YOUR-PASSWORD]" not in st.secrets["postgres_url"]
    if is_postgres:
        q_translated = translate_sqlite_to_postgres(q)
        conn = psycopg2.connect(st.secrets["postgres_url"])
        c = conn.cursor()
        try:
            c.execute(q_translated, p)
            ql = q_translated.lower().strip()
            if ql.startswith("select") or ql.startswith("show") or "returning" in ql:
                res = c.fetchall()
                conn.close()
                return res
            else:
                conn.commit()
                conn.close()
                return True
        except Exception as e:
            st.error(f"Postgres Error: {e}\nQuery: {q_translated}\nParams: {p}")
            conn.close()
            return False
    else:
        conn = get_db_connection()
        c = conn.cursor()
        try:
            c.execute(q, p)
            if q.lower().strip().startswith("select") or q.lower().strip().startswith("pragma"):
                res = c.fetchall()
                conn.close()
                return res
            else:
                conn.commit()
                conn.close()
                return True
        except Exception as e:
            st.error(f"DB Error: {e}")
            conn.close()
            return False

def init_db():
    is_postgres = "postgres_url" in st.secrets and st.secrets["postgres_url"] and "[YOUR-PASSWORD]" not in st.secrets["postgres_url"]
    
    if is_postgres:
        conn = psycopg2.connect(st.secrets["postgres_url"])
    else:
        conn = get_db_connection()
    c = conn.cursor()
    
    if is_postgres:
        c.execute('''CREATE TABLE IF NOT EXISTS personal (
            id SERIAL PRIMARY KEY, nombre TEXT UNIQUE, puesto TEXT, salario_semanal DOUBLE PRECISION, 
            horas_semanales INTEGER, dias_base INTEGER DEFAULT 6, aplica_imss INTEGER DEFAULT 0, 
            aplica_infonavit INTEGER DEFAULT 0, ultimo_imss DOUBLE PRECISION DEFAULT 0, ultimo_infonavit DOUBLE PRECISION DEFAULT 0,
            entrada_oficial TEXT DEFAULT '08:00', salida_oficial TEXT DEFAULT '17:00',
            entrada_sabado TEXT DEFAULT '09:00', salida_sabado TEXT DEFAULT '14:00',
            es_transfer INTEGER DEFAULT 0, es_confianza INTEGER DEFAULT 0,
            cuota_imss DOUBLE PRECISION DEFAULT 0.0, cuota_infonavit DOUBLE PRECISION DEFAULT 0.0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS deducciones (id SERIAL PRIMARY KEY, nombre_empleado TEXT, fecha TEXT, monto DOUBLE PRECISION, motivo TEXT, estado TEXT DEFAULT 'PENDIENTE', monto_semanal DOUBLE PRECISION DEFAULT 0, saldo_restante DOUBLE PRECISION DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS asistencia_live (uid TEXT PRIMARY KEY, semana_id TEXT, nombre TEXT, lun TEXT, mar TEXT, mie TEXT, jue TEXT, vie TEXT, sab TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS he_live (uid TEXT PRIMARY KEY, semana_id TEXT, nombre TEXT, lun DOUBLE PRECISION, mar DOUBLE PRECISION, mie DOUBLE PRECISION, jue DOUBLE PRECISION, vie DOUBLE PRECISION, sab DOUBLE PRECISION, dom DOUBLE PRECISION)''')
        c.execute('''CREATE TABLE IF NOT EXISTS nomina_historica (
            id SERIAL PRIMARY KEY, semana_id TEXT, fecha_cierre TEXT, nombre TEXT, salario_base DOUBLE PRECISION,
            dias_trabajados INTEGER, dias_vacaciones INTEGER, pago_vacaciones DOUBLE PRECISION, horas_extra_cant DOUBLE PRECISION, horas_extra_monto DOUBLE PRECISION,
            incentivos DOUBLE PRECISION, desc_imss DOUBLE PRECISION, desc_info DOUBLE PRECISION, otros_desc DOUBLE PRECISION, abono_prestamo DOUBLE PRECISION, total_pagar DOUBLE PRECISION
        )''')
        
        c.execute("INSERT INTO usuarios (username, password, role) VALUES ('admin', 'admin', 'ADMIN') ON CONFLICT (username) DO NOTHING")
        c.execute("INSERT INTO usuarios (username, password, role) VALUES ('rrhh', '1234', 'RRHH') ON CONFLICT (username) DO NOTHING")
        c.execute("INSERT INTO usuarios (username, password, role) VALUES ('it', '1234', 'IT') ON CONFLICT (username) DO NOTHING")
        c.execute("INSERT INTO configuracion (clave, valor) VALUES ('precio_hora_extra', '100.0') ON CONFLICT (clave) DO NOTHING")
    else:
        c.execute('''CREATE TABLE IF NOT EXISTS personal (
            id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, puesto TEXT, salario_semanal REAL, 
            horas_semanales INTEGER, dias_base INTEGER DEFAULT 6, aplica_imss INTEGER DEFAULT 0, 
            aplica_infonavit INTEGER DEFAULT 0, ultimo_imss REAL DEFAULT 0, ultimo_infonavit REAL DEFAULT 0,
            entrada_oficial TEXT DEFAULT '08:00', salida_oficial TEXT DEFAULT '17:00',
            entrada_sabado TEXT DEFAULT '09:00', salida_sabado TEXT DEFAULT '14:00',
            es_transfer INTEGER DEFAULT 0, es_confianza INTEGER DEFAULT 0
        )''')
        c.execute('''CREATE TABLE IF NOT EXISTS deducciones (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre_empleado TEXT, fecha TEXT, monto REAL, motivo TEXT, estado TEXT DEFAULT 'PENDIENTE', monto_semanal REAL DEFAULT 0, saldo_restante REAL DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS asistencia_live (uid TEXT PRIMARY KEY, semana_id TEXT, nombre TEXT, lun TEXT, mar TEXT, mie TEXT, jue TEXT, vie TEXT, sab TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS he_live (uid TEXT PRIMARY KEY, semana_id TEXT, nombre TEXT, lun REAL, mar REAL, mie REAL, jue REAL, vie REAL, sab REAL, dom REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS nomina_historica (
            id INTEGER PRIMARY KEY AUTOINCREMENT, semana_id TEXT, fecha_cierre TEXT, nombre TEXT, salario_base REAL,
            dias_trabajados INTEGER, dias_vacaciones INTEGER, pago_vacaciones REAL, horas_extra_cant REAL, horas_extra_monto REAL,
            incentivos REAL, desc_imss REAL, desc_info REAL, otros_desc REAL, abono_prestamo REAL, total_pagar REAL
        )''')
        
        c.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('admin', 'admin', 'ADMIN')")
        c.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('rrhh', '1234', 'RRHH')")
        c.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('it', '1234', 'IT')")
        c.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('precio_hora_extra', '100.0')")
        
    cols = get_table_columns("personal", conn, is_postgres)
    # Add columns if missing
    for col, default_val in [
        ('entrada_oficial', "'08:00'"),
        ('salida_oficial', "'17:00'"),
        ('entrada_sabado', "'09:00'"),
        ('salida_sabado', "'14:00'"),
        ('es_transfer', "0"),
        ('es_confianza', "0"),
        ('cuota_imss', "0.0"),
        ('cuota_infonavit', "0.0")
    ]:
        if col not in cols:
            c.execute(f"ALTER TABLE personal ADD COLUMN {col} {'DOUBLE PRECISION' if 'cuota' in col else 'INTEGER' if 'es_' in col else 'TEXT'} DEFAULT {default_val}")
            
    conn.commit()
    conn.close()

def get_config(clave, v_def):
    r = run_query("SELECT valor FROM configuracion WHERE clave=?", (clave,))
    return r[0][0] if r else v_def

def set_config(clave, val):
    run_query("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (clave, str(val)))

def get_df_secure(t, role):
    is_postgres = "postgres_url" in st.secrets and st.secrets["postgres_url"] and "[YOUR-PASSWORD]" not in st.secrets["postgres_url"]
    if is_postgres:
        conn = psycopg2.connect(st.secrets["postgres_url"])
    else:
        conn = get_db_connection()
    df = pd.read_sql_query(f"SELECT * FROM {t}", conn)
    conn.close()
    if role == 'IT':
        if t == 'personal': df['salario_semanal'] = df['id'].apply(lambda x: (x * 12345 % 5000) + 2000)
        if t == 'deducciones': df['monto'] = df['id'].apply(lambda x: (x * 987 % 1000) + 500); df['saldo_restante'] = df['monto']; df['monto_semanal'] = 200.0
    return df

def update_password(user, new_pass):
    run_query("UPDATE usuarios SET password=? WHERE username=?", (new_pass, user))

def verify_and_change_password(user, old_pass, new_pass):
    res = run_query("SELECT password FROM usuarios WHERE username=?", (user,))
    if res and res[0][0] == old_pass:
        run_query("UPDATE usuarios SET password=? WHERE username=?", (new_pass, user))
        return True
    return False

def safe_parse_time_str(t_str, default="08:00"):
    try:
        s = str(t_str).strip()
        if len(s) > 5: s = s[:5] 
        return datetime.strptime(s, "%H:%M").time()
    except:
        return datetime.strptime(default, "%H:%M").time()

def get_current_week_id():
    return get_local_now().strftime("%Y-W%W")

def load_saved_progress(semana_id, df_empleados):
    is_postgres = "postgres_url" in st.secrets and st.secrets["postgres_url"] and "[YOUR-PASSWORD]" not in st.secrets["postgres_url"]
    if is_postgres:
        conn = psycopg2.connect(st.secrets["postgres_url"])
        q_asis = "SELECT * FROM asistencia_live WHERE semana_id = %s"
        q_he = "SELECT * FROM he_live WHERE semana_id = %s"
    else:
        conn = get_db_connection()
        q_asis = "SELECT * FROM asistencia_live WHERE semana_id = ?"
        q_he = "SELECT * FROM he_live WHERE semana_id = ?"
        
    try: df_saved_asis = pd.read_sql(q_asis, conn, params=(semana_id,))
    except: df_saved_asis = pd.DataFrame()
    try: df_saved_he = pd.read_sql(q_he, conn, params=(semana_id,))
    except: df_saved_he = pd.DataFrame()
    conn.close()
    
    base_asis = pd.DataFrame({'nombre': df_empleados['nombre'], 'dias_base': df_empleados['dias_base']})
    base_he = pd.DataFrame({'nombre': df_empleados['nombre']})
    
    if not df_saved_asis.empty:
        merged_asis = pd.merge(base_asis, df_saved_asis, on='nombre', how='left')
        for d in ['lun', 'mar', 'mie', 'jue', 'vie', 'sab']: merged_asis[d] = merged_asis[d].fillna("-")
        for idx, row in merged_asis.iterrows():
            if row['dias_base'] == 5 and row['sab'] == "-": merged_asis.at[idx, 'sab'] = "-"
        final_asis = merged_asis[['nombre', 'lun', 'mar', 'mie', 'jue', 'vie', 'sab']]
    else:
        d = {'nombre': df_empleados['nombre'], 'lun': "-", 'mar': "-", 'mie': "-", 'jue': "-", 'vie': "-", 'sab': "-"}
        final_asis = pd.DataFrame(d)
        for idx, row in df_empleados.iterrows():
            if row['dias_base'] == 5: final_asis.loc[final_asis['nombre'] == row['nombre'], 'sab'] = "-"

    if not df_saved_he.empty:
        merged_he = pd.merge(base_he, df_saved_he, on='nombre', how='left').fillna(0.0)
        final_he = merged_he[['nombre', 'lun', 'mar', 'mie', 'jue', 'vie', 'sab', 'dom']]
    else:
        d_he = {'nombre': df_empleados['nombre'], 'lun': 0.0, 'mar': 0.0, 'mie': 0.0, 'jue': 0.0, 'vie': 0.0, 'sab': 0.0, 'dom': 0.0}
        final_he = pd.DataFrame(d_he)
    
    cols_he_check = ['lun', 'mar', 'mie', 'jue', 'vie', 'sab', 'dom']
    for c in cols_he_check:
        if c in final_he.columns:
            final_he[c] = pd.to_numeric(final_he[c], errors='coerce').fillna(0.0).astype(float)
        
    final_asis.columns = ['nombre', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']
    final_he.columns = ['nombre', 'HE_Lun', 'HE_Mar', 'HE_Mie', 'HE_Jue', 'HE_Vie', 'HE_Sab', 'HE_Dom']
    return final_asis, final_he

def save_daily_progress(semana_id, df_asis, df_he):
    for i, row in df_asis.iterrows():
        uid = f"{semana_id}_{row['nombre']}"
        run_query("INSERT OR REPLACE INTO asistencia_live VALUES (?,?,?,?,?,?,?,?,?)", (uid, semana_id, row['nombre'], row['Lun'], row['Mar'], row['Mie'], row['Jue'], row['Vie'], row['Sab']))
    for i, row in df_he.iterrows():
        uid = f"{semana_id}_{row['nombre']}"
        run_query("INSERT OR REPLACE INTO he_live VALUES (?,?,?,?,?,?,?,?,?,?)", (uid, semana_id, row['nombre'], row['HE_Lun'], row['HE_Mar'], row['HE_Mie'], row['HE_Jue'], row['HE_Vie'], row['HE_Sab'], row['HE_Dom']))

def archivar_nomina_cerrada(semana_id, df_final):
    fecha_hoy = get_local_now().strftime("%Y-%m-%d %H:%M")
    run_query("DELETE FROM nomina_historica WHERE semana_id=?", (semana_id,))
    for i, row in df_final.iterrows():
        run_query("""INSERT INTO nomina_historica (
            semana_id, fecha_cierre, nombre, salario_base, dias_trabajados, dias_vacaciones,
            pago_vacaciones, horas_extra_cant, horas_extra_monto, incentivos, 
            desc_imss, desc_info, otros_desc, abono_prestamo, total_pagar
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
            semana_id, fecha_hoy, row['nombre'], row['Sueldo'], row['Días Trab'], row['Días Vac'],
            row['Pago_Vacaciones'], row['Horas Extra'], row['$ Extras'], row['Incentivos'],
            row['Desc_IMSS'], row['Desc_Info'], row['Otros Descuentos'], row['Abono a Aplicar'], row['A PAGAR']
        ))
        run_query("UPDATE personal SET ultimo_imss=?, ultimo_infonavit=? WHERE nombre=?", (row['Desc_IMSS'], row['Desc_Info'], row['nombre']))

def create_portable_zip():
    bat_content = f"""@echo off\ncd /d "%~dp0"\necho INICIANDO OTD RH PORTABLE...\nstreamlit run {CURRENT_FILE_NAME}\npause"""
    with open("iniciar.bat", "w") as f: f.write(bat_content)
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.write(__file__, CURRENT_FILE_NAME)
        if os.path.exists(DB_NAME): zip_file.write(DB_NAME)
        if os.path.exists(LOGO_FILE): zip_file.write(LOGO_FILE)
        zip_file.write("iniciar.bat")
    try: os.remove("iniciar.bat")
    except: pass
    return zip_buffer.getvalue()

def restore_from_zip(uploaded_zip_file):
    try:
        with zipfile.ZipFile(uploaded_zip_file) as z:
            namelist = z.namelist()
            if DB_NAME in namelist:
                shutil.copy(DB_NAME, f"backup_pre_sync_{get_local_now().strftime('%H%M%S')}.db")
                with open(DB_NAME, 'wb') as f: f.write(z.read(DB_NAME))
            py_files = [f for f in namelist if f.endswith(".py") and not f.startswith("__")]
            if py_files:
                target_py = py_files[0]
                shutil.copy(__file__, f"backup_code_{get_local_now().strftime('%H%M%S')}.py")
                with open(__file__, 'wb') as f: f.write(z.read(target_py))
        return True, ["✅ Sistema sincronizado."]
    except Exception as e: return False, [str(e)]

def normalizar_texto(texto):
    if not isinstance(texto, str): return ""
    t = ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')
    return " ".join(t.strip().upper().split())

def buscar_mejor_coincidencia(nombre_hik, lista_db_original):
    hik_norm = normalizar_texto(nombre_hik)
    if not hik_norm: return None
    tokens_hik = set(hik_norm.split())
    db_map = {normalizar_texto(n): n for n in lista_db_original}
    if hik_norm in db_map: return db_map[hik_norm]
    candidatos = []
    for db_norm, db_real in db_map.items():
        tokens_db = set(db_norm.split())
        if not tokens_db: continue
        if tokens_db.issubset(tokens_hik):
            candidatos.append((len(tokens_db), db_real))
    if candidatos:
        candidatos.sort(key=lambda x: x[0], reverse=True)
        return candidatos[0][1]
    matches = difflib.get_close_matches(hik_norm, list(db_map.keys()), n=1, cutoff=0.6)
    return db_map[matches[0]] if matches else None

def detectar_inicio_datos_nativo(contenido_str):
    for i, linea in enumerate(contenido_str.split('\n')[:25]):
        if sum(1 for k in ['first name', 'date', 'time', 'nombre', 'fecha'] if k in linea.lower()) >= 3: return i
    return 0

def analizar_hikvision_con_horarios(file_obj, df_personal_db, debug_mode=False):
    try:
        try: content = file_obj.getvalue().decode("utf-8")
        except: content = file_obj.getvalue().decode("latin-1", errors='ignore')
        
        start_row = detectar_inicio_datos_nativo(content)
        lines = content.split('\n')
        clean_content = '\n'.join(lines[start_row:])
        df_raw = pd.read_csv(io.StringIO(clean_content), on_bad_lines='skip', engine='python')
        df_raw.columns = df_raw.columns.str.strip()
        
        col_name = next((c for c in df_raw.columns if 'name' in c.lower() or 'nombre' in c.lower()), None)
        col_date = next((c for c in df_raw.columns if 'date' in c.lower() or 'fecha' in c.lower()), None)
        col_time = next((c for c in df_raw.columns if 'time' in c.lower() or 'hora' in c.lower()), None)
        
        if not col_name: return None, ["Error: No encuentro columna de Nombre."]
        
        df_raw['Nombre Completo'] = (df_raw['First Name'].fillna('') + ' ' + df_raw['Last Name'].fillna('')) if 'First Name' in df_raw.columns else df_raw[col_name]
        df_raw['Nombre Completo'] = df_raw['Nombre Completo'].astype(str).str.strip().str.upper()
        
        df_raw['Datetime'] = pd.to_datetime(df_raw[col_date] + ' ' + df_raw[col_time], dayfirst=True, errors='coerce')

        df_raw = df_raw.dropna(subset=['Datetime'])
        if df_raw.empty: return None, ["Error: Sin fechas válidas."]
        
        df_raw['Fecha'] = df_raw['Datetime'].dt.date
        df_raw['DiaSemana'] = df_raw['Datetime'].dt.dayofweek
        
        if debug_mode:
            st.caption("🔍 Muestra de Datos Leídos (Primeros 5):")
            st.dataframe(df_raw[['Nombre Completo', 'Datetime']].head(), use_container_width=True)

        asistencia = df_raw.groupby(['Nombre Completo', 'Fecha', 'DiaSemana'])['Datetime'].agg(['min', 'max']).reset_index()
        asistencia.columns = ['Nombre_Hik', 'Fecha', 'DiaSemana', 'Entrada_Real', 'Salida_Real']
        
        nombres_db = df_personal_db['nombre'].tolist()
        mapa_dias = {0: 'LUN', 1: 'MAR', 2: 'MIE', 3: 'JUE', 4: 'VIE', 5: 'SAB', 6: 'DOM'}
        resultados = []; registros_procesados = []; no_encontrados_set = set()
        
        for idx, row in asistencia.iterrows():
            nombre_db = buscar_mejor_coincidencia(row['Nombre_Hik'], nombres_db)
            if nombre_db:
                info_emp = df_personal_db[df_personal_db['nombre'] == nombre_db].iloc[0]
                registros_procesados.append((nombre_db, row['Fecha']))
                
                es_sabado = (row['DiaSemana'] == 5)
                dias_base = info_emp.get('dias_base', 6)
                es_transfer = bool(info_emp.get('es_transfer', 0))
                es_confianza = bool(info_emp.get('es_confianza', 0))
                
                h_ent = safe_parse_time_str(info_emp.get('entrada_sabado' if es_sabado else 'entrada_oficial'), '09:00' if es_sabado else '08:00')
                h_sal = safe_parse_time_str(info_emp.get('salida_sabado' if es_sabado else 'salida_oficial'), '14:00' if es_sabado else '17:00')
                
                ent_real = row['Entrada_Real']
                sal_real = row['Salida_Real']
                
                dt_ent = datetime.combine(datetime.today(), h_ent)
                dt_sal = datetime.combine(datetime.today(), h_sal)
                if dt_ent > dt_sal: dt_sal += timedelta(days=1)
                horas_req = (dt_sal - dt_ent).total_seconds() / 3600.0
                if horas_req <= 0: horas_req = 8.0 
                
                duracion_real = (sal_real - ent_real).total_seconds() / 3600.0 
                tiene_salida_valida = duracion_real > (15.0 / 60.0) 
                
                horas_trabajadas = duracion_real if tiene_salida_valida else 0.0
                he_calc = 0.0
                
                if es_sabado and dias_base == 5:
                    if tiene_salida_valida:
                        he_calc = math.floor(horas_trabajadas * 2) / 2.0
                        resultados.append({'Nombre_DB': nombre_db, 'Nombre_Hik': row['Nombre_Hik'], 'Dia': 'SAB', 'Fecha': row['Fecha'], 'Entrada': ent_real.strftime("%H:%M"), 'Salida': sal_real.strftime("%H:%M"), 'H. Reales': round(horas_trabajadas, 1), 'H. Extra': he_calc, 'Estatus': 'EXTRA', 'Detalle': f'Voluntario ({horas_trabajadas:.1f}h)'})
                    continue

                if tiene_salida_valida:
                    str_entrada = ent_real.strftime("%H:%M")
                    str_salida = sal_real.strftime("%H:%M")
                    
                    if horas_trabajadas > (horas_req + 0.5):
                        he_raw = horas_trabajadas - horas_req
                        he_calc = math.floor(he_raw * 2) / 2.0 
                    
                    if horas_trabajadas >= (horas_req - 0.5): 
                        est = "OK"
                        det = f"Turno Completo ({horas_trabajadas:.1f}h)"
                    elif horas_trabajadas > 2.0:
                        est = "REVISAR"
                        det = f"Inc. ({horas_trabajadas:.1f}h de {horas_req:.1f}h)"
                    else:
                        est = "FALTA"
                        det = f"<2h ({horas_trabajadas:.1f}h)"
                else:
                    diff_ent = abs((datetime.combine(datetime.today(), ent_real.time()) - dt_ent).total_seconds())
                    diff_sal = abs((datetime.combine(datetime.today(), ent_real.time()) - dt_sal).total_seconds())
                    if diff_sal < diff_ent: 
                        str_salida = ent_real.strftime("%H:%M"); str_entrada = "-"
                    else:
                        str_entrada = ent_real.strftime("%H:%M"); str_salida = "-"
                    
                    est = "FALTA"
                    det = "Sin Registro de Salida"

                if es_confianza: est = "OK"; det = "CONFIANZA (Libre)"; he_calc = 0.0
                elif es_transfer and est == "FALTA": est = "OK"; det = "TRANSFER"
                    
                resultados.append({'Nombre_DB': nombre_db, 'Nombre_Hik': row['Nombre_Hik'], 'Dia': mapa_dias.get(row['DiaSemana']), 'Fecha': row['Fecha'], 'Entrada': str_entrada, 'Salida': str_salida, 'H. Reales': round(horas_trabajadas, 1), 'H. Extra': he_calc, 'Estatus': est, 'Detalle': det})
            else: no_encontrados_set.add(row['Nombre_Hik'])
        
        if not asistencia.empty:
            rango_dias = pd.date_range(start=asistencia['Fecha'].min(), end=asistencia['Fecha'].max()).date
            for emp in set([r['Nombre_DB'] for r in resultados]):
                info = df_personal_db[df_personal_db['nombre'] == emp].iloc[0]
                es_confianza = bool(info.get('es_confianza', 0))
                for dia in rango_dias:
                    if dia.weekday() == 6: continue
                    if (emp, dia) not in registros_procesados:
                        if dia.weekday() == 5 and info.get('dias_base', 6) == 5: continue
                        est_miss = "OK" if es_confianza else "-"; det_miss = "CONFIANZA (S/C)" if es_confianza else "Sin Registro"
                        resultados.append({'Nombre_DB': emp, 'Nombre_Hik': emp, 'Dia': mapa_dias.get(dia.weekday()), 'Fecha': dia, 'Entrada': '-', 'Salida': '-', 'H. Reales': 0.0, 'H. Extra': 0.0, 'Estatus': est_miss, 'Detalle': det_miss})

        return pd.DataFrame(resultados).sort_values(by=['Nombre_DB', 'Fecha']), list(no_encontrados_set)
    except Exception as e: return None, [str(e)]

def kill_previous_sandbox():
    if os.path.exists(PID_FILE):
        try: os.kill(int(open(PID_FILE).read().strip()), signal.SIGTERM); return True
        except: return False
    return False

def launch_sandbox(code_content):
    kill_previous_sandbox(); time.sleep(1)
    with open(SANDBOX_FILE, "w", encoding="utf-8") as f: f.write(code_content)
    cmd = [sys.executable, "-m", "streamlit", "run", SANDBOX_FILE, "--server.port", str(SANDBOX_PORT), "--server.address", "0.0.0.0", "--server.headless", "true", "--server.enableCORS", "false", "--server.enableXsrfProtection", "false", "--server.maxUploadSize", "500"]
    with open("sandbox.log", "w") as log: proc = subprocess.Popen(cmd, stdout=log, stderr=subprocess.STDOUT); open(PID_FILE, "w").write(str(proc.pid))

def ejecutar_simulacion_total():
    start_time = time.time()
    logs = ["🔥 INICIANDO MODO CAOS (RANDOM): Generando Empleados Aleatorios..."]
    try:
        conn = get_db_connection(SANDBOX_DB); c = conn.cursor()
        tables = ["personal", "deducciones", "asistencia_live", "he_live", "nomina_historica", "configuracion", "usuarios"]
        for t in tables: c.execute(f"DROP TABLE IF EXISTS {t}")
        conn.commit()
        logs.append("✅ Tablas eliminadas (DB Reset).")
        
        c.execute('''CREATE TABLE IF NOT EXISTS personal (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre TEXT UNIQUE, puesto TEXT, salario_semanal REAL, horas_semanales INTEGER, dias_base INTEGER DEFAULT 6, aplica_imss INTEGER DEFAULT 0, aplica_infonavit INTEGER DEFAULT 0, ultimo_imss REAL DEFAULT 0, ultimo_infonavit REAL DEFAULT 0, entrada_oficial TEXT DEFAULT '08:00', salida_oficial TEXT DEFAULT '17:00', entrada_sabado TEXT DEFAULT '09:00', salida_sabado TEXT DEFAULT '14:00', es_transfer INTEGER DEFAULT 0, es_confianza INTEGER DEFAULT 0, cuota_imss REAL DEFAULT 0.0, cuota_infonavit REAL DEFAULT 0.0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS deducciones (id INTEGER PRIMARY KEY AUTOINCREMENT, nombre_empleado TEXT, fecha TEXT, monto REAL, motivo TEXT, estado TEXT DEFAULT 'PENDIENTE', monto_semanal REAL DEFAULT 0, saldo_restante REAL DEFAULT 0)''')
        c.execute('''CREATE TABLE IF NOT EXISTS configuracion (clave TEXT PRIMARY KEY, valor TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS usuarios (username TEXT PRIMARY KEY, password TEXT, role TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS asistencia_live (uid TEXT PRIMARY KEY, semana_id TEXT, nombre TEXT, lun TEXT, mar TEXT, mie TEXT, jue TEXT, vie TEXT, sab TEXT)''')
        c.execute('''CREATE TABLE IF NOT EXISTS he_live (uid TEXT PRIMARY KEY, semana_id TEXT, nombre TEXT, lun REAL, mar REAL, mie REAL, jue REAL, vie REAL, sab REAL, dom REAL)''')
        c.execute('''CREATE TABLE IF NOT EXISTS nomina_historica (id INTEGER PRIMARY KEY AUTOINCREMENT, semana_id TEXT, fecha_cierre TEXT, nombre TEXT, salario_base REAL, dias_trabajados INTEGER, dias_vacaciones INTEGER, pago_vacaciones REAL, horas_extra_cant REAL, horas_extra_monto REAL, incentivos REAL, desc_imss REAL, desc_info REAL, otros_desc REAL, abono_prestamo REAL, total_pagar REAL)''')
        c.execute("INSERT OR IGNORE INTO configuracion (clave, valor) VALUES ('precio_hora_extra', '100.0')")
        
        # FIX USUARIOS
        c.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('admin', 'admin', 'ADMIN')")
        c.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('rrhh', '1234', 'RRHH')")
        c.execute("INSERT OR IGNORE INTO usuarios (username, password, role) VALUES ('it', '1234', 'IT')")

        logs.append("✅ Base de datos Sandbox limpia.")
        NUM_EMPLEADOS = 20 # REDUCIDO A 20 PARA EVITAR CRASH DE MEMORIA POR IMAGENES
        df_asis_rows = []
        df_he_rows = []
        dias_sem = ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']
        
        for i in range(1, NUM_EMPLEADOS + 1):
            name = f"EMP_TEST_{i:03d}"
            puesto = f"PUESTO_{i%5}"
            salario = random.choice([1200.0, 1500.0, 2000.0, 3500.0, 5000.0, 10000.0])
            es_conf = 1 if random.random() > 0.8 else 0
            es_trans = 1 if random.random() > 0.9 else 0
            rand_imss = random.choice([0, 1]); rand_info = random.choice([0, 1])
            
            c.execute("INSERT INTO personal (nombre, puesto, salario_semanal, horas_semanales, dias_base, aplica_imss, aplica_infonavit, cuota_imss, cuota_infonavit, es_transfer, es_confianza) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                      (name, puesto, salario, 48, 6, rand_imss, rand_info, 100.0 if rand_imss else 0, 500.0 if rand_info else 0, es_trans, es_conf))
            
            if random.random() > 0.7: 
                monto = random.randint(500, 5000)
                c.execute("INSERT INTO deducciones (nombre_empleado, fecha, monto, motivo, monto_semanal, saldo_restante, estado) VALUES (?,?,?,?,?,?,?)",
                          (name, get_local_now().strftime("%Y-%m-%d"), float(monto), "PRESTAMO_TEST", 500.0, float(monto), "PENDIENTE"))

            row_a = {'nombre': name}; row_h = {'nombre': name}
            for d in dias_sem:
                r = random.random()
                if r < 0.8: status = 'A'
                elif r < 0.9: status = 'F'
                else: status = 'V'
                row_a[d] = status
                he = 0
                if status == 'A' and random.random() > 0.9: he = random.choice([2, 3, 4])
                row_h[f'HE_{d}'] = he
            row_h['HE_Dom'] = 0
            df_asis_rows.append(row_a); df_he_rows.append(row_h)

        conn.commit(); conn.close()
        logs.append(f"✅ {NUM_EMPLEADOS} Empleados generados.")

        save_daily_progress("SIM-CHAOS", pd.DataFrame(df_asis_rows), pd.DataFrame(df_he_rows))
        logs.append("✅ Asistencia masiva guardada.")

        calc_start = time.time()
        conn = get_db_connection(SANDBOX_DB)
        df_per = pd.read_sql("SELECT * FROM personal", conn)
        df_per['aplica_imss'] = df_per['aplica_imss'].astype(bool)
        df_per['aplica_infonavit'] = df_per['aplica_infonavit'].astype(bool)
        deudas = pd.read_sql("SELECT nombre_empleado, sum(monto_semanal) as monto_semanal, sum(saldo_restante) as saldo_restante FROM deducciones WHERE estado='PENDIENTE' GROUP BY nombre_empleado", conn)
        conn.close()
        
        df_fin = pd.merge(df_per, deudas, left_on="nombre", right_on="nombre_empleado", how="left").fillna(0.0)
        df_fin = pd.merge(df_fin, pd.DataFrame(df_asis_rows), on="nombre", how="left")
        df_fin['Dias_A'] = df_fin[dias_sem].apply(lambda x: (x == 'A').sum(), axis=1)
        df_fin['Dias_V'] = df_fin[dias_sem].apply(lambda x: (x == 'V').sum(), axis=1)
        df_fin = pd.merge(df_fin, pd.DataFrame(df_he_rows), on='nombre', how='left')
        he_cols = [c for c in df_fin.columns if 'HE_' in c]
        df_fin['Total_HE'] = df_fin[he_cols].sum(axis=1)

        phe = 100.0
        df_fin['Pago_Diario'] = df_fin['salario_semanal'] / df_fin['dias_base']
        df_fin['Sueldo'] = df_fin['Pago_Diario'] * df_fin['Dias_A']
        df_fin['Pago_Vacaciones'] = df_fin['Pago_Diario'] * df_fin['Dias_V']
        df_fin['$ Extras'] = df_fin['Total_HE'] * phe
        df_fin['Incentivos'] = 0.0
        df_fin['Desc_IMSS'] = df_fin.apply(lambda x: float(x.get('cuota_imss', 0.0)) if x['aplica_imss'] else 0.0, axis=1)
        df_fin['Desc_Info'] = df_fin.apply(lambda x: float(x.get('cuota_infonavit', 0.0)) if x['aplica_infonavit'] else 0.0, axis=1)
        df_fin['Otros Descuentos'] = 0.0
        df_fin['Abono a Aplicar'] = df_fin.apply(lambda x: min(x['monto_semanal'], x['saldo_restante']), axis=1)
        df_fin['A PAGAR'] = (df_fin['Sueldo'] + df_fin['Pago_Vacaciones'] + df_fin['$ Extras']) - (df_fin['Abono a Aplicar'] + df_fin['Desc_IMSS'] + df_fin['Desc_Info'])
        
        df_fin['Días Trab'] = df_fin['Dias_A']
        df_fin['Días Vac'] = df_fin['Dias_V']
        df_fin['Horas Extra'] = df_fin['Total_HE']
        
        calc_time = time.time() - calc_start
        logs.append(f"✅ Nómina calculada en {calc_time:.4f} segundos.")

        excel_start = time.time()
        excel_bytes = generar_recibos_premium(df_fin, pd.DataFrame(df_asis_rows), pd.DataFrame(df_he_rows), df_per)
        excel_time = time.time() - excel_start
        
        if len(excel_bytes) > 5000: logs.append(f"✅ Excel Masivo ({len(excel_bytes)/1024:.1f} KB) generado en {excel_time:.4f} segundos.")
        else: logs.append("❌ Falló generación Excel.")

        total_time = time.time() - start_time
        logs.append(f"🎉 MODO CAOS FINALIZADO EN {total_time:.2f} SEGUNDOS TOTALES.")
        logs.append(f"💰 Nómina Total Simulada: ${df_fin['A PAGAR'].sum():,.2f}")
        
        gc.collect()
        return True, logs

    except Exception as e:
        return False, logs + [f"❌ ERROR CRÍTICO: {str(e)}"]

# --- V9.90: BUFFER DE MEMORIA DE IMAGEN EXCEL PARA EVITAR OOM CRASH ---
def generar_recibos_premium(dataframe_nomina, df_asistencia_det=None, df_he_det=None, df_personal_info=None, is_history=False):
    output = io.BytesIO()
    
    img_data = None
    if os.path.exists(LOGO_FILE):
        try:
            with open(LOGO_FILE, "rb") as f:
                img_data = io.BytesIO(f.read())
        except: pass

    with pd.ExcelWriter(output, engine='xlsxwriter', engine_kwargs={'options': {'nan_inf_to_errors': True}}) as writer:
        wb = writer.book
        ws = wb.add_worksheet("Recibos")
        ws.set_paper(1); ws.fit_to_pages(1, 0); ws.set_margins(0.5, 0.5, 0.5, 0.5)
        ws.set_column('A:A', 2); ws.set_column('B:B', 30); ws.set_column('C:I', 7); ws.set_column('J:J', 15)
        
        row = 1; receipt_count = 0; fecha_hoy = get_local_now().strftime("%d/%b/%Y"); page_breaks = []
        
        s_titulo = wb.add_format({'bold': True, 'font_size': 16, 'align': 'center'})
        s_header_gris = wb.add_format({'bold': True, 'bg_color': '#f0f0f0', 'border': 1, 'align': 'center'})
        s_texto = wb.add_format({'border': 1, 'align': 'left'})
        s_moneda = wb.add_format({'border': 1, 'num_format': '$ #,##0.00', 'align': 'right'})
        s_total = wb.add_format({'bold': True, 'bg_color': '#e6f3ff', 'border': 1, 'num_format': '$ #,##0.00', 'align': 'right'})
        s_center = wb.add_format({'align': 'center', 'border': 1})
        s_he_day = wb.add_format({'font_size': 8, 'align': 'center', 'border': 1})
        s_asis_A = wb.add_format({'bg_color': '#c6efce', 'font_color': '#006100', 'align': 'center', 'border': 1}) 
        s_asis_F = wb.add_format({'bg_color': '#ffc7ce', 'font_color': '#9c0006', 'align': 'center', 'border': 1}) 
        s_cut_line = wb.add_format({'bottom': 6, 'align': 'center', 'valign': 'vcenter', 'font_color': '#808080', 'font_size': 9}) 
        
        for i, data in dataframe_nomina.iterrows():
            nom = data['nombre']
            sem_title = data['semana_id'] if 'semana_id' in data else f"SEMANA {get_current_week_id()}"
            ws.merge_range(row, 1, row, 9, f"{NOMBRE_EMPRESA} - {sem_title}", s_titulo)
            if img_data: ws.insert_image(row, 1, LOGO_FILE, {'image_data': img_data, 'x_scale': 0.12, 'y_scale': 0.12, 'x_offset': 10, 'y_offset': 5})
            row += 1
            ws.merge_range(row, 1, row, 9, f"Empleado: {nom} | Sueldo Base: ${data.get('salario_semanal', 0):,.2f} | Fecha: {fecha_hoy}", wb.add_format({'align': 'center'}))
            row += 2
            
            if not is_history and df_asistencia_det is not None:
                ws.write(row, 1, "DÍA", s_header_gris); col_idx = 2
                for d in ["LUN", "MAR", "MIE", "JUE", "VIE", "SAB", "DOM"]: ws.write(row, col_idx, d, s_header_gris); col_idx += 1
                row += 1
                ws.write(row, 1, "ASISTENCIA", s_texto); col_idx = 2
                mask_asis = df_asistencia_det['nombre'] == nom
                if mask_asis.any():
                    row_asis = df_asistencia_det[mask_asis].iloc[0]
                    for d_key in ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']:
                        val = row_asis.get(d_key, '-')
                        estilo = s_asis_A if val == 'A' else s_asis_F if val == 'F' else s_center
                        ws.write(row, col_idx, val, estilo); col_idx += 1
                    ws.write(row, col_idx, "-", s_center) 
                else: ws.merge_range(row, 2, row, 8, "SIN DATOS", s_center)
                row += 1
                ws.write(row, 1, "HORAS EXTRA", s_texto); col_idx = 2
                mask_he = df_he_det['nombre'] == nom
                if mask_he.any():
                    row_he = df_he_det[mask_he].iloc[0]
                    for he_k in ['HE_Lun', 'HE_Mar', 'HE_Mie', 'HE_Jue', 'HE_Vie', 'HE_Sab', 'HE_Dom']:
                        hrs = row_he.get(he_k, 0)
                        if hrs > 0: ws.write(row, col_idx, f"{hrs}h", s_he_day)
                        else: ws.write(row, col_idx, "", s_he_day)
                        col_idx += 1
                row += 2

            ws.write(row, 1, "CONCEPTO", s_header_gris); ws.merge_range(row, 2, row, 8, "", s_header_gris); ws.write(row, 9, "IMPORTE", s_header_gris); row += 1
            def write_mon(r, label, amount, style_lbl=s_texto, style_amt=s_moneda):
                ws.write(r, 1, label, style_lbl); ws.merge_range(r, 2, r, 8, "", style_lbl); ws.write(r, 9, amount, style_amt)
                return r + 1
            
            row = write_mon(row, f"Sueldo Base (Calculado)", data.get('Sueldo', 0))
            if data.get('Pago_Vacaciones', 0) > 0: row = write_mon(row, f"Pago Vacaciones", data.get('Pago_Vacaciones', 0))
            if data.get('$ Extras', 0) > 0: row = write_mon(row, f"Horas Extra", data.get('$ Extras', 0))
            if data.get('Incentivos', 0) > 0: row = write_mon(row, "Bonos / Incentivos", data.get('Incentivos', 0))
            if data.get('Desc_IMSS', 0) > 0: row = write_mon(row, "IMSS", -data.get('Desc_IMSS', 0))
            if data.get('Desc_Info', 0) > 0: row = write_mon(row, "INFONAVIT", -data.get('Desc_Info', 0))
            if data.get('Otros Descuentos', 0) > 0: row = write_mon(row, "Otros Descuentos", -data.get('Otros Descuentos', 0))
            if data.get('Abono a Aplicar', 0) > 0: row = write_mon(row, "Abono Deuda", -data.get('Abono a Aplicar', 0))
            
            ws.write(row, 1, "NETO A RECIBIR", s_header_gris); ws.merge_range(row, 2, row, 8, "", s_header_gris); ws.write(row, 9, data.get('A PAGAR', 0), s_total); row += 1
            row += 2; receipt_count += 1
            if receipt_count % 2 == 0: page_breaks.append(row); row += 1 
            else: ws.merge_range(row, 1, row, 9, "- - - - - CORTAR AQUÍ - - - - -", s_cut_line); row += 2
        
        if page_breaks: ws.set_h_pagebreaks(page_breaks)
        
        ws2 = wb.add_worksheet("Tabular_General")
        cols = ['nombre', 'salario_semanal', 'Días Trab', 'Días Vac', 'Sueldo', 'Horas Extra', '$ Extras', 'Incentivos', 'Desc_IMSS', 'Desc_Info', 'Abono a Aplicar', 'Otros Descuentos', 'A PAGAR']
        for idx, col in enumerate(cols): ws2.write(0, idx, col.upper(), s_header_gris)
        
        # --- V9.90: PROTECCION INDEX PARA PANDAS (Elimina falla silenciosa de tuplas) ---
        for row_idx, data_tuple in enumerate(dataframe_nomina[cols].itertuples(index=False, name=None), 1):
            ws2.write(row_idx, 0, data_tuple[0], s_texto)
            ws2.write(row_idx, 1, data_tuple[1], s_moneda)
            ws2.write(row_idx, 2, data_tuple[2], s_center)
            ws2.write(row_idx, 3, data_tuple[3], s_center)
            ws2.write(row_idx, 4, data_tuple[4], s_moneda)
            ws2.write(row_idx, 5, data_tuple[5], s_center)
            ws2.write(row_idx, 6, data_tuple[6], s_moneda)
            ws2.write(row_idx, 7, data_tuple[7], s_moneda)
            ws2.write(row_idx, 8, data_tuple[8], s_moneda)
            ws2.write(row_idx, 9, data_tuple[9], s_moneda)
            ws2.write(row_idx, 10, data_tuple[10], s_moneda)
            ws2.write(row_idx, 11, data_tuple[11], s_moneda)
            ws2.write(row_idx, 12, data_tuple[12], s_total)
        ws2.set_column('A:A', 30); ws2.set_column('B:M', 15)

    return output.getvalue()

init_db()

# --- 7. INICIO LOGICA DE NEGOCIO ---
if 'authenticated' not in st.session_state: st.session_state.authenticated = False
if not st.session_state.authenticated:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<div style='margin-top: 50px;'></div>", unsafe_allow_html=True)
        with st.container(border=True):
            if os.path.exists(LOGO_FILE): st.image(LOGO_FILE, width=120)
            st.markdown(f"### {PAGE_TITLE}"); st.caption("Sistema de Nómina OTD")
            with st.form("login_form"):
                u = st.selectbox("Usuario", sorted([r[0].upper() for r in run_query("SELECT username FROM usuarios")]))
                p = st.text_input("Contraseña", type="password")
                if st.form_submit_button("Ingresar", type="primary"):
                    if run_query("SELECT password, role FROM usuarios WHERE username=?", (u.lower(),)) and run_query("SELECT password FROM usuarios WHERE username=?", (u.lower(),))[0][0] == p:
                        for key in list(st.session_state.keys()): del st.session_state[key]
                        st.session_state.authenticated = True; st.session_state.role = run_query("SELECT role FROM usuarios WHERE username=?", (u.lower(),))[0][0]; st.session_state.user = u.lower(); st.rerun()
                    else: st.error("Error")
    st.stop()

# --- 8. VARIABLES GLOBALES (POST-LOGIN) ---
ROLE = st.session_state.role
USER = st.session_state.user
IS_SIMULATION = ROLE == 'IT'
CAN_EDIT_CODE = ROLE in ['IT', 'ADMIN']
CAN_RESET_PASSWORDS = ROLE in ['IT', 'ADMIN']

def clear_cache():
    if 'df_asis_cache' in st.session_state: del st.session_state.df_asis_cache
    if 'df_he_cache' in st.session_state: del st.session_state.df_he_cache

@st.dialog("⚠️ CONFIRMAR CAMBIOS")
def confirmar_edicion_empleado(emp_name, new_sal, new_days, imss_val, info_val, cuota_imss, cuota_info, new_name, new_puesto, h_ent, h_sal, h_ent_sab, h_sal_sab, es_trans, es_conf):
    st.warning(f"Estás a punto de modificar el perfil de **{emp_name}**.")
    c1, c2 = st.columns(2)
    c1.markdown(f"🕒 L-V: **{h_ent} - {h_sal}**")
    c2.markdown(f"🕒 SAB: **{h_ent_sab} - {h_sal_sab}**")
    if st.button("✅ CONFIRMAR Y GUARDAR", type="primary"):
        run_query("""UPDATE personal SET nombre=?, puesto=?, salario_semanal=?, dias_base=?, aplica_imss=?, aplica_infonavit=?, cuota_imss=?, cuota_infonavit=?, entrada_oficial=?, salida_oficial=?, entrada_sabado=?, salida_sabado=?, es_transfer=?, es_confianza=? WHERE nombre=?""", 
                  (new_name, new_puesto, new_sal, new_days, 1 if imss_val else 0, 1 if info_val else 0, cuota_imss if imss_val else 0.0, cuota_info if info_val else 0.0, str(h_ent), str(h_sal), str(h_ent_sab), str(h_sal_sab), 1 if es_trans else 0, 1 if es_conf else 0, emp_name))
        if new_name != emp_name:
            run_query("UPDATE deducciones SET nombre_empleado=? WHERE nombre_empleado=?", (new_name, emp_name))
        st.success("Guardado exitosamente")
        clear_cache(); time.sleep(1); st.rerun()

@st.dialog("📋 CONFIRMACIÓN DE DEDUCCIONES")
def verificar_montos_sugeridos(df_input):
    st.info("💡 Puedes editar los montos de IMSS e INFONAVIT aquí mismo si es necesario.")
    df_work = df_input.copy()
    for c in ['Desc_IMSS', 'Desc_Info']: df_work[c] = pd.to_numeric(df_work[c], errors='coerce').fillna(0.0)
    mask_show = (df_work['aplica_imss'] == 1) | (df_work['aplica_infonavit'] == 1) | (df_work['Desc_IMSS'] > 0.01) | (df_work['Desc_Info'] > 0.01)
    df_editable = df_work.loc[mask_show, ['nombre', 'Desc_IMSS', 'Desc_Info']].copy()
    
    edited_subset = st.data_editor(
        df_editable,
        column_config={
            "nombre": st.column_config.TextColumn("Colaborador", disabled=True),
            "Desc_IMSS": st.column_config.NumberColumn("Desc. IMSS", format="$%.2f", step=1.0),
            "Desc_Info": st.column_config.NumberColumn("Desc. INFO", format="$%.2f", step=1.0)
        },
        hide_index=True, use_container_width=True, key="editor_deducciones_popup" 
    )
    
    if not edited_subset.empty:
        df_work.set_index('nombre', inplace=True); edited_subset.set_index('nombre', inplace=True)
        df_work.update(edited_subset); df_work.reset_index(inplace=True)
    
    errores = []
    mask_imss_missing = (df_work['aplica_imss'] == 1) & (df_work['Desc_IMSS'] <= 0.01)
    mask_info_missing = (df_work['aplica_infonavit'] == 1) & (df_work['Desc_Info'] <= 0.01)
    mask_imss_extra = (df_work['aplica_imss'] == 0) & (df_work['Desc_IMSS'] > 0.01)
    mask_info_extra = (df_work['aplica_infonavit'] == 0) & (df_work['Desc_Info'] > 0.01)
    
    for i, r in df_work[mask_imss_missing].iterrows(): errores.append(f"⛔ {r['nombre']}: Tiene IMSS activo pero cobro $0.00")
    for i, r in df_work[mask_info_missing].iterrows(): errores.append(f"⛔ {r['nombre']}: Tiene INFONAVIT activo pero cobro $0.00")
    for i, r in df_work[mask_imss_extra].iterrows(): errores.append(f"⚠️ {r['nombre']}: Cobro IMSS sin tener el check activo.")
    for i, r in df_work[mask_info_extra].iterrows(): errores.append(f"⚠️ {r['nombre']}: Cobro INFONAVIT sin tener el check activo.")
    
    if errores:
        st.error("Errores pendientes:")
        for e in errores: st.write(e)
        st.warning("Corrige los montos en la tabla de arriba para continuar.")
    else:
        st.success("✅ Validación Correcta.")
        if st.button("🚀 CONFIRMAR Y PROCESAR", type="primary"):
            st.session_state.temp_df_calc = df_work 
            st.session_state.montos_verificados = True
            st.rerun()

# --- 9. UI SIDEBAR ---
with st.sidebar:
    if os.path.exists(LOGO_FILE): st.image(LOGO_FILE, use_container_width=True)
    st.markdown(f"### {USER.upper()}")
    if IS_SIMULATION: st.warning("⚠️ MODO SIMULACIÓN")
    if IS_SANDBOX: st.warning("🧪 MODO SANDBOX")
    with st.expander("🔐 Password"):
        curr_p = st.text_input("Actual", type="password"); new_p = st.text_input("Nueva", type="password")
        if st.button("Actualizar"): 
            if verify_and_change_password(USER, curr_p, new_p): st.success("Listo"); time.sleep(1); st.rerun()
            else: st.error("Error")
    st.markdown("---"); opciones_menu = ["🏠 Directorio", "💸 Deducciones", "💰 Nómina", "⚙️ Ajustes"]
    if CAN_EDIT_CODE: opciones_menu.append("🛠️ Modo Dev")
    menu = st.radio("Nav", opciones_menu, label_visibility="collapsed")
    st.markdown("---"); 
    if st.button("🔄 Recargar"): clear_cache(); st.rerun()
    if st.button("🚪 Salir"): 
        for key in list(st.session_state.keys()): del st.session_state[key]
        st.rerun()

# --- 10. MAIN CONTENT ---
if menu == "🏠 Directorio":
    st.markdown("""<div class="header-box"><h2>Directorio</h2><p>Gestión de Colaboradores</p></div>""", unsafe_allow_html=True)
    t1, t2, t3 = st.tabs(["Alta", "Lista / Edición", "🔗 Match Hikvision"])
    with t1:
        with st.form("add_emp", clear_on_submit=True):
            c1, c2 = st.columns(2); nom = c1.text_input("Nombre").upper(); pue = c2.text_input("Puesto").upper(); sal = c1.number_input("Salario Semanal", step=100.0)
            dias_b = c2.number_input("Días Base", value=6); hrs_b = c1.number_input("Horas Sem", value=48)
            
            c_imss1, c_imss2, c_info1, c_info2 = st.columns(4)
            check_imss = c_imss1.checkbox("Aplica IMSS")
            val_imss = c_imss2.number_input("Cuota IMSS ($)", min_value=0.0, step=10.0, disabled=not check_imss)
            check_info = c_info1.checkbox("Aplica INFONAVIT")
            val_info = c_info2.number_input("Cuota INFO ($)", min_value=0.0, step=10.0, disabled=not check_info)
            
            c3, c4 = st.columns(2); check_transfer = c3.checkbox("Es Transfer"); check_confianza = c4.checkbox("Es Confianza")
            
            if st.form_submit_button("Guardar", type="primary"):
                run_query("INSERT INTO personal (nombre, puesto, salario_semanal, horas_semanales, dias_base, aplica_imss, aplica_infonavit, cuota_imss, cuota_infonavit, es_transfer, es_confianza) VALUES (?,?,?,?,?,?,?,?,?,?,?)", 
                          (nom, pue, sal, hrs_b, dias_b, 1 if check_imss else 0, 1 if check_info else 0, val_imss if check_imss else 0.0, val_info if check_info else 0.0, 1 if check_transfer else 0, 1 if check_confianza else 0))
                st.success("Guardado"); clear_cache(); time.sleep(1); st.rerun()
    with t2:
        df_p = get_df_secure("personal", ROLE)
        df_p['aplica_imss'] = df_p['aplica_imss'].astype(bool); df_p['aplica_infonavit'] = df_p['aplica_infonavit'].astype(bool)
        df_p['es_transfer'] = df_p['es_transfer'].astype(bool); df_p['es_confianza'] = df_p['es_confianza'].astype(bool)
        conf = { "aplica_imss": st.column_config.CheckboxColumn("🛡️ IMSS"), "aplica_infonavit": st.column_config.CheckboxColumn("🏠 INFONAVIT"), "es_transfer": st.column_config.CheckboxColumn("🚌 Transfer"), "es_confianza": st.column_config.CheckboxColumn("⭐ Confianza"), "salario_semanal": st.column_config.NumberColumn("Salario", format="$%.2f") }
        view_mode = st.radio("Vista:", ["📋 Datos Generales", "🕒 Horarios y Turnos"], horizontal=True, label_visibility="collapsed")
        if view_mode == "📋 Datos Generales":
            cols = ["nombre", "puesto", "salario_semanal", "aplica_imss", "aplica_infonavit", "es_transfer", "es_confianza"]
            st.dataframe(df_p, column_order=cols, column_config=conf, use_container_width=True, hide_index=True)
        else:
            def format_time_range(s, e):
                try: return f"{datetime.strptime(s[:5],'%H:%M').strftime('%H:%M')} - {datetime.strptime(e[:5],'%H:%M').strftime('%H:%M')}"
                except: return "-"
            def calc_weekly_hours(row):
                try:
                    s_lv = datetime.strptime(row['entrada_oficial'][:5], "%H:%M"); e_lv = datetime.strptime(row['salida_oficial'][:5], "%H:%M")
                    d_lv = (e_lv - s_lv).total_seconds()/3600; d_lv = d_lv+24 if d_lv<0 else d_lv
                    s_s = datetime.strptime(row['entrada_sabado'][:5], "%H:%M"); e_s = datetime.strptime(row['salida_sabado'][:5], "%H:%M")
                    d_s = (e_s - s_s).total_seconds()/3600; d_s = d_s+24 if d_s<0 else d_s
                    return (d_lv*5)+d_s
                except: return 0.0
            df_sched = df_p.copy()
            df_sched['🕒 L-V'] = df_sched.apply(lambda x: format_time_range(x['entrada_oficial'], x['salida_oficial']), axis=1)
            df_sched['🕒 Sab'] = df_sched.apply(lambda x: format_time_range(x['entrada_sabado'], x['salida_sabado']), axis=1)
            df_sched['⏱️ Hrs'] = df_sched.apply(calc_weekly_hours, axis=1)
            st.dataframe(df_sched[['nombre', '🕒 L-V', '🕒 Sab', '⏱️ Hrs']], use_container_width=True, hide_index=True, column_config={"⏱️ Hrs": st.column_config.NumberColumn(format="%.1f hrs")})

        if not IS_SIMULATION:
            st.markdown("---"); sel_emp = st.selectbox("Editar", [""] + df_p['nombre'].tolist())
            if sel_emp:
                curr = df_p[df_p['nombre'] == sel_emp].iloc[0]
                with st.container(border=True):
                    c1, c2 = st.columns(2); n_nom = c1.text_input("Nombre", curr['nombre']).upper(); n_pue = c2.text_input("Puesto", curr['puesto']).upper()
                    c3, c4 = st.columns(2); n_sal = c3.number_input("Salario", value=float(curr['salario_semanal'])); n_dias = c4.number_input("Días", value=int(curr['dias_base']))
                    c5, c6 = st.columns(2); n_ent = c5.time_input("Entrada L-V", safe_parse_time_str(curr['entrada_oficial'])); n_sal_h = c5.time_input("Salida L-V", safe_parse_time_str(curr['salida_oficial']))
                    n_ent_s = c6.time_input("Entrada S", safe_parse_time_str(curr['entrada_sabado'])); n_sal_s = c6.time_input("Salida S", safe_parse_time_str(curr['salida_sabado']))
                    
                    st.markdown("---"); ck1, ck2, ck3, ck4 = st.columns(4)
                    n_imss = ck1.checkbox("IMSS", bool(curr['aplica_imss']))
                    n_val_imss = ck2.number_input("Cuota IMSS", value=float(curr.get('cuota_imss', 0.0)), disabled=not n_imss)
                    
                    n_info = ck3.checkbox("INFONAVIT", bool(curr['aplica_infonavit']))
                    n_val_info = ck4.number_input("Cuota INFO", value=float(curr.get('cuota_infonavit', 0.0)), disabled=not n_info)
                    
                    c9, c10 = st.columns(2)
                    n_trans = c9.checkbox("Transfer", bool(curr.get('es_transfer', 0))); n_conf = c10.checkbox("Confianza", bool(curr.get('es_confianza', 0)))
                    
                    if st.button("Guardar Cambios", type="primary"): confirmar_edicion_empleado(sel_emp, n_sal, n_dias, n_imss, n_info, n_val_imss, n_val_info, n_nom, n_pue, n_ent, n_sal_h, n_ent_s, n_sal_s, n_trans, n_conf)
            if st.expander("Borrar"): 
                if st.button("Eliminar Definitivamente") and sel_emp: run_query("DELETE FROM personal WHERE nombre=?", (sel_emp,)); clear_cache(); st.rerun()
    with t3:
        st.markdown("##### 🔗 Sincronizador de Nombres (Hikvision vs Sistema)")
        uploaded_hik = st.file_uploader("Cargar Lista Hikvision (CSV/Excel)", type=["csv", "xlsx"])
        if uploaded_hik:
            try:
                if uploaded_hik.name.endswith('.csv'):
                    content = uploaded_hik.getvalue().decode("utf-8", errors='ignore')
                    start_row = detectar_inicio_datos_nativo(content)
                    lines = content.split('\n')
                    clean_content = '\n'.join(lines[start_row:])
                    df_hik_names = pd.read_csv(io.StringIO(clean_content), on_bad_lines='skip', engine='python')
                else: df_hik_names = pd.read_excel(uploaded_hik)
                
                df_hik_names.columns = df_hik_names.columns.str.replace('*', '').str.strip()
                if 'First Name' in df_hik_names.columns: df_hik_names['Nombre Completo'] = df_hik_names['First Name'].fillna('') + ' ' + df_hik_names['Last Name'].fillna('')
                else:
                    col_name = next((c for c in df_hik_names.columns if 'name' in c.lower() or 'nombre' in c.lower()), None)
                    if col_name: df_hik_names['Nombre Completo'] = df_hik_names[col_name]
                    else: st.error("No se encontraron columnas de nombre."); st.stop()
                
                df_hik_names['Nombre Completo'] = df_hik_names['Nombre Completo'].astype(str).str.strip().str.upper()
                st.info(f"📊 Filas encontradas: {len(df_hik_names)}")
                db_names = [r[0] for r in run_query("SELECT nombre FROM personal")]
                results = []
                for hik_name in df_hik_names['Nombre Completo'].unique():
                    if not hik_name or hik_name == 'NAN': continue
                    match = buscar_mejor_coincidencia(hik_name, db_names)
                    results.append({"Nombre en Hikvision": hik_name, "Coincidencia en DB": match if match else "-", "Estatus": "✅ OK" if match else "❌ NO ENCONTRADO"})
                st.dataframe(pd.DataFrame(results).style.applymap(lambda v: 'background-color: #d1fae5' if v=='✅ OK' else 'background-color: #fee2e2', subset=['Estatus']), use_container_width=True)
            except Exception as e: st.error(f"Error: {e}")

elif menu == "💸 Deducciones":
    st.markdown("""<div class="header-box"><h2>Deducciones</h2><p>Control de Deudas</p></div>""", unsafe_allow_html=True)
    t1, t2 = st.tabs(["Nuevo", "Saldos"])
    with t1:
        emps = [r[0] for r in run_query("SELECT nombre FROM personal ORDER BY nombre")]
        if emps:
            c1, c2 = st.columns(2); e = c1.selectbox("Empleado", emps); m = st.number_input("Monto", value=1000.0); mot = c2.text_input("Motivo").upper()
            if st.button("Registrar", type="primary"): run_query("INSERT INTO deducciones (nombre_empleado, fecha, monto, motivo, monto_semanal, saldo_restante) VALUES (?,?,?,?,?,?)", (e, get_local_now().strftime("%Y-%m-%d"), m, mot, 500.0, m)); st.success("Listo"); st.rerun()
    with t2:
        df_d = get_df_secure("deducciones", ROLE); ed = st.data_editor(df_d[df_d['estado']=='PENDIENTE'][['id', 'nombre_empleado', 'saldo_restante', 'monto_semanal']], use_container_width=True, hide_index=True, column_config={"id": st.column_config.NumberColumn(disabled=True)})
        if not IS_SIMULATION and st.button("Guardar Cambios"):
            for i, r in ed.iterrows():
                run_query("UPDATE deducciones SET saldo_restante=?, monto_semanal=?, estado=? WHERE id=?", 
                          (r['saldo_restante'], r['monto_semanal'], 'PAGADO' if r['saldo_restante']<=0 else 'PENDIENTE', r['id']))
            st.success("Ok"); st.rerun()
        with st.expander("🗑️ Borrar Deducción"):
            del_list = [f"ID: {r['id']} - {r['nombre_empleado']}" for i,r in df_d[df_d['estado']=='PENDIENTE'].iterrows()]
            d_sel = st.selectbox("Seleccionar para borrar", [""] + del_list)
            if st.button("Borrar Registro") and d_sel:
                run_query("DELETE FROM deducciones WHERE id=?", (d_sel.split("-")[0].replace("ID:","").strip(),)); st.success("Eliminado"); time.sleep(1); st.rerun()

elif menu == "💰 Nómina":
    st.markdown("""<div class="header-box"><h2>Nómina</h2><p>Cálculo Semanal Progresivo</p></div>""", unsafe_allow_html=True)
    
    # --- SELECTOR DE SEMANA ---
    hoy = get_local_now()
    opciones_semanas = []
    for i in range(0, 5): 
        fecha_iter = hoy - timedelta(weeks=i)
        opciones_semanas.append(fecha_iter.strftime("%Y-W%W"))
    
    col_sel, col_info = st.columns([1, 3])
    selected_week = col_sel.selectbox("📅 Seleccionar Semana de Trabajo", opciones_semanas, index=0)
    
    if 'active_week' not in st.session_state or st.session_state.active_week != selected_week:
        st.session_state.active_week = selected_week
        if 'df_asis_cache' in st.session_state: del st.session_state.df_asis_cache
        if 'df_he_cache' in st.session_state: del st.session_state.df_he_cache
        st.rerun()
        
    current_week = st.session_state.active_week

    df_per = get_df_secure("personal", ROLE); df_ded = get_df_secure("deducciones", ROLE)
    
    if not df_per.empty:
        if 'df_asis_cache' not in st.session_state:
            saved_asis, saved_he = load_saved_progress(current_week, df_per)
            st.session_state.df_asis_cache = saved_asis; st.session_state.df_he_cache = saved_he
        
        with st.expander("🗑️ Opciones de Reinicio"):
            if st.button("🗑️ BORRAR DATOS SEMANA", type="primary"):
                conn = get_db_connection(DB_NAME); c = conn.cursor()
                c.execute("DELETE FROM asistencia_live WHERE semana_id=?", (current_week,))
                c.execute("DELETE FROM he_live WHERE semana_id=?", (current_week,))
                conn.commit(); conn.close()
                del st.session_state['df_asis_cache']; del st.session_state['df_he_cache']
                st.success("Datos eliminados."); time.sleep(1); st.rerun()

        st.markdown("---")
        
        # --- HIKVISION MODULE ---
        with st.expander("📥 Revisión de Asistencia (Hikvision)", expanded=False):
            uploaded_file = st.file_uploader("CSV", type=["csv"])
            if uploaded_file:
                if st.button("Analizar y Previsualizar", type="secondary"):
                    uploaded_file.seek(0)
                    show_debug = (ROLE in ['IT', 'ADMIN'])
                    rep, miss = analizar_hikvision_con_horarios(uploaded_file, df_per, debug_mode=show_debug)
                    st.session_state.hik_report = rep
                    st.session_state.hik_missing = miss
                    if rep is None: st.error(f"❌ Error al leer el archivo: {miss[0]}")
                    else: st.success("✅ Análisis completado. Revisa la tabla abajo.")
                
                if 'hik_report' in st.session_state and st.session_state.hik_report is not None:
                    st.dataframe(
                        st.session_state.hik_report.style.applymap(lambda v: 'background-color: #d1fae5' if v in ['OK', 'EXTRA'] else 'background-color: #fee2e2' if v=='FALTA' else 'background-color: #fef3c7' if v=='REVISAR' else '', subset=['Estatus']).format({'H. Reales': '{:.1f}', 'H. Extra': '{:.1f}'}), 
                        use_container_width=True
                    )
                    if st.session_state.hik_missing: st.warning(f"No encontrados: {st.session_state.hik_missing}")
                    
                    if st.button("✅ Confirmar y Aplicar (Asistencia y Extras)"):
                        df_upd_asis = st.session_state.df_asis_cache.copy()
                        df_upd_he = st.session_state.df_he_cache.copy()
                        day_map = {'LUN':'Lun', 'MAR':'Mar', 'MIE':'Mie', 'JUE':'Jue', 'VIE':'Vie', 'SAB':'Sab'}
                        
                        for i, r in st.session_state.hik_report.iterrows():
                            if r['Dia'] in day_map:
                                m_asis = df_upd_asis['nombre'].str.upper().str.strip() == str(r['Nombre_DB']).strip().upper()
                                m_he = df_upd_he['nombre'].str.upper().str.strip() == str(r['Nombre_DB']).strip().upper()
                                
                                status_code = 'A' if r['Estatus'] in ['OK', 'EXTRA', 'REVISAR'] else '-'
                                if r['Estatus'] == 'FALTA': status_code = 'F'
                                if m_asis.any(): df_upd_asis.loc[m_asis, day_map[r['Dia']]] = status_code
                                
                                if m_he.any() and r.get('H. Extra', 0) > 0:
                                    df_upd_he.loc[m_he, f"HE_{day_map[r['Dia']]}"] = r['H. Extra']
                                    
                        st.session_state.df_asis_cache = df_upd_asis
                        st.session_state.df_he_cache = df_upd_he
                        del st.session_state.hik_report
                        st.success("✅ Asistencias y Horas Extra inyectadas en las tablas."); st.rerun()

        t1, t2, t3 = st.tabs(["Asistencia", "Horas Extra", "Historial"])
        with t1:
            col_btn_all, col_glossary = st.columns([1, 3])
            with col_btn_all:
                if st.button("✅ ASISTENCIA PERFECTA (AUTO)", type="secondary", use_container_width=True, help="Pone 'A' de L-V. Sábados solo si aplica."):
                    df_curr = st.session_state.df_asis_cache.copy()
                    for c in ['Lun', 'Mar', 'Mie', 'Jue', 'Vie']: df_curr[c] = 'A'
                    df_curr['Sab'] = df_curr['Sab'].apply(lambda x: 'A' if x != '-' else '-')
                    st.session_state.df_asis_cache = df_curr
                    st.rerun()
            with col_glossary:
                st.markdown("""<div style="background-color: #f0f2f6; padding: 10px; border-radius: 8px; margin-bottom: 10px; font-size: 0.9em; border: 1px solid #e0e0e0;"><strong>📖 Glosario:</strong> <span style="color:#198754; font-weight:bold">A</span> = Asistencia | <span style="color:#dc3545; font-weight:bold">F</span> = Falta | <span style="color:#6c757d; font-weight:bold">-</span> = Sin Registro</div>""", unsafe_allow_html=True)
            
            col_conf = {
                "nombre": st.column_config.TextColumn("Colaborador", disabled=True),
                "Dias_A": None, "Dias_V": None, "uid": None, "semana_id": None
            }
            for d in ['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']: col_conf[d] = st.column_config.SelectboxColumn(label=d, options=["A", "F", "-", "V"], required=True)

            edited_asis = st.data_editor(st.session_state.df_asis_cache, use_container_width=True, hide_index=True, key="editor_asis", column_config=col_conf)
            edited_asis['Dias_A'] = edited_asis[['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']].apply(lambda x: (x == 'A').sum(), axis=1)
            edited_asis['Dias_V'] = edited_asis[['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']].apply(lambda x: (x == 'V').sum(), axis=1)
            
            st.caption("🔥 Mapa de Calor (Vista Previa en Tiempo Real):")
            def style_asis(val):
                if val == 'A': return 'background-color: #d1fae5; color: #065f46'
                if val == 'F': return 'background-color: #fee2e2; color: #991b1b'
                if val == 'V': return 'background-color: #fef3c7; color: #92400e'
                return ''
            st.dataframe(edited_asis[['nombre', 'Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']].style.applymap(style_asis, subset=['Lun', 'Mar', 'Mie', 'Jue', 'Vie', 'Sab']), use_container_width=True, hide_index=True)

        with t2:
            cols_he_nombres = ['HE_Lun', 'HE_Mar', 'HE_Mie', 'HE_Jue', 'HE_Vie', 'HE_Sab', 'HE_Dom']
            
            he_col_config = {
                "nombre": st.column_config.TextColumn("Colaborador", disabled=True),
                "Total_HE": st.column_config.NumberColumn("Total", disabled=True, format="%.1f")
            }
            for dia in cols_he_nombres:
                he_col_config[dia] = st.column_config.NumberColumn(
                    label=dia.replace("HE_", ""), 
                    min_value=0.0, 
                    max_value=24.0, 
                    step=0.5,
                    format="%.1f"
                )

            edited_he = st.data_editor(
                st.session_state.df_he_cache, 
                use_container_width=True, 
                hide_index=True, 
                key="editor_he",
                column_config=he_col_config
            )
            
            cols_num = edited_he[cols_he_nombres].fillna(0.0)
            edited_he['Total_HE'] = cols_num.sum(axis=1)

        # --- BOTÓN DE GUARDADO ---
        st.markdown("---")
        if st.button("💾 GUARDAR TODO (Asistencia y HE)", type="primary", use_container_width=True):
            save_daily_progress(current_week, edited_asis, edited_he)
            st.session_state.df_asis_cache = edited_asis
            st.session_state.df_he_cache = edited_he
            st.toast("✅ Guardado Exitosamente")
            time.sleep(0.5)

        with t3:
            is_postgres = "postgres_url" in st.secrets and st.secrets["postgres_url"] and "[YOUR-PASSWORD]" not in st.secrets["postgres_url"]
            if is_postgres:
                conn_h = psycopg2.connect(st.secrets["postgres_url"])
            else:
                conn_h = get_db_connection()
            df_h = pd.read_sql("SELECT * FROM nomina_historica ORDER BY semana_id DESC", conn_h)
            conn_h.close()
            if not df_h.empty:
                s = st.selectbox("Semana Histórica", df_h['semana_id'].unique())
                if s: 
                    df_s = df_h[df_h['semana_id']==s]
                    st.dataframe(df_s, use_container_width=True)
                    st.download_button("Descargar", data=generar_recibos_premium(df_s, is_history=True), file_name=f"Nomina_{s}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        st.divider(); st.markdown("##### 💵 Cálculo")
        deudas = df_ded[df_ded['estado']=='PENDIENTE'].groupby('nombre_empleado')[['monto_semanal', 'saldo_restante']].sum().reset_index()
        
        # V9.90: FILLNA (Anti-Crash Frontend)
        df_w = pd.merge(df_per, deudas, left_on="nombre", right_on="nombre_empleado", how="left").fillna(0.0)
        df_w = pd.merge(df_w, edited_asis[['nombre', 'Dias_A', 'Dias_V']], on='nombre', how='left').fillna(0.0)
        df_w['Días Trab'] = df_w['Dias_A']; df_w['Días Vac'] = df_w['Dias_V']
        df_w = pd.merge(df_w, edited_he[['nombre', 'Total_HE']], on='nombre', how='left').fillna(0.0)
        df_w['Horas Extra'] = df_w['Total_HE']
        
        df_w['Desc_IMSS'] = df_w.apply(lambda x: float(x.get('cuota_imss', 0.0)) if x['aplica_imss'] else 0.0, axis=1)
        df_w['Desc_Info'] = df_w.apply(lambda x: float(x.get('cuota_infonavit', 0.0)) if x['aplica_infonavit'] else 0.0, axis=1)
        
        df_w['Abono a Aplicar'] = df_w.apply(lambda x: min(x['monto_semanal'], x['saldo_restante']), axis=1)
        df_w['Incentivos'] = 0.0; df_w['Otros Descuentos'] = 0.0
        
        df_w['aplica_imss'] = df_w['aplica_imss'].astype(bool); df_w['aplica_infonavit'] = df_w['aplica_infonavit'].astype(bool)
        
        calc_config = {
            "nombre": st.column_config.TextColumn("Colaborador", disabled=True),
            "salario_semanal": st.column_config.NumberColumn("Sueldo Sem", format="$%.2f", disabled=True),
            "aplica_imss": st.column_config.CheckboxColumn("🛡️ IMSS"),
            "aplica_infonavit": st.column_config.CheckboxColumn("🏠 INFO"),
            "Días Trab": st.column_config.NumberColumn("Días A", disabled=True),
            "Días Vac": st.column_config.NumberColumn("Días V", disabled=True),
            "Desc_IMSS": st.column_config.NumberColumn("Desc. IMSS", format="$%.2f"),
            "Desc_Info": st.column_config.NumberColumn("Desc. INFO", format="$%.2f"),
            "Abono a Aplicar": st.column_config.NumberColumn("Abono Deuda", format="$%.2f"),
            "Otros Descuentos": st.column_config.NumberColumn(format="$%.2f"),
            "Incentivos": st.column_config.NumberColumn(format="$%.2f"),
            "Horas Extra": st.column_config.NumberColumn("Hrs Extra")
        }
        
        edited_calc = st.data_editor(df_w[['nombre', 'salario_semanal', 'aplica_imss', 'aplica_infonavit', 'Días Trab', 'Días Vac', 'Desc_IMSS', 'Desc_Info', 'Abono a Aplicar', 'Otros Descuentos', 'Incentivos', 'Horas Extra']], use_container_width=True, key="nc", column_config=calc_config)
        
        if st.button("CALCULAR NÓMINA", type="primary", use_container_width=True):
            st.session_state.temp_df_calc = edited_calc; verificar_montos_sugeridos(edited_calc)
        
        if 'montos_verificados' in st.session_state:
            df_fin = pd.merge(st.session_state.temp_df_calc, df_per[['nombre', 'dias_base']], on='nombre', how='left').fillna(0.0)
            phe = float(get_config("precio_hora_extra", 100.0))
            df_fin['Pago_Diario'] = df_fin['salario_semanal'] / df_fin['dias_base']
            df_fin['Sueldo'] = df_fin['Pago_Diario'] * df_fin['Días Trab']
            df_fin['Pago_Vacaciones'] = df_fin['Pago_Diario'] * df_fin['Días Vac']
            df_fin['$ Extras'] = df_fin['Horas Extra'] * phe
            df_fin['A PAGAR'] = (df_fin['Sueldo'] + df_fin['Pago_Vacaciones'] + df_fin['$ Extras'] + df_fin['Incentivos']) - (df_fin['Abono a Aplicar'] + df_fin['Otros Descuentos'] + df_fin['Desc_IMSS'] + df_fin['Desc_Info'])
            
            # V9.90: ANTI-CRASH PRE-RENDER
            df_fin = df_fin.fillna(0.0)
            
            m1, m2, m3, m4 = st.columns(4)
            m1.metric("💰 Total a Pagar", f"${df_fin['A PAGAR'].sum():,.2f}")
            m2.metric("⏱️ Horas Extra", f"{df_fin['Horas Extra'].sum():.1f} hrs")
            m3.metric("🛡️ Ret. IMSS", f"${df_fin['Desc_IMSS'].sum():,.2f}")
            m4.metric("🏠 Ret. INFONAVIT", f"${df_fin['Desc_Info'].sum():,.2f}")

            st.dataframe(df_fin[['nombre', 'Sueldo', '$ Extras', 'A PAGAR']].style.format({'Sueldo': '${:,.2f}', '$ Extras': '${:,.2f}', 'A PAGAR': '${:,.2f}'}), use_container_width=True)
            
            c1, c2 = st.columns(2)
            c1.download_button("Bajar Excel", data=generar_recibos_premium(df_fin, edited_asis, edited_he, df_per), file_name="Nomina.xlsx", use_container_width=True)
            if not IS_SIMULATION and c2.button("CERRAR SEMANA", type="primary", use_container_width=True):
                archivar_nomina_cerrada(current_week, df_fin)
                is_postgres = "postgres_url" in st.secrets and st.secrets["postgres_url"] and "[YOUR-PASSWORD]" not in st.secrets["postgres_url"]
                if is_postgres:
                    conn_cs = psycopg2.connect(st.secrets["postgres_url"])
                    q_deds = "SELECT * FROM deducciones WHERE nombre_empleado = %s AND estado = 'PENDIENTE'"
                else:
                    conn_cs = get_db_connection()
                    q_deds = "SELECT * FROM deducciones WHERE nombre_empleado = ? AND estado = 'PENDIENTE'"
                for i, r in df_fin.iterrows():
                    cob = r['Abono a Aplicar']
                    if cob > 0:
                        df_deds_emp = pd.read_sql(q_deds, conn_cs, params=(r['nombre'],))
                        for j, d in df_deds_emp.iterrows():
                            if cob <= 0: break
                            p = min(d['saldo_restante'], cob); cob -= p
                            run_query("UPDATE deducciones SET saldo_restante=?, estado=? WHERE id=?", (d['saldo_restante']-p, 'PAGADO' if d['saldo_restante']-p<0.1 else 'PENDIENTE', d['id']))
                conn_cs.close()
                del st.session_state.montos_verificados; clear_cache(); st.success("Cerrado"); st.rerun()

elif menu == "⚙️ Ajustes":
    st.markdown("""<div class="header-box"><h2>Configuración</h2></div>""", unsafe_allow_html=True)
    if ROLE in ['IT', 'ADMIN']:
        c1, c2 = st.columns(2)
        c1.download_button("📥 PORTABLE", data=create_portable_zip(), file_name="OTD_RH.zip", mime="application/zip", use_container_width=True)
        up = c2.file_uploader("Cargar Backup", type=["zip"])
        if up and c2.button("Restaurar"): 
            ok, m = restore_from_zip(up); st.success("OK") if ok else st.error(m[0])
    with st.form("c"):
        nh = st.number_input("Precio HE", value=float(get_config("precio_hora_extra", 100.0)))
        if st.form_submit_button("Guardar"): set_config("precio_hora_extra", nh); st.rerun()
    if ROLE == 'ADMIN':
        with st.expander("Usuarios"): st.dataframe(run_query("SELECT username, password, role FROM usuarios"))

elif menu == "🛠️ Modo Dev" and CAN_EDIT_CODE:
    st.markdown("### 🛠️ Panel de Desarrollador")
    
    if st.button("🧪 EJECUTAR SIMULACIÓN TOTAL (AUTO-QA)", type="primary"):
        with st.spinner("⏳ Ejecutando pruebas de estrés..."):
            ok, log = ejecutar_simulacion_total()
        if ok:
            st.success("✅ TEST EXITOSO")
            with st.expander("Ver Reporte de QA"):
                for l in log: st.write(l)
        else:
            st.error("❌ FALLO EN EL TEST")
            with st.expander("Ver Errores"):
                for l in log: st.write(l)

    if IS_SANDBOX: 
        st.info("⚠️ Estás dentro del Sandbox. El editor de código está deshabilitado para evitar recursión.")
    else:
        t1, t2 = st.tabs(["Editor", "Sandbox Launcher"])
        with t1:
            code = st.text_area("Code", value=open(__file__, encoding="utf-8").read(), height=400)
            if st.button("Guardar"): shutil.copy(__file__, f"backup_{get_local_now().strftime('%H%M%S')}.py"); open(__file__, "w", encoding="utf-8").write(code); st.rerun()
        with t2:
            sc = st.text_area("Sandbox Code", value=open(__file__, encoding="utf-8").read(), height=400)
            c1, c2, c3 = st.columns(3)
            if c1.button("🔥 ON (8599)"): launch_sandbox(sc); st.success(f"http://{SERVER_IP}:{SANDBOX_PORT}")
            if c2.button("🛑 OFF"): kill_previous_sandbox(); st.success("Off")
            if c3.button("🚀 DEPLOY"): shutil.copy(__file__, f"backup_PRE_{get_local_now().strftime('%H%M%S')}.py"); open(__file__, "w", encoding="utf-8").write(sc); st.success("Deployed"); st.rerun()