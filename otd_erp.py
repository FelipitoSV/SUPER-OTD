# ==============================================================================
# SISTEMA: OTD ERP (ENTERPRISE RESOURCE PLANNING)
# CLIENTE: OTD FREIGHT
# VERSION: V2.20 (IN-APP SANDBOX LAUNCHER + CUSTOM IP)
# ==============================================================================
import streamlit as st
import pandas as pd
import sqlite3
from datetime import datetime, timedelta, date
import io
import time
import os
import shutil
import base64
import calendar
import xml.etree.ElementTree as ET
import subprocess
import sys
import signal

# --- 1. CONFIGURACIÓN ---
LOGO_FILE = "OTD Logo.png" 

st.set_page_config(
    page_title="OTD Freight", 
    page_icon="🚛",
    layout="wide",
    initial_sidebar_state="collapsed"
)

APP_VERSION = "V2.20 (Sandbox IP)" 
ADMIN_PASSWORD = "2526"
BACKUP_DIR = "backups"
DB_NAME = "hydra_v1.db"

# --- HELPER: IMAGEN ---
def get_image_base64(path):
    try:
        with open(path, "rb") as f: return f"data:image/png;base64,{base64.b64encode(f.read()).decode()}"
    except: return None

# --- 2. SISTEMA DE RESPALDO ---
def run_auto_backup():
    if not os.path.exists(BACKUP_DIR): os.makedirs(BACKUP_DIR)
    try:
        backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")], reverse=True)
        if not backups or (get_local_now() - datetime.strptime(backups[0].replace("backup_", "").replace(".db", ""), "%Y%m%d_%H%M") > timedelta(hours=1)):
            if os.path.exists(DB_NAME):
                shutil.copy(DB_NAME, f"{BACKUP_DIR}/backup_{get_local_now().strftime('%Y%m%d_%H%M')}.db")
    except: pass

run_auto_backup()

# --- 3. GLOBALES ---
if 'menu_actual' not in st.session_state: st.session_state.menu_actual = "OPERACIONES"
if 'admin_unlocked' not in st.session_state: st.session_state.admin_unlocked = False
if 'db_connection_error' not in st.session_state: st.session_state.db_connection_error = None
if 'use_postgres_fallback' not in st.session_state: st.session_state.use_postgres_fallback = False

# --- 4. CSS ---
BACKGROUND_URL = "https://images.unsplash.com/photo-1451187580459-43490279c0fa?q=80&w=2072&auto=format&fit=crop"
st.markdown(f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;600;800&display=swap');
    html, body, [class*="css"] {{ font-family: 'Inter', sans-serif; }}
    [data-testid="stAppViewContainer"] {{
        background-color: #0f172a !important;
        background-image: linear-gradient(rgba(15, 23, 42, 0.85), rgba(15, 23, 42, 0.95)), url('{BACKGROUND_URL}');
        background-size: cover; background-attachment: fixed;
    }}
    .block-container {{ padding-top: 4.5rem !important; max-width: 95% !important; }}
    [data-testid="stForm"], .stDataFrame, .admin-panel, .filter-box, div[data-testid="stExpander"] {{
        background-color: rgba(30, 41, 59, 0.6) !important;
        backdrop-filter: blur(12px); border: 1px solid rgba(255, 255, 255, 0.1); border-radius: 16px; padding: 20px;
    }}
    .top-nav {{
        background: rgba(0, 43, 91, 0.8); padding: 12px 25px; border-radius: 16px; color: white;
        display: flex; align-items: center; justify-content: space-between; margin-bottom: 25px;
    }}
    .stTextInput input, .stSelectbox div[data-baseweb="select"] > div, .stNumberInput input, .stDateInput input {{
        background-color: rgba(15, 23, 42, 0.6) !important; color: #e2e8f0 !important;
    }}
    .stButton > button {{ border-radius: 10px; font-weight: 600; background-color: rgba(255,255,255,0.05); color: white; }}
    div[data-testid="stVerticalBlock"] > div > .stButton > button[kind="primary"] {{ 
        background: linear-gradient(135deg, #002B5B 0%, #004e92 100%); color: white; 
    }}
    
    /* Legibilidad de etiquetas, radios, checkboxes y textos */
    label, .stWidgetLabel, div[data-testid="stWidgetLabel"] p, 
    span[data-testid="stWidgetLabel"], div[role="radiogroup"] label, 
    div[data-testid="stCheckbox"] label, div[data-testid="stMarkdownContainer"] p,
    .stMarkdown p, .stSubheader p {{
        color: #f8fafc !important; /* Slate 50 */
    }}
    
    /* Legibilidad de pestañas (Tabs) */
    button[data-baseweb="tab"] p {{
        color: #cbd5e1 !important; /* Slate 300 */
    }}
    button[data-baseweb="tab"][aria-selected="true"] p {{
        color: #ffffff !important; /* Blanco */
        font-weight: 700 !important;
    }}
    </style>
    """, unsafe_allow_html=True)


# --- 5. DB & HELPERS ---
import psycopg2
import psycopg2.pool

@st.cache_resource
def get_postgres_pool(url):
    # Pool de conexiones (Mínimo 1, Máximo 20)
    return psycopg2.pool.ThreadedConnectionPool(1, 20, url)

class CoercedConnection:
    def __init__(self, conn, pool=None):
        self._conn = conn
        self._pool = pool
        self._returned = False

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def close(self):
        if not self._returned:
            try:
                if self._pool:
                    self._pool.putconn(self._conn)
                else:
                    self._conn.close()
            except:
                try:
                    self._conn.close()
                except:
                    pass
            self._returned = True

    def __del__(self):
        self.close()

def check_is_postgres():
    return "postgres_url" in st.secrets and st.secrets["postgres_url"] and "[YOUR-PASSWORD]" not in st.secrets["postgres_url"] and not st.session_state.get("use_postgres_fallback", False)

def get_connection():
    is_postgres = "postgres_url" in st.secrets and st.secrets["postgres_url"] and "[YOUR-PASSWORD]" not in st.secrets["postgres_url"]
    if is_postgres and not st.session_state.get("use_postgres_fallback", False):
        try:
            pool = get_postgres_pool(st.secrets["postgres_url"].strip())
            conn = pool.getconn()
            if conn.closed:
                try:
                    pool.discard(conn)
                except:
                    pass
                conn = pool.getconn()
            return CoercedConnection(conn, pool)
        except Exception as e:
            err_msg = str(e)
            try:
                import urllib.parse
                url = st.secrets["postgres_url"]
                parsed = urllib.parse.urlparse(url)
                if parsed.password:
                    err_msg = err_msg.replace(parsed.password, "****").replace(urllib.parse.quote_plus(parsed.password), "****")
            except:
                pass
            st.session_state.db_connection_error = err_msg
            st.session_state.use_postgres_fallback = True
            sqlite_conn = sqlite3.connect(DB_NAME)
            return CoercedConnection(sqlite_conn)
    else:
        sqlite_conn = sqlite3.connect(DB_NAME)
        return CoercedConnection(sqlite_conn)

def translate_sqlite_to_postgres(query):
    query = query.replace("?", "%s")
    ql = query.lower().strip()
    if ql.startswith("insert or ignore into"):
        if "notepad" in ql:
            if "%s" in query:
                query = "INSERT INTO notepad (id, contenido) VALUES (%s, %s) ON CONFLICT (id) DO NOTHING"
            else:
                query = "INSERT INTO notepad (id, contenido) VALUES (1, '') ON CONFLICT (id) DO NOTHING"
        elif "choferes" in ql:
            if "select" in ql:
                query = "INSERT INTO choferes (nombre) SELECT DISTINCT operador FROM flota WHERE operador IS NOT NULL AND operador != '' ON CONFLICT (nombre) DO NOTHING"
            else:
                query = "INSERT INTO choferes (nombre, tipo, disponible) VALUES (%s, %s, %s) ON CONFLICT (nombre) DO UPDATE SET tipo = EXCLUDED.tipo, disponible = EXCLUDED.disponible"
        elif "camiones" in ql:
            if "select" in ql:
                query = "INSERT INTO camiones (tracto, placas) SELECT DISTINCT tracto, placas FROM flota WHERE tracto IS NOT NULL AND tracto != '' ON CONFLICT (tracto) DO NOTHING"
            else:
                query = "INSERT INTO camiones (tracto, placas, disponible) VALUES (%s, %s, %s) ON CONFLICT (tracto) DO UPDATE SET placas = EXCLUDED.placas, disponible = EXCLUDED.disponible"
        elif "cajas" in ql:
            if "select" in ql:
                query = "INSERT INTO cajas (caja) SELECT DISTINCT caja FROM panel WHERE caja IS NOT NULL AND caja != '' AND caja != 'N/A' ON CONFLICT (caja) DO NOTHING"
            else:
                query = "INSERT INTO cajas (caja, disponible) VALUES (%s, %s) ON CONFLICT (caja) DO UPDATE SET disponible = EXCLUDED.disponible" 
        elif "cat_vencimientos" in ql:
            query = "INSERT INTO cat_vencimientos VALUES (%s) ON CONFLICT (tipo) DO NOTHING"
            
    elif ql.startswith("insert or replace into"):
        if "config" in ql:
            if "'tc'" in ql or '"tc"' in ql:
                query = "INSERT INTO config (clave, valor) VALUES ('TC', %s) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"
            else:
                query = "INSERT INTO config (clave, valor) VALUES (%s, %s) ON CONFLICT (clave) DO UPDATE SET valor = EXCLUDED.valor"
        elif "mantenimiento" in ql:
            query = "INSERT INTO mantenimiento VALUES (%s, %s, %s, %s) ON CONFLICT (unidad) DO UPDATE SET ultimo_servicio_millas = EXCLUDED.ultimo_servicio_millas, intervalo_millas = EXCLUDED.intervalo_millas, fecha_servicio = EXCLUDED.fecha_servicio"
            
    return query



def get_local_now():
    from datetime import timezone
    offset_hours = -5
    try:
        # Try loading offset from config table in Supabase
        res = run_query("SELECT valor FROM config WHERE clave='timezone_offset'")
        if res:
            offset_hours = float(res[0][0])
    except:
        pass
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=offset_hours)



def get_local_now():
    from datetime import timezone
    offset_hours = -5
    try:
        res = run_query("SELECT valor FROM config WHERE clave='timezone_offset'")
        if res:
            offset_hours = float(res[0][0])
    except:
        pass
    return datetime.now(timezone.utc).replace(tzinfo=None) + timedelta(hours=offset_hours)

def run_query(query, params=()):
    is_postgres = check_is_postgres()
    
    # Prevenir escritura en SQLite temporal para evitar pérdida de datos
    ql = query.lower().strip()
    is_write = ql.startswith("insert") or ql.startswith("update") or ql.startswith("delete")
    if is_write and st.session_state.get("use_postgres_fallback", False):
        blocked_tables = ["panel", "gastos", "boletas", "choferes", "camiones", "cajas", "vencimientos", "historial_vencimientos", "historial_panel", "mantenimiento", "notepad"]
        if any(table in ql for table in blocked_tables):
            st.error("⚠️ **Modo de Seguridad (Lectura):** La escritura de registros está deshabilitada en la base de datos temporal local para evitar la pérdida de tus datos. Restablece la conexión a la nube para poder guardar cambios.")
            return False

    if is_postgres:
        query_translated = translate_sqlite_to_postgres(query)
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute(query_translated, params)
            ql = query_translated.lower().strip()
            if ql.startswith("select") or ql.startswith("pragma") or ql.startswith("show") or "returning" in ql:
                res = c.fetchall()
                conn.close()
                return res
            else:
                conn.commit()
                conn.close()
                return True
        except Exception as e:
            st.error(f"Postgres Error: {e}\nQuery: {query_translated}\nParams: {params}")
            conn.close()
            return False
    else:
        conn = get_connection()
        c = conn.cursor()
        try:
            c.execute(query, params)
            if query.lower().strip().startswith("select") or query.lower().strip().startswith("pragma"):
                res = c.fetchall()
                conn.close()
                return res
            else:
                conn.commit()
                conn.close()
                return True
        except Exception as e:
            st.error(f"SQLite Error: {e}")
            conn.close()
            return False

def check_col_exists(table, col):
    is_postgres = check_is_postgres()
    if is_postgres:
        try:
            res = run_query("SELECT 1 FROM information_schema.columns WHERE table_name = ? AND column_name = ?", (table.lower(), col.lower()))
            return len(res) > 0
        except:
            return False
    else:
        try:
            info = run_query(f"PRAGMA table_info({table})")
            for col_info in info:
                if col_info[1] == col: return True
            return False
        except: return False

def init_db():
    is_postgres = check_is_postgres()
    
    if is_postgres:
        run_query("""CREATE TABLE IF NOT EXISTS panel (
            rowid SERIAL PRIMARY KEY,
            fecha TEXT, movimiento TEXT, cliente TEXT, operador TEXT, tracto TEXT, caja TEXT, 
            factura TEXT, folio_cp TEXT, bascula TEXT, costo_final DOUBLE PRECISION, moneda TEXT, 
            ip_log TEXT, status_dia TEXT DEFAULT 'CONFIRMADO', ups TEXT, profepa TEXT, hora TEXT, 
            carta_porte TEXT DEFAULT 'NO', manifiesto TEXT DEFAULT 'NO', destino TEXT DEFAULT ''
        )""")
        run_query("""CREATE TABLE IF NOT EXISTS gastos (
            rowid SERIAL PRIMARY KEY,
            fecha TEXT, factura TEXT, tracto TEXT, caja TEXT, estado TEXT, operador TEXT, 
            costo_cruce DOUBLE PRECISION, moneda TEXT
        )""")
        run_query("""CREATE TABLE IF NOT EXISTS boletas (
            rowid SERIAL PRIMARY KEY,
            fecha TEXT, movimiento TEXT, descripcion TEXT, tracto TEXT, caja TEXT, d_caja TEXT, 
            yarda TEXT, operador TEXT, sellos TEXT, folio_cp TEXT, boleta TEXT, cobro TEXT
        )""")
        run_query("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT)")
        run_query("CREATE TABLE IF NOT EXISTS flota (tracto TEXT PRIMARY KEY, operador TEXT, placas TEXT)")
        run_query("CREATE TABLE IF NOT EXISTS vencimientos (id SERIAL PRIMARY KEY, unidad TEXT, tipo TEXT, fecha_venc TEXT, notas TEXT)")
        run_query("CREATE TABLE IF NOT EXISTS historial_vencimientos (id SERIAL PRIMARY KEY, unidad TEXT, tipo TEXT, fecha_venc TEXT, fecha_completado TEXT)")
        run_query("CREATE TABLE IF NOT EXISTS cat_vencimientos (tipo TEXT PRIMARY KEY)")
        run_query("""CREATE TABLE IF NOT EXISTS historial_panel (
            rowid SERIAL PRIMARY KEY,
            fecha TEXT, movimiento TEXT, cliente TEXT, operador TEXT, tracto TEXT, caja TEXT, 
            factura TEXT, folio_cp TEXT, bascula TEXT, costo_final DOUBLE PRECISION, moneda TEXT, 
            ip_log TEXT, status_dia TEXT DEFAULT 'CONFIRMADO', ups TEXT, profepa TEXT, hora TEXT, 
            carta_porte TEXT DEFAULT 'NO', manifiesto TEXT DEFAULT 'NO', destino TEXT DEFAULT '',
            fecha_completado TEXT
        )""")
        run_query("CREATE TABLE IF NOT EXISTS mantenimiento (unidad TEXT PRIMARY KEY, ultimo_servicio_millas DOUBLE PRECISION, intervalo_millas DOUBLE PRECISION, fecha_servicio TEXT)")
        run_query("CREATE TABLE IF NOT EXISTS notepad (id INTEGER PRIMARY KEY, contenido TEXT)")
        run_query("INSERT OR IGNORE INTO notepad (id, contenido) VALUES (1, '')")
        
        # Nuevas tablas para conductores, camiones y cajas separados:
        run_query("CREATE TABLE IF NOT EXISTS choferes (nombre TEXT PRIMARY KEY, tipo TEXT DEFAULT 'TRANSFER', disponible TEXT DEFAULT 'SI')")
        run_query("CREATE TABLE IF NOT EXISTS camiones (tracto TEXT PRIMARY KEY, placas TEXT, disponible TEXT DEFAULT 'SI')")
        run_query("CREATE TABLE IF NOT EXISTS cajas (caja TEXT PRIMARY KEY, disponible TEXT DEFAULT 'SI')")
    else:
        run_query('''CREATE TABLE IF NOT EXISTS panel (fecha TEXT, movimiento TEXT, cliente TEXT, operador TEXT, tracto TEXT, caja TEXT, factura TEXT, folio_cp TEXT, bascula TEXT, costo_final REAL, moneda TEXT, ip_log TEXT, status_dia TEXT DEFAULT 'CONFIRMADO', ups TEXT, profepa TEXT, hora TEXT, carta_porte TEXT DEFAULT 'NO', manifiesto TEXT DEFAULT 'NO', destino TEXT DEFAULT '')''')
        run_query('''CREATE TABLE IF NOT EXISTS gastos (fecha TEXT, factura TEXT, tracto TEXT, caja TEXT, estado TEXT, operador TEXT, costo_cruce REAL, moneda TEXT)''')
        run_query('''CREATE TABLE IF NOT EXISTS boletas (fecha TEXT, movimiento TEXT, descripcion TEXT, tracto TEXT, caja TEXT, d_caja TEXT, yarda TEXT, operador TEXT, sellos TEXT, folio_cp TEXT, boleta TEXT, cobro TEXT)''')
        run_query('''CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT)''')
        run_query('''CREATE TABLE IF NOT EXISTS flota (tracto TEXT PRIMARY KEY, operador TEXT, placas TEXT)''') 
        run_query('''CREATE TABLE IF NOT EXISTS vencimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, unidad TEXT, tipo TEXT, fecha_venc TEXT, notas TEXT)''')
        run_query('''CREATE TABLE IF NOT EXISTS historial_vencimientos (id INTEGER PRIMARY KEY AUTOINCREMENT, unidad TEXT, tipo TEXT, fecha_venc TEXT, fecha_completado TEXT)''')
        run_query('''CREATE TABLE IF NOT EXISTS cat_vencimientos (tipo TEXT PRIMARY KEY)''')
        run_query("""CREATE TABLE IF NOT EXISTS historial_panel (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha TEXT, movimiento TEXT, cliente TEXT, operador TEXT, tracto TEXT, caja TEXT, 
            factura TEXT, folio_cp TEXT, bascula TEXT, costo_final REAL, moneda TEXT, 
            ip_log TEXT, status_dia TEXT DEFAULT 'CONFIRMADO', ups TEXT, profepa TEXT, hora TEXT, 
            carta_porte TEXT DEFAULT 'NO', manifiesto TEXT DEFAULT 'NO', destino TEXT DEFAULT '',
            fecha_completado TEXT
        )""")
        run_query('''CREATE TABLE IF NOT EXISTS mantenimiento (unidad TEXT PRIMARY KEY, ultimo_servicio_millas REAL, intervalo_millas REAL, fecha_servicio TEXT)''')
        run_query('''CREATE TABLE IF NOT EXISTS notepad (id INTEGER PRIMARY KEY, contenido TEXT)''')
        run_query("INSERT OR IGNORE INTO notepad (id, contenido) VALUES (1, '')")
        
        # Nuevas tablas para conductores, camiones y cajas separados:
        run_query("CREATE TABLE IF NOT EXISTS choferes (nombre TEXT PRIMARY KEY, tipo TEXT DEFAULT 'TRANSFER', disponible TEXT DEFAULT 'SI')")
        run_query("CREATE TABLE IF NOT EXISTS camiones (tracto TEXT PRIMARY KEY, placas TEXT, disponible TEXT DEFAULT 'SI')")
        run_query("CREATE TABLE IF NOT EXISTS cajas (caja TEXT PRIMARY KEY, disponible TEXT DEFAULT 'SI')")
        
    if not check_col_exists("choferes", "tipo"): run_query("ALTER TABLE choferes ADD COLUMN tipo TEXT DEFAULT 'TRANSFER'")
    run_query("UPDATE choferes SET tipo = 'B1' WHERE tipo = 'CARRETERO'")
    
    # Migrar datos existentes a las nuevas tablas si están vacías:
    try:
        if not run_query("SELECT count(*) FROM choferes")[0][0]:
            run_query("INSERT OR IGNORE INTO choferes (nombre) SELECT DISTINCT operador FROM flota WHERE operador IS NOT NULL AND operador != ''")
        if not run_query("SELECT count(*) FROM camiones")[0][0]:
            run_query("INSERT OR IGNORE INTO camiones (tracto, placas) SELECT DISTINCT tracto, placas FROM flota WHERE tracto IS NOT NULL AND tracto != ''")
        if not run_query("SELECT count(*) FROM cajas")[0][0]:
            run_query("INSERT OR IGNORE INTO cajas (caja) SELECT DISTINCT caja FROM panel WHERE caja IS NOT NULL AND caja != '' AND caja != 'N/A'")
    except:
        pass
    
    if not check_col_exists("flota", "placas"): run_query("ALTER TABLE flota ADD COLUMN placas TEXT")
    if not check_col_exists("choferes", "disponible"): run_query("ALTER TABLE choferes ADD COLUMN disponible TEXT DEFAULT 'SI'")
    if not check_col_exists("camiones", "disponible"): run_query("ALTER TABLE camiones ADD COLUMN disponible TEXT DEFAULT 'SI'")
    if not check_col_exists("cajas", "disponible"): run_query("ALTER TABLE cajas ADD COLUMN disponible TEXT DEFAULT 'SI'")
    if not check_col_exists("panel", "ups"): run_query("ALTER TABLE panel ADD COLUMN ups TEXT")
    if not check_col_exists("panel", "profepa"): run_query("ALTER TABLE panel ADD COLUMN profepa TEXT")
    if not check_col_exists("panel", "hora"): run_query("ALTER TABLE panel ADD COLUMN hora TEXT")
    if not check_col_exists("panel", "carta_porte"): run_query("ALTER TABLE panel ADD COLUMN carta_porte TEXT DEFAULT 'NO'")
    if not check_col_exists("panel", "manifiesto"): run_query("ALTER TABLE panel ADD COLUMN manifiesto TEXT DEFAULT 'NO'")
    if not check_col_exists("panel", "destino"): run_query("ALTER TABLE panel ADD COLUMN destino TEXT DEFAULT ''")
    
    if not run_query("SELECT count(*) FROM cat_vencimientos")[0][0]:
        for d in ["SEGURO MEX", "SEGURO USA", "PLACAS", "LICENCIA", "F.MECANICA", "VERIF. HUMO"]: 
            run_query("INSERT OR IGNORE INTO cat_vencimientos VALUES (?)", (d,))

init_db()

# --- 6. MOTOR XML ---
def parse_cfdi_xml(file_obj, flota_map):
    try:
        tree = ET.parse(file_obj)
        root = tree.getroot()
        ns = {'cfdi': 'http://www.sat.gob.mx/cfd/4', 'cp31': 'http://www.sat.gob.mx/CartaPorte31'}
        
        fecha_emision = root.get('Fecha', '')[:10]
        folio_xml = root.get('Folio', '') 
        moneda = root.get('Moneda', 'MXN')
        total = float(root.get('Total', '0'))
        folio_cp_final = f"FAC{folio_xml}" if folio_xml else ""
        
        receptor = root.find('cfdi:Receptor', ns)
        nombre_receptor = receptor.get('Nombre', '').upper()
        
        row = {
            "Fecha": fecha_emision,
            "Factura": "", 
            "Cliente": "OTROS",
            "Movimiento": "PENDIENTE",
            "Camión": "S/D",
            "Chofer": "",
            "Caja": "",
            "Folio CP": folio_cp_final,
            "Báscula": False,
            "UPS": False,
            "Tarimas": False,
            "Profepa": False, 
            "Placas Detectadas": "",
            "Total XML": total,
            "Moneda": moneda,
            "Es Gasto": False,
            "carta_porte": False,
            "manifiesto": False
        }

        if "VIDRIO DECORATIVO" in nombre_receptor: row["Cliente"] = "VDO"
        elif "OTD FREIGHT" in nombre_receptor: row["Cliente"] = "Kwalu"
        else: 
            row["Es Gasto"] = True
            row["Cliente"] = "PROVEEDOR"

        complemento = root.find('cfdi:Complemento', ns)
        cp = complemento.find('cp31:CartaPorte', ns) if complemento is not None else None
        
        if cp:
            figura = cp.find('cp31:FiguraTransporte', ns)
            if figura:
                for t in figura.findall('cp31:TiposFigura', ns):
                    if t.get('TipoFigura') == '01': row["Chofer"] = t.get('NombreFigura', '')

            ubicaciones = cp.find('cp31:Ubicaciones', ns)
            pais_origen, pais_destino = "", ""
            if ubicaciones:
                for ubi in ubicaciones.findall('cp31:Ubicacion', ns):
                    tipo = ubi.get('TipoUbicacion')
                    domicilio = ubi.find('cp31:Domicilio', ns)
                    pais = domicilio.get('Pais', '') if domicilio is not None else ''
                    if tipo == 'Origen': pais_origen = pais
                    if tipo == 'Destino': pais_destino = pais
            
            if pais_origen == "MEX" and pais_destino == "USA": row["Movimiento"] = "EXPORTACION"
            elif pais_origen == "USA" and pais_destino == "MEX": row["Movimiento"] = "IMPORTACION"
            else: row["Movimiento"] = "TRANSFER"

            mercancias = cp.find('cp31:Mercancias', ns)
            if mercancias:
                auto = mercancias.find('cp31:Autotransporte', ns)
                if auto:
                    vehiculo = auto.find('cp31:IdentificacionVehicular', ns)
                    if vehiculo:
                        placa = vehiculo.get('PlacaVM', '')
                        row["Placas Detectadas"] = placa
                        if placa in flota_map: row["Camión"] = flota_map[placa]
                        else: row["Camión"] = "" 

        return row
    except: return None

# --- HELPERS ---
def get_tc():
    res = run_query("SELECT valor FROM config WHERE clave='TC'")
    return float(res[0][0]) if res else 20.0

def set_tc(valor): run_query("INSERT OR REPLACE INTO config (clave, valor) VALUES ('TC', ?)", (str(valor),))

def cargar_dataframe(table, date_filter=None):
    is_postgres = check_is_postgres()
    
    if is_postgres:
        query = f"SELECT * FROM {table}"
        if date_filter:
            query += " WHERE fecha = %s ORDER BY rowid DESC"
            params = (date_filter,)
        else:
            query += " ORDER BY fecha DESC, rowid DESC LIMIT 50"
            params = ()
    else:
        query = f"SELECT rowid, * FROM {table}"
        if date_filter:
            query += " WHERE fecha = ? ORDER BY rowid DESC"
            params = (date_filter,)
        else:
            query += " ORDER BY fecha DESC, rowid DESC LIMIT 50"
            params = ()
            
    conn = get_connection()
    df = pd.read_sql_query(query, conn, params=params)
    conn.close()
    
    if 'fecha' in df.columns:
        df['fecha'] = pd.to_datetime(df['fecha'], errors='coerce')
        
    if 'carta_porte' in df.columns:
        df['carta_porte'] = df['carta_porte'].apply(lambda x: x == 'SI' or x is True)
    if 'manifiesto' in df.columns:
        df['manifiesto'] = df['manifiesto'].apply(lambda x: x == 'SI' or x is True)
        
    return df

def smart_save_camion(camion, chofer="", placas="", tipo="TRANSFER"):
    clean_c = ""
    if camion:
        clean_c = camion.strip().upper()
        if clean_c.isdigit(): clean_c = f"F{clean_c}"
        exists = run_query("SELECT 1 FROM camiones WHERE tracto=?", (clean_c,))
        if exists:
            if placas: run_query("UPDATE camiones SET placas=? WHERE tracto=?", (placas.upper(), clean_c))
        else:
            run_query("INSERT INTO camiones (tracto, placas) VALUES (?, ?)", (clean_c, placas.upper()))
            
    if chofer:
        clean_o = chofer.strip().upper()
        exists_o = run_query("SELECT 1 FROM choferes WHERE nombre=?", (clean_o,))
        if exists_o:
            run_query("UPDATE choferes SET tipo=? WHERE nombre=?", (tipo if tipo else 'TRANSFER', clean_o))
        else:
            run_query("INSERT INTO choferes (nombre, tipo) VALUES (?, ?)", (clean_o, tipo if tipo else 'TRANSFER'))
            
    return clean_c

def smart_save_caja(caja):
    if caja:
        clean_c = caja.strip().upper()
        if clean_c != 'N/A' and clean_c != '':
            exists = run_query("SELECT 1 FROM cajas WHERE caja=?", (clean_c,))
            if not exists:
                run_query("INSERT INTO cajas (caja) VALUES (?)", (clean_c,))
            return clean_c
    return ""

def get_cajas_list():
    data = run_query("SELECT caja FROM cajas ORDER BY caja ASC")
    return [row[0] for row in data]

def get_cajas_ocupados_hoy():
    hoy_str = get_local_now().strftime("%Y-%m-%d")
    data = run_query("SELECT DISTINCT caja FROM panel WHERE fecha = ?", (hoy_str,))
    return {row[0].upper() for row in data if row[0]}

def get_camiones_list():
    data = run_query("SELECT tracto FROM camiones ORDER BY tracto ASC")
    return [row[0] for row in data]

def get_camiones_map_placas():
    data = run_query("SELECT placas, tracto FROM camiones WHERE placas IS NOT NULL AND placas != ''")
    return {row[0]: row[1] for row in data}

def get_choferes_list():
    data = run_query("SELECT nombre FROM choferes ORDER BY nombre ASC")
    return [row[0] for row in data]

def get_ocupados_hoy():
    hoy_str = get_local_now().strftime("%Y-%m-%d")
    data = run_query("SELECT DISTINCT operador FROM panel WHERE fecha = ?", (hoy_str,))
    return {row[0].upper() for row in data if row[0]}

def get_camiones_ocupados_hoy():
    hoy_str = get_local_now().strftime("%Y-%m-%d")
    data = run_query("SELECT DISTINCT tracto FROM panel WHERE fecha = ?", (hoy_str,))
    return {row[0].upper() for row in data if row[0]}

def get_last_driver_for_truck(tracto):
    data = run_query("SELECT operador FROM panel WHERE tracto = ? ORDER BY fecha DESC, hora DESC LIMIT 1", (tracto,))
    return data[0][0] if data else ""

def get_flota_list():
    return get_camiones_list()

def get_flota_map_placas():
    return get_camiones_map_placas()

def get_notepad_content():
    data = run_query("SELECT contenido FROM notepad WHERE id=1")
    return data[0][0] if data else ""

def save_notepad_content(content):
    run_query("UPDATE notepad SET contenido = ? WHERE id=1", (content,))

def get_flota_dict():
    data = run_query("SELECT tracto, operador FROM flota ORDER BY tracto ASC")
    return {row[0]: row[1] for row in data}

def generar_excel_perfecto(fecha_filtro):
    output = io.BytesIO()
    if not fecha_filtro: fecha_filtro = get_local_now().strftime("%Y-%m-%d")
    
    df_panel = cargar_dataframe("panel", fecha_filtro).drop(columns=['rowid', 'ip_log', 'status_dia'], errors='ignore').rename(columns={'operador': 'chofer', 'tracto': 'camion'})
    if 'fecha' in df_panel.columns: df_panel['fecha'] = df_panel['fecha'].dt.strftime('%Y-%m-%d')
    if 'carta_porte' in df_panel.columns:
        df_panel['carta_porte'] = df_panel['carta_porte'].map({True: 'SI', False: 'NO'})
    if 'manifiesto' in df_panel.columns:
        df_panel['manifiesto'] = df_panel['manifiesto'].map({True: 'SI', False: 'NO'})
        
    df_gastos = cargar_dataframe("gastos", fecha_filtro).drop(columns=['rowid'], errors='ignore').rename(columns={'operador': 'chofer', 'tracto': 'camion'})
    if 'fecha' in df_gastos.columns: df_gastos['fecha'] = df_gastos['fecha'].dt.strftime('%Y-%m-%d')

    df_boletas = cargar_dataframe("boletas", fecha_filtro).drop(columns=['rowid'], errors='ignore').rename(columns={'operador': 'chofer', 'tracto': 'camion'})
    if 'fecha' in df_boletas.columns: df_boletas['fecha'] = df_boletas['fecha'].dt.strftime('%Y-%m-%d')
    
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df_panel.to_excel(writer, sheet_name='PANEL', index=False)
        df_gastos.to_excel(writer, sheet_name='GASTOS', index=False)
        df_boletas.to_excel(writer, sheet_name='BOLETAS', index=False)
    return output.getvalue()

@st.dialog("🛠️ Registrar Mantenimiento")
def popup_mantenimiento(unidad, millas_actuales):
    st.markdown(f"### 🚛 Unidad: {unidad}")
    st.info(f"📍 **Nuevo Base:** {millas_actuales:,.0f} millas")
    if st.button("✅ Confirmar", type="primary"):
        run_query("UPDATE mantenimiento SET ultimo_servicio_millas=?, fecha_servicio=? WHERE unidad=?", (millas_actuales, get_local_now().strftime("%Y-%m-%d"), unidad))
        st.success("Registrado"); st.rerun()

# --- 0. CHECK MODO TV DIRECTO ---
if "tv" in st.query_params and st.query_params["tv"] == "true":
    st.markdown("""
        <style>
        [data-testid="stHeader"] { display: none !important; }
        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 1.5rem !important;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
            max-width: 98% !important;
        }
        </style>
        """, unsafe_allow_html=True)
    
    is_postgres = check_is_postgres()
    if is_postgres:
        db_status = '<span style="background-color: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; padding: 4px 10px; border-radius: 8px; font-size: 13px; color: #10b981; font-weight: bold; margin-left: 15px; vertical-align: middle;">☁️ BD: Nube</span>'
    else:
        db_status = '<span style="background-color: rgba(239, 68, 68, 0.2); border: 1px solid #ef4444; padding: 4px 10px; border-radius: 8px; font-size: 13px; color: #fca5a5; font-weight: bold; margin-left: 15px; vertical-align: middle;">⚠️ BD: SQLite Temporal</span>'

    c_title, c_date, c_refresh = st.columns([5, 3, 2])
    with c_title:
        st.markdown(f"<h2 style='margin:0; padding:0; color:#e2e8f0;'>📺 OTD Freight <span style='color:#10b981; font-size:16px; font-weight:bold; animation: blink 1.5s infinite;'>● EN VIVO</span> {db_status}</h2><style>@keyframes blink {{ 0% {{ opacity: 0.3; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.3; }} }}</style>", unsafe_allow_html=True)

    if st.session_state.get("db_connection_error"):
        st.error(f"⚠️ **Error conexión BD Nube:** {st.session_state.db_connection_error}")
    with c_date:
        tv_fecha = st.date_input("📅 Fecha Proyectada", value=get_local_now(), key="tv_only_fecha_input")
        tv_fecha_str = tv_fecha.strftime("%Y-%m-%d")
    with c_refresh:
        refresh_rate = st.selectbox("🔄 Auto-refresco", ["30 segundos", "1 minuto", "5 minutos", "Desactivado"], index=0, key="tv_only_refresh_rate")
        refresh_seconds = 30
        if refresh_rate == "1 minuto": refresh_seconds = 60
        elif refresh_rate == "5 minutos": refresh_seconds = 300
        elif refresh_rate == "Desactivado": refresh_seconds = None

    tab_tv_viajes, tab_tv_dispo = st.tabs(["📋 VIAJES DEL DÍA", "📊 DISPONIBILIDAD FLOTA"])
    
    with tab_tv_viajes:
        @st.fragment(run_every=refresh_seconds)
        def render_tv_only_layout(fecha_filtro):
            df_tv = cargar_dataframe("panel", fecha_filtro).rename(columns={'operador': 'chofer', 'tracto': 'camion'})
            if not df_tv.empty:
                st.markdown(
                    """
                    <div style="background: rgba(255, 255, 255, 0.05); color: #94a3b8; padding: 12px 18px; border-radius: 12px; display: flex; align-items: center; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.1); margin-bottom: 10px; font-size: 15px;">
                        <div style="flex: 0.8;">HORA</div>
                        <div style="flex: 1.5;">MOVIMIENTO</div>
                        <div style="flex: 0.8;">CLIENTE</div>
                        <div style="flex: 1.8;">FOLIO / FACTURA</div>
                        <div style="flex: 2.5;">CHOFER</div>
                        <div style="flex: 0.8;">CAMIÓN</div>
                        <div style="flex: 0.8;">CAJA</div>
                        <div style="flex: 2.2;">DESTINO</div>
                        <div style="flex: 1.2; text-align: center;">DOCS</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                for idx, row in df_tv.iterrows():
                    mov = str(row['movimiento']).upper()
                    
                    if "EXPORTACION" in mov:
                        bg_color, text_color, border_color = "rgba(59, 130, 246, 0.15)", "#93c5fd", "rgba(59, 130, 246, 0.35)"
                    elif "IMPORTACION" in mov:
                        bg_color, text_color, border_color = "rgba(16, 185, 129, 0.15)", "#6ee7b7", "rgba(16, 185, 129, 0.35)"
                    elif "TARIMAS" in mov:
                        bg_color, text_color, border_color = "rgba(245, 158, 11, 0.15)", "#fcd34d", "rgba(245, 158, 11, 0.35)"
                    else: # TRANSFER
                        bg_color, text_color, border_color = "rgba(139, 92, 246, 0.15)", "#c084fc", "rgba(139, 92, 246, 0.35)"
                    
                    folio = str(row['folio_cp']) if row['folio_cp'] else ""
                    factura = str(row['factura']) if row['factura'] else ""
                    if folio and factura:
                        folio_factura = f"{folio} / {factura}"
                    else:
                        folio_factura = folio or factura or "-"
                    
                    cp_badge = "<span style='background: rgba(16, 185, 129, 0.25); border: 1px solid rgba(16, 185, 129, 0.45); padding: 2px 6px; border-radius: 4px; font-size: 11px; color:#6ee7b7; font-weight:bold; margin-right:4px;'>📄 CP</span>" if row['carta_porte'] else ""
                    man_badge = "<span style='background: rgba(16, 185, 129, 0.25); border: 1px solid rgba(16, 185, 129, 0.45); padding: 2px 6px; border-radius: 4px; font-size: 11px; color:#6ee7b7; font-weight:bold;'>📋 MAN</span>" if row['manifiesto'] else ""
                    docs_badges = f"{cp_badge} {man_badge}".strip() if (cp_badge or man_badge) else "<span style='color: #64748b; font-size:13px;'>-</span>"
                    
                    st.markdown(
                        f"""
                        <div style="background-color: {bg_color}; color: {text_color}; padding: 16px 20px; border-radius: 12px; border: 1px solid {border_color}; display: flex; align-items: center; min-height: 56px; margin-bottom: 10px; font-size: 16px;">
                            <div style="flex: 0.8; font-weight: 500;">{row['hora']}</div>
                            <div style="flex: 1.5; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">{mov}</div>
                            <div style="flex: 0.8; font-weight: 600;">{row['cliente']}</div>
                            <div style="flex: 1.8; font-family: monospace; font-size: 15px;">{folio_factura}</div>
                            <div style="flex: 2.5; font-weight: 600; text-transform: uppercase;">{row['chofer']}</div>
                            <div style="flex: 0.8; font-weight: bold;">{row['camion']}</div>
                            <div style="flex: 0.8; font-weight: bold;">{row['caja']}</div>
                            <div style="flex: 2.2; font-size: 15px;">{row['destino'] or ''}</div>
                            <div style="flex: 1.2; display: flex; gap: 4px; justify-content: center; align-items: center;">{docs_badges}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                st.caption(f"Última actualización automática: {get_local_now().strftime('%H:%M:%S')}")
            else:
                st.info(f"No hay registros de viajes para el {fecha_filtro}.")
                
        render_tv_only_layout(tv_fecha_str)

    with tab_tv_dispo:
        @st.fragment(run_every=refresh_seconds)
        def render_tv_disponibilidad():
            col1, col2, col3 = st.columns(3)
            
            # 1. Choferes
            with col1:
                st.markdown("#### 👥 Choferes")
                df_ch = pd.read_sql_query("SELECT nombre, tipo, disponible FROM choferes ORDER BY nombre ASC", get_connection())
                ocupados = get_ocupados_hoy()
                if df_ch.empty:
                    st.info("No hay choferes registrados.")
                else:
                    for idx, row in df_ch.iterrows():
                        name = row['nombre']
                        disp = row['disponible']
                        
                        if name and name.upper() in ocupados:
                            bg, txt, border = "rgba(239, 68, 68, 0.15)", "#fca5a5", "rgba(239, 68, 68, 0.35)"
                            badge = "🔴 EN VIAJE"
                        elif disp == 'NO':
                            bg, txt, border = "rgba(245, 158, 11, 0.15)", "#fcd34d", "rgba(245, 158, 11, 0.35)"
                            badge = "🟡 NO DISPONIBLE"
                        else:
                            bg, txt, border = "rgba(16, 185, 129, 0.15)", "#6ee7b7", "rgba(16, 185, 129, 0.35)"
                            badge = "🟢 DISPONIBLE"
                            
                        cc_card, cc_btn = st.columns([3.5, 1.5])
                        with cc_card:
                            st.markdown(f"""
                            <div style="background-color: {bg}; color: {txt}; padding: 12px 15px; border-radius: 10px; border: 1px solid {border}; display: flex; flex-direction: column; justify-content: center; min-height: 48px; margin-bottom: 8px;">
                                <div style="font-weight: 700; text-transform: uppercase; font-size:14px;">{name}</div>
                                <div style="font-size: 11px; font-weight: bold; opacity: 0.9; margin-top:2px;">{badge} ({row['tipo']})</div>
                            </div>
                            """, unsafe_allow_html=True)
                        with cc_btn:
                            btn_lbl = "🔴 Desact." if disp == 'SI' else "🟢 Activar"
                            if st.button(btn_lbl, key=f"tv_toggle_chof_{name}", use_container_width=True):
                                new_disp = 'NO' if disp == 'SI' else 'SI'
                                run_query("UPDATE choferes SET disponible = ? WHERE nombre = ?", (new_disp, name))
                                st.rerun()

            # 2. Camiones
            with col2:
                st.markdown("#### 🚛 Camiones")
                df_cam = pd.read_sql_query("SELECT tracto, placas, disponible FROM camiones ORDER BY tracto ASC", get_connection())
                camiones_ocupados = get_camiones_ocupados_hoy()
                if df_cam.empty:
                    st.info("No hay camiones registrados.")
                else:
                    for idx, row in df_cam.iterrows():
                        tracto = row['tracto']
                        placas = row['placas'] or ''
                        disp = row['disponible']
                        
                        if tracto and tracto.upper() in camiones_ocupados:
                            bg, txt, border = "rgba(239, 68, 68, 0.15)", "#fca5a5", "rgba(239, 68, 68, 0.35)"
                            badge = "🔴 EN VIAJE"
                        elif disp == 'NO':
                            bg, txt, border = "rgba(245, 158, 11, 0.15)", "#fcd34d", "rgba(245, 158, 11, 0.35)"
                            badge = "🟡 NO DISPONIBLE"
                        else:
                            bg, txt, border = "rgba(16, 185, 129, 0.15)", "#6ee7b7", "rgba(16, 185, 129, 0.35)"
                            badge = "🟢 DISPONIBLE"
                            
                        cc_card, cc_btn = st.columns([3.5, 1.5])
                        with cc_card:
                            st.markdown(f"""
                            <div style="background-color: {bg}; color: {txt}; padding: 12px 15px; border-radius: 10px; border: 1px solid {border}; display: flex; flex-direction: column; justify-content: center; min-height: 48px; margin-bottom: 8px;">
                                <div style="font-weight: 700; text-transform: uppercase; font-size:14px;">{tracto}</div>
                                <div style="font-size: 11px; font-weight: bold; opacity: 0.9; margin-top:2px;">{badge} {f'({placas})' if placas else ''}</div>
                            </div>
                            """, unsafe_allow_html=True)
                        with cc_btn:
                            btn_lbl = "🔴 Desact." if disp == 'SI' else "🟢 Activar"
                            if st.button(btn_lbl, key=f"tv_toggle_cam_{tracto}", use_container_width=True):
                                new_disp = 'NO' if disp == 'SI' else 'SI'
                                run_query("UPDATE camiones SET disponible = ? WHERE tracto = ?", (new_disp, tracto))
                                st.rerun()

            # 3. Cajas
            with col3:
                st.markdown("#### 📦 Cajas")
                df_cj = pd.read_sql_query("SELECT caja, disponible FROM cajas ORDER BY caja ASC", get_connection())
                cajas_ocupadas = get_cajas_ocupados_hoy()
                if df_cj.empty:
                    st.info("No hay cajas registradas.")
                else:
                    for idx, row in df_cj.iterrows():
                        caja = row['caja']
                        disp = row['disponible']
                        
                        if caja and caja.upper() in cajas_ocupadas:
                            bg, txt, border = "rgba(239, 68, 68, 0.15)", "#fca5a5", "rgba(239, 68, 68, 0.35)"
                            badge = "🔴 EN VIAJE"
                        elif disp == 'NO':
                            bg, txt, border = "rgba(245, 158, 11, 0.15)", "#fcd34d", "rgba(245, 158, 11, 0.35)"
                            badge = "🟡 NO DISPONIBLE"
                        else:
                            bg, txt, border = "rgba(16, 185, 129, 0.15)", "#6ee7b7", "rgba(16, 185, 129, 0.35)"
                            badge = "🟢 DISPONIBLE"
                            
                        cc_card, cc_btn = st.columns([3.5, 1.5])
                        with cc_card:
                            st.markdown(f"""
                            <div style="background-color: {bg}; color: {txt}; padding: 12px 15px; border-radius: 10px; border: 1px solid {border}; display: flex; flex-direction: column; justify-content: center; min-height: 48px; margin-bottom: 8px;">
                                <div style="font-weight: 700; text-transform: uppercase; font-size:14px;">{caja}</div>
                                <div style="font-size: 11px; font-weight: bold; opacity: 0.9; margin-top:2px;">{badge}</div>
                            </div>
                            """, unsafe_allow_html=True)
                        with cc_btn:
                            btn_lbl = "🔴 Desact." if disp == 'SI' else "🟢 Activar"
                            if st.button(btn_lbl, key=f"tv_toggle_cj_{caja}", use_container_width=True):
                                new_disp = 'NO' if disp == 'SI' else 'SI'
                                run_query("UPDATE cajas SET disponible = ? WHERE caja = ?", (new_disp, caja))
                                st.rerun()
        render_tv_disponibilidad()
    
    st.stop()

# --- NAVBAR ---
logo_b64 = get_image_base64(LOGO_FILE); logo_html = f'<img src="{logo_b64}" style="height:35px;">' if logo_b64 else "🚛 "
is_postgres = check_is_postgres()
if is_postgres:
    db_status = '<span style="background-color: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; padding: 4px 10px; border-radius: 8px; font-size: 13px; color: #10b981; font-weight: bold; margin-left: 15px;">☁️ BD: Nube (Postgres)</span>'
else:
    db_status = '<span style="background-color: rgba(239, 68, 68, 0.2); border: 1px solid #ef4444; padding: 4px 10px; border-radius: 8px; font-size: 13px; color: #fca5a5; font-weight: bold; margin-left: 15px;">⚠️ BD: Local Temporal (SQLite) - ¡Los datos se borrarán al reiniciar!</span>'
st.markdown(f'<div class="top-nav"><div>{logo_html} OTD FREIGHT {db_status}</div><div>{APP_VERSION}</div></div>', unsafe_allow_html=True)

if st.session_state.get("db_connection_error"):
    st.error(f"❌ **Error al conectar a PostgreSQL (Base de Datos en la Nube):**\n\n`{st.session_state.db_connection_error}`\n\nEl sistema se ha redirigido a la base de datos local **SQLite** temporal. **ATENCIÓN:** Para evitar pérdidas accidentales de información, la escritura, inserción y edición de registros ha sido deshabilitada de forma temporal hasta que se restablezca la conexión con la nube.")
    if st.button("🔄 Intentar Reconectar a la Nube (PostgreSQL)"):
        st.session_state.use_postgres_fallback = False
        st.session_state.db_connection_error = None
        try:
            get_postgres_pool.clear()
        except:
            pass
        st.rerun()

# --- NAVEGACION ---
c1, c2, c3, c4 = st.columns(4)
if c1.button("🚛 OPERACIONES", use_container_width=True): st.session_state.menu_actual = "OPERACIONES"; st.rerun()
if c2.button("🚨 VENCIMIENTOS", use_container_width=True): st.session_state.menu_actual = "VENCIMIENTOS"; st.rerun()
if c3.button("🔧 MANTENIMIENTO", use_container_width=True): st.session_state.menu_actual = "MANTENIMIENTO"; st.rerun()
if c4.button("📺 MODO TV", use_container_width=True): st.session_state.menu_actual = "MODO_TV"; st.rerun()

# ==============================================================================
# 6. MÓDULO OPERACIONES
# ==============================================================================
if st.session_state.menu_actual == "OPERACIONES":
    with st.expander("📝 Bloc de Notas", expanded=False):
        note_content = st.text_area("...", value=get_notepad_content(), height=80, key="notepad_area")
        if st.button("💾 Guardar Nota"): save_notepad_content(note_content); st.toast("Guardado")

    col_stats, col_actions = st.columns([3, 1])
    with col_stats:
        c1, c2, c3 = st.columns(3)
        with c1: 
            fecha_dt = st.date_input("📅 Fecha", get_local_now())
            fecha_str = fecha_dt.strftime("%Y-%m-%d")
        with c2:
            tc_val = st.number_input("💲 TC (MXN)", value=get_tc(), step=0.1)
            if tc_val != get_tc(): set_tc(tc_val)
        
        df_dia = cargar_dataframe("panel", fecha_str)
        with c3: st.metric("Viajes (Fecha)", len(df_dia))
    
    with col_actions:
        st.write("") 
        excel_data = generar_excel_perfecto(fecha_str)
        st.download_button("📥 BAJAR EXCEL", data=excel_data, file_name=f"OTD_{fecha_str}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True, type="primary")
        
        # Botón para abrir el Modo TV en una pestaña nueva
        st.markdown(
            """
            <a href="?tv=true" target="_blank" style="text-decoration: none;">
                <button style="width: 100%; padding: 10px; border-radius: 10px; font-weight: 600; background: linear-gradient(135deg, #1d4ed8 0%, #3b82f6 100%); color: white; border: none; cursor: pointer; margin-top: 8px;">
                    📺 PROYECTAR EN TV
                </button>
            </a>
            """,
            unsafe_allow_html=True
        )

    tab1, tab_xml, tab2, tab3, tab4, tab_hist_viajes = st.tabs(["📝 MANUAL", "📂 CARGA XML", "📊 DATA DEL DÍA (EDITABLE)", "📑 BOLETAS", "🚛 CHOFERES", "🏆 HISTORIAL VIAJES"])
    
    # ------------------ REGISTRO MANUAL ------------------
    with tab1:
        flota_dict = get_flota_dict()
        def aplicar_carga_rapida():
            sel = st.session_state.quick_op
            if sel:
                st.session_state.k_tracto = sel
                last_driver = get_last_driver_for_truck(sel)
                if last_driver:
                    st.session_state.k_operador = last_driver
        
        st.selectbox("⚡ Carga Rápida", options=[""] + get_camiones_list(), key="quick_op", on_change=aplicar_carga_rapida)
        c_a, c_b = st.columns(2)
        with c_a: st.selectbox("Movimiento", ["EXPORTACION", "IMPORTACION", "RECOLECCION TARIMAS"], key="k_mov")
        with c_b: st.selectbox("Cliente", ["VDO", "Kwalu"], key="k_cli")
        st.radio("Estado", ["CARGADO", "VACIO", "MOSCO"], horizontal=True, key="k_est")
        
        c1, c2, c3 = st.columns(3)
        op_list = get_choferes_list()
        op = c1.selectbox("Chofer", options=[""] + op_list, key="k_operador")
        tr = c2.selectbox("Camión", options=[""] + get_camiones_list(), key="k_tracto")
        caj = c3.selectbox("Caja", options=[""] + get_cajas_list(), key="k_caja", disabled=(st.session_state.k_est == "MOSCO"))
        
        c4, c5, c6 = st.columns(3)
        fac = c4.text_input("Factura", key="k_factura")
        fol = c5.text_input("Carta Porte", key="k_folio")
        with c6: st.write(""); basc = st.checkbox("Báscula", key="k_bascula")

        st.markdown("##### 📄 Documentación y Destino")
        c7, c8, c_dest = st.columns([1, 1, 2])
        with c7: st.write(""); cp_check = st.checkbox("Carta Porte", key="k_carta_porte")
        with c8: st.write(""); man_check = st.checkbox("Manifiesto", key="k_manifiesto")
        dest = c_dest.text_input("Destino", key="k_destino")

        if st.button("💾 REGISTRAR MANUAL", type="primary", use_container_width=True):
            caj_final = "N/A" if st.session_state.k_est == "MOSCO" else (caj.upper() if caj else "")
            base = 55 if st.session_state.k_mov == "RECOLECCION TARIMAS" else (135 if st.session_state.k_cli=="VDO" else 100)
            moneda = "USD" if st.session_state.k_cli == "Kwalu" or st.session_state.k_mov == "RECOLECCION TARIMAS" else "MXN"
            if moneda == "MXN": total = (base * tc_val + (15*tc_val if basc else 0)) * 1.12
            else: total = base + (15 if basc else 0)
            
            hora_actual = get_local_now().strftime("%H:%M:%S")
            cp_val = "SI" if st.session_state.k_carta_porte else "NO"
            man_val = "SI" if st.session_state.k_manifiesto else "NO"
            run_query("""
                INSERT INTO panel (
                    fecha, movimiento, cliente, operador, tracto, caja, 
                    factura, folio_cp, bascula, costo_final, moneda, 
                    ip_log, status_dia, ups, profepa, hora, carta_porte, manifiesto, destino
                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            """, (
                fecha_str, st.session_state.k_mov, st.session_state.k_cli, 
                op.upper(), tr.upper(), caj_final, fac.upper(), fol.upper(), 
                "SI" if basc else "NO", total, moneda, "MANUAL", 
                "CONFIRMADO", "NO", "NO", hora_actual, cp_val, man_val, dest.upper()
            ))
            
            mon_g = "USD" if st.session_state.k_mov == "IMPORTACION" else "MXN"
            c_g = (19.25 if st.session_state.k_est=="CARGADO" else 13) if st.session_state.k_mov=="IMPORTACION" else (196 if st.session_state.k_est=="CARGADO" else 95)
            run_query("INSERT INTO gastos VALUES (?,?,?,?,?,?,?,?)", (fecha_str, fac.upper(), tr.upper(), caj_final, st.session_state.k_est, op.upper(), c_g, mon_g))
            
            mc = "TARIMAS" if st.session_state.k_mov=="RECOLECCION TARIMAS" else ("EXPO" if st.session_state.k_mov=="EXPORTACION" else ("IMPO" if st.session_state.k_mov=="IMPORTACION" else "VACIA"))
            run_query("INSERT INTO boletas VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", (fecha_str, mc, f"{mc} {fac.upper()}", tr.upper(), caj_final, "", "", op.upper(), "", fol.upper(), "", ""))
            smart_save_camion(tr, op)
            smart_save_caja(caj_final)
            st.toast("✅ Registrado Correctamente"); st.rerun()

    # ------------------ CARGA XML ------------------
    with tab_xml:
        st.info("Arrastra los XMLs.")
        uploaded_files = st.file_uploader("Subir CFDI Carta Porte", type=["xml"], accept_multiple_files=True)
        
        if uploaded_files:
            if "xml_cache" not in st.session_state: st.session_state.xml_cache = []
            
            if st.button(f"⚡ PROCESAR {len(uploaded_files)} ARCHIVOS"):
                temp_data = []
                flota_map = get_flota_map_placas() 
                for f in uploaded_files:
                    data = parse_cfdi_xml(f, flota_map)
                    if data: temp_data.append(data)
                st.session_state.xml_cache = temp_data

            if st.session_state.get("xml_cache"):
                st.markdown("##### 📝 Revisión y Edición antes de Guardar")
                df_xml = pd.DataFrame(st.session_state.xml_cache)
                all_tractos = [""] + get_camiones_list()
                
                edited_xml = st.data_editor(
                    df_xml,
                    column_config={
                        "Camión": st.column_config.SelectboxColumn("Camión (Link)", options=all_tractos, required=True),
                        "Chofer": st.column_config.SelectboxColumn("Chofer", options=[""] + get_choferes_list()),
                        "Caja": st.column_config.SelectboxColumn("Caja", options=[""] + get_cajas_list()),
                        "Movimiento": st.column_config.SelectboxColumn("Movimiento", options=["IMPORTACION", "EXPORTACION", "RECOLECCION TARIMAS", "TRANSFER"]),
                        "Báscula": st.column_config.CheckboxColumn("⚖️ Báscula", default=False),
                        "UPS": st.column_config.CheckboxColumn("📦 UPS (Info)", default=False),
                        "Tarimas": st.column_config.CheckboxColumn("🪵 Tarimas", default=False),
                        "Profepa": st.column_config.CheckboxColumn("🌲 PROFEPA", default=False),
                        "Folio CP": st.column_config.TextColumn("Folio (XML)", disabled=True),
                        "Factura": st.column_config.TextColumn("Factura (Manual)", required=True),
                        "Es Gasto": st.column_config.CheckboxColumn("Es Gasto", disabled=True),
                        "Fecha": st.column_config.TextColumn("Fecha XML", disabled=True),
                        "carta_porte": st.column_config.CheckboxColumn("📄 Carta Porte", default=False),
                        "manifiesto": st.column_config.CheckboxColumn("📋 Manifiesto", default=False),
                    },
                    hide_index=True, num_rows="fixed", use_container_width=True
                )
                
                col_save, col_clear = st.columns([1,4])
                
                if col_save.button("💾 GUARDAR OPERACIONES", type="primary"):
                    c_ops, c_gas = 0, 0
                    fechas_afectadas = set()
                    hora_actual = get_local_now().strftime("%H:%M:%S")
                    
                    for idx, row in edited_xml.iterrows():
                        fechas_afectadas.add(row['Fecha'])
                        if row['Es Gasto']:
                            run_query("INSERT INTO gastos VALUES (?,?,?,?,?,?,?,?)", 
                                     (row['Fecha'], row['Factura'], row['Camión'], "N/A", "N/A", "PROVEEDOR", row['Total XML'], row['Moneda']))
                            c_gas += 1
                        else:
                            mov_final = "RECOLECCION TARIMAS" if row['Tarimas'] else row['Movimiento']
                            costo_op = 0
                            if row['Cliente'] == "VDO":
                                sub_mxn = 135 * tc_val
                                costo_op = sub_mxn * 1.12 if row['Movimiento'] == "IMPORTACION" else sub_mxn
                            elif row['Cliente'] == "Kwalu":
                                costo_op = 55 if row['Tarimas'] else 100
                            
                            moneda_db = "USD" if row['Cliente'] == "Kwalu" else "MXN"
                            
                            cp_val = "SI" if row.get('carta_porte') else "NO"
                            man_val = "SI" if row.get('manifiesto') else "NO"
                            
                            run_query("""
                                INSERT INTO panel (
                                    fecha, movimiento, cliente, operador, tracto, caja, 
                                    factura, folio_cp, bascula, costo_final, moneda, 
                                    ip_log, status_dia, ups, profepa, hora, carta_porte, manifiesto, destino
                                ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                            """, (
                                row['Fecha'], mov_final, row['Cliente'], row['Chofer'], 
                                row['Camión'], row['Caja'], row['Factura'], row['Folio CP'], 
                                "SI" if row['Báscula'] else "NO", costo_op, moneda_db, "XML-AUTO", "CONFIRMADO", 
                                "SI" if row['UPS'] else "NO",
                                "SI" if row['Profepa'] else "NO", hora_actual, cp_val, man_val, ""
                            )) 
                            c_ops += 1
                            
                            mon_g = "USD" if row['Movimiento'] == "IMPORTACION" else "MXN"
                            c_g = (19.25 if row['Movimiento']=="IMPORTACION" else 196)
                            run_query("INSERT INTO gastos VALUES (?,?,?,?,?,?,?,?)", 
                                      (row['Fecha'], row['Factura'], row['Camión'], row['Caja'], "CARGADO", row['Chofer'], c_g, mon_g))

                        if row['Camión'] and row['Placas Detectadas']:
                            smart_save_camion(row['Camión'], row['Chofer'], row['Placas Detectadas'])
                        if row.get('Caja'):
                            smart_save_caja(row['Caja'])

                    st.session_state.xml_cache = []
                    st.balloons()
                    msg_fechas = ", ".join(list(fechas_afectadas))
                    st.success(f"✅ Guardado. Fechas: {msg_fechas}.")
                    time.sleep(3); st.rerun()

                if col_clear.button("❌ Limpiar"):
                    st.session_state.xml_cache = []
                    st.rerun()

    # ------------------ DATA DEL DIA (EDITABLE) ------------------
    with tab2:
        c_filter, c_view, c_void = st.columns([2, 2, 2])
        with c_filter:
            show_all = st.checkbox("🔄 Ver Todo el Historial (Últimos 50)", value=False)
        with c_view:
            vista_tipo = st.radio("👁️ Vista", ["🎴 Tarjetas", "📝 Tabla Editable"], horizontal=True, key="main_view_type_radio")
        
        if show_all:
            df_full = cargar_dataframe("panel", None).rename(columns={'operador': 'chofer', 'tracto': 'camion'})
            st.caption("Mostrando últimos 50 registros (Cualquier fecha)")
        else:
            df_full = cargar_dataframe("panel", fecha_str).rename(columns={'operador': 'chofer', 'tracto': 'camion'})
            st.caption(f"Mostrando registros del {fecha_str}")

        if not df_full.empty:
            if vista_tipo == "🎴 Tarjetas":
                # Render Cabecera de Tarjetas
                st.markdown(
                    """
                    <div style="background: rgba(255, 255, 255, 0.05); color: #94a3b8; padding: 10px 15px; border-radius: 10px; display: flex; align-items: center; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.1); margin-bottom: 8px; font-size: 13px;">
                        <div style="flex: 1.2;">HORA / FECHA</div>
                        <div style="flex: 1.5;">MOVIMIENTO</div>
                        <div style="flex: 0.8;">CLIENTE</div>
                        <div style="flex: 1.8;">FOLIO / FACTURA</div>
                        <div style="flex: 2.2;">CHOFER</div>
                        <div style="flex: 0.8;">CAMIÓN</div>
                        <div style="flex: 0.8;">CAJA</div>
                        <div style="flex: 2.2;">DESTINO</div>
                        <div style="flex: 1.2; text-align: center;">DOCS</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                for idx, row in df_full.iterrows():
                    mov = str(row['movimiento']).upper()
                    
                    # Asignar tema de color según el movimiento
                    if "EXPORTACION" in mov:
                        bg_color, text_color, border_color = "rgba(59, 130, 246, 0.12)", "#93c5fd", "rgba(59, 130, 246, 0.3)"
                    elif "IMPORTACION" in mov:
                        bg_color, text_color, border_color = "rgba(16, 185, 129, 0.12)", "#6ee7b7", "rgba(16, 185, 129, 0.3)"
                    elif "TARIMAS" in mov:
                        bg_color, text_color, border_color = "rgba(245, 158, 11, 0.12)", "#fcd34d", "rgba(245, 158, 11, 0.3)"
                    else: # TRANSFER
                        bg_color, text_color, border_color = "rgba(139, 92, 246, 0.12)", "#c084fc", "rgba(139, 92, 246, 0.3)"
                    
                    # Formatear fecha y hora
                    time_str = str(row['hora'])
                    if show_all and pd.notnull(row['fecha']):
                        time_str = f"{row['fecha'].strftime('%m-%d')} {time_str}"
                    
                    # Combinar Folio y Factura
                    folio = str(row['folio_cp']) if row['folio_cp'] else ""
                    factura = str(row['factura']) if row['factura'] else ""
                    if folio and factura:
                        folio_factura = f"{folio} / {factura}"
                    else:
                        folio_factura = folio or factura or "-"
                    
                    # Badges de documentos
                    cp_val = row.get('carta_porte', False)
                    man_val = row.get('manifiesto', False)
                    
                    cp_badge = "<span style='background: rgba(16, 185, 129, 0.2); border: 1px solid rgba(16, 185, 129, 0.4); padding: 2px 5px; border-radius: 4px; font-size: 11px; color:#6ee7b7; font-weight:bold;'>📄 CP</span>" if cp_val else ""
                    man_badge = "<span style='background: rgba(16, 185, 129, 0.2); border: 1px solid rgba(16, 185, 129, 0.4); padding: 2px 5px; border-radius: 4px; font-size: 11px; color:#6ee7b7; font-weight:bold;'>📋 MAN</span>" if man_val else ""
                    docs_badges = f"{cp_badge} {man_badge}".strip() if (cp_badge or man_badge) else "<span style='color: #64748b; font-size:12px;'>-</span>"
                    
                    st.markdown(
                        f"""
                        <div style="background-color: {bg_color}; color: {text_color}; padding: 12px 15px; border-radius: 10px; border: 1px solid {border_color}; display: flex; align-items: center; min-height: 48px; margin-bottom: 8px; font-size: 14px;">
                            <div style="flex: 1.2; font-weight: 500;">{time_str}</div>
                            <div style="flex: 1.5; font-weight: bold; text-transform: uppercase;">{mov}</div>
                            <div style="flex: 0.8; font-weight: 600;">{row['cliente']}</div>
                            <div style="flex: 1.8; font-family: monospace; font-size: 13px;">{folio_factura}</div>
                            <div style="flex: 2.2; font-weight: 600;">{row['chofer']}</div>
                            <div style="flex: 0.8; font-weight: bold;">{row['camion']}</div>
                            <div style="flex: 0.8; font-weight: bold;">{row['caja']}</div>
                            <div style="flex: 2.2; font-size: 13px;">{row['destino'] or ''}</div>
                            <div style="flex: 1.2; display: flex; gap: 4px; justify-content: center; align-items: center;">{docs_badges}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
            
            else: # Tabla Editable
                df_editor = df_full.drop(columns=['ip_log', 'status_dia'], errors='ignore')
                
                # Reorder columns as requested by the user
                ordered_cols = ['rowid', 'fecha', 'hora', 'movimiento', 'cliente', 'folio_cp', 'factura', 'bascula', 'costo_final', 'moneda', 'ups', 'profepa', 'carta_porte', 'manifiesto', 'chofer', 'camion', 'caja', 'destino']
                ordered_cols = [c for c in ordered_cols if c in df_editor.columns]
                df_editor = df_editor[ordered_cols]
                
                # Define column configurations with optimized compact widths
                cols_options = {
                    "fecha": ("Fecha", st.column_config.DateColumn("Fecha", width=85)),
                    "hora": ("Hora", st.column_config.TextColumn("Hora", disabled=True, width=70)),
                    "movimiento": ("Movimiento", st.column_config.SelectboxColumn("Movimiento", options=["IMPORTACION", "EXPORTACION", "RECOLECCION TARIMAS", "TRANSFER"], width=105)),
                    "cliente": ("Cliente", st.column_config.TextColumn("Cliente", width=70)),
                    "folio_cp": ("Folio", st.column_config.TextColumn("Folio", width=80)),
                    "factura": ("Factura", st.column_config.TextColumn("Factura", width=80)),
                    "bascula": ("Báscula", st.column_config.SelectboxColumn("Báscula", options=["SI", "NO"], width=65)),
                    "costo_final": ("Costo Final", st.column_config.NumberColumn("Costo Final", format="$%.2f", width=85)),
                    "moneda": ("Moneda", st.column_config.TextColumn("Moneda", width=65)),
                    "ups": ("UPS", st.column_config.SelectboxColumn("UPS", options=["SI", "NO"], width=55)),
                    "profepa": ("PROFEPA", st.column_config.SelectboxColumn("PROFEPA", options=["SI", "NO"], width=55)),
                    "carta_porte": ("📄 CP", st.column_config.CheckboxColumn("📄 CP", default=False, width=50)),
                    "manifiesto": ("📋 Man", st.column_config.CheckboxColumn("📋 Man", default=False, width=50)),
                    "chofer": ("Chofer", st.column_config.SelectboxColumn("Chofer", options=[""] + get_choferes_list(), width=140)),
                    "camion": ("Camión", st.column_config.SelectboxColumn("Camión", options=[""] + get_camiones_list(), width=65)),
                    "caja": ("Caja", st.column_config.SelectboxColumn("Caja", options=[""] + get_cajas_list(), width=65)),
                    "destino": ("Destino", st.column_config.TextColumn("Destino", width=120)),
                }
                
                c_tv, c_cols = st.columns([1, 2])
                with c_tv:
                    ajustar_tv = st.checkbox("📺 Ajustar para Proyección / TV (Ocultar secundarias)", value=False)
                
                cols_default = list(cols_options.keys())
                if ajustar_tv:
                    # Ocultar columnas secundarias para que quepa perfectamente
                    cols_default = [c for c in cols_default if c not in ["ups", "profepa", "bascula", "moneda", "carta_porte", "manifiesto"]]
                    
                with c_cols:
                    cols_to_show = st.multiselect(
                        "👁️ Seleccionar Columnas a Mostrar",
                        options=list(cols_options.keys()),
                        default=cols_default,
                        format_func=lambda x: cols_options[x][0]
                    )
                
                # Build column config mapping based on selections
                config_dict = {"rowid": None}
                for col_name, (label, col_obj) in cols_options.items():
                    if col_name in cols_to_show:
                        config_dict[col_name] = col_obj
                    else:
                        config_dict[col_name] = None
                
                edited_df = st.data_editor(
                    df_editor,
                    column_config=config_dict,
                    use_container_width=True,
                    num_rows="dynamic",
                    hide_index=True, 
                    key="data_editor_main"
                )
                
                if st.button("💾 GUARDAR CAMBIOS TABLA", type="primary"):
                    try:
                        for idx, row in edited_df.iterrows():
                            rid = row['rowid']
                            f_val = row['fecha']
                            if isinstance(f_val, pd.Timestamp) or isinstance(f_val, date): f_val = str(f_val)
                            
                            run_query("""
                                UPDATE panel SET 
                                fecha=?, movimiento=?, cliente=?, operador=?, tracto=?, caja=?, 
                                factura=?, folio_cp=?, bascula=?, costo_final=?, moneda=?, ups=?, profepa=?, hora=?, carta_porte=?, manifiesto=?, destino=?
                                WHERE rowid=?
                            """, (
                                f_val, row['movimiento'], row['cliente'], row['chofer'], 
                                row['camion'], row['caja'], row['factura'], row['folio_cp'],  
                                row['bascula'], row['costo_final'], row['moneda'], row.get('ups','NO'), row.get('profepa', 'NO'),
                                row.get('hora', ''),
                                "SI" if row.get('carta_porte') else "NO",
                                "SI" if row.get('manifiesto') else "NO",
                                row.get('destino', ''),
                                rid
                            ))
                        st.success("✅ Datos actualizados correctamente.")
                        time.sleep(1); st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar: {e}")
            
            st.markdown("---")
            if st.checkbox("🗑️ Habilitar Borrado"):
                ids_disponibles = df_full['rowid'].tolist()
                id_borrar = st.selectbox("Seleccionar ID para eliminar definitivamente:", ids_disponibles)
                
                st.warning(f"⚠️ ¿Estás seguro de que deseas eliminar definitivamente el registro con ID {id_borrar}?")
                if st.button("CONFIRMAR BORRADO", type="secondary", key="btn_confirmar_borrado_panel"):
                    try:
                        rec = run_query(f"SELECT factura, fecha FROM panel WHERE rowid={id_borrar}")
                        if rec:
                            factura_del, fecha_del = rec[0]
                            run_query(f"DELETE FROM panel WHERE rowid={id_borrar}")
                            if factura_del:
                                run_query("DELETE FROM gastos WHERE factura=? AND fecha=?", (factura_del, fecha_del))
                                run_query("DELETE FROM boletas WHERE descripcion LIKE ? AND fecha=?", (f"%{factura_del}%", fecha_del))
                            st.toast(f"🗑️ Registro {id_borrar} eliminado.")
                            time.sleep(1); st.rerun()
                    except Exception as e:
                        st.error(f"Error al borrar: {e}")
            
            st.markdown("---")
            if st.checkbox("🏆 Completar/Archivar Viaje"):
                ids_disponibles = df_full['rowid'].tolist()
                id_completar = st.selectbox("Seleccionar ID para archivar en Historial:", ids_disponibles, key="sb_completar_viaje")
                
                st.warning(f"⚠️ ¿Estás seguro de que deseas completar/archivar el viaje con ID {id_completar}?")
                if st.button("ARCHIVAR VIAJE", type="primary", key="btn_archivar_viaje"):
                    try:
                        rec = run_query(f"SELECT fecha, movimiento, cliente, operador, tracto, caja, factura, folio_cp, bascula, costo_final, moneda, ip_log, status_dia, ups, profepa, hora, carta_porte, manifiesto, destino FROM panel WHERE rowid={id_completar}")
                        if rec:
                            row_data = rec[0]
                            fecha_comp = get_local_now().strftime("%Y-%m-%d %H:%M:%S")
                            
                            # Insert into historial_panel
                            run_query("""INSERT INTO historial_panel 
                                (fecha, movimiento, cliente, operador, tracto, caja, factura, folio_cp, bascula, costo_final, moneda, ip_log, status_dia, ups, profepa, hora, carta_porte, manifiesto, destino, fecha_completado) 
                                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""", 
                                row_data + (fecha_comp,))
                            
                            # Delete from panel
                            run_query(f"DELETE FROM panel WHERE rowid={id_completar}")
                            st.toast(f"🏆 Viaje {id_completar} archivado en el historial.")
                            time.sleep(1); st.rerun()
                    except Exception as e:
                        st.error(f"Error al archivar: {e}")

        else: st.info("No hay registros con el filtro actual.")

    # ------------------ HISTORIAL VIAJES ------------------
    with tab_hist_viajes:
        st.markdown("### 🏆 Historial de Viajes Completados / Archivados")
        
        is_postgres = check_is_postgres()
        
        if is_postgres:
            query_hist = "SELECT rowid, fecha, hora, movimiento, cliente, folio_cp, factura, bascula, costo_final, moneda, ups, profepa, carta_porte, manifiesto, operador as chofer, tracto as camion, caja, destino, fecha_completado FROM historial_panel ORDER BY fecha_completado DESC LIMIT 100"
        else:
            query_hist = "SELECT id as rowid, fecha, hora, movimiento, cliente, folio_cp, factura, bascula, costo_final, moneda, ups, profepa, carta_porte, manifiesto, operador as chofer, tracto as camion, caja, destino, fecha_completado FROM historial_panel ORDER BY fecha_completado DESC LIMIT 100"
            
        conn_h = get_connection()
        try:
            df_hist = pd.read_sql_query(query_hist, conn_h)
        except Exception as e:
            df_hist = pd.DataFrame()
        conn_h.close()
        
        if not df_hist.empty:
            search_term = st.text_input("🔍 Buscar por Chofer, Camión, Cliente o Factura:", key="search_hist_viajes")
            
            if search_term:
                search_term = search_term.strip().lower()
                df_hist = df_hist[
                    df_hist['chofer'].str.lower().str.contains(search_term, na=False) |
                    df_hist['camion'].str.lower().str.contains(search_term, na=False) |
                    df_hist['cliente'].str.lower().str.contains(search_term, na=False) |
                    df_hist['factura'].str.lower().str.contains(search_term, na=False)
                ]
                
            st.markdown(
                """
                <div style="background: rgba(255, 255, 255, 0.05); color: #94a3b8; padding: 10px 15px; border-radius: 10px; display: flex; align-items: center; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.1); margin-bottom: 8px; font-size: 13px;">
                    <div style="flex: 1.5;">HORA / FECHA</div>
                    <div style="flex: 1.5;">MOVIMIENTO</div>
                    <div style="flex: 1.0;">CLIENTE</div>
                    <div style="flex: 2.0;">FOLIO / FACTURA</div>
                    <div style="flex: 2.2;">CHOFER</div>
                    <div style="flex: 0.8;">CAMIÓN</div>
                    <div style="flex: 0.8;">CAJA</div>
                    <div style="flex: 2.2;">DESTINO</div>
                    <div style="flex: 2.5; color: #10B981;">ARCHIVADO EL</div>
                </div>
                """,
                unsafe_allow_html=True
            )
            
            for idx, row in df_hist.iterrows():
                mov = str(row['movimiento']).upper()
                if "EXPORTACION" in mov:
                    bg_color, text_color, border_color = "rgba(59, 130, 246, 0.12)", "#93c5fd", "rgba(59, 130, 246, 0.3)"
                elif "IMPORTACION" in mov:
                    bg_color, text_color, border_color = "rgba(16, 185, 129, 0.12)", "#6ee7b7", "rgba(16, 185, 129, 0.3)"
                elif "TARIMAS" in mov:
                    bg_color, text_color, border_color = "rgba(245, 158, 11, 0.12)", "#fcd34d", "rgba(245, 158, 11, 0.3)"
                else:
                    bg_color, text_color, border_color = "rgba(139, 92, 246, 0.12)", "#c084fc", "rgba(139, 92, 246, 0.3)"
                
                folio = str(row['folio_cp']) if row['folio_cp'] else ""
                factura = str(row['factura']) if row['factura'] else ""
                if folio and factura:
                    folio_factura = f"{folio} / {factura}"
                else:
                    folio_factura = folio or factura or "-"
                
                st.markdown(
                    f"""
                    <div style="background: {bg_color}; border: 1px solid {border_color}; padding: 12px 15px; border-radius: 12px; display: flex; align-items: center; margin-bottom: 8px; font-size: 13.5px;">
                        <div style="flex: 1.5; color: #94a3b8;">{row['fecha']} {row['hora']}</div>
                        <div style="flex: 1.5; font-weight: bold; color: {text_color};">{mov}</div>
                        <div style="flex: 1.0; color: #cbd5e1;">{row['cliente']}</div>
                        <div style="flex: 2.0; color: #e2e8f0; font-family: monospace;">{folio_factura}</div>
                        <div style="flex: 2.2; font-weight: 500; color: #f8fafc;">{row['chofer']}</div>
                        <div style="flex: 0.8; color: #cbd5e1;">{row['camion']}</div>
                        <div style="flex: 0.8; color: #cbd5e1;">{row['caja']}</div>
                        <div style="flex: 2.2; color: #94a3b8;">{row['destino']}</div>
                        <div style="flex: 2.5; font-weight: bold; color: #34d399;">{row['fecha_completado']}</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
            st.markdown("---")
            if st.checkbox("🧹 Habilitar Limpieza del Historial de Viajes", key="chk_limpiar_hist_viajes"):
                if st.button("Limpiar Todo el Historial de Viajes", type="secondary", key="btn_limpiar_hist_viajes"):
                    run_query("DELETE FROM historial_panel")
                    st.success("Historial de viajes limpiado con éxito.")
                    time.sleep(1); st.rerun()
        else:
            st.info("El historial de viajes completados está vacío.")

# ------------------ BOLETAS ------------------
    with tab3:
        vista_boletas = st.radio("👁️ Vista", ["🎴 Tarjetas", "📝 Tabla Editable"], horizontal=True, key="vista_boletas_radio")
        df_boletas = cargar_dataframe("boletas", fecha_str)
        
        if not df_boletas.empty:
            if vista_boletas == "🎴 Tarjetas":
                st.markdown(
                    """
                    <div style="background: rgba(255, 255, 255, 0.05); color: #94a3b8; padding: 10px 15px; border-radius: 10px; display: flex; align-items: center; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.1); margin-bottom: 8px; font-size: 13px;">
                        <div style="flex: 1.2;">MOVIMIENTO</div>
                        <div style="flex: 2.2;">DESCRIPCIÓN</div>
                        <div style="flex: 1.5;">CAMIÓN / CAJA</div>
                        <div style="flex: 2.2;">CHOFER</div>
                        <div style="flex: 1.5;">FOLIO CP</div>
                        <div style="flex: 1.5;">BOLETA</div>
                        <div style="flex: 1.2;">COBRO</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                for idx, row in df_boletas.iterrows():
                    mov = str(row['movimiento']).upper()
                    
                    if "EXPO" in mov:
                        bg_color, text_color, border_color = "rgba(59, 130, 246, 0.12)", "#93c5fd", "rgba(59, 130, 246, 0.3)"
                    elif "IMPO" in mov:
                        bg_color, text_color, border_color = "rgba(16, 185, 129, 0.12)", "#6ee7b7", "rgba(16, 185, 129, 0.3)"
                    elif "TARIMAS" in mov:
                        bg_color, text_color, border_color = "rgba(245, 158, 11, 0.12)", "#fcd34d", "rgba(245, 158, 11, 0.3)"
                    else:
                        bg_color, text_color, border_color = "rgba(139, 92, 246, 0.12)", "#c084fc", "rgba(139, 92, 246, 0.3)"
                    
                    tracto_caja = f"{row['tracto'] or ''} / {row['caja'] or ''}"
                    if tracto_caja == " / ": tracto_caja = "-"
                    
                    st.markdown(
                        f"""
                        <div style="background-color: {bg_color}; color: {text_color}; padding: 12px 15px; border-radius: 10px; border: 1px solid {border_color}; display: flex; align-items: center; min-height: 44px; margin-bottom: 8px; font-size: 14px;">
                            <div style="flex: 1.2; font-weight: bold;">{mov}</div>
                            <div style="flex: 2.2; font-weight: 500;">{row['descripcion'] or ''}</div>
                            <div style="flex: 1.5; font-weight: 600;">{tracto_caja}</div>
                            <div style="flex: 2.2; font-weight: 600;">{row['operador'] or ''}</div>
                            <div style="flex: 1.5; font-family: monospace;">{row['folio_cp'] or ''}</div>
                            <div style="flex: 1.5;">{row['boleta'] or ''}</div>
                            <div style="flex: 1.2; font-weight: bold;">{row['cobro'] or ''}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
            else: # Tabla Editable
                edited_df = st.data_editor(df_boletas.drop(columns=['rowid'], errors='ignore'), key="edit_bol", num_rows="dynamic", use_container_width=True)
                if st.button("💾 ACTUALIZAR BOLETAS", use_container_width=True):
                    run_query("DELETE FROM boletas WHERE fecha=?", (fecha_str,))
                    for row in edited_df.itertuples(index=False): 
                        vals = row[1:] 
                        f_val = vals[0]
                        if isinstance(f_val, pd.Timestamp) or isinstance(f_val, date): f_val = str(f_val.date())
                        final_vals = (f_val,) + vals[1:]
                        run_query("INSERT INTO boletas (fecha, movimiento, descripcion, tracto, caja, d_caja, yarda, operador, sellos, folio_cp, boleta, cobro) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", final_vals)
                    st.success("Boletas Actualizadas"); st.rerun()
        else:
            st.info("No hay boletas registradas para esta fecha.")

    # ------------------ FLOTA / CHOFERES ------------------
    with tab4:
        st.markdown("### 🚛 Gestión de Choferes, Camiones y Cajas")
        
        vista_flota = st.radio("👁️ Vista General", ["🎴 Vista de Tarjetas", "📝 Editar Tablas"], horizontal=True, key="vista_flota_global")
        st.markdown("<br>", unsafe_allow_html=True)
        
        col_chof, col_cam, col_caj = st.columns(3)
        
        with col_chof:
            st.markdown("#### 👤 Gestión de Choferes")
            c_add_ch, c_new_ch_type = st.columns(2)
            with c_add_ch:
                val_o = st.text_input("Chofer (Nombre)", key="new_chof_name")
            with c_new_ch_type:
                val_tipo = st.selectbox("Tipo de Chofer", ["TRANSFER", "B1", "LOCAL"], key="new_chof_type")
                
            if st.button("💾 AGREGAR CHOFER"):
                if val_o:
                    smart_save_camion(camion="", chofer=val_o, tipo=val_tipo)
                    st.success(f"Chofer guardado.")
                    st.rerun()
            
            conn_chof = get_connection()
            df_choferes = pd.read_sql_query("SELECT nombre, tipo, disponible FROM choferes ORDER BY nombre ASC", conn_chof)
            conn_chof.close()
            ocupados = get_ocupados_hoy()
            if df_choferes.empty:
                df_choferes = pd.DataFrame(columns=['nombre', 'tipo', 'disponible', 'Estado'])
            else:
                def get_chof_state(row):
                    name = row['nombre']
                    disp = row['disponible']
                    if name and name.upper() in ocupados:
                        return "🔴 EN VIAJE"
                    elif disp == 'NO':
                        return "🟡 NO DISPONIBLE"
                    else:
                        return "🟢 DISPONIBLE"
                df_choferes['Estado'] = df_choferes.apply(get_chof_state, axis=1)
            
            if vista_flota == "🎴 Vista de Tarjetas":
                st.markdown("##### 🎴 Disponibilidad de Choferes")
                st.markdown(
                    """
                    <div style="background: rgba(255, 255, 255, 0.05); color: #94a3b8; padding: 8px 12px; border-radius: 8px; display: flex; align-items: center; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.08); margin-bottom: 6px; font-size: 12px;">
                        <div style="flex: 2.2;">CHOFER</div>
                        <div style="flex: 1;">TIPO</div>
                        <div style="flex: 1.5; text-align: right;">ESTADO / ACCIÓN</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                for idx, row in df_choferes.iterrows():
                    estado = row['Estado']
                    disp = row['disponible']
                    
                    if "🟢 DISPONIBLE" in estado:
                        bg, txt, border = "rgba(16, 185, 129, 0.08)", "#6ee7b7", "rgba(16, 185, 129, 0.2)"
                        badge = "<span style='color: #10b981; font-weight: bold;'>● DISPO</span>"
                    elif "🔴 EN VIAJE" in estado:
                        bg, txt, border = "rgba(239, 68, 68, 0.08)", "#fca5a5", "rgba(239, 68, 68, 0.2)"
                        badge = "<span style='color: #ef4444; font-weight: bold;'>● VIAJE</span>"
                    else: # 🟡 NO DISPONIBLE
                        bg, txt, border = "rgba(245, 158, 11, 0.08)", "#fcd34d", "rgba(245, 158, 11, 0.2)"
                        badge = "<span style='color: #f59e0b; font-weight: bold;'>● NO DISPO</span>"
                    
                    c_card, c_btn = st.columns([3.5, 1.5])
                    with c_card:
                        st.markdown(
                            f"""
                            <div style="background-color: {bg}; color: {txt}; padding: 8px 12px; border-radius: 8px; border: 1px solid {border}; display: flex; align-items: center; min-height: 38px; font-size: 13px;">
                                <div style="flex: 2.2; font-weight: 600; text-transform: uppercase;">{row['nombre']}</div>
                                <div style="flex: 1; font-weight: bold; font-size: 11px; opacity: 0.85;">{row['tipo']}</div>
                                <div style="flex: 1.5; text-align: right; font-size: 11px;">{badge}</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with c_btn:
                        btn_lbl = "🔴 Desact." if disp == 'SI' else "🟢 Activar"
                        if st.button(btn_lbl, key=f"btn_toggle_chof_{row['nombre']}", use_container_width=True):
                            new_disp = 'NO' if disp == 'SI' else 'SI'
                            run_query("UPDATE choferes SET disponible = ? WHERE nombre = ?", (new_disp, row['nombre']))
                            st.rerun()
            else:
                st.markdown("##### 📝 Editar Choferes de Forma Manual")
                
                df_chof_to_edit = df_choferes.copy()
                df_chof_to_edit['disponible'] = df_chof_to_edit['disponible'].apply(lambda x: x == 'SI')
                
                df_choferes_renamed = df_chof_to_edit.rename(columns={
                    'nombre': 'Chofer',
                    'tipo': 'Tipo',
                    'disponible': 'Disponible',
                    'Estado': 'Estado Actual'
                })
                
                edited_choferes = st.data_editor(
                    df_choferes_renamed,
                    column_config={
                        "Chofer": st.column_config.TextColumn("Chofer", required=True),
                        "Tipo": st.column_config.SelectboxColumn("Tipo", options=["TRANSFER", "B1", "LOCAL"], required=True),
                        "Disponible": st.column_config.CheckboxColumn("Disponible", default=True),
                        "Estado Actual": st.column_config.TextColumn("Estado Actual", disabled=True)
                    },
                    use_container_width=True,
                    num_rows="dynamic",
                    hide_index=True,
                    key="choferes_editor"
                )
                
                # Auto-save changes in drivers table
                orig_compare = df_choferes_renamed[['Chofer', 'Tipo', 'Disponible']].copy()
                orig_compare['Chofer'] = orig_compare['Chofer'].fillna('').str.strip().str.upper()
                orig_compare['Tipo'] = orig_compare['Tipo'].fillna('TRANSFER').str.strip().str.upper()
                
                edited_compare = edited_choferes[['Chofer', 'Tipo', 'Disponible']].copy()
                edited_compare['Chofer'] = edited_compare['Chofer'].fillna('').str.strip().str.upper()
                edited_compare['Tipo'] = edited_compare['Tipo'].fillna('TRANSFER').str.strip().str.upper()
                edited_compare = edited_compare[edited_compare['Chofer'] != '']
                
                # Convert back boolean to text for comparisons
                orig_compare['Disponible'] = orig_compare['Disponible'].apply(lambda x: 'SI' if x else 'NO')
                edited_compare['Disponible'] = edited_compare['Disponible'].apply(lambda x: 'SI' if x else 'NO')
                
                if not orig_compare.equals(edited_compare):
                    try:
                        run_query("DELETE FROM choferes")
                        for idx, row in edited_compare.iterrows():
                            run_query("INSERT OR IGNORE INTO choferes (nombre, tipo, disponible) VALUES (?, ?, ?)", (row['Chofer'], row['Tipo'], row['Disponible']))
                        st.toast("✅ Cambios en choferes guardados.")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar choferes: {e}")
                    
        with col_cam:
            st.markdown("#### 🚛 Gestión de Camiones")
            c_add_cam, c_new_cam_pl = st.columns(2)
            with c_add_cam:
                val_t = st.text_input("Camión (Número)", key="new_cam_id")
            with c_new_cam_pl:
                val_p = st.text_input("Placas (Patente)", key="new_cam_placas")
                
            if st.button("💾 AGREGAR CAMIÓN"):
                if val_t:
                    smart_save_camion(camion=val_t, placas=val_p)
                    st.success(f"Camión guardado.")
                    st.rerun()
            
            conn_cam = get_connection()
            df_camiones = pd.read_sql_query("SELECT tracto, placas, disponible FROM camiones ORDER BY tracto ASC", conn_cam)
            conn_cam.close()
            camiones_ocupados = get_camiones_ocupados_hoy()
            if df_camiones.empty:
                df_camiones = pd.DataFrame(columns=['tracto', 'placas', 'disponible', 'Estado'])
            else:
                def get_camion_state(row):
                    tr = row['tracto']
                    disp = row['disponible']
                    if tr and tr.upper() in camiones_ocupados:
                        return "🔴 EN VIAJE"
                    elif disp == 'NO':
                        return "🟡 NO DISPONIBLE"
                    else:
                        return "🟢 DISPONIBLE"
                df_camiones['Estado'] = df_camiones.apply(get_camion_state, axis=1)
            
            if vista_flota == "🎴 Vista de Tarjetas":
                st.markdown("##### 🎴 Disponibilidad de Camiones")
                st.markdown(
                    """
                    <div style="background: rgba(255, 255, 255, 0.05); color: #94a3b8; padding: 8px 12px; border-radius: 8px; display: flex; align-items: center; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.08); margin-bottom: 6px; font-size: 12px;">
                        <div style="flex: 1.2;">CAMIÓN</div>
                        <div style="flex: 1.8;">PLACAS</div>
                        <div style="flex: 1.5; text-align: right;">ESTADO / ACCIÓN</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                for idx, row in df_camiones.iterrows():
                    estado = row['Estado']
                    disp = row['disponible']
                    
                    if "🟢 DISPONIBLE" in estado:
                        bg, txt, border = "rgba(16, 185, 129, 0.08)", "#6ee7b7", "rgba(16, 185, 129, 0.2)"
                        badge = "<span style='color: #10b981; font-weight: bold;'>● DISPO</span>"
                    elif "🔴 EN VIAJE" in estado:
                        bg, txt, border = "rgba(239, 68, 68, 0.08)", "#fca5a5", "rgba(239, 68, 68, 0.2)"
                        badge = "<span style='color: #ef4444; font-weight: bold;'>● VIAJE</span>"
                    else: # 🟡 NO DISPONIBLE
                        bg, txt, border = "rgba(245, 158, 11, 0.08)", "#fcd34d", "rgba(245, 158, 11, 0.2)"
                        badge = "<span style='color: #f59e0b; font-weight: bold;'>● NO DISPO</span>"
                    
                    c_card, c_btn = st.columns([3.5, 1.5])
                    with c_card:
                        st.markdown(
                            f"""
                            <div style="background-color: {bg}; color: {txt}; padding: 8px 12px; border-radius: 8px; border: 1px solid {border}; display: flex; align-items: center; min-height: 38px; font-size: 13px;">
                                <div style="flex: 1.2; font-weight: bold; text-transform: uppercase;">{row['tracto']}</div>
                                <div style="flex: 1.8; font-family: monospace; font-size: 11px;">{row['placas'] or ''}</div>
                                <div style="flex: 1.5; text-align: right; font-size: 11px;">{badge}</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with c_btn:
                        btn_lbl = "🔴 Desact." if disp == 'SI' else "🟢 Activar"
                        if st.button(btn_lbl, key=f"btn_toggle_cam_{row['tracto']}", use_container_width=True):
                            new_disp = 'NO' if disp == 'SI' else 'SI'
                            run_query("UPDATE camiones SET disponible = ? WHERE tracto = ?", (new_disp, row['tracto']))
                            st.rerun()
            else:
                st.markdown("##### 📝 Editar Camiones de Forma Manual")
                
                df_cam_to_edit = df_camiones.copy()
                df_cam_to_edit['disponible'] = df_cam_to_edit['disponible'].apply(lambda x: x == 'SI')
                
                df_camiones_renamed = df_cam_to_edit.rename(columns={
                    'tracto': 'Camión',
                    'placas': 'Placas',
                    'disponible': 'Disponible',
                    'Estado': 'Estado Actual'
                })
                
                edited_camiones = st.data_editor(
                    df_camiones_renamed,
                    column_config={
                        "Camión": st.column_config.TextColumn("Camión", required=True),
                        "Placas": st.column_config.TextColumn("Placas"),
                        "Disponible": st.column_config.CheckboxColumn("Disponible", default=True),
                        "Estado Actual": st.column_config.TextColumn("Estado Actual", disabled=True)
                    },
                    use_container_width=True,
                    num_rows="dynamic",
                    hide_index=True,
                    key="camiones_editor"
                )
                
                # Auto-save changes in trucks table
                orig_compare = df_camiones_renamed[['Camión', 'Placas', 'Disponible']].copy()
                orig_compare['Camión'] = orig_compare['Camión'].fillna('').str.strip().str.upper()
                orig_compare['Placas'] = orig_compare['Placas'].fillna('').str.strip().str.upper()
                
                edited_compare = edited_camiones[['Camión', 'Placas', 'Disponible']].copy()
                edited_compare['Camión'] = edited_compare['Camión'].fillna('').str.strip().str.upper()
                edited_compare['Placas'] = edited_compare['Placas'].fillna('').str.strip().str.upper()
                edited_compare = edited_compare[edited_compare['Camión'] != '']
                
                # Convert back boolean to text for comparisons
                orig_compare['Disponible'] = orig_compare['Disponible'].apply(lambda x: 'SI' if x else 'NO')
                edited_compare['Disponible'] = edited_compare['Disponible'].apply(lambda x: 'SI' if x else 'NO')
                
                if not orig_compare.equals(edited_compare):
                    try:
                        run_query("DELETE FROM camiones")
                        for idx, row in edited_compare.iterrows():
                            run_query("INSERT OR IGNORE INTO camiones (tracto, placas, disponible) VALUES (?, ?, ?)", (row['Camión'], row['Placas'], row['Disponible']))
                        st.toast("✅ Cambios en camiones guardados.")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar camiones: {e}")
                    
        with col_caj:
            st.markdown("#### 📦 Gestión de Cajas")
            val_c = st.text_input("Caja (Número)", key="new_caja_id")
            
            if st.button("💾 AGREGAR CAJA"):
                if val_c:
                    smart_save_caja(val_c)
                    st.success(f"Caja guardada.")
                    st.rerun()
            
            conn_caj = get_connection()
            df_cajas = pd.read_sql_query("SELECT caja, disponible FROM cajas ORDER BY caja ASC", conn_caj)
            conn_caj.close()
            cajas_ocupadas = get_cajas_ocupados_hoy()
            if df_cajas.empty:
                df_cajas = pd.DataFrame(columns=['caja', 'disponible', 'Estado'])
            else:
                def get_caja_state(row):
                    cj = row['caja']
                    disp = row['disponible']
                    if cj and cj.upper() in cajas_ocupadas:
                        return "🔴 EN VIAJE"
                    elif disp == 'NO':
                        return "🟡 NO DISPONIBLE"
                    else:
                        return "🟢 DISPONIBLE"
                df_cajas['Estado'] = df_cajas.apply(get_caja_state, axis=1)
            
            if vista_flota == "🎴 Vista de Tarjetas":
                st.markdown("##### 🎴 Disponibilidad de Cajas")
                st.markdown(
                    """
                    <div style="background: rgba(255, 255, 255, 0.05); color: #94a3b8; padding: 8px 12px; border-radius: 8px; display: flex; align-items: center; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.08); margin-bottom: 6px; font-size: 12px;">
                        <div style="flex: 2.2;">CAJA</div>
                        <div style="flex: 1.8; text-align: right;">ESTADO / ACCIÓN</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                for idx, row in df_cajas.iterrows():
                    estado = row['Estado']
                    disp = row['disponible']
                    
                    if "🟢 DISPONIBLE" in estado:
                        bg, txt, border = "rgba(16, 185, 129, 0.08)", "#6ee7b7", "rgba(16, 185, 129, 0.2)"
                        badge = "<span style='color: #10b981; font-weight: bold;'>● DISPO</span>"
                    elif "🔴 EN VIAJE" in estado:
                        bg, txt, border = "rgba(239, 68, 68, 0.08)", "#fca5a5", "rgba(239, 68, 68, 0.2)"
                        badge = "<span style='color: #ef4444; font-weight: bold;'>● VIAJE</span>"
                    else: # 🟡 NO DISPONIBLE
                        bg, txt, border = "rgba(245, 158, 11, 0.08)", "#fcd34d", "rgba(245, 158, 11, 0.2)"
                        badge = "<span style='color: #f59e0b; font-weight: bold;'>● NO DISPO</span>"
                    
                    c_card, c_btn = st.columns([3.5, 1.5])
                    with c_card:
                        st.markdown(
                            f"""
                            <div style="background-color: {bg}; color: {txt}; padding: 8px 12px; border-radius: 8px; border: 1px solid {border}; display: flex; align-items: center; min-height: 38px; font-size: 13px;">
                                <div style="flex: 2.2; font-weight: bold; text-transform: uppercase;">{row['caja']}</div>
                                <div style="flex: 1.8; text-align: right; font-size: 11px;">{badge}</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with c_btn:
                        btn_lbl = "🔴 Desact." if disp == 'SI' else "🟢 Activar"
                        if st.button(btn_lbl, key=f"btn_toggle_caj_{row['caja']}", use_container_width=True):
                            new_disp = 'NO' if disp == 'SI' else 'SI'
                            run_query("UPDATE cajas SET disponible = ? WHERE caja = ?", (new_disp, row['caja']))
                            st.rerun()
            else:
                st.markdown("##### 📝 Editar Cajas de Forma Manual")
                
                df_caj_to_edit = df_cajas.copy()
                df_caj_to_edit['disponible'] = df_caj_to_edit['disponible'].apply(lambda x: x == 'SI')
                
                df_cajas_renamed = df_caj_to_edit.rename(columns={
                    'caja': 'Caja',
                    'disponible': 'Disponible',
                    'Estado': 'Estado Actual'
                })
                
                edited_cajas = st.data_editor(
                    df_cajas_renamed,
                    column_config={
                        "Caja": st.column_config.TextColumn("Caja", required=True),
                        "Disponible": st.column_config.CheckboxColumn("Disponible", default=True),
                        "Estado Actual": st.column_config.TextColumn("Estado Actual", disabled=True)
                    },
                    use_container_width=True,
                    num_rows="dynamic",
                    hide_index=True,
                    key="cajas_editor"
                )
                
                # Auto-save changes in cajas table
                orig_compare = df_cajas_renamed[['Caja', 'Disponible']].copy()
                orig_compare['Caja'] = orig_compare['Caja'].fillna('').str.strip().str.upper()
                
                edited_compare = edited_cajas[['Caja', 'Disponible']].copy()
                edited_compare['Caja'] = edited_compare['Caja'].fillna('').str.strip().str.upper()
                edited_compare = edited_compare[edited_compare['Caja'] != '']
                
                # Convert back boolean to text for comparisons
                orig_compare['Disponible'] = orig_compare['Disponible'].apply(lambda x: 'SI' if x else 'NO')
                edited_compare['Disponible'] = edited_compare['Disponible'].apply(lambda x: 'SI' if x else 'NO')
                
                if not orig_compare.equals(edited_compare):
                    try:
                        run_query("DELETE FROM cajas")
                        for idx, row in edited_compare.iterrows():
                            run_query("INSERT OR IGNORE INTO cajas (caja, disponible) VALUES (?, ?)", (row['Caja'], row['Disponible']))
                        st.toast("✅ Cambios en cajas guardados.")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Error al guardar cajas: {e}")

# ==============================================================================
# 7. MÓDULO VENCIMIENTOS
# ==============================================================================
if st.session_state.menu_actual == "VENCIMIENTOS":
    st.markdown("### 🚨 Gestión de Vencimientos")
    
    tab_reg, tab_cat, tab_hist = st.tabs(["1. REGISTROS", "2. EDITAR CATEGORÍAS", "3. HISTORIAL DE COMPLETADOS"])
    
    with tab_reg:
        with st.container():
            st.markdown("#### 🔍 Filtros")
            c_f1, c_f2, c_f3 = st.columns(3)
            
            all_units = [""] + get_camiones_list()
            f_uni = c_f1.selectbox("Unidad", all_units, key="venc_filter_uni")
            f_cat = c_f2.multiselect("Documento", [r[0] for r in run_query("SELECT tipo FROM cat_vencimientos")], key="venc_filter_doc")
            
            meses_filter = ["TODOS", "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
            f_mes = c_f3.selectbox("Mes", meses_filter, key="venc_filter_mes")
        
        st.markdown("---")
        col_reg, col_view = st.columns([1, 2])
        
        with col_reg:
            st.markdown("#### ➕ Nuevo Registro")
            v_uni = st.selectbox("Unidad", [""] + get_camiones_list(), key="venc_new_uni")
            v_tipo = st.selectbox("Documento", [r[0] for r in run_query("SELECT tipo FROM cat_vencimientos ORDER BY tipo")], key="venc_new_doc")
            
            c_mes, c_anio = st.columns(2)
            meses_input = ["ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE"]
            mes_sel = c_mes.selectbox("Mes Vencimiento", meses_input, key="venc_new_mes")
            anio_sel = c_anio.number_input("Año", value=get_local_now().year, step=1, key="venc_new_anio")
            
            if st.button("💾 GUARDAR", key="btn_save_venc"):
                if v_uni:
                    mes_idx = meses_input.index(mes_sel) + 1
                    last_day = calendar.monthrange(anio_sel, mes_idx)[1]
                    fecha_final = f"{anio_sel}-{mes_idx:02d}-{last_day}"
                    
                    check_q = "SELECT fecha_venc FROM vencimientos WHERE unidad=? AND tipo=?"
                    existing_record = run_query(check_q, (v_uni, v_tipo))
                    if existing_record:
                        old_date = existing_record[0][0]
                        run_query("UPDATE vencimientos SET fecha_venc=? WHERE unidad=? AND tipo=?", (fecha_final, v_uni, v_tipo))
                        st.toast(f"🔄 Actualizado {v_uni} ({v_tipo}): {old_date} ➝ {fecha_final}", icon="🔄")
                        time.sleep(1.5)
                    else:
                        run_query("INSERT INTO vencimientos (unidad, tipo, fecha_venc) VALUES (?,?,?)", (v_uni, v_tipo, fecha_final))
                        st.toast(f"✅ Nuevo documento registrado: {v_uni} - {v_tipo}", icon="✅")
                        time.sleep(1)
                    st.rerun()
                else: st.warning("Selecciona una unidad")
            
            st.markdown("---")
            st.markdown("#### 🗑️ Borrar Registro")
            del_list = run_query("SELECT id, unidad, tipo FROM vencimientos")
            if del_list:
                sel_del = st.selectbox("Eliminar por ID:", [""] + [f"{r[0]} | {r[1]} - {r[2]}" for r in del_list])
                if st.button("🗑️ ELIMINAR") and sel_del:
                    id_to_del = sel_del.split(" | ")[0]
                    run_query("DELETE FROM vencimientos WHERE id=?", (id_to_del,))
                    st.rerun()

        with col_view:
            query = "SELECT id, unidad as 'UNIDAD', tipo as 'DOCUMENTO', fecha_venc as 'FECHA VENC' FROM vencimientos WHERE 1=1"
            params = []
            
            if f_uni and f_uni.strip() != "":
                query += " AND UPPER(TRIM(unidad)) = ?"
                params.append(f_uni.strip().upper())
            
            if f_cat:
                placeholders = ",".join(["?"] * len(f_cat))
                query += f" AND tipo IN ({placeholders})"
                params.extend(f_cat)
            
            if f_mes != "TODOS":
                mes_num = f"{meses_filter.index(f_mes):02d}"
                query += " AND substr(fecha_venc, 6, 2) = ?"
                params.append(mes_num)
            
            query += " ORDER BY fecha_venc ASC"
            
            is_postgres = check_is_postgres()
            if is_postgres:
                query = query.replace("?", "%s")
            conn = get_connection()
            df_v = pd.read_sql_query(query, conn, params=params)
            conn.close()
            
            if not df_v.empty:
                df_v['FECHA VENC'] = pd.to_datetime(df_v['FECHA VENC'])
                
                # Render Table Headers
                h_col1, h_col2 = st.columns([5, 1])
                with h_col1:
                    st.markdown(
                        """
                        <div style="background: rgba(255, 255, 255, 0.05); color: #94a3b8; padding: 10px 15px; border-radius: 10px; display: flex; align-items: center; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.1); margin-bottom: 8px;">
                            <div style="flex: 1;">UNIDAD</div>
                            <div style="flex: 2;">DOCUMENTO</div>
                            <div style="flex: 2;">MES</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                with h_col2:
                    st.markdown('<div style="text-align: center; color: #94a3b8; font-weight: bold; padding: 10px 0; font-size: 14px;">ACCIÓN</div>', unsafe_allow_html=True)
                
                # Render Row by Row
                meses_es = {1:"ENERO", 2:"FEBRERO", 3:"MARZO", 4:"ABRIL", 5:"MAYO", 6:"JUNIO", 7:"JULIO", 8:"AGOSTO", 9:"SEPTIEMBRE", 10:"OCTUBRE", 11:"NOVIEMBRE", 12:"DICIEMBRE"}
                
                for idx, row in df_v.iterrows():
                    venc = row['FECHA VENC']
                    # Calculate style
                    hoy = get_local_now()
                    meses_venc = venc.year * 12 + venc.month
                    meses_hoy = hoy.year * 12 + hoy.month
                    diff = meses_venc - meses_hoy
                    
                    if diff <= 0:
                        bg_color = "rgba(239, 68, 68, 0.15)"
                        text_color = "#fca5a5"
                        border_color = "rgba(239, 68, 68, 0.3)"
                    elif diff == 1:
                        bg_color = "rgba(245, 158, 11, 0.15)"
                        text_color = "#fcd34d"
                        border_color = "rgba(245, 158, 11, 0.3)"
                    else:
                        bg_color = "rgba(16, 185, 129, 0.1)"
                        text_color = "#6ee7b7"
                        border_color = "rgba(16, 185, 129, 0.2)"
                    
                    mes_str = f"{meses_es[venc.month]} {venc.year}"
                    task_id = row['id']
                    
                    r_col1, r_col2 = st.columns([5, 1])
                    with r_col1:
                        st.markdown(
                            f"""
                            <div style="background-color: {bg_color}; color: {text_color}; padding: 8px 15px; border-radius: 10px; border: 1px solid {border_color}; display: flex; align-items: center; min-height: 38px;">
                                <div style="flex: 1; font-weight: bold;">{row['UNIDAD']}</div>
                                <div style="flex: 2; font-weight: 600;">{row['DOCUMENTO']}</div>
                                <div style="flex: 2;">{mes_str}</div>
                            </div>
                            """,
                            unsafe_allow_html=True
                        )
                    with r_col2:
                        if st.button("✅ Completar", key=f"btn_comp_{task_id}", use_container_width=True):
                            # Mark as completed and delete
                            try:
                                # Save to history
                                fecha_comp = get_local_now().strftime("%Y-%m-%d %H:%M:%S")
                                run_query("INSERT INTO historial_vencimientos (unidad, tipo, fecha_venc, fecha_completado) VALUES (?, ?, ?, ?)",
                                             (row['UNIDAD'], row['DOCUMENTO'], str(venc.date()), fecha_comp))
                                # Delete from vencimientos
                                run_query("DELETE FROM vencimientos WHERE id=?", (task_id,))
                                st.toast(f"✅ Completado: {row['UNIDAD']} - {row['DOCUMENTO']}")
                                time.sleep(0.5)
                                st.rerun()
                            except Exception as e:
                                st.error(f"Error: {e}")
            else:
                st.info("No se encontraron registros.")

    with tab_cat:
        st.markdown("### ⚙️ Administración de Categorías")
        c1, c2, c3 = st.columns(3)
        with c1:
            st.markdown("#### ➕ Agregar")
            new_cat = st.text_input("Nueva Categoría").upper()
            if st.button("Guardar Nueva"):
                if new_cat:
                    run_query("INSERT OR IGNORE INTO cat_vencimientos VALUES (?)", (new_cat,))
                    st.success(f"Creada: {new_cat}"); time.sleep(1); st.rerun()
        with c2:
            st.markdown("#### ✏️ Editar")
            cats = [r[0] for r in run_query("SELECT tipo FROM cat_vencimientos ORDER BY tipo")]
            cat_old = st.selectbox("Categoría a Editar", [""] + cats)
            cat_new_name = st.text_input("Nuevo Nombre").upper()
            if st.button("Actualizar Nombre"):
                if cat_old and cat_new_name:
                    run_query("UPDATE cat_vencimientos SET tipo=? WHERE tipo=?", (cat_new_name, cat_old))
                    run_query("UPDATE vencimientos SET tipo=? WHERE tipo=?", (cat_new_name, cat_old))
                    st.success(f"Actualizado: {cat_old} -> {cat_new_name}"); time.sleep(1); st.rerun()
        with c3:
            st.markdown("#### 🗑️ Eliminar")
            cat_del = st.selectbox("Categoría a Borrar", [""] + cats, key="del_cat_sel")
            if st.button("Borrar Definitivamente"):
                if cat_del:
                    run_query("DELETE FROM cat_vencimientos WHERE tipo=?", (cat_del,))
                    st.warning(f"Eliminada: {cat_del}"); time.sleep(1); st.rerun()

        with tab_hist:
            st.markdown("#### 📜 Historial de Vencimientos Completados")
            conn_hist = get_connection()
            df_hist = pd.read_sql_query("SELECT id, unidad as 'UNIDAD', tipo as 'DOCUMENTO', fecha_venc as 'FECHA VENCIMIENTO', fecha_completado as 'FECHA COMPLETADO' FROM historial_vencimientos ORDER BY fecha_completado DESC", conn_hist)
            conn_hist.close()
            if not df_hist.empty:
                # Cabecera de Tarjetas
                st.markdown(
                    """
                    <div style="background: rgba(255, 255, 255, 0.05); color: #94a3b8; padding: 10px 15px; border-radius: 10px; display: flex; align-items: center; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.1); margin-bottom: 8px; font-size: 13px;">
                        <div style="flex: 1;">UNIDAD</div>
                        <div style="flex: 2;">DOCUMENTO</div>
                        <div style="flex: 2;">FECHA VENCIMIENTO</div>
                        <div style="flex: 2;">FECHA COMPLETADO</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                # Renderizar cada historial en una tarjeta gris con fecha completado en verde
                for idx, row in df_hist.iterrows():
                    bg_color = "rgba(255, 255, 255, 0.03)"
                    text_color = "#cbd5e1"
                    border_color = "rgba(255, 255, 255, 0.1)"
                    
                    st.markdown(
                        f"""
                        <div style="background-color: {bg_color}; color: {text_color}; padding: 10px 15px; border-radius: 10px; border: 1px solid {border_color}; display: flex; align-items: center; min-height: 40px; margin-bottom: 8px; font-size: 14px;">
                            <div style="flex: 1; font-weight: bold;">{row['UNIDAD']}</div>
                            <div style="flex: 2; font-weight: 600; opacity: 0.9;">{row['DOCUMENTO']}</div>
                            <div style="flex: 2; opacity: 0.8;">{row['FECHA VENCIMIENTO']}</div>
                            <div style="flex: 2; color: #6ee7b7; font-weight: 500;">✅ {row['FECHA COMPLETADO']}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                
                st.markdown("<br>", unsafe_allow_html=True)
                if st.checkbox("🗑️ Habilitar Limpieza del Historial"):
                    if st.button("Limpiar Todo el Historial", type="secondary"):
                        run_query("DELETE FROM historial_vencimientos")
                        st.success("Historial limpiado.")
                        time.sleep(0.5)
                        st.rerun()
            else:
                st.info("El historial está vacío.")

# ==============================================================================
# 8. MÓDULO MANTENIMIENTO
# ==============================================================================
if st.session_state.menu_actual == "MANTENIMIENTO":
    st.markdown("### 🔧 Mantenimiento Preventivo")
    c1, c2 = st.columns([1, 2])
    with c1:
        st.markdown("##### Configurar Unidad")
        m_unidad = st.text_input("Camión / Unidad (Ej. F10)", key="maint_uni_input").upper()
        m_millas_last = st.number_input("Millas Último Servicio", min_value=0, step=100)
        m_intervalo = st.number_input("Intervalo Servicio", value=15000, step=1000)
        if st.button("💾 Guardar Configuración", use_container_width=True):
            if m_unidad:
                smart_save_camion(m_unidad)
                run_query("INSERT OR REPLACE INTO mantenimiento VALUES (?,?,?,?)", (m_unidad, m_millas_last, m_intervalo, get_local_now().strftime("%Y-%m-%d")))
                st.success(f"Configurado para {m_unidad}"); st.rerun()

    with c2:
        st.markdown("##### 📊 Estado de la Flota")
        conn_m = get_connection()
        df_m = pd.read_sql_query("SELECT * FROM mantenimiento", conn_m)
        conn_m.close()
        if not df_m.empty:
            for index, row in df_m.iterrows():
                with st.container():
                    col_info, col_input = st.columns([2, 1])
                    with col_input:
                        millas_actuales = st.number_input(f"Millas Actuales {row['unidad']}", min_value=float(row['ultimo_servicio_millas']), step=100.0, key=f"millas_{row['unidad']}")
                    with col_info:
                        limite = row['ultimo_servicio_millas'] + row['intervalo_millas']
                        restante = limite - millas_actuales
                        porcentaje = max(0.0, min(1.0, 1 - (restante / row['intervalo_millas'])))
                        st.markdown(f"**{row['unidad']}** (Servicio: {row['fecha_servicio']})")
                        st.progress(porcentaje)
                        if restante <= 0:
                            st.error(f"🚨 VENCIDO")
                            if st.button(f"🛠️ REGISTRAR SERVICIO {row['unidad']}", key=f"btn_{row['unidad']}", type="primary"): popup_mantenimiento(row['unidad'], millas_actuales)
                        else: st.success(f"✅ OK ({restante:,.0f} millas restantes)")

# ==============================================================================
# 8.5 MÓDULO MODO TV / PROYECCIÓN
# ==============================================================================
if st.session_state.menu_actual == "MODO_TV":
    # 1. CSS personalizado para pantalla completa en TV/Proyección
    st.markdown("""
        <style>
        [data-testid="stHeader"] { display: none !important; }
        .block-container {
            padding-top: 1.5rem !important;
            padding-bottom: 1.5rem !important;
            padding-left: 2rem !important;
            padding-right: 2rem !important;
            max-width: 98% !important;
        }
        </style>
        """, unsafe_allow_html=True)
    
    # 2. Barra superior
    is_postgres = check_is_postgres()
    if is_postgres:
        db_status = '<span style="background-color: rgba(16, 185, 129, 0.2); border: 1px solid #10b981; padding: 4px 10px; border-radius: 8px; font-size: 13px; color: #10b981; font-weight: bold; margin-left: 15px; vertical-align: middle;">☁️ BD: Nube</span>'
    else:
        db_status = '<span style="background-color: rgba(239, 68, 68, 0.2); border: 1px solid #ef4444; padding: 4px 10px; border-radius: 8px; font-size: 13px; color: #fca5a5; font-weight: bold; margin-left: 15px; vertical-align: middle;">⚠️ BD: SQLite Temporal</span>'

    c_title, c_date, c_refresh, c_exit = st.columns([4, 2, 2, 2])
    with c_title:
        st.markdown(f"<h2 style='margin:0; padding:0; color:#e2e8f0;'>📺 OTD Freight <span style='color:#10b981; font-size:16px; font-weight:bold; animation: blink 1.5s infinite;'>● EN VIVO</span> {db_status}</h2><style>@keyframes blink {{ 0% {{ opacity: 0.3; }} 50% {{ opacity: 1; }} 100% {{ opacity: 0.3; }} }}</style>", unsafe_allow_html=True)

    if st.session_state.get("db_connection_error"):
        st.error(f"⚠️ **Error conexión BD Nube:** {st.session_state.db_connection_error}")
    with c_date:
        tv_fecha = st.date_input("📅 Fecha Proyectada", value=get_local_now(), key="tv_fecha_input")
        tv_fecha_str = tv_fecha.strftime("%Y-%m-%d")
    with c_refresh:
        refresh_rate = st.selectbox("🔄 Auto-refresco", ["30 segundos", "1 minuto", "5 minutos", "Desactivado"], index=0, key="tv_refresh_rate")
        refresh_seconds = 30
        if refresh_rate == "1 minuto": refresh_seconds = 60
        elif refresh_rate == "5 minutos": refresh_seconds = 300
        elif refresh_rate == "Desactivado": refresh_seconds = None
    with c_exit:
        if st.button("🔙 Salir de Modo TV", type="primary", use_container_width=True, key="btn_exit_tv"):
            st.session_state.menu_actual = "OPERACIONES"
            st.rerun()
            
    # 3. Pestañas de Navegación del Modo TV
    tab_tv_viajes, tab_tv_dispo = st.tabs(["📋 VIAJES DEL DÍA", "📊 DISPONIBILIDAD FLOTA"])
    
    with tab_tv_viajes:
        @st.fragment(run_every=refresh_seconds)
        def render_tv_layout(fecha_filtro):
            df_tv = cargar_dataframe("panel", fecha_filtro)
            if not df_tv.empty:
                st.markdown(
                    """
                    <div style="background: rgba(255, 255, 255, 0.05); color: #94a3b8; padding: 12px 18px; border-radius: 12px; display: flex; align-items: center; font-weight: bold; border: 1px solid rgba(255, 255, 255, 0.1); margin-bottom: 10px; font-size: 15px;">
                        <div style="flex: 0.8;">HORA</div>
                        <div style="flex: 1.5;">MOVIMIENTO</div>
                        <div style="flex: 0.8;">CLIENTE</div>
                        <div style="flex: 1.8;">FOLIO / FACTURA</div>
                        <div style="flex: 2.5;">CHOFER</div>
                        <div style="flex: 0.8;">CAMIÓN</div>
                        <div style="flex: 0.8;">CAJA</div>
                        <div style="flex: 2.2;">DESTINO</div>
                        <div style="flex: 1.2; text-align: center;">DOCS</div>
                    </div>
                    """,
                    unsafe_allow_html=True
                )
                
                for idx, row in df_tv.iterrows():
                    mov = str(row['movimiento']).upper()
                    
                    # Asignar tema de color según el movimiento
                    if "EXPORTACION" in mov:
                        bg_color, text_color, border_color = "rgba(59, 130, 246, 0.15)", "#93c5fd", "rgba(59, 130, 246, 0.35)"
                    elif "IMPORTACION" in mov:
                        bg_color, text_color, border_color = "rgba(16, 185, 129, 0.15)", "#6ee7b7", "rgba(16, 185, 129, 0.35)"
                    elif "TARIMAS" in mov:
                        bg_color, text_color, border_color = "rgba(245, 158, 11, 0.15)", "#fcd34d", "rgba(245, 158, 11, 0.35)"
                    else: # TRANSFER
                        bg_color, text_color, border_color = "rgba(139, 92, 246, 0.15)", "#c084fc", "rgba(139, 92, 246, 0.35)"
                    
                    # Combinar Folio y Factura
                    folio = str(row['folio_cp']) if row['folio_cp'] else ""
                    factura = str(row['factura']) if row['factura'] else ""
                    if folio and factura:
                        folio_factura = f"{folio} / {factura}"
                    else:
                        folio_factura = folio or factura or "-"
                    
                    # Badges de documentos
                    cp_badge = "<span style='background: rgba(16, 185, 129, 0.25); border: 1px solid rgba(16, 185, 129, 0.45); padding: 2px 6px; border-radius: 4px; font-size: 11px; color:#6ee7b7; font-weight:bold; margin-right:4px;'>📄 CP</span>" if row['carta_porte'] else ""
                    man_badge = "<span style='background: rgba(16, 185, 129, 0.25); border: 1px solid rgba(16, 185, 129, 0.45); padding: 2px 6px; border-radius: 4px; font-size: 11px; color:#6ee7b7; font-weight:bold;'>📋 MAN</span>" if row['manifiesto'] else ""
                    docs_badges = f"{cp_badge} {man_badge}".strip() if (cp_badge or man_badge) else "<span style='color: #64748b; font-size:13px;'>-</span>"
                    
                    st.markdown(
                        f"""
                        <div style="background-color: {bg_color}; color: {text_color}; padding: 16px 20px; border-radius: 12px; border: 1px solid {border_color}; display: flex; align-items: center; min-height: 56px; margin-bottom: 10px; font-size: 16px;">
                            <div style="flex: 0.8; font-weight: 500;">{row['hora']}</div>
                            <div style="flex: 1.5; font-weight: bold; text-transform: uppercase; letter-spacing: 0.5px;">{mov}</div>
                            <div style="flex: 0.8; font-weight: 600;">{row['cliente']}</div>
                            <div style="flex: 1.8; font-family: monospace; font-size: 15px;">{folio_factura}</div>
                            <div style="flex: 2.5; font-weight: 600; text-transform: uppercase;">{row['operador']}</div>
                            <div style="flex: 0.8; font-weight: bold;">{row['tracto']}</div>
                            <div style="flex: 0.8; font-weight: bold;">{row['caja']}</div>
                            <div style="flex: 2.2; font-size: 15px;">{row['destino'] or ''}</div>
                            <div style="flex: 1.2; display: flex; gap: 4px; justify-content: center; align-items: center;">{docs_badges}</div>
                        </div>
                        """,
                        unsafe_allow_html=True
                    )
                st.caption(f"Última actualización automática: {get_local_now().strftime('%H:%M:%S')}")
            else:
                st.info(f"No hay registros de viajes para el {fecha_filtro}.")
                
        render_tv_layout(tv_fecha_str)

    with tab_tv_dispo:
        @st.fragment(run_every=refresh_seconds)
        def render_tv_disponibilidad_nav():
            col1, col2, col3 = st.columns(3)
            
            # 1. Choferes
            with col1:
                st.markdown("#### 👥 Choferes")
                df_ch = pd.read_sql_query("SELECT nombre, tipo, disponible FROM choferes ORDER BY nombre ASC", get_connection())
                ocupados = get_ocupados_hoy()
                if df_ch.empty:
                    st.info("No hay choferes registrados.")
                else:
                    for idx, row in df_ch.iterrows():
                        name = row['nombre']
                        disp = row['disponible']
                        
                        if name and name.upper() in ocupados:
                            bg, txt, border = "rgba(239, 68, 68, 0.15)", "#fca5a5", "rgba(239, 68, 68, 0.35)"
                            badge = "🔴 EN VIAJE"
                        elif disp == 'NO':
                            bg, txt, border = "rgba(245, 158, 11, 0.15)", "#fcd34d", "rgba(245, 158, 11, 0.35)"
                            badge = "🟡 NO DISPONIBLE"
                        else:
                            bg, txt, border = "rgba(16, 185, 129, 0.15)", "#6ee7b7", "rgba(16, 185, 129, 0.35)"
                            badge = "🟢 DISPONIBLE"
                            
                        cc_card, cc_btn = st.columns([3.5, 1.5])
                        with cc_card:
                            st.markdown(f"""
                            <div style="background-color: {bg}; color: {txt}; padding: 12px 15px; border-radius: 10px; border: 1px solid {border}; display: flex; flex-direction: column; justify-content: center; min-height: 48px; margin-bottom: 8px;">
                                <div style="font-weight: 700; text-transform: uppercase; font-size:14px;">{name}</div>
                                <div style="font-size: 11px; font-weight: bold; opacity: 0.9; margin-top:2px;">{badge} ({row['tipo']})</div>
                            </div>
                            """, unsafe_allow_html=True)
                        with cc_btn:
                            btn_lbl = "🔴 Desact." if disp == 'SI' else "🟢 Activar"
                            if st.button(btn_lbl, key=f"tv_nav_toggle_chof_{name}", use_container_width=True):
                                new_disp = 'NO' if disp == 'SI' else 'SI'
                                run_query("UPDATE choferes SET disponible = ? WHERE nombre = ?", (new_disp, name))
                                st.rerun()

            # 2. Camiones
            with col2:
                st.markdown("#### 🚛 Camiones")
                df_cam = pd.read_sql_query("SELECT tracto, placas, disponible FROM camiones ORDER BY tracto ASC", get_connection())
                camiones_ocupados = get_camiones_ocupados_hoy()
                if df_cam.empty:
                    st.info("No hay camiones registrados.")
                else:
                    for idx, row in df_cam.iterrows():
                        tracto = row['tracto']
                        placas = row['placas'] or ''
                        disp = row['disponible']
                        
                        if tracto and tracto.upper() in camiones_ocupados:
                            bg, txt, border = "rgba(239, 68, 68, 0.15)", "#fca5a5", "rgba(239, 68, 68, 0.35)"
                            badge = "🔴 EN VIAJE"
                        elif disp == 'NO':
                            bg, txt, border = "rgba(245, 158, 11, 0.15)", "#fcd34d", "rgba(245, 158, 11, 0.35)"
                            badge = "🟡 NO DISPONIBLE"
                        else:
                            bg, txt, border = "rgba(16, 185, 129, 0.15)", "#6ee7b7", "rgba(16, 185, 129, 0.35)"
                            badge = "🟢 DISPONIBLE"
                            
                        cc_card, cc_btn = st.columns([3.5, 1.5])
                        with cc_card:
                            st.markdown(f"""
                            <div style="background-color: {bg}; color: {txt}; padding: 12px 15px; border-radius: 10px; border: 1px solid {border}; display: flex; flex-direction: column; justify-content: center; min-height: 48px; margin-bottom: 8px;">
                                <div style="font-weight: 700; text-transform: uppercase; font-size:14px;">{tracto}</div>
                                <div style="font-size: 11px; font-weight: bold; opacity: 0.9; margin-top:2px;">{badge} {f'({placas})' if placas else ''}</div>
                            </div>
                            """, unsafe_allow_html=True)
                        with cc_btn:
                            btn_lbl = "🔴 Desact." if disp == 'SI' else "🟢 Activar"
                            if st.button(btn_lbl, key=f"tv_nav_toggle_cam_{tracto}", use_container_width=True):
                                new_disp = 'NO' if disp == 'SI' else 'SI'
                                run_query("UPDATE camiones SET disponible = ? WHERE tracto = ?", (new_disp, tracto))
                                st.rerun()

            # 3. Cajas
            with col3:
                st.markdown("#### 📦 Cajas")
                df_cj = pd.read_sql_query("SELECT caja, disponible FROM cajas ORDER BY caja ASC", get_connection())
                cajas_ocupadas = get_cajas_ocupados_hoy()
                if df_cj.empty:
                    st.info("No hay cajas registradas.")
                else:
                    for idx, row in df_cj.iterrows():
                        caja = row['caja']
                        disp = row['disponible']
                        
                        if caja and caja.upper() in cajas_ocupadas:
                            bg, txt, border = "rgba(239, 68, 68, 0.15)", "#fca5a5", "rgba(239, 68, 68, 0.35)"
                            badge = "🔴 EN VIAJE"
                        elif disp == 'NO':
                            bg, txt, border = "rgba(245, 158, 11, 0.15)", "#fcd34d", "rgba(245, 158, 11, 0.35)"
                            badge = "🟡 NO DISPONIBLE"
                        else:
                            bg, txt, border = "rgba(16, 185, 129, 0.15)", "#6ee7b7", "rgba(16, 185, 129, 0.35)"
                            badge = "🟢 DISPONIBLE"
                            
                        cc_card, cc_btn = st.columns([3.5, 1.5])
                        with cc_card:
                            st.markdown(f"""
                            <div style="background-color: {bg}; color: {txt}; padding: 12px 15px; border-radius: 10px; border: 1px solid {border}; display: flex; flex-direction: column; justify-content: center; min-height: 48px; margin-bottom: 8px;">
                                <div style="font-weight: 700; text-transform: uppercase; font-size:14px;">{caja}</div>
                                <div style="font-size: 11px; font-weight: bold; opacity: 0.9; margin-top:2px;">{badge}</div>
                            </div>
                            """, unsafe_allow_html=True)
                        with cc_btn:
                            btn_lbl = "🔴 Desact." if disp == 'SI' else "🟢 Activar"
                            if st.button(btn_lbl, key=f"tv_nav_toggle_cj_{caja}", use_container_width=True):
                                new_disp = 'NO' if disp == 'SI' else 'SI'
                                run_query("UPDATE cajas SET disponible = ? WHERE caja = ?", (new_disp, caja))
                                st.rerun()
        render_tv_disponibilidad_nav()

# ==============================================================================
# 9. BLOQUE ADMIN & DEV
# ==============================================================================
st.markdown("<br><br>", unsafe_allow_html=True)

if not st.session_state.admin_unlocked:
    with st.expander("🔐 ACCESO ADMINISTRATIVO"):
        pwd = st.text_input("Ingrese Clave de Soporte", type="password")
        if st.button("DESBLOQUEAR SISTEMA"):
            if pwd == ADMIN_PASSWORD:
                st.session_state.admin_unlocked = True
                st.rerun()
            else:
                st.error("Clave Incorrecta")
else:
    st.markdown('<div class="admin-box">', unsafe_allow_html=True)
    c_head, c_exit = st.columns([3, 1])
    c_head.markdown("### 🔧 MODO DESARROLLADOR / SOPORTE")
    if c_exit.button("🔒 BLOQUEAR / SALIR"):
        st.session_state.admin_unlocked = False
        st.rerun()

    mode = st.radio("Herramienta:", ["EDITOR DE CÓDIGO", "RESTAURAR BACKUP", "🧪 ENTORNO SANDBOX", "🧪 DIAGNÓSTICO BD"], horizontal=True)
    
    if mode == "EDITOR DE CÓDIGO":
        st.warning("⚠️ Editar este código afecta al sistema en vivo.")
        this_file = __file__
        try:
            with open(this_file, "r", encoding="utf-8") as f: code = f.read()
            new_code = st.text_area("Código Fuente", value=code, height=500)
            
            if st.button("🔴 GUARDAR CAMBIOS Y REINICIAR"):
                shutil.copy(this_file, f"{BACKUP_DIR}/code_backup_{int(time.time())}.py")
                with open(this_file, "w", encoding="utf-8") as f: f.write(new_code)
                st.success("Actualizado. Reiniciando...")
                time.sleep(1)
                st.rerun()
        except Exception as e:
            st.error(f"Error leyendo archivo: {e}")

    elif mode == "RESTAURAR BACKUP":
        st.info("Restaura la base de datos a un punto anterior.")
        backups = sorted([f for f in os.listdir(BACKUP_DIR) if f.endswith(".db")], reverse=True)
        if backups:
            bs = st.selectbox("Seleccionar Backup:", backups)
            if st.button("⚠️ RESTAURAR BD"):
                shutil.copy(f"{BACKUP_DIR}/{bs}", DB_NAME)
                st.success("Base de datos restaurada.")
                time.sleep(1)
                st.rerun()
        else:
            st.write("No hay backups disponibles.")
            
    elif mode == "🧪 ENTORNO SANDBOX":
        st.info("Lanza una versión de prueba aislada en el puerto 9000 sin afectar tu base de datos real.")
        
        is_running = os.path.exists("sandbox.pid")
        
        if is_running:
            st.success("🟢 El Sandbox está actualmente en ejecución (Puerto 9000).")
            # --- AQUÍ ESTÁ EL CAMBIO DE LA IP ---
            st.markdown("### [👉 CLIC AQUÍ PARA ABRIR EL SANDBOX](http://100.75.64.13:9000)")
            st.markdown("*Nota: Usando la IP de red especificada.*")
            
            if st.button("🛑 DETENER SANDBOX", type="primary"):
                try:
                    with open("sandbox.pid", "r") as f: pid = int(f.read().strip())
                    if os.name == 'nt':
                        subprocess.call(['taskkill', '/F', '/T', '/PID', str(pid)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    else:
                        os.kill(pid, signal.SIGTERM)
                except Exception as e:
                    pass
                
                if os.path.exists("sandbox.pid"): os.remove("sandbox.pid")
                st.toast("Sandbox detenido correctamente.")
                time.sleep(1)
                st.rerun()
        else:
            try:
                with open(__file__, "r", encoding="utf-8") as f: default_code = f.read()
                
                default_code = default_code.replace('DB_NAME = "hydra_v1.db"', 'DB_NAME = "hydra_sandbox.db"')
                default_code = default_code.replace('APP_VERSION = "', 'APP_VERSION = "[SANDBOX] ')
                
                sandbox_code = st.text_area("Código a Testear (Modifícalo libremente. La Base de Datos ya fue protegida):", value=default_code, height=400)
                
                if st.button("🚀 LANZAR SANDBOX (PUERTO 9000)"):
                    with open("otd_sandbox_temp.py", "w", encoding="utf-8") as f:
                        f.write(sandbox_code)
                    
                    proc = subprocess.Popen(
                        [sys.executable, "-m", "streamlit", "run", "otd_sandbox_temp.py", "--server.port", "9000", "--server.headless", "true"],
                        stdout=subprocess.DEVNULL, 
                        stderr=subprocess.DEVNULL
                    )
                    
                    with open("sandbox.pid", "w") as f: 
                        f.write(str(proc.pid))
                    
                    st.toast("Lanzando Sandbox...")
                    time.sleep(2) 
                    st.rerun()
            except Exception as e:
                st.error(f"Error preparando el Sandbox: {e}")
                
    elif mode == "🧪 DIAGNÓSTICO BD":
        st.markdown("#### 🧪 Diagnóstico de Conexión a Base de Datos")
        
        # 1. Verificar presencia de secrets
        st.write("**Estado de st.secrets:**")
        if "postgres_url" in st.secrets:
            url_str = st.secrets["postgres_url"]
            st.success("✅ `postgres_url` está configurado en st.secrets.")
            
            # Intentar parsear
            try:
                import urllib.parse
                parsed = urllib.parse.urlparse(url_str)
                st.write(f"- **Protocolo:** `{parsed.scheme}`")
                st.write(f"- **Usuario:** `{parsed.username}`")
                st.write(f"- **Servidor (Host):** `{parsed.hostname}`")
                st.write(f"- **Puerto:** `{parsed.port}`")
                st.write(f"- **Base de Datos:** `{parsed.path.replace('/', '')}`")
                if parsed.password:
                    pass_censored = parsed.password[0] + "*" * (len(parsed.password) - 2) + parsed.password[-1] if len(parsed.password) > 2 else "***"
                    st.write(f"- **Contraseña:** `{pass_censored}` (Longitud: {len(parsed.password)})")
                else:
                    st.warning("⚠️ No se detectó contraseña en el URL.")
            except Exception as pe:
                st.error(f"Error al analizar el URL de conexión: {pe}")
        else:
            st.error("❌ `postgres_url` NO está configurado en st.secrets en Streamlit Cloud.")
            st.info("Para solucionarlo, ve a la configuración de tu App en Streamlit Cloud (Settings -> Secrets) y pega el url de conexión.")

        st.markdown("---")
        
        # 2. Pruebas activas
        c_test1, c_test2 = st.columns(2)
        with c_test1:
            if st.button("🔍 Probar Conexión TCP/DNS a Supabase"):
                if "postgres_url" in st.secrets:
                    import socket
                    try:
                        import urllib.parse
                        url_str = st.secrets["postgres_url"].strip()
                        parsed = urllib.parse.urlparse(url_str)
                        host = parsed.hostname
                        port = parsed.port or 5432
                        
                        st.write(f"Intentando resolver IP de `{host}`...")
                        addr_info = socket.getaddrinfo(host, port)
                        st.success(f"✅ Resolvió correctamente. IPs encontradas:")
                        for addr in addr_info:
                            st.write(f"- `{addr[4][0]}` (Familia: {addr[0]}, Protocolo: {addr[2]})")
                            
                        st.write(f"Intentando abrir puerto TCP `{port}` en `{host}`...")
                        s = socket.create_connection((host, port), timeout=5)
                        s.close()
                        st.success("✅ ¡Puerto TCP abierto con éxito! La red de Streamlit puede conectarse a Supabase.")
                    except Exception as te:
                        st.error(f"❌ Falló la prueba de red: {te}")
                else:
                    st.warning("No hay URL configurado para probar.")
                    
        with c_test2:
            if st.button("🐘 Probar Conexión Completa Psycopg2"):
                if "postgres_url" in st.secrets:
                    try:
                        url_str = st.secrets["postgres_url"].strip()
                        st.write("Estableciendo conexión con psycopg2...")
                        conn = psycopg2.connect(url_str)
                        st.success("✅ ¡Conexión establecida con éxito!")
                        c = conn.cursor()
                        c.execute("SELECT version()")
                        ver = c.fetchone()[0]
                        st.write(f"Versión de base de datos: `{ver}`")
                        conn.close()
                    except Exception as pge:
                        st.error(f"❌ Falló conexión con psycopg2: {pge}")
                else:
                    st.warning("No hay URL configurado para probar.")
            
st.markdown('</div>', unsafe_allow_html=True)