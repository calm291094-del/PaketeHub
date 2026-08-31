import http.server
import json
import os
import sys
import urllib.parse
import mimetypes
import csv
import io
import shutil
from datetime import datetime, timedelta
import sqlite3
import secrets
import hashlib
import threading
import socket
import logging

# ============================================================
# CONFIGURACION DE RUTAS (COMPATIBLE CON EXE)
# ============================================================
if getattr(sys, 'frozen', False):
    BASE_DIR = os.path.dirname(sys.executable)
else:
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))

PUERTO = 8000
CARPETA_BASE = os.path.join(BASE_DIR, "Pakete")
CARPETA_COVERS = os.path.join(BASE_DIR, "covers")
CARPETA_STATIC = os.path.join(BASE_DIR, "static")
CARPETA_BACKUPS = os.path.join(BASE_DIR, "backups")
CARPETA_LOGS = os.path.join(BASE_DIR, "logs")
DB_FILE = os.path.join(BASE_DIR, "pakete.db")

# Crear carpetas
for carpeta in [CARPETA_BASE, CARPETA_COVERS, CARPETA_STATIC, CARPETA_BACKUPS, CARPETA_LOGS]:
    if not os.path.exists(carpeta):
        os.makedirs(carpeta)
os.makedirs(os.path.join(CARPETA_STATIC, "js"), exist_ok=True)
os.makedirs(os.path.join(CARPETA_STATIC, "css"), exist_ok=True)

# ============================================================
# LOGGING
# ============================================================
logging.basicConfig(
    filename=os.path.join(CARPETA_LOGS, "pakete.log"),
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger("PaketeHub")

# ============================================================
# BASE DE DATOS COMPLETA
# ============================================================
class BaseDatos:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.lock = threading.Lock()
        self.crear_tablas()
        self.configurar_defaults()

    def crear_tablas(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS sesiones (token TEXT PRIMARY KEY, usuario TEXT, creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP, expira TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS dispositivos (ip TEXT PRIMARY KEY, user_agent TEXT, primera_conexion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ultima_conexion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, nombre_dispositivo TEXT, visitas INTEGER DEFAULT 1, bloqueado INTEGER DEFAULT 0, motivo_bloqueo TEXT, fecha_bloqueo TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS descargas (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, archivo TEXT, tamano_mb REAL, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, user_agent TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS peticiones (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, tipo TEXT, contenido TEXT, detalles TEXT, estado TEXT DEFAULT 'pendiente', fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS estadisticas_diarias (fecha DATE PRIMARY KEY, visitas INTEGER DEFAULT 0, descargas INTEGER DEFAULT 0, gb_descargados REAL DEFAULT 0, dispositivos_unicos INTEGER DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS pagos (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, concepto TEXT, monto REAL, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, notas TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS codigos (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT UNIQUE, tipo TEXT, valor TEXT, usado INTEGER DEFAULT 0, fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, fecha_uso TIMESTAMP, ip_uso TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS anuncios (id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT, contenido TEXT, activo INTEGER DEFAULT 1, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS votos (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, archivo TEXT, voto INTEGER, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS logs_sistema (id INTEGER PRIMARY KEY AUTOINCREMENT, nivel TEXT, mensaje TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            self.conn.commit()

    def configurar_defaults(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT valor FROM config WHERE clave = 'admin_user'")
            if not c.fetchone():
                c.execute("INSERT INTO config (clave, valor) VALUES ('admin_user', 'root')")
            c.execute("SELECT valor FROM config WHERE clave = 'admin_pass'")
            if not c.fetchone():
                c.execute("INSERT INTO config (clave, valor) VALUES ('admin_pass', 'admin123')")
            self.conn.commit()

    def obtener_config(self, clave):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT valor FROM config WHERE clave = ?", (clave,))
            r = c.fetchone()
            return r[0] if r else None

    def set_config(self, clave, valor):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES (?, ?)", (clave, valor))
            self.conn.commit()

    def verificar_credenciales(self, usuario, password):
        u = self.obtener_config('admin_user')
        p = self.obtener_config('admin_pass')
        return usuario == u and password == p

    def cambiar_password(self, nueva_pass):
        self.set_config('admin_pass', nueva_pass)
        self.log_evento('INFO', 'Contrasena de administrador cambiada')

    def crear_sesion(self, usuario):
        with self.lock:
            token = secrets.token_urlsafe(32)
            expira = datetime.now() + timedelta(hours=24)
            c = self.conn.cursor()
            c.execute("INSERT INTO sesiones (token, usuario, expira) VALUES (?, ?, ?)", (token, usuario, expira.isoformat()))
            self.conn.commit()
            return token

    def verificar_sesion(self, token):
        if not token:
            return False
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT usuario FROM sesiones WHERE token = ? AND expira > ?", (token, datetime.now().isoformat()))
            return c.fetchone() is not None

    def eliminar_sesion(self, token):
        with self.lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM sesiones WHERE token = ?", (token,))
            self.conn.commit()

    def limpiar_sesiones_viejas(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM sesiones WHERE expira < ?", (datetime.now().isoformat(),))
            eliminadas = c.rowcount
            self.conn.commit()
            if eliminadas > 0:
                self.log_evento('INFO', f'Sesiones viejas limpiadas: {eliminadas}')
            return eliminadas

    def registrar_dispositivo(self, ip, user_agent):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE dispositivos SET ultima_conexion = CURRENT_TIMESTAMP, visitas = visitas + 1 WHERE ip = ?", (ip,))
            if c.rowcount == 0:
                nombre = self.detectar_dispositivo(user_agent)
                c.execute("INSERT INTO dispositivos (ip, user_agent, nombre_dispositivo) VALUES (?, ?, ?)", (ip, user_agent, nombre))
            self.conn.commit()

    def detectar_dispositivo(self, ua):
        ua = ua.lower()
        if 'iphone' in ua or 'ipad' in ua: return 'iOS (Apple)'
        elif 'android' in ua: return 'Android'
        elif 'windows' in ua: return 'Windows'
        elif 'macintosh' in ua: return 'MacOS'
        elif 'linux' in ua: return 'Linux'
        return 'Desconocido'

    def dispositivo_bloqueado(self, ip):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT bloqueado FROM dispositivos WHERE ip = ?", (ip,))
            r = c.fetchone()
            return r and r[0] == 1

    def bloquear_dispositivo(self, ip, motivo=""):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE dispositivos SET bloqueado = 1, motivo_bloqueo = ?, fecha_bloqueo = CURRENT_TIMESTAMP WHERE ip = ?", (motivo, ip))
            self.conn.commit()
        self.log_evento('WARN', f'Dispositivo bloqueado: {ip} - Motivo: {motivo}')

    def desbloquear_dispositivo(self, ip):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE dispositivos SET bloqueado = 0, motivo_bloqueo = NULL, fecha_bloqueo = NULL WHERE ip = ?", (ip,))
            self.conn.commit()
        self.log_evento('INFO', f'Dispositivo desbloqueado: {ip}')

    def registrar_descarga(self, ip, archivo, tamano_mb, user_agent):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO descargas (ip, archivo, tamano_mb, user_agent) VALUES (?, ?, ?, ?)", (ip, archivo, tamano_mb, user_agent))
            hoy = datetime.now().date().isoformat()
            c.execute("INSERT INTO estadisticas_diarias (fecha, visitas, descargas, gb_descargados, dispositivos_unicos) VALUES (?, 0, 1, ?, 0) ON CONFLICT(fecha) DO UPDATE SET descargas = descargas + 1, gb_descargados = gb_descargados + ?", (hoy, tamano_mb / 1024, tamano_mb / 1024))
            self.conn.commit()
        self.log_evento('INFO', f'Descarga: {archivo} ({tamano_mb} MB) desde {ip}')

    def registrar_visita(self, ip):
        with self.lock:
            c = self.conn.cursor()
            hoy = datetime.now().date().isoformat()
            c.execute("INSERT INTO estadisticas_diarias (fecha, visitas, descargas, gb_descargados, dispositivos_unicos) VALUES (?, 1, 0, 0, 1) ON CONFLICT(fecha) DO UPDATE SET visitas = visitas + 1", (hoy,))
            self.conn.commit()

    def agregar_peticion(self, ip, tipo, contenido, detalles):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO peticiones (ip, tipo, contenido, detalles) VALUES (?, ?, ?, ?)", (ip, tipo, contenido, detalles))
            self.conn.commit()
        self.log_evento('INFO', f'Nueva peticion desde {ip}: {contenido}')

    def registrar_pago(self, ip, concepto, monto, notas=""):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO pagos (ip, concepto, monto, notas) VALUES (?, ?, ?, ?)", (ip, concepto, monto, notas))
            self.conn.commit()
        self.log_evento('INFO', f'Pago registrado: {concepto} - {monto} CUP de {ip}')

    def generar_codigo(self, tipo, valor):
        codigo = secrets.token_hex(6).upper()
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO codigos (codigo, tipo, valor) VALUES (?, ?, ?)", (codigo, tipo, valor))
            self.conn.commit()
        self.log_evento('INFO', f'Codigo generado: {codigo} (tipo: {tipo})')
        return codigo

    def validar_codigo(self, codigo, ip):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT id, usado FROM codigos WHERE codigo = ?", (codigo,))
            r = c.fetchone()
            if r and r[1] == 0:
                c.execute("UPDATE codigos SET usado = 1, fecha_uso = CURRENT_TIMESTAMP, ip_uso = ? WHERE id = ?", (ip, r[0]))
                self.conn.commit()
                return True
            return False

    def agregar_anuncio(self, titulo, contenido):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO anuncios (titulo, contenido) VALUES (?, ?)", (titulo, contenido))
            self.conn.commit()
        self.log_evento('INFO', f'Nuevo anuncio: {titulo}')

    def votar(self, ip, archivo, voto):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT id FROM votos WHERE ip = ? AND archivo = ?", (ip, archivo))
            if c.fetchone():
                c.execute("UPDATE votos SET voto = ? WHERE ip = ? AND archivo = ?", (voto, ip, archivo))
            else:
                c.execute("INSERT INTO votos (ip, archivo, voto) VALUES (?, ?, ?)", (ip, archivo, voto))
            self.conn.commit()

    def log_evento(self, nivel, mensaje):
        try:
            with self.lock:
                c = self.conn.cursor()
                c.execute("INSERT INTO logs_sistema (nivel, mensaje) VALUES (?, ?)", (nivel, mensaje))
                self.conn.commit()
        except:
            pass

    def backup_db(self):
        fecha = datetime.now().strftime('%Y%m%d_%H%M%S')
        destino = os.path.join(CARPETA_BACKUPS, f'pakete_backup_{fecha}.db')
        try:
            with self.lock:
                self.conn.commit()
            shutil.copy2(DB_FILE, destino)
            self.log_evento('INFO', f'Backup creado: {destino}')
            return destino
        except Exception as e:
            self.log_evento('ERROR', f'Error en backup: {str(e)}')
            return None

    def obtener_estadisticas(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT ip, COUNT(*) as td, SUM(tamano_mb) as tm FROM descargas GROUP BY ip ORDER BY td DESC LIMIT 10")
            top = c.fetchall()
            c.execute("SELECT ip, nombre_dispositivo, ultima_conexion, visitas, bloqueado, motivo_bloqueo FROM dispositivos ORDER BY ultima_conexion DESC LIMIT 20")
            devs = c.fetchall()
            c.execute("SELECT SUM(visitas), SUM(descargas), SUM(gb_descargados) FROM estadisticas_diarias")
            gen = c.fetchone()
            c.execute("SELECT fecha, visitas, descargas, gb_descargados FROM estadisticas_diarias WHERE fecha >= date('now', '-7 days') ORDER BY fecha ASC")
            dias = c.fetchall()
            c.execute("SELECT COUNT(*) FROM peticiones WHERE estado = 'pendiente'")
            pend = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM dispositivos WHERE bloqueado = 1")
            bloq = c.fetchone()[0]
            c.execute("SELECT SUM(monto) FROM pagos")
            total_ingresos = c.fetchone()[0] or 0
            c.execute("SELECT SUM(monto) FROM pagos WHERE fecha >= date('now', '-7 days')")
            ingresos_semana = c.fetchone()[0] or 0
            return {
                "top_descargadores": [{"ip": r[0], "descargas": r[1], "mb": r[2]} for r in top],
                "dispositivos": [{"ip": r[0], "dispositivo": r[1], "ultima_conexion": r[2], "visitas": r[3], "bloqueado": r[4], "motivo": r[5]} for r in devs],
                "generales": {"visitas": gen[0] or 0, "descargas": gen[1] or 0, "gb": round(gen[2] or 0, 2)},
                "ultimos_7_dias": [{"fecha": r[0], "visitas": r[1], "descargas": r[2], "gb": r[3]} for r in dias],
                "peticiones_pendientes": pend,
                "dispositivos_bloqueados": bloq,
                "ingresos_totales": round(total_ingresos, 2),
                "ingresos_semana": round(ingresos_semana, 2),
                "ingresos_estimados_mes": round(ingresos_semana * 4.33, 2)
            }

    def obtener_peticiones(self, estado='todas'):
        with self.lock:
            c = self.conn.cursor()
            if estado == 'todas':
                c.execute("SELECT * FROM peticiones ORDER BY fecha DESC")
            else:
                c.execute("SELECT * FROM peticiones WHERE estado = ? ORDER BY fecha DESC", (estado,))
            return c.fetchall()

    def actualizar_peticion(self, id_p, nuevo_estado):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE peticiones SET estado = ? WHERE id = ?", (nuevo_estado, id_p))
            self.conn.commit()

    def obtener_pagos(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT * FROM pagos ORDER BY fecha DESC LIMIT 50")
            return c.fetchall()

    def obtener_codigos(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT * FROM codigos ORDER BY fecha_creacion DESC LIMIT 50")
            return c.fetchall()

    def obtener_anuncios(self, solo_activos=True):
        with self.lock:
            c = self.conn.cursor()
            if solo_activos:
                c.execute("SELECT * FROM anuncios WHERE activo = 1 ORDER BY fecha DESC LIMIT 10")
            else:
                c.execute("SELECT * FROM anuncios ORDER BY fecha DESC LIMIT 20")
            return c.fetchall()

    def toggle_anuncio(self, id_a):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE anuncios SET activo = CASE WHEN activo = 1 THEN 0 ELSE 1 END WHERE id = ?", (id_a,))
            self.conn.commit()

    def obtener_logs(self, limite=100):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT * FROM logs_sistema ORDER BY fecha DESC LIMIT ?", (limite,))
            return c.fetchall()

    def obtener_historial_ip(self, ip):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT archivo, tamano_mb, fecha FROM descargas WHERE ip = ? ORDER BY fecha DESC LIMIT 20", (ip,))
            return c.fetchall()

    def obtener_votos_archivo(self, archivo):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT SUM(voto), COUNT(*) FROM votos WHERE archivo = ?", (archivo,))
            r = c.fetchone()
            return {"total": r[0] or 0, "cantidad": r[1] or 0}

    def exportar_csv(self, tipo):
        with self.lock:
            c = self.conn.cursor()
            output = io.StringIO()
            writer = csv.writer(output)
            if tipo == 'descargas':
                writer.writerow(['IP', 'Archivo', 'Tamano_MB', 'Fecha', 'User_Agent'])
                c.execute("SELECT ip, archivo, tamano_mb, fecha, user_agent FROM descargas")
            elif tipo == 'pagos':
                writer.writerow(['IP', 'Concepto', 'Monto', 'Fecha', 'Notas'])
                c.execute("SELECT ip, concepto, monto, fecha, notas FROM pagos")
            elif tipo == 'dispositivos':
                writer.writerow(['IP', 'Dispositivo', 'Primera_Conexion', 'Ultima_Conexion', 'Visitas', 'Bloqueado'])
                c.execute("SELECT ip, nombre_dispositivo, primera_conexion, ultima_conexion, visitas, bloqueado FROM dispositivos")
            else:
                return ""
            for row in c.fetchall():
                writer.writerow(row)
            return output.getvalue()


db = BaseDatos()

# Limpieza inicial de sesiones viejas
db.limpiar_sesiones_viejas()
db.log_evento('INFO', 'Servidor iniciado')

# ============================================================
# HTML PAGINA PRINCIPAL (con anuncios, filtros, votaciones)
# ============================================================
HTML_PAGINA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Mi Pakete - Centro Multimedia</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--p:#00ff88;--s:#00d4ff;--a:#ff00ff;--d:#ff3366;--w:#ffaa00;--dk:#050816;--l:#e0e6ed;--g:rgba(10,14,39,0.75)}
body{font-family:'Segoe UI',Arial,sans-serif;background:var(--dk);color:var(--l);min-height:100vh;overflow-x:hidden}
#mc{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;opacity:0.12}
.go{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;background-image:linear-gradient(rgba(0,255,136,0.03) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,0.03) 1px,transparent 1px);background-size:50px 50px;animation:gm 20s linear infinite}
@keyframes gm{0%{transform:translate(0,0)}100%{transform:translate(50px,50px)}}
.ct{max-width:1200px;margin:0 auto;padding:24px 20px;position:relative;z-index:1}
.hd{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;padding:24px 32px;background:var(--g);backdrop-filter:blur(20px);border-radius:16px;border:1px solid rgba(0,255,136,0.2);box-shadow:0 0 30px rgba(0,255,136,0.1);margin-bottom:40px;position:relative;overflow:hidden}
.hd::before{content:'';position:absolute;top:0;left:-100%;width:100%;height:2px;background:linear-gradient(90deg,transparent,var(--p),transparent);animation:sc 3s linear infinite}
@keyframes sc{0%{left:-100%}100%{left:100%}}
.lg h1{font-size:32px;font-weight:800;background:linear-gradient(135deg,var(--p),var(--s),var(--a));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;font-family:'Courier New',monospace}
.lg span{font-size:14px;color:var(--p);margin-top:4px;opacity:0.7;font-family:'Courier New',monospace;display:block}
.ha{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.bt{padding:10px 20px;border-radius:8px;border:none;font-weight:600;font-size:14px;cursor:pointer;transition:all 0.3s;font-family:'Courier New',monospace}
.bp{background:linear-gradient(135deg,var(--p),var(--s));color:var(--dk);box-shadow:0 4px 20px rgba(0,255,136,0.3)}
.bp:hover{transform:translateY(-2px);box-shadow:0 6px 30px rgba(0,255,136,0.5)}
.bg2{background:rgba(0,255,136,0.1);color:var(--p);border:1px solid rgba(0,255,136,0.3)}
.bg2:hover{background:rgba(0,255,136,0.2);border-color:var(--p)}
.st{margin-bottom:48px}
.stt{display:flex;align-items:center;gap:12px;margin-bottom:24px;font-size:24px;font-weight:700;color:var(--l);font-family:'Courier New',monospace}
.stt::before{content:'>';color:var(--p);animation:bl 1s infinite}
@keyframes bl{0%,50%{opacity:1}51%,100%{opacity:0}}
.bdg{background:linear-gradient(135deg,var(--a),var(--s));font-size:10px;padding:4px 14px;border-radius:4px;color:var(--dk);letter-spacing:1px;font-weight:700}
.cw{position:relative;overflow:hidden;border-radius:16px;background:var(--g);backdrop-filter:blur(15px);border:1px solid rgba(0,255,136,0.2);box-shadow:0 0 40px rgba(0,255,136,0.1)}
.ctrk{display:flex;transition:transform 0.8s cubic-bezier(0.4,0,0.2,1)}
.csl{min-width:100%;display:flex;align-items:center;gap:32px;padding:40px}
.csl img{width:160px;height:220px;object-fit:cover;border-radius:12px;border:2px solid var(--p);box-shadow:0 0 30px rgba(0,255,136,0.3);transition:all 0.4s;flex-shrink:0}
.csl img:hover{transform:scale(1.05) rotate(2deg)}
.ci{flex:1;min-width:0}
.ci h3{font-size:26px;font-weight:700;color:var(--l);margin-bottom:12px;font-family:'Courier New',monospace}
.ci p{color:rgba(224,230,237,0.7);font-size:15px;line-height:1.6;margin-bottom:16px}
.tgs{display:flex;gap:8px;flex-wrap:wrap}
.tg{background:rgba(0,255,136,0.15);color:var(--p);padding:6px 16px;border-radius:4px;font-size:12px;font-weight:600;border:1px solid rgba(0,255,136,0.3);font-family:'Courier New',monospace}
.cds{display:flex;justify-content:center;gap:8px;padding:16px 0 4px 0}
.cds button{width:10px;height:10px;border-radius:50%;border:none;background:rgba(0,255,136,0.3);cursor:pointer;transition:all 0.3s}
.cds button.act{background:var(--p);box-shadow:0 0 20px var(--p);width:32px;border-radius:10px}
.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:16px}
.sc{background:var(--g);backdrop-filter:blur(15px);border:1px solid rgba(0,255,136,0.2);border-radius:12px;padding:24px 20px;text-align:center;transition:all 0.3s;position:relative;overflow:hidden}
.sc::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--p),var(--s),var(--a));transform:scaleX(0);transition:transform 0.3s}
.sc:hover::before{transform:scaleX(1)}
.sc:hover{transform:translateY(-4px);border-color:var(--p);box-shadow:0 0 30px rgba(0,255,136,0.2)}
.si{font-size:30px;margin-bottom:8px}
.sv{font-size:26px;font-weight:800;color:var(--p);font-family:'Courier New',monospace;text-shadow:0 0 20px rgba(0,255,136,0.5)}
.sl2{font-size:12px;color:rgba(224,230,237,0.6);margin-top:6px;font-family:'Courier New',monospace}
.ex{background:var(--g);backdrop-filter:blur(15px);border-radius:16px;border:1px solid rgba(0,255,136,0.2);padding:28px;box-shadow:0 0 40px rgba(0,255,136,0.1)}
.eh{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px;margin-bottom:24px}
.eh h2{font-family:'Courier New',monospace;color:var(--p);font-size:20px;margin:0}
.sb{background:rgba(0,0,0,0.5);border:1px solid rgba(0,255,136,0.3);border-radius:8px;padding:10px 20px;display:flex;align-items:center;transition:all 0.3s}
.sb:focus-within{border-color:var(--p);box-shadow:0 0 30px rgba(0,255,136,0.3)}
.sb input{background:transparent;border:none;color:var(--l);padding:6px 12px;width:220px;outline:none;font-size:14px;font-family:'Courier New',monospace}
.flts{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:16px}
.flt{padding:6px 14px;border-radius:6px;background:rgba(0,255,136,0.08);border:1px solid rgba(0,255,136,0.2);cursor:pointer;font-size:12px;font-family:'Courier New',monospace;color:var(--l);transition:all 0.2s}
.flt.act,.flt:hover{background:rgba(0,255,136,0.2);border-color:var(--p);color:var(--p)}
.cp{margin:8px 0}
.cpt{cursor:pointer;padding:10px 18px;border-radius:8px;background:rgba(0,255,136,0.1);border:1px solid rgba(0,255,136,0.3);font-weight:600;color:var(--p);transition:all 0.2s;display:inline-block;user-select:none;font-family:'Courier New',monospace}
.cpt:hover{background:rgba(0,255,136,0.2);border-color:var(--p)}
.cpc{padding-left:28px;border-left:2px solid rgba(0,255,136,0.3);margin-left:14px;display:none}
.cpc.ab{display:block}
.ar{padding:8px 16px;margin:4px 0;border-radius:8px;transition:all 0.15s;border-left:3px solid transparent}
.ar:hover{background:rgba(0,255,136,0.1);border-left-color:var(--p)}
.ar a{color:var(--l);text-decoration:none;display:flex;align-items:center;gap:8px;font-size:15px;font-family:'Courier New',monospace}
.ar a:hover{color:var(--p);text-shadow:0 0 10px rgba(0,255,136,0.5)}
.tm{color:rgba(0,255,136,0.6);font-size:12px;font-family:'Courier New',monospace}
.vt{display:flex;gap:4px;align-items:center;margin-left:auto}
.vt button{background:none;border:1px solid rgba(0,255,136,0.3);color:var(--p);border-radius:4px;padding:2px 8px;cursor:pointer;font-size:12px;transition:all 0.2s}
.vt button:hover{background:rgba(0,255,136,0.2)}
.vc{text-align:center;color:rgba(224,230,237,0.5);padding:60px 0;font-style:italic;font-family:'Courier New',monospace}
.anc{background:var(--g);backdrop-filter:blur(15px);border:1px solid rgba(0,212,255,0.3);border-radius:12px;padding:16px 20px;margin-bottom:12px;border-left:4px solid var(--s)}
.anc h4{color:var(--s);font-family:'Courier New',monospace;margin-bottom:6px;font-size:14px}
.anc p{color:rgba(224,230,237,0.7);font-size:13px;font-family:'Courier New',monospace}
.md{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.9);backdrop-filter:blur(10px);z-index:1000;align-items:center;justify-content:center;padding:20px}
.md.ac{display:flex}
.mdc{background:var(--g);border:1px solid var(--p);border-radius:16px;padding:32px;max-width:500px;width:100%;box-shadow:0 0 60px rgba(0,255,136,0.3);position:relative;max-height:90vh;overflow-y:auto}
.mdc::before{content:'';position:absolute;top:-1px;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--p),var(--s),var(--a));border-radius:16px 16px 0 0}
.mdc h2{margin-bottom:20px;color:var(--p);font-family:'Courier New',monospace}
.fg{margin-bottom:16px}
.fg label{display:block;margin-bottom:6px;color:rgba(224,230,237,0.7);font-size:13px;font-weight:600;font-family:'Courier New',monospace}
.fg input,.fg select,.fg textarea{width:100%;padding:10px 14px;background:rgba(0,0,0,0.5);border:1px solid rgba(0,255,136,0.3);border-radius:8px;color:var(--l);font-family:'Courier New',monospace;font-size:14px}
.fg textarea{resize:vertical;min-height:80px}
.ma{display:flex;gap:12px;margin-top:20px}
.ft{margin-top:48px;text-align:center;font-size:13px;color:rgba(224,230,237,0.4);padding-top:24px;border-top:1px solid rgba(0,255,136,0.1);font-family:'Courier New',monospace}
.ft .cr{font-size:14px;color:var(--p);text-shadow:0 0 10px rgba(0,255,136,0.3)}
.ld{display:inline-block;width:20px;height:20px;border:3px solid rgba(0,255,136,0.1);border-radius:50%;border-top-color:var(--p);animation:sp 1s ease-in-out infinite}
@keyframes sp{to{transform:rotate(360deg)}}
::-webkit-scrollbar{width:8px}::-webkit-scrollbar-track{background:var(--dk)}::-webkit-scrollbar-thumb{background:var(--p);border-radius:10px}
@media(max-width:768px){
.hd{flex-direction:column;align-items:stretch;gap:16px;padding:20px;margin-bottom:28px}
.st{margin-bottom:32px}
.csl{flex-direction:column;text-align:center;padding:24px;gap:20px}
.csl img{width:130px;height:180px}
.ci h3{font-size:22px}
.sb input{width:150px}
.ex{padding:20px}
.sg{grid-template-columns:repeat(2,1fr);gap:12px}
.ha{justify-content:center}
.eh{flex-direction:column;align-items:stretch}
.sb{width:100%}
.sb input{width:100%}
}
@media(max-width:400px){.sg{grid-template-columns:1fr 1fr}.sc{padding:16px 12px}.sv{font-size:22px}.si{font-size:24px}}
</style>
</head>
<body>
<canvas id="mc"></canvas>
<div class="go"></div>
<div class="ct">
<header class="hd">
<div class="lg"><h1>./mi_pakete</h1><span>root@multimedia:~$ ./start_server.sh</span></div>
<div class="ha">
<button class="bt bg2" id="btnPet">📝 solicitar_contenido</button>
<button class="bt bp" id="btnAdm">🔐 sudo admin</button>
</div>
</header>
<section class="st" id="secAnuncios" style="display:none">
<div class="stt">📢 ANUNCIOS</div>
<div id="listaAnuncios"></div>
</section>
<section class="st">
<div class="stt">🎬 ESTRENOS_EXCLUSIVOS <span class="bdg">NUEVO</span></div>
<div class="cw"><div class="ctrk" id="ctrk"><div class="csl" style="justify-content:center;min-height:200px"><div class="ld"></div></div></div></div>
<div class="cds" id="cds"></div>
</section>
<section class="st">
<div class="stt">💰 PLANES_Y_PRECIOS</div>
<div class="sg">
<div class="sc"><div class="si">💰</div><div class="sv">6.25 CUP</div><div class="sl2">por GB descargado</div></div>
<div class="sc"><div class="si">🌙</div><div class="sv">50 CUP</div><div class="sl2">dia ilimitado</div></div>
<div class="sc"><div class="si">📅</div><div class="sv">200 CUP</div><div class="sl2">semanal (mejor oferta)</div></div>
<div class="sc"><div class="si">📂</div><div class="sv" id="tArch">0</div><div class="sl2">archivos disponibles</div></div>
</div>
</section>
<section class="st">
<div class="stt">📂 BIBLIOTECA_COMPLETA</div>
<div class="ex">
<div class="eh">
<h2>ls -la biblioteca/</h2>
<div class="sb"><span style="color:var(--p)">🔍</span><input type="text" id="bsc" placeholder="buscar archivo..."></div>
</div>
<div class="flts">
<div class="flt act" data-f="todos">📁 todos</div>
<div class="flt" data-f="video">🎬 videos</div>
<div class="flt" data-f="audio">🎵 musica</div>
<div class="flt" data-f="imagen">🖼️ imagenes</div>
<div class="flt" data-f="subtitulo">📝 subtitulos</div>
<div class="flt" data-f="otro">📄 otros</div>
</div>
<div id="larch"><div class="vc"><div class="ld"></div><p style="margin-top:16px">cargando archivos...</p></div></div>
</div>
</section>
<div class="ft"><div class="cr">☕ Creado por <strong>Carlos A Lorenzo Marro</strong> con cafe, anime e IA 🌸🤖</div></div>
</div>
<div class="md" id="mPet">
<div class="mdc">
<h2>📝 solicitar_contenido.sh</h2>
<p style="color:rgba(224,230,237,0.7);margin-bottom:20px">No encuentras lo que buscas? Dinoslo y lo agregaremos.</p>
<form id="fPet">
<div class="fg"><label>tipo_contenido:</label>
<select name="tipo" required><option value="">selecciona...</option><option value="pelicula">🎬 pelicula</option><option value="serie">📺 serie</option><option value="musica">🎵 musica</option><option value="otro">📦 otro</option></select></div>
<div class="fg"><label>nombre:</label><input type="text" name="contenido" placeholder="Ej: The Batman 2022" required></div>
<div class="fg"><label>detalles:</label><textarea name="detalles" placeholder="temporada, episodio, calidad..."></textarea></div>
<div class="ma"><button type="button" class="bt bg2" id="btnCanPet">cancelar</button><button type="submit" class="bt bp">enviar</button></div>
</form>
</div>
</div>
<div class="md" id="mLog">
<div class="mdc">
<h2>🔐 autenticacion_root</h2>
<form id="fLog">
<div class="fg"><label>usuario:</label><input type="text" name="usuario" value="root" required></div>
<div class="fg"><label>contrasena:</label><input type="password" name="password" required></div>
<div class="ma"><button type="button" class="bt bg2" id="btnCanLog">cancelar</button><button type="submit" class="bt bp" id="btnSubLog">ingresar</button></div>
</form>
</div>
</div>
<script>
(function(){
var cv=document.getElementById('mc'),cx=cv.getContext('2d');
cv.width=window.innerWidth;cv.height=window.innerHeight;
var ch='01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン';
var fs=14,cl=Math.floor(cv.width/fs),dr=[],i;
for(i=0;i<cl;i++)dr[i]=1;
setInterval(function(){cx.fillStyle='rgba(5,8,22,0.05)';cx.fillRect(0,0,cv.width,cv.height);cx.fillStyle='#00ff88';cx.font=fs+'px monospace';for(var j=0;j<dr.length;j++){var t=ch[Math.floor(Math.random()*ch.length)];cx.fillText(t,j*fs,dr[j]*fs);if(dr[j]*fs>cv.height&&Math.random()>0.975)dr[j]=0;dr[j]++;}},50);
window.addEventListener('resize',function(){cv.width=window.innerWidth;cv.height=window.innerHeight;});
var si2=0,sd=[],api=null;
function cargarCovers(){fetch('/api/covers').then(function(r){return r.json()}).then(function(d){sd=d;var tk=document.getElementById('ctrk'),dt=document.getElementById('cds');if(d.length===0){tk.innerHTML='<div class="csl" style="justify-content:center;min-height:200px"><div style="text-align:center;color:rgba(224,230,237,0.5)"><div style="font-size:48px;margin-bottom:12px">🎬</div><p>Proximamente nuevos estrenos...</p></div></div>';dt.innerHTML='';return;}var h='';for(var k=0;k<d.length;k++){var nb=d[k].name.replace(/\.[^.]+$/,'');h+='<div class="csl"><img src="'+d[k].url+'" alt="'+nb+'" loading="lazy"><div class="ci"><h3>'+nb+'</h3><p>Estreno exclusivo disponible. Descargalo ahora con la mejor calidad.</p><div class="tgs"><span class="tg">🔥 disponible</span><span class="tg">⭐ exclusivo</span></div></div></div>';}tk.innerHTML=h;var dh='';for(var m=0;m<d.length;m++){dh+='<button class="'+(m===0?'act':'')+'" data-i="'+m+'"></button>';}dt.innerHTML=dh;var btns=dt.querySelectorAll('button');for(var n=0;n<btns.length;n++){(function(btn){btn.addEventListener('click',function(){irA(parseInt(btn.getAttribute('data-i')));});})(btns[n]);}if(d.length>1){if(api)clearInterval(api);api=setInterval(function(){irA((si2+1)%d.length)},5000);}}).catch(function(){});}
function irA(idx){var tk=document.getElementById('ctrk'),dts=document.querySelectorAll('#cds button'),tot=sd.length;if(tot===0)return;if(idx<0)idx=tot-1;if(idx>=tot)idx=0;si2=idx;tk.style.transform='translateX(-'+(idx*100)+'%)';for(var q=0;q<dts.length;q++){if(q===idx)dts[q].className='act';else dts[q].className='';}}
function cargarAnuncios(){fetch('/api/anuncios').then(function(r){return r.json()}).then(function(d){if(d.length===0){document.getElementById('secAnuncios').style.display='none';return;}document.getElementById('secAnuncios').style.display='block';var h='';for(var i=0;i<d.length;i++){h+='<div class="anc"><h4>📢 '+d[i][1]+'</h4><p>'+d[i][2]+'</p></div>';}document.getElementById('listaAnuncios').innerHTML=h;}).catch(function(){});}
var cont=document.getElementById('larch'),bsc=document.getElementById('bsc'),tA=document.getElementById('tArch');
var filtroActual='todos';
function getTipo(n){var e=n.split('.').pop().toLowerCase();if(['mp4','avi','mkv','mov','wmv','webm'].indexOf(e)>=0)return'video';if(['mp3','wav','flac','aac','ogg'].indexOf(e)>=0)return'audio';if(['jpg','jpeg','png','gif','bmp','webp'].indexOf(e)>=0)return'imagen';if(['srt','ass','ssa','sub'].indexOf(e)>=0)return'subtitulo';return'otro';}
function getIco(n){var e=n.split('.').pop().toLowerCase();if(['mp4','avi','mkv','mov','wmv','webm'].indexOf(e)>=0)return'🎬';if(['mp3','wav','flac','aac','ogg'].indexOf(e)>=0)return'🎵';if(['jpg','jpeg','png','gif','bmp','webp'].indexOf(e)>=0)return'🖼️';if(['srt','ass','ssa','sub'].indexOf(e)>=0)return'📝';if(['zip','rar','7z','tar','gz'].indexOf(e)>=0)return'📦';return'📄';}
function esc(t){var d=document.createElement('div');d.textContent=t;return d.innerHTML;}
function renderArbol(items,nv){nv=nv||0;var h='';for(var i=0;i<items.length;i++){var it=items[i],mg=nv*20;if(it.type==='folder'){var id='f'+Date.now()+'_'+Math.random().toString(36).substr(2,5);h+='<div class="cp" style="margin-left:'+mg+'px" data-tipo="folder"><div class="cpt" data-f="'+id+'">📁 '+esc(it.name)+'</div><div class="cpc" id="'+id+'">';if(it.children&&it.children.length>0)h+=renderArbol(it.children,nv+1);else h+='<div style="color:rgba(224,230,237,0.5);font-size:13px;padding:8px 12px">📭 carpeta vacia</div>';h+='</div></div>';}else{var ic=getIco(it.name);var tp=getTipo(it.name);h+='<div class="ar" style="margin-left:'+mg+'px" data-tipo="'+tp+'"><a href="/download/'+encodeURIComponent(it.path)+'">'+ic+' <span style="flex:1">'+esc(it.name)+'</span> <span class="tm">('+it.size+' MB)</span></a><div class="vt"><button data-voto="1" data-archivo="'+esc(it.name)+'">👍</button><button data-voto="-1" data-archivo="'+esc(it.name)+'">👎</button></div></div>';}}return h;}
document.addEventListener('click',function(e){var el=e.target;while(el&&el!==document.body){if(el.classList&&el.classList.contains('cpt')){var fid=el.getAttribute('data-f'),fc=document.getElementById(fid);if(fc){fc.classList.toggle('ab');var ab=fc.classList.contains('ab');var txt=el.textContent.replace(/[📂📁]\s*/,'');el.textContent=(ab?'📂 ':'📁 ')+txt;}return;}if(el.tagName==='BUTTON'&&el.getAttribute('data-voto')){var arch=el.getAttribute('data-archivo');var voto=parseInt(el.getAttribute('data-voto'));fetch('/api/votar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({archivo:arch,voto:voto})});el.textContent=voto===1?'👍 ✓':'👎 ✓';el.disabled=true;return;}el=el.parentElement;}});
function aplicarFiltro(){var ars=document.querySelectorAll('.ar');for(var i=0;i<ars.length;i++){var tp=ars[i].getAttribute('data-tipo');if(filtroActual==='todos'||tp===filtroActual){ars[i].style.display='';}else{ars[i].style.display='none';}}}
var flts=document.querySelectorAll('.flt');
for(var f=0;f<flts.length;f++){(function(fl){fl.addEventListener('click',function(){for(var x=0;x<flts.length;x++)flts[x].classList.remove('act');fl.classList.add('act');filtroActual=fl.getAttribute('data-f');aplicarFiltro();});})(flts[f]);}
function filtrar(){var t=bsc.value.toLowerCase().trim();var ars=document.querySelectorAll('.ar'),cps=document.querySelectorAll('.cp');var j;if(t===''){for(j=0;j<ars.length;j++)ars[j].style.display='';for(j=0;j<cps.length;j++)cps[j].style.display='';var ccs=document.querySelectorAll('.cpc');for(j=0;j<ccs.length;j++)ccs[j].classList.remove('ab');aplicarFiltro();return;}for(j=0;j<ars.length;j++)ars[j].style.display='none';for(j=0;j<cps.length;j++)cps[j].style.display='none';for(j=0;j<ars.length;j++){if(ars[j].textContent.toLowerCase().indexOf(t)>=0){ars[j].style.display='';var p=ars[j].parentElement;while(p){if(p.classList&&p.classList.contains('cpc')){p.classList.add('ab');if(p.parentElement&&p.parentElement.classList.contains('cp'))p.parentElement.style.display='';}p=p.parentElement;}}}}
function cargarArchivos(){fetch('/api/list').then(function(r){return r.json()}).then(function(d){if(d.length===0){cont.innerHTML='<div class="vc"><div style="font-size:48px;margin-bottom:12px">📭</div><p>No hay archivos disponibles. Vuelve pronto.</p></div>';tA.textContent='0';}else{cont.innerHTML=renderArbol(d);tA.textContent=document.querySelectorAll('.ar').length;aplicarFiltro();}}).catch(function(e){cont.innerHTML='<div class="vc">❌ error: '+e+'</div>';});}
document.getElementById('btnPet').addEventListener('click',function(){document.getElementById('mPet').classList.add('ac');});
document.getElementById('btnCanPet').addEventListener('click',function(){document.getElementById('mPet').classList.remove('ac');});
document.getElementById('btnCanLog').addEventListener('click',function(){document.getElementById('mLog').classList.remove('ac');});
document.getElementById('btnAdm').addEventListener('click',function(){var tk=localStorage.getItem('admin_token');if(tk){fetch('/api/verificar-token?token='+encodeURIComponent(tk)).then(function(r){return r.json()}).then(function(d){if(d.valido){window.location.href='/admin?token='+encodeURIComponent(tk);}else{localStorage.removeItem('admin_token');document.getElementById('mLog').classList.add('ac');}}).catch(function(){localStorage.removeItem('admin_token');document.getElementById('mLog').classList.add('ac');});}else{document.getElementById('mLog').classList.add('ac');}});
bsc.addEventListener('input',filtrar);
document.getElementById('fPet').addEventListener('submit',function(e){e.preventDefault();var fd=new FormData(e.target);fetch('/api/peticion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tipo:fd.get('tipo'),contenido:fd.get('contenido'),detalles:fd.get('detalles')})}).then(function(r){if(r.ok){alert('✅ solicitud enviada exitosamente.');document.getElementById('mPet').classList.remove('ac');e.target.reset();}}).catch(function(){alert('❌ error al enviar solicitud');});});
document.getElementById('fLog').addEventListener('submit',function(e){e.preventDefault();var fd=new FormData(e.target);var btn=document.getElementById('btnSubLog');btn.disabled=true;btn.textContent='verificando...';localStorage.removeItem('admin_token');fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({usuario:fd.get('usuario'),password:fd.get('password')})}).then(function(r){return r.json()}).then(function(d){btn.disabled=false;btn.textContent='ingresar';if(d.success&&d.token){localStorage.setItem('admin_token',d.token);document.getElementById('mLog').classList.remove('ac');setTimeout(function(){window.location.href='/admin?token='+encodeURIComponent(d.token);},150);}else{alert('❌ credenciales incorrectas');}}).catch(function(err){btn.disabled=false;btn.textContent='ingresar';alert('❌ error: '+err);});});
cargarCovers();cargarArchivos();cargarAnuncios();fetch('/api/registrar-visita',{method:'POST'});
})();
</script>
</body>
</html>"""

# ============================================================
# HTML PANEL ADMIN COMPLETO
# ============================================================
HTML_ADMIN = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>root@pakete:~# panel_admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--p:#00ff88;--s:#00d4ff;--a:#ff00ff;--d:#ff3366;--w:#ffaa00;--dk:#050816;--l:#e0e6ed;--g:rgba(10,14,39,0.75)}
body{font-family:'Segoe UI',Arial,sans-serif;background:var(--dk);color:var(--l);min-height:100vh}
#mc{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;opacity:0.12}
.ct{max-width:1400px;margin:0 auto;padding:24px 20px;position:relative;z-index:1}
.hd{display:flex;justify-content:space-between;align-items:center;padding:24px 32px;background:var(--g);backdrop-filter:blur(20px);border-radius:16px;border:1px solid var(--p);margin-bottom:32px;box-shadow:0 0 30px rgba(0,255,136,0.2);flex-wrap:wrap;gap:16px}
.hd h1{font-size:24px;background:linear-gradient(135deg,var(--p),var(--a));-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-family:'Courier New',monospace}
.bt{padding:8px 16px;border-radius:8px;border:none;font-weight:600;cursor:pointer;transition:all 0.3s;font-family:'Courier New',monospace;font-size:12px}
.bp{background:linear-gradient(135deg,var(--p),var(--s));color:var(--dk)}
.bd{background:rgba(255,51,102,0.2);color:var(--d);border:1px solid var(--d)}
.bg2{background:rgba(0,255,136,0.1);color:var(--p);border:1px solid rgba(0,255,136,0.3)}
.bs2{background:rgba(0,255,136,0.2);color:var(--p);border:1px solid var(--p)}
.nav{display:flex;gap:8px;margin-bottom:24px;flex-wrap:wrap}
.nav button{padding:8px 16px;border-radius:8px;background:rgba(0,255,136,0.08);border:1px solid rgba(0,255,136,0.2);color:var(--l);cursor:pointer;font-family:'Courier New',monospace;font-size:12px;transition:all 0.2s}
.nav button.act,.nav button:hover{background:rgba(0,255,136,0.2);border-color:var(--p);color:var(--p)}
.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:12px;margin-bottom:24px}
.sc{background:var(--g);backdrop-filter:blur(15px);border:1px solid rgba(0,255,136,0.2);border-radius:12px;padding:20px;position:relative;overflow:hidden;text-align:center}
.sc::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--p),var(--s),var(--a))}
.si{font-size:28px;margin-bottom:6px}
.sv{font-size:24px;font-weight:800;color:var(--p);font-family:'Courier New',monospace}
.sl2{font-size:11px;color:rgba(224,230,237,0.6);margin-top:4px;font-family:'Courier New',monospace}
.sec{display:none}
.sec.act{display:block}
.cd{background:var(--g);backdrop-filter:blur(15px);border:1px solid rgba(0,255,136,0.2);border-radius:12px;padding:24px;margin-bottom:24px}
.cd h2{font-size:18px;margin-bottom:16px;color:var(--p);font-family:'Courier New',monospace}
table{width:100%;border-collapse:collapse}
th,td{padding:10px;text-align:left;border-bottom:1px solid rgba(0,255,136,0.1);font-family:'Courier New',monospace;font-size:12px}
th{color:var(--p);font-weight:600;text-transform:uppercase;font-size:10px}
td{color:var(--l)}
.db{background:rgba(0,255,136,0.15);color:var(--p);padding:3px 10px;border-radius:4px;font-size:10px;font-weight:600}
.sp{background:rgba(255,170,0,0.15);color:var(--w);padding:3px 10px;border-radius:4px;font-size:10px}
.scc{background:rgba(0,255,136,0.15);color:var(--p);padding:3px 10px;border-radius:4px;font-size:10px}
.sr{background:rgba(255,51,102,0.15);color:var(--d);padding:3px 10px;border-radius:4px;font-size:10px}
.sb2{background:rgba(255,51,102,0.15);color:var(--d);padding:3px 10px;border-radius:4px;font-size:10px}
.sa{background:rgba(0,255,136,0.15);color:var(--p);padding:3px 10px;border-radius:4px;font-size:10px}
.ab2{padding:4px 10px;border-radius:4px;border:none;cursor:pointer;font-size:10px;font-family:'Courier New',monospace;margin:2px}
.ab2:hover{transform:scale(1.05)}
.fg{margin-bottom:12px}
.fg label{display:block;margin-bottom:4px;color:rgba(224,230,237,0.7);font-size:12px;font-weight:600;font-family:'Courier New',monospace}
.fg input,.fg select,.fg textarea{width:100%;padding:8px 12px;background:rgba(0,0,0,0.5);border:1px solid rgba(0,255,136,0.3);border-radius:6px;color:var(--l);font-family:'Courier New',monospace;font-size:13px}
.fg textarea{resize:vertical;min-height:60px}
.tbs{display:flex;gap:8px;margin-bottom:16px;flex-wrap:wrap}
.tb{padding:6px 14px;border-radius:6px;background:rgba(0,255,136,0.1);border:1px solid rgba(0,255,136,0.3);cursor:pointer;font-size:12px;font-family:'Courier New',monospace;color:var(--l);transition:all 0.2s}
.tb.ac{background:rgba(0,255,136,0.2);border-color:var(--p);color:var(--p)}
.fa{margin-top:30px;text-align:center;font-size:12px;color:rgba(224,230,237,0.3);font-family:'Courier New',monospace;padding-top:15px;border-top:1px solid rgba(0,255,136,0.1)}
@media(max-width:768px){.sg{grid-template-columns:repeat(2,1fr)}.hd{padding:16px}}
</style>
</head>
<body>
<canvas id="mc"></canvas>
<div class="ct">
<header class="hd">
<h1>root@pakete:~# panel_admin</h1>
<div style="display:flex;gap:12px;flex-wrap:wrap">
<button class="bt bg2" id="btnVol">🏠 volver</button>
<button class="bt bp" id="btnBackup">💾 backup</button>
<button class="bt bd" id="btnOut">🚪 cerrar_sesion</button>
</div>
</header>
<div class="nav">
<button class="act" data-sec="dashboard">📊 dashboard</button>
<button data-sec="dispositivos">📱 dispositivos</button>
<button data-sec="peticiones">📝 peticiones</button>
<button data-sec="pagos">💳 pagos</button>
<button data-sec="codigos">🎫 codigos</button>
<button data-sec="anuncios">📢 anuncios</button>
<button data-sec="logs">📋 logs</button>
<button data-sec="config">⚙️ config</button>
</div>
<div class="sg">
<div class="sc"><div class="si">👥</div><div class="sv" id="tVis">0</div><div class="sl2">visitas</div></div>
<div class="sc"><div class="si">📥</div><div class="sv" id="tDes">0</div><div class="sl2">descargas</div></div>
<div class="sc"><div class="si">💾</div><div class="sv" id="tGB">0</div><div class="sl2">gb_descargados</div></div>
<div class="sc"><div class="si">💰</div><div class="sv" id="tIng">0</div><div class="sl2">ingresos_totales</div></div>
<div class="sc"><div class="si">📈</div><div class="sv" id="tIngM">0</div><div class="sl2">estimado_mes</div></div>
<div class="sc"><div class="si">📝</div><div class="sv" id="tPet">0</div><div class="sl2">peticiones</div></div>
<div class="sc"><div class="si">🚫</div><div class="sv" id="tBloq">0</div><div class="sl2">bloqueados</div></div>
</div>

<div class="sec act" id="sec-dashboard">
<div class="cd"><h2>📊 actividad_7_dias.log</h2><div style="position:relative;height:280px"><canvas id="chA"></canvas></div><div id="chF" style="display:none;text-align:center;padding:40px;color:rgba(224,230,237,0.5);font-family:'Courier New',monospace">⚠️ Chart.js no cargado</div></div>
<div class="cd"><h2>🏆 top_descargadores</h2><table id="tTop"><thead><tr><th>IP</th><th>Descargas</th><th>MB</th></tr></thead><tbody></tbody></table></div>
</div>

<div class="sec" id="sec-dispositivos">
<div class="cd"><h2>📱 dispositivos_conectados</h2><div style="overflow-x:auto"><table id="tDev"><thead><tr><th>IP</th><th>Dispositivo</th><th>Ultima conexion</th><th>Visitas</th><th>Estado</th><th>Acciones</th></tr></thead><tbody></tbody></table></div></div>
</div>

<div class="sec" id="sec-peticiones">
<div class="cd"><h2>📝 peticiones_contenido</h2>
<div class="tbs"><div class="tb ac" data-e="todas">todas</div><div class="tb" data-e="pendiente">pendientes</div><div class="tb" data-e="completado">completadas</div><div class="tb" data-e="rechazado">rechazadas</div></div>
<div style="overflow-x:auto"><table id="tPet2"><thead><tr><th>Tipo</th><th>Contenido</th><th>IP</th><th>Estado</th><th>Fecha</th><th>Acciones</th></tr></thead><tbody></tbody></table></div></div>
</div>

<div class="sec" id="sec-pagos">
<div class="cd"><h2>💳 registrar_pago</h2>
<div class="fg"><label>IP del cliente:</label><input type="text" id="payIp" placeholder="192.168.137.x"></div>
<div class="fg"><label>Concepto:</label><select id="payConcepto"><option value="por_gb">Por GB descargado</option><option value="dia">Acceso diario</option><option value="semana">Acceso semanal</option><option value="otro">Otro</option></select></div>
<div class="fg"><label>Monto (CUP):</label><input type="number" id="payMonto" placeholder="50" step="0.01"></div>
<div class="fg"><label>Notas:</label><input type="text" id="payNotas" placeholder="opcional"></div>
<button class="bt bp" id="btnAddPago">💾 registrar pago</button>
<button class="bt bg2" id="btnExpPagos" style="margin-left:8px">📄 exportar CSV</button>
</div>
<div class="cd"><h2>📋 historial_pagos</h2><div style="overflow-x:auto"><table id="tPagos"><thead><tr><th>IP</th><th>Concepto</th><th>Monto</th><th>Fecha</th><th>Notas</th></tr></thead><tbody></tbody></table></div></div>
</div>

<div class="sec" id="sec-codigos">
<div class="cd"><h2>🎫 generar_codigo_acceso</h2>
<div class="fg"><label>Tipo:</label><select id="codTipo"><option value="descarga">Descarga gratuita</option><option value="dia">Acceso 1 dia</option><option value="semana">Acceso 1 semana</option></select></div>
<div class="fg"><label>Valor/Descripcion:</label><input type="text" id="codValor" placeholder="descripcion"></div>
<button class="bt bp" id="btnGenCod">🎫 generar codigo</button>
<div id="codResultado" style="margin-top:12px;font-family:'Courier New',monospace;color:var(--p)"></div>
</div>
<div class="cd"><h2>📋 codigos_generados</h2><div style="overflow-x:auto"><table id="tCodigos"><thead><tr><th>Codigo</th><th>Tipo</th><th>Valor</th><th>Usado</th><th>Fecha</th></tr></thead><tbody></tbody></table></div></div>
</div>

<div class="sec" id="sec-anuncios">
<div class="cd"><h2>📢 nuevo_anuncio</h2>
<div class="fg"><label>Titulo:</label><input type="text" id="ancTitulo" placeholder="titulo del anuncio"></div>
<div class="fg"><label>Contenido:</label><textarea id="ancContenido" placeholder="contenido del anuncio"></textarea></div>
<button class="bt bp" id="btnAddAnc">📢 publicar anuncio</button>
</div>
<div class="cd"><h2>📋 anuncios_activos</h2><div id="listaAnc"></div></div>
</div>

<div class="sec" id="sec-logs">
<div class="cd"><h2>📋 logs_sistema</h2><button class="bt bg2" id="btnRefreshLogs" style="margin-bottom:12px">🔄 actualizar</button><div style="overflow-x:auto"><table id="tLogs"><thead><tr><th>Nivel</th><th>Mensaje</th><th>Fecha</th></tr></thead><tbody></tbody></table></div></div>
</div>

<div class="sec" id="sec-config">
<div class="cd"><h2>⚙️ cambiar_contrasena</h2>
<div class="fg"><label>Nueva contrasena:</label><input type="password" id="cfgPass" placeholder="nueva contrasena"></div>
<div class="fg"><label>Confirmar contrasena:</label><input type="password" id="cfgPass2" placeholder="confirmar"></div>
<button class="bt bp" id="btnCambiarPass">🔐 cambiar contrasena</button>
</div>
<div class="cd"><h2>📄 exportar_datos</h2>
<div style="display:flex;gap:8px;flex-wrap:wrap">
<button class="bt bg2" data-exp="descargas">📥 descargas.csv</button>
<button class="bt bg2" data-exp="pagos">💳 pagos.csv</button>
<button class="bt bg2" data-exp="dispositivos">📱 dispositivos.csv</button>
</div>
</div>
</div>

<div class="fa">☕ Creado por Carlos A Lorenzo Marro con cafe, anime e IA 🌸🤖</div>
</div>
<script>
(function(){
var cv=document.getElementById('mc'),cx=cv.getContext('2d');cv.width=window.innerWidth;cv.height=window.innerHeight;
var ch='01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン';
var fs=14,cl=Math.floor(cv.width/fs),dr=[],i;for(i=0;i<cl;i++)dr[i]=1;
setInterval(function(){cx.fillStyle='rgba(5,8,22,0.05)';cx.fillRect(0,0,cv.width,cv.height);cx.fillStyle='#00ff88';cx.font=fs+'px monospace';for(var j=0;j<dr.length;j++){var t=ch[Math.floor(Math.random()*ch.length)];cx.fillText(t,j*fs,dr[j]*fs);if(dr[j]*fs>cv.height&&Math.random()>0.975)dr[j]=0;dr[j]++;}},50);
window.addEventListener('resize',function(){cv.width=window.innerWidth;cv.height=window.innerHeight;});
var chAct=null,fail=0;
var tok=new URLSearchParams(window.location.search).get('token');
var navBtns=document.querySelectorAll('.nav button');
for(var n=0;n<navBtns.length;n++){(function(btn){btn.addEventListener('click',function(){for(var x=0;x<navBtns.length;x++)navBtns[x].classList.remove('act');btn.classList.add('act');var secs=document.querySelectorAll('.sec');for(var y=0;y<secs.length;y++)secs[y].classList.remove('act');var target=document.getElementById('sec-'+btn.getAttribute('data-sec'));if(target)target.classList.add('act');});})(navBtns[n]);}
function cargarDatos(){
fetch('/api/admin/stats?token='+encodeURIComponent(tok)).then(function(r){if(!r.ok){fail++;if(fail>=2){localStorage.removeItem('admin_token');alert('⚠️ sesion expirada.');window.location.href='/';}return null;}fail=0;return r.json();}).then(function(d){if(!d)return;
document.getElementById('tVis').textContent=d.generales.visitas;
document.getElementById('tDes').textContent=d.generales.descargas;
document.getElementById('tGB').textContent=d.generales.gb.toFixed(2);
document.getElementById('tIng').textContent=d.ingresos_totales.toFixed(2);
document.getElementById('tIngM').textContent=d.ingresos_estimados_mes.toFixed(2);
document.getElementById('tPet').textContent=d.peticiones_pendientes;
document.getElementById('tBloq').textContent=d.dispositivos_bloqueados;
if(typeof Chart!=='undefined'){document.getElementById('chF').style.display='none';if(chAct)chAct.destroy();var ctxC=document.getElementById('chA').getContext('2d');var lb=[],dv=[],dd=[];for(var i=0;i<d.ultimos_7_dias.length;i++){lb.push(d.ultimos_7_dias[i].fecha);dv.push(d.ultimos_7_dias[i].visitas);dd.push(d.ultimos_7_dias[i].descargas);}chAct=new Chart(ctxC,{type:'line',data:{labels:lb,datasets:[{label:'Visitas',data:dv,borderColor:'#00ff88',backgroundColor:'rgba(0,255,136,0.1)',tension:0.4,fill:true},{label:'Descargas',data:dd,borderColor:'#00d4ff',backgroundColor:'rgba(0,212,255,0.1)',tension:0.4,fill:true}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'rgba(224,230,237,0.7)'}}},scales:{y:{ticks:{color:'rgba(224,230,237,0.7)'},grid:{color:'rgba(0,255,136,0.1)'}},x:{ticks:{color:'rgba(224,230,237,0.7)'},grid:{color:'rgba(0,255,136,0.1)'}}}}});}else{document.getElementById('chA').style.display='none';document.getElementById('chF').style.display='block';}
var th='';for(var a=0;a<d.top_descargadores.length;a++){var tp=d.top_descargadores[a];th+='<tr><td>'+tp.ip+'</td><td>'+tp.descargas+'</td><td>'+tp.mb.toFixed(2)+'</td></tr>';}
document.querySelector('#tTop tbody').innerHTML=th||'<tr><td colspan="3" style="text-align:center;color:rgba(224,230,237,0.5)">sin datos</td></tr>';
var dh='';for(var b=0;b<d.dispositivos.length;b++){var dv2=d.dispositivos[b];dh+='<tr><td>'+dv2.ip+'</td><td><span class="db">'+dv2.dispositivo+'</span></td><td>'+dv2.ultima_conexion+'</td><td>'+dv2.visitas+'</td><td>';if(dv2.bloqueado===1){dh+='<span class="sb2">BLOQUEADO</span>';}else{dh+='<span class="sa">ACTIVO</span>';}if(dv2.motivo){dh+='<br><small style="color:rgba(224,230,237,0.5)">'+dv2.motivo+'</small>';}dh+='</td><td>';if(dv2.bloqueado===1){dh+='<button class="ab2 bs2" data-ip="'+dv2.ip+'" data-acc="unblock">✓ desbloquear</button>';}else{dh+='<button class="ab2 bd" data-ip="'+dv2.ip+'" data-acc="block">✗ bloquear</button>';}dh+='</td></tr>';}
document.querySelector('#tDev tbody').innerHTML=dh||'<tr><td colspan="6" style="text-align:center;color:rgba(224,230,237,0.5)">sin dispositivos</td></tr>';
cargarPeticiones('todas');cargarPagos();cargarCodigos();cargarAnunciosAdmin();cargarLogs();
}).catch(function(e){console.error('error:',e);});}
function cargarPeticiones(est){var tabs=document.querySelectorAll('.tb');for(var i=0;i<tabs.length;i++)tabs[i].classList.remove('ac');var ta=document.querySelector('.tb[data-e="'+est+'"]');if(ta)ta.classList.add('ac');
fetch('/api/admin/peticiones?token='+encodeURIComponent(tok)+'&estado='+est).then(function(r){return r.json()}).then(function(pts){var h='';for(var i=0;i<pts.length;i++){var p=pts[i];var cls='sp';if(p[5]==='completado')cls='scc';if(p[5]==='rechazado')cls='sr';h+='<tr><td>'+p[2]+'</td><td>'+p[3]+'</td><td>'+p[1]+'</td><td><span class="'+cls+'">'+p[5]+'</span></td><td>'+p[6]+'</td><td>';if(p[5]==='pendiente'){h+='<button class="ab2 bs2" data-pid="'+p[0]+'" data-acc="ok">✓</button> <button class="ab2 bd" data-pid="'+p[0]+'" data-acc="no">✗</button>';}else{h+='-';}h+='</td></tr>';}document.querySelector('#tPet2 tbody').innerHTML=h||'<tr><td colspan="6" style="text-align:center;color:rgba(224,230,237,0.5)">sin peticiones</td></tr>';}).catch(function(){});}
function cargarPagos(){fetch('/api/admin/pagos?token='+encodeURIComponent(tok)).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){h+='<tr><td>'+d[i][1]+'</td><td>'+d[i][2]+'</td><td>'+d[i][3]+' CUP</td><td>'+d[i][4]+'</td><td>'+(d[i][5]||'-')+'</td></tr>';}document.querySelector('#tPagos tbody').innerHTML=h||'<tr><td colspan="5" style="text-align:center;color:rgba(224,230,237,0.5)">sin pagos</td></tr>';}).catch(function(){});}
function cargarCodigos(){fetch('/api/admin/codigos?token='+encodeURIComponent(tok)).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){h+='<tr><td style="color:var(--p);font-weight:bold">'+d[i][1]+'</td><td>'+d[i][2]+'</td><td>'+d[i][3]+'</td><td>'+(d[i][4]===1?'✓ usado':'✗ disponible')+'</td><td>'+d[i][5]+'</td></tr>';}document.querySelector('#tCodigos tbody').innerHTML=h||'<tr><td colspan="5" style="text-align:center;color:rgba(224,230,237,0.5)">sin codigos</td></tr>';}).catch(function(){});}
function cargarAnunciosAdmin(){fetch('/api/admin/anuncios?token='+encodeURIComponent(tok)).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){h+='<div style="padding:10px;border-bottom:1px solid rgba(0,255,136,0.1);display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px"><div><strong style="color:var(--s)">'+d[i][1]+'</strong><br><small>'+d[i][2]+'</small></div><button class="ab2 '+(d[i][3]===1?'bd':'bs2')+'" data-aid="'+d[i][0]+'" data-acc="toggleAnc">'+(d[i][3]===1?'desactivar':'activar')+'</button></div>';}document.getElementById('listaAnc').innerHTML=h||'<p style="color:rgba(224,230,237,0.5)">sin anuncios</p>';}).catch(function(){});}
function cargarLogs(){fetch('/api/admin/logs?token='+encodeURIComponent(tok)).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){var cls=d[i][1]==='ERROR'?'sr':(d[i][1]==='WARN'?'sp':'scc');h+='<tr><td><span class="'+cls+'">'+d[i][1]+'</span></td><td>'+d[i][2]+'</td><td>'+d[i][3]+'</td></tr>';}document.querySelector('#tLogs tbody').innerHTML=h||'<tr><td colspan="3" style="text-align:center;color:rgba(224,230,237,0.5)">sin logs</td></tr>';}).catch(function(){});}
document.getElementById('tDev').addEventListener('click',function(e){var el=e.target;while(el&&el!==this){if(el.tagName==='BUTTON'&&el.getAttribute('data-acc')){var ip=el.getAttribute('data-ip');var acc=el.getAttribute('data-acc');if(acc==='block'){var mot=prompt('motivo del bloqueo (opcional):','');if(mot===null)return;fetch('/api/admin/dispositivo/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip:ip,bloquear:true,motivo:mot,token:tok})}).then(function(){cargarDatos();});}else{fetch('/api/admin/dispositivo/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip:ip,bloquear:false,motivo:'',token:tok})}).then(function(){cargarDatos();});}return;}el=el.parentElement;}});
document.getElementById('tPet2').addEventListener('click',function(e){var el=e.target;while(el&&el!==this){if(el.tagName==='BUTTON'&&el.getAttribute('data-acc')){var pid=el.getAttribute('data-pid');var acc=el.getAttribute('data-acc');var est=acc==='ok'?'completado':'rechazado';fetch('/api/admin/peticion/actualizar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:parseInt(pid),estado:est,token:tok})}).then(function(){cargarDatos();});return;}el=el.parentElement;}});
document.getElementById('listaAnc').addEventListener('click',function(e){var el=e.target;while(el&&el!==this){if(el.tagName==='BUTTON'&&el.getAttribute('data-aid')){fetch('/api/admin/anuncio/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:parseInt(el.getAttribute('data-aid')),token:tok})}).then(function(){cargarDatos();});return;}el=el.parentElement;}});
var tabs=document.querySelectorAll('.tb');for(var t=0;t<tabs.length;t++){(function(tab){tab.addEventListener('click',function(){cargarPeticiones(tab.getAttribute('data-e'));});})(tabs[t]);}
document.getElementById('btnAddPago').addEventListener('click',function(){var ip=document.getElementById('payIp').value;var concepto=document.getElementById('payConcepto').value;var monto=document.getElementById('payMonto').value;var notas=document.getElementById('payNotas').value;if(!monto){alert('ingresa el monto');return;}fetch('/api/admin/pago/registrar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip:ip,concepto:concepto,monto:parseFloat(monto),notas:notas,token:tok})}).then(function(){alert('✅ pago registrado');document.getElementById('payIp').value='';document.getElementById('payMonto').value='';document.getElementById('payNotas').value='';cargarDatos();});});
document.getElementById('btnGenCod').addEventListener('click',function(){var tipo=document.getElementById('codTipo').value;var valor=document.getElementById('codValor').value;fetch('/api/admin/codigo/generar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tipo:tipo,valor:valor,token:tok})}).then(function(r){return r.json()}).then(function(d){document.getElementById('codResultado').textContent='✅ Codigo generado: '+d.codigo;cargarDatos();});});
document.getElementById('btnAddAnc').addEventListener('click',function(){var titulo=document.getElementById('ancTitulo').value;var contenido=document.getElementById('ancContenido').value;if(!titulo||!contenido){alert('completa todos los campos');return;}fetch('/api/admin/anuncio/agregar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({titulo:titulo,contenido:contenido,token:tok})}).then(function(){alert('✅ anuncio publicado');document.getElementById('ancTitulo').value='';document.getElementById('ancContenido').value='';cargarDatos();});});
document.getElementById('btnCambiarPass').addEventListener('click',function(){var p1=document.getElementById('cfgPass').value;var p2=document.getElementById('cfgPass2').value;if(p1!==p2){alert('las contrasenas no coinciden');return;}if(p1.length<4){alert('minimo 4 caracteres');return;}fetch('/api/admin/cambiar-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:p1,token:tok})}).then(function(){alert('✅ contrasena cambiada exitosamente');document.getElementById('cfgPass').value='';document.getElementById('cfgPass2').value='';});});
document.getElementById('btnBackup').addEventListener('click',function(){fetch('/api/admin/backup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:tok})}).then(function(r){return r.json()}).then(function(d){alert('✅ backup creado: '+d.archivo);});});
document.getElementById('btnRefreshLogs').addEventListener('click',function(){cargarLogs();});
document.getElementById('btnExpPagos').addEventListener('click',function(){window.location.href='/api/admin/exportar?tipo=pagos&token='+encodeURIComponent(tok);});
var expBtns=document.querySelectorAll('[data-exp]');for(var e2=0;e2<expBtns.length;e2++){(function(btn){btn.addEventListener('click',function(){window.location.href='/api/admin/exportar?tipo='+btn.getAttribute('data-exp')+'&token='+encodeURIComponent(tok);});})(expBtns[e2]);}
document.getElementById('btnVol').addEventListener('click',function(){window.location.href='/';});
document.getElementById('btnOut').addEventListener('click',function(){fetch('/api/logout?token='+encodeURIComponent(tok),{method:'POST'});localStorage.removeItem('admin_token');window.location.href='/';});
function cargarChart(){var s=document.createElement('script');s.src='/static/js/chart.min.js';s.onload=function(){cargarDatos();};s.onerror=function(){cargarDatos();};document.head.appendChild(s);}
cargarChart();setInterval(cargarDatos,30000);
})();
</script>
</body>
</html>"""

# ============================================================
# SERVIDOR HTTP CON TODOS LOS ENDPOINTS
# ============================================================
class ManejadorPersonalizado(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def obtener_ip(self):
        fw = self.headers.get('X-Forwarded-For')
        if fw: return fw.split(',')[0].strip()
        return self.client_address[0]

    def get_cookie(self, name):
        ck = self.headers.get('Cookie', '')
        for c in ck.split(';'):
            if '=' in c:
                k, v = c.strip().split('=', 1)
                if k == name: return v
        return None

    def set_cookie(self, name, value):
        self.send_header('Set-Cookie', name + '=' + value + '; Max-Age=86400; Path=/; HttpOnly')

    def verificar_admin(self):
        token = self.get_cookie('admin_token')
        if not token:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            token = params.get('token', [None])[0]
        if token and db.verificar_sesion(token):
            return True, token
        return False, None

    def leer_json(self):
        cl = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(cl).decode('utf-8'))

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        ruta = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        if ruta == '/' or ruta == '':
            self.enviar_html(200, HTML_PAGINA); return

        if ruta == '/api/verificar-token':
            token = params.get('token', [None])[0]
            valido = token and db.verificar_sesion(token)
            self.enviar_json(200, {"valido": bool(valido)}); return

        if ruta == '/admin':
            es_admin, token = self.verificar_admin()
            if not es_admin:
                self.enviar_html(200, HTML_PAGINA); return
            self.enviar_html(200, HTML_ADMIN); return

        if ruta == '/api/list':
            try: self.enviar_json(200, self.obtener_arbol(CARPETA_BASE))
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/covers':
            try:
                covers = []
                if os.path.exists(CARPETA_COVERS):
                    for f in os.listdir(CARPETA_COVERS):
                        ext = f.split('.')[-1].lower()
                        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                            covers.append({"name": f, "url": "/static/covers/" + urllib.parse.quote(f)})
                self.enviar_json(200, covers)
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/anuncios':
            try:
                anuncios = db.obtener_anuncios(solo_activos=True)
                self.enviar_json(200, anuncios)
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/stats':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try: self.enviar_json(200, db.obtener_estadisticas())
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/peticiones':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            estado = params.get('estado', ['todas'])[0]
            try: self.enviar_json(200, db.obtener_peticiones(estado))
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/pagos':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try: self.enviar_json(200, db.obtener_pagos())
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/codigos':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try: self.enviar_json(200, db.obtener_codigos())
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/anuncios':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try: self.enviar_json(200, db.obtener_anuncios(solo_activos=False))
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/logs':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try: self.enviar_json(200, db.obtener_logs(100))
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/exportar':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            tipo = params.get('tipo', ['descargas'])[0]
            try:
                csv_data = db.exportar_csv(tipo)
                self.send_response(200)
                self.send_header('Content-type', 'text/csv; charset=utf-8')
                self.send_header('Content-Disposition', 'attachment; filename="' + tipo + '.csv"')
                self.end_headers()
                self.wfile.write(csv_data.encode('utf-8'))
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta.startswith('/static/'):
            nombre = ruta[len('/static/'):]
            ruta_segura = os.path.normpath(urllib.parse.unquote(nombre))
            if ruta_segura.startswith('..') or os.path.isabs(ruta_segura):
                self.enviar_error(403, "Acceso denegado"); return
            ruta_completa = os.path.join(CARPETA_STATIC, ruta_segura)
            if not os.path.exists(ruta_completa) or os.path.isdir(ruta_completa):
                self.enviar_error(404, "No encontrado"); return
            try:
                self.send_response(200)
                tipo, _ = mimetypes.guess_type(ruta_completa)
                if tipo is None: tipo = 'application/octet-stream'
                self.send_header('Content-type', tipo)
                self.send_header('Cache-Control', 'public, max-age=3600')
                self.end_headers()
                with open(ruta_completa, 'rb') as f: self.wfile.write(f.read())
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta.startswith('/download/'):
            ip = self.obtener_ip()
            ua = self.headers.get('User-Agent', 'Unknown')
            if db.dispositivo_bloqueado(ip):
                self.enviar_error(403, "Dispositivo bloqueado. Contacta al administrador."); return
            ruta_rel = urllib.parse.unquote(ruta[len('/download/'):])
            ruta_segura = os.path.normpath(ruta_rel)
            if ruta_segura.startswith('..') or os.path.isabs(ruta_segura):
                self.enviar_error(403, "Acceso denegado"); return
            ruta_completa = os.path.join(CARPETA_BASE, ruta_segura)
            if not os.path.exists(ruta_completa) or os.path.isdir(ruta_completa):
                self.enviar_error(404, "Archivo no encontrado"); return
            try:
                tamano = os.path.getsize(ruta_completa)
                tamano_mb = round(tamano / (1024 * 1024), 2)
                db.registrar_descarga(ip, ruta_segura, tamano_mb, ua)
                self.send_response(200)
                tipo, _ = mimetypes.guess_type(ruta_completa)
                if tipo is None: tipo = 'application/octet-stream'
                self.send_header('Content-type', tipo)
                self.send_header('Content-Disposition', 'attachment; filename="' + os.path.basename(ruta_completa) + '"')
                self.end_headers()
                with open(ruta_completa, 'rb') as f: self.wfile.write(f.read())
            except Exception as e: self.enviar_error(500, str(e))
            return

        self.enviar_error(404, "Pagina no encontrada")

    def do_POST(self):
        ruta = urllib.parse.urlparse(self.path).path

        if ruta == '/api/login':
            try:
                data = self.leer_json()
                if db.verificar_credenciales(data.get('usuario', ''), data.get('password', '')):
                    token = db.crear_sesion(data['usuario'])
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.set_cookie('admin_token', token)
                    self.end_headers()
                    self.wfile.write(json.dumps({"success": True, "token": token}).encode('utf-8'))
                else:
                    self.enviar_json(401, {"success": False, "error": "Credenciales invalidas"})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/logout':
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            token = params.get('token', [None])[0]
            if token: db.eliminar_sesion(token)
            self.enviar_json(200, {"success": True}); return

        if ruta == '/api/registrar-visita':
            try:
                ip = self.obtener_ip()
                ua = self.headers.get('User-Agent', 'Unknown')
                db.registrar_dispositivo(ip, ua)
                db.registrar_visita(ip)
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/peticion':
            try:
                data = self.leer_json()
                ip = self.obtener_ip()
                db.agregar_peticion(ip, data.get('tipo', ''), data.get('contenido', ''), data.get('detalles', ''))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/votar':
            try:
                data = self.leer_json()
                ip = self.obtener_ip()
                db.votar(ip, data.get('archivo', ''), data.get('voto', 0))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        # ENDPOINTS ADMIN
        if ruta == '/api/admin/peticion/actualizar':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try:
                data = self.leer_json()
                db.actualizar_peticion(data.get('id'), data.get('estado'))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/dispositivo/toggle':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try:
                data = self.leer_json()
                ip = data.get('ip')
                if data.get('bloquear'): db.bloquear_dispositivo(ip, data.get('motivo', ''))
                else: db.desbloquear_dispositivo(ip)
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/pago/registrar':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try:
                data = self.leer_json()
                db.registrar_pago(data.get('ip', ''), data.get('concepto', ''), data.get('monto', 0), data.get('notas', ''))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/codigo/generar':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try:
                data = self.leer_json()
                codigo = db.generar_codigo(data.get('tipo', ''), data.get('valor', ''))
                self.enviar_json(200, {"success": True, "codigo": codigo})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/anuncio/agregar':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try:
                data = self.leer_json()
                db.agregar_anuncio(data.get('titulo', ''), data.get('contenido', ''))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/anuncio/toggle':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try:
                data = self.leer_json()
                db.toggle_anuncio(data.get('id'))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/cambiar-password':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try:
                data = self.leer_json()
                db.cambiar_password(data.get('password', ''))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/backup':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try:
                archivo = db.backup_db()
                if archivo:
                    self.enviar_json(200, {"success": True, "archivo": os.path.basename(archivo)})
                else:
                    self.enviar_json(500, {"success": False, "error": "Error en backup"})
            except Exception as e: self.enviar_error(500, str(e))
            return

        self.enviar_error(404, "Endpoint no encontrado")

    def enviar_html(self, codigo, contenido):
        self.send_response(codigo)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.end_headers()
        self.wfile.write(contenido.encode('utf-8'))

    def enviar_json(self, codigo, data):
        self.send_response(codigo)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def enviar_error(self, codigo, mensaje):
        self.send_response(codigo)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(("Error " + str(codigo) + ": " + mensaje).encode('utf-8'))

    def obtener_arbol(self, ruta_actual, ruta_relativa=""):
        items = []
        try:
            entradas = sorted(os.listdir(ruta_actual), key=lambda x: x.lower())
        except (PermissionError, FileNotFoundError):
            return []
        for entrada in entradas:
            ruta_completa = os.path.join(ruta_actual, entrada)
            if ruta_relativa == "":
                ruta_rel_web = entrada
            else:
                ruta_rel_web = os.path.join(ruta_relativa, entrada).replace("\\", "/")
            if os.path.isdir(ruta_completa):
                items.append({"name": entrada, "type": "folder", "path": ruta_rel_web, "children": self.obtener_arbol(ruta_completa, ruta_rel_web)})
            else:
                tamano_mb = round(os.path.getsize(ruta_completa) / (1024 * 1024), 2)
                items.append({"name": entrada, "type": "file", "path": ruta_rel_web, "size": tamano_mb})
        return items


def main():
    os.chdir(BASE_DIR)
    hostname = socket.gethostname()
    ip_local = socket.gethostbyname(hostname)
    ip_wifi = "192.168.137.1"
    try:
        import subprocess
        resultado = subprocess.run(['ipconfig'], capture_output=True, text=True)
        for linea in resultado.stdout.split('\n'):
            if "IPv4" in linea and "192.168.137" in linea:
                ip_wifi = linea.split(":")[-1].strip()
                break
    except:
        ip_wifi = ip_local

    print("\n" + "=" * 70)
    print("  🚀 MI PAKETE v6.0 - Centro Multimedia Premium")
    print("  ☕ Creado por Carlos A Lorenzo Marro con cafe, anime e IA")
    print("=" * 70)
    print("  📂 Archivos:   " + CARPETA_BASE)
    print("  🖼️ Covers:      " + CARPETA_COVERS)
    print("  📦 Static:      " + CARPETA_STATIC)
    print("  💾 Base datos: " + DB_FILE)
    print("  📋 Logs:        " + CARPETA_LOGS)
    print("  💾 Backups:     " + CARPETA_BACKUPS)
    print("\n  🌐 ABRE EN TU NAVEGADOR:")
    print("     ➜ http://localhost:" + str(PUERTO))
    print("  📱 DESDE OTROS DISPOSITIVOS:")
    print("     ➜ http://" + ip_wifi + ":" + str(PUERTO))
    print("\n  🔐 PANEL DE ADMINISTRADOR:")
    print("     ➜ Usuario: " + (db.obtener_config('admin_user') or 'root'))
    print("     ➜ Contrasena: " + (db.obtener_config('admin_pass') or 'admin123'))
    print("\n  🛑 Presiona Ctrl + C para detener")
    print("=" * 70 + "\n")

    servidor = http.server.HTTPServer(('0.0.0.0', PUERTO), ManejadorPersonalizado)
    try:
        servidor.serve_forever()
    except KeyboardInterrupt:
        print("\n⏹️ Servidor detenido.")
        db.log_evento('INFO', 'Servidor detenido por usuario')
        servidor.shutdown()


if __name__ == "__main__":
    main()