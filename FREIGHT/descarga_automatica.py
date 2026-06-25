import os
import io
import pandas as pd
import psycopg2
from datetime import datetime, timedelta, timezone
import argparse
import warnings
warnings.simplefilter(action='ignore', category=UserWarning)

# 1. Parse arguments
parser = argparse.ArgumentParser(description="Descarga automática de informes Excel de OTD Freight.")
parser.add_argument("--date", help="Fecha del informe (YYYY-MM-DD). Si se omite, se usa la fecha de ayer.", default=None)
args = parser.parse_args()

# 2. Determine target date
offset_hours = -5
local_now = datetime.now(timezone.utc) + timedelta(hours=offset_hours)

if args.date:
    fecha_filtro = args.date
else:
    # Si se corre a las 12:00 AM (o primeras horas del día), descargamos el reporte del día que acaba de terminar (ayer)
    fecha_filtro = (local_now - timedelta(days=1)).strftime("%Y-%m-%d")

print(f"Generando reporte para la fecha: {fecha_filtro}")

# 3. Load connection string from secrets
secrets_path = os.path.join(os.path.dirname(__file__), ".streamlit", "secrets.toml")
postgres_url = None
if os.path.exists(secrets_path):
    with open(secrets_path, "r", encoding="utf-8") as f:
        for line in f:
            if line.strip().startswith("postgres_url"):
                parts = line.split("=")
                if len(parts) >= 2:
                    postgres_url = "=".join(parts[1:]).strip().strip('"').strip("'")

if not postgres_url:
    print("[ERROR] No se pudo encontrar postgres_url en secrets.toml")
    exit(1)

# 4. Connect and load data
try:
    conn = psycopg2.connect(postgres_url)
    
    # Helper to load dataframes
    def load_df(table, date):
        query = f'SELECT * FROM "{table}" WHERE fecha = %s'
        return pd.read_sql_query(query, conn, params=(date,))

    df_panel = load_df("panel", fecha_filtro).drop(columns=['rowid', 'ip_log', 'status_dia'], errors='ignore').rename(columns={'operador': 'chofer', 'tracto': 'camion'})
    if 'fecha' in df_panel.columns:
        df_panel['fecha'] = pd.to_datetime(df_panel['fecha']).dt.strftime('%Y-%m-%d')
    if 'carta_porte' in df_panel.columns:
        df_panel['carta_porte'] = df_panel['carta_porte'].map({True: 'SI', False: 'NO'})
    if 'manifiesto' in df_panel.columns:
        df_panel['manifiesto'] = df_panel['manifiesto'].map({True: 'SI', False: 'NO'})
        
    df_gastos = load_df("gastos", fecha_filtro).drop(columns=['rowid'], errors='ignore').rename(columns={'operador': 'chofer', 'tracto': 'camion'})
    if 'fecha' in df_gastos.columns:
        df_gastos['fecha'] = pd.to_datetime(df_gastos['fecha']).dt.strftime('%Y-%m-%d')
        
    df_boletas = load_df("boletas", fecha_filtro).drop(columns=['rowid'], errors='ignore').rename(columns={'operador': 'chofer', 'tracto': 'camion'})
    if 'fecha' in df_boletas.columns:
        df_boletas['fecha'] = pd.to_datetime(df_boletas['fecha']).dt.strftime('%Y-%m-%d')
        
    conn.close()
except Exception as e:
    print(f"[ERROR] Conexión a la base de datos o consulta fallida: {e}")
    exit(1)

# 5. Define output folder and path
output_dir = r"C:\Users\famed\Downloads\ERP\Reportes_Diarios"
os.makedirs(output_dir, exist_ok=True)
output_path = os.path.join(output_dir, f"Reporte_Operaciones_{fecha_filtro}.xlsx")

# 6. Generate Excel
try:
    with pd.ExcelWriter(output_path, engine='xlsxwriter') as writer:
        df_panel.to_excel(writer, sheet_name='PANEL', index=False)
        df_gastos.to_excel(writer, sheet_name='GASTOS', index=False)
        df_boletas.to_excel(writer, sheet_name='BOLETAS', index=False)
    print(f"[OK] Reporte generado y guardado exitosamente en:\n{output_path}")
except Exception as e:
    print(f"[ERROR] Falló la creación del archivo Excel: {e}")
    exit(1)
