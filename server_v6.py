import http.server
import json
import os
import sys
import urllib.parse
import mimetypes
import csv
import io
import shutil
import socketserver
from datetime import datetime, timedelta
import sqlite3
import secrets
import threading
import socket
import logging
import time

# ============================================================
# CONFIGURACION DE RUTAS
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

for carpeta in [CARPETA_BASE, CARPETA_COVERS, CARPETA_STATIC, CARPETA_BACKUPS, CARPETA_LOGS]:
    if not os.path.exists(carpeta):
        os.makedirs(carpeta)
os.makedirs(os.path.join(CARPETA_STATIC, "js"), exist_ok=True)
os.makedirs(os.path.join(CARPETA_STATIC, "css"), exist_ok=True)

logging.basicConfig(
    filename=os.path.join(CARPETA_LOGS, "pakete.log"),
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)

# ============================================================
# BASE DE DATOS CON MIGRACION AUTOMATICA
# ============================================================
class BaseDatos:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        self.lock = threading.Lock()
        self.crear_tablas()
        self.migrar_db()
        self.configurar_defaults()

    def crear_tablas(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("CREATE TABLE IF NOT EXISTS config (clave TEXT PRIMARY KEY, valor TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS sesiones (token TEXT PRIMARY KEY, usuario TEXT, creado TIMESTAMP DEFAULT CURRENT_TIMESTAMP, expira TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS dispositivos (ip TEXT PRIMARY KEY, user_agent TEXT, primera_conexion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, ultima_conexion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, nombre_dispositivo TEXT, nombre_dueno TEXT, visitas INTEGER DEFAULT 1, bloqueado INTEGER DEFAULT 0, motivo_bloqueo TEXT, fecha_bloqueo TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS descargas (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, archivo TEXT, tamano_mb REAL, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, user_agent TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS peticiones (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, tipo TEXT, contenido TEXT, detalles TEXT, estado TEXT DEFAULT 'pendiente', fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS estadisticas_diarias (fecha DATE PRIMARY KEY, visitas INTEGER DEFAULT 0, descargas INTEGER DEFAULT 0, gb_descargados REAL DEFAULT 0, dispositivos_unicos INTEGER DEFAULT 0)")
            c.execute("CREATE TABLE IF NOT EXISTS pagos (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, concepto TEXT, monto REAL, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, notas TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS codigos (id INTEGER PRIMARY KEY AUTOINCREMENT, codigo TEXT UNIQUE, tipo TEXT, valor TEXT, usado INTEGER DEFAULT 0, fecha_creacion TIMESTAMP DEFAULT CURRENT_TIMESTAMP, fecha_uso TIMESTAMP, ip_uso TEXT)")
            c.execute("CREATE TABLE IF NOT EXISTS anuncios (id INTEGER PRIMARY KEY AUTOINCREMENT, titulo TEXT, contenido TEXT, activo INTEGER DEFAULT 1, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS votos (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, archivo TEXT, voto INTEGER, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS logs_sistema (id INTEGER PRIMARY KEY AUTOINCREMENT, nivel TEXT, mensaje TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            self.conn.commit()

    def migrar_db(self):
        with self.lock:
            c = self.conn.cursor()
            try:
                c.execute("PRAGMA table_info(descargas)")
                cols = [r[1] for r in c.fetchall()]
                if 'tamaño_mb' in cols and 'tamano_mb' not in cols:
                    try:
                        c.execute("ALTER TABLE descargas RENAME COLUMN tamaño_mb TO tamano_mb")
                    except Exception:
                        c.execute("CREATE TABLE descargas_nueva (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, archivo TEXT, tamano_mb REAL, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, user_agent TEXT)")
                        c.execute("INSERT INTO descargas_nueva (id,ip,archivo,tamano_mb,fecha,user_agent) SELECT id,ip,archivo,tamaño_mb,fecha,user_agent FROM descargas")
                        c.execute("DROP TABLE descargas")
                        c.execute("ALTER TABLE descargas_nueva RENAME TO descargas")
            except Exception: pass
            try:
                c.execute("PRAGMA table_info(dispositivos)")
                cols = [r[1] for r in c.fetchall()]
                if 'nombre_dueno' not in cols:
                    c.execute("ALTER TABLE dispositivos ADD COLUMN nombre_dueno TEXT")
            except Exception: pass
            self.conn.commit()

    def configurar_defaults(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT valor FROM config WHERE clave='admin_user'")
            if not c.fetchone():
                c.execute("INSERT INTO config (clave, valor) VALUES ('admin_user','root')")
            c.execute("SELECT valor FROM config WHERE clave='admin_pass'")
            if not c.fetchone():
                c.execute("INSERT INTO config (clave, valor) VALUES ('admin_pass','admin123')")
            self.conn.commit()

    def obtener_config(self, clave):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT valor FROM config WHERE clave=?", (clave,))
            r = c.fetchone()
            return r[0] if r else None

    def set_config(self, clave, valor):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT OR REPLACE INTO config (clave, valor) VALUES (?,?)", (clave, valor))
            self.conn.commit()

    def verificar_credenciales(self, usuario, password):
        return usuario == self.obtener_config('admin_user') and password == self.obtener_config('admin_pass')

    def cambiar_password(self, nueva):
        self.set_config('admin_pass', nueva)
        self.log_evento('INFO', 'Contrasena cambiada')

    def crear_sesion(self, usuario):
        with self.lock:
            token = secrets.token_urlsafe(32)
            expira = datetime.now() + timedelta(hours=24)
            c = self.conn.cursor()
            c.execute("INSERT INTO sesiones (token,usuario,expira) VALUES (?,?,?)", (token, usuario, expira.isoformat()))
            self.conn.commit()
            return token

    def verificar_sesion(self, token):
        if not token: return False
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT usuario FROM sesiones WHERE token=? AND expira>?", (token, datetime.now().isoformat()))
            return c.fetchone() is not None

    def eliminar_sesion(self, token):
        with self.lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM sesiones WHERE token=?", (token,))
            self.conn.commit()

    def limpiar_sesiones_viejas(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("DELETE FROM sesiones WHERE expira<?", (datetime.now().isoformat(),))
            self.conn.commit()

    def registrar_dispositivo(self, ip, ua):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE dispositivos SET ultima_conexion=CURRENT_TIMESTAMP, visitas=visitas+1 WHERE ip=?", (ip,))
            if c.rowcount == 0:
                c.execute("INSERT INTO dispositivos (ip,user_agent,nombre_dispositivo) VALUES (?,?,?)", (ip, ua, self.detectar_dispositivo(ua)))
            self.conn.commit()

    def detectar_dispositivo(self, ua):
        ua = ua.lower()
        if 'iphone' in ua or 'ipad' in ua: return 'iOS'
        elif 'android' in ua: return 'Android'
        elif 'windows' in ua: return 'Windows'
        elif 'macintosh' in ua: return 'MacOS'
        elif 'linux' in ua: return 'Linux'
        return 'Otro'

    def set_nombre_dueno(self, ip, nombre):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE dispositivos SET nombre_dueno=? WHERE ip=?", (nombre, ip))
            self.conn.commit()
        self.log_evento('INFO', 'Dueno de ' + ip + ' -> ' + nombre)

    def dispositivo_bloqueado(self, ip):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT bloqueado FROM dispositivos WHERE ip=?", (ip,))
            r = c.fetchone()
            return r and r[0] == 1

    def bloquear_dispositivo(self, ip, motivo=""):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE dispositivos SET bloqueado=1, motivo_bloqueo=?, fecha_bloqueo=CURRENT_TIMESTAMP WHERE ip=?", (motivo, ip))
            self.conn.commit()
        self.log_evento('WARN', 'Bloqueado: ' + ip)

    def desbloquear_dispositivo(self, ip):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE dispositivos SET bloqueado=0, motivo_bloqueo=NULL, fecha_bloqueo=NULL WHERE ip=?", (ip,))
            self.conn.commit()
        self.log_evento('INFO', 'Desbloqueado: ' + ip)

    def registrar_descarga(self, ip, archivo, tamano_mb, ua):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO descargas (ip,archivo,tamano_mb,user_agent) VALUES (?,?,?,?)", (ip, archivo, tamano_mb, ua))
            hoy = datetime.now().date().isoformat()
            c.execute("INSERT INTO estadisticas_diarias (fecha,visitas,descargas,gb_descargados,dispositivos_unicos) VALUES (?,0,1,?,0) ON CONFLICT(fecha) DO UPDATE SET descargas=descargas+1, gb_descargados=gb_descargados+?", (hoy, tamano_mb/1024, tamano_mb/1024))
            self.conn.commit()

    def registrar_visita(self, ip):
        with self.lock:
            c = self.conn.cursor()
            hoy = datetime.now().date().isoformat()
            c.execute("INSERT INTO estadisticas_diarias (fecha,visitas,descargas,gb_descargados,dispositivos_unicos) VALUES (?,1,0,0,1) ON CONFLICT(fecha) DO UPDATE SET visitas=visitas+1", (hoy,))
            self.conn.commit()

    def agregar_peticion(self, ip, tipo, contenido, detalles):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO peticiones (ip,tipo,contenido,detalles) VALUES (?,?,?,?)", (ip, tipo, contenido, detalles))
            self.conn.commit()

    def registrar_pago(self, ip, concepto, monto, notas=""):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO pagos (ip,concepto,monto,notas) VALUES (?,?,?,?)", (ip, concepto, monto, notas))
            self.conn.commit()

    def generar_codigo(self, tipo, valor):
        codigo = secrets.token_hex(6).upper()
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO codigos (codigo,tipo,valor) VALUES (?,?,?)", (codigo, tipo, valor))
            self.conn.commit()
        return codigo

    def validar_codigo(self, codigo, ip):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT id, usado FROM codigos WHERE codigo = ?", (codigo.strip().upper(),))
            r = c.fetchone()
            if not r: return False, "codigo no valido"
            if r[1] == 1: return False, "el codigo ya fue usado"
            c.execute("UPDATE codigos SET usado = 1, fecha_uso = CURRENT_TIMESTAMP, ip_uso = ? WHERE id = ?", (ip, r[0]))
            c.execute("UPDATE dispositivos SET bloqueado = 0, motivo_bloqueo = NULL WHERE ip = ?", (ip,))
            self.conn.commit()
        self.log_evento('INFO', 'Codigo canjeado por ' + ip)
        return True, "codigo aplicado - descargas activadas"

    def agregar_anuncio(self, titulo, contenido):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO anuncios (titulo,contenido) VALUES (?,?)", (titulo, contenido))
            self.conn.commit()

    def toggle_anuncio(self, id_a):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE anuncios SET activo=CASE WHEN activo=1 THEN 0 ELSE 1 END WHERE id=?", (id_a,))
            self.conn.commit()

    def votar(self, ip, archivo, voto):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT id FROM votos WHERE ip=? AND archivo=?", (ip, archivo))
            if c.fetchone():
                c.execute("UPDATE votos SET voto=? WHERE ip=? AND archivo=?", (voto, ip, archivo))
            else:
                c.execute("INSERT INTO votos (ip,archivo,voto) VALUES (?,?,?)", (ip, archivo, voto))
            self.conn.commit()

    def log_evento(self, nivel, mensaje):
        try:
            with self.lock:
                c = self.conn.cursor()
                c.execute("INSERT INTO logs_sistema (nivel,mensaje) VALUES (?,?)", (nivel, mensaje))
                self.conn.commit()
        except: pass

    def backup_db(self):
        fecha = datetime.now().strftime('%Y%m%d_%H%M%S')
        destino = os.path.join(CARPETA_BACKUPS, 'pakete_' + fecha + '.db')
        try:
            with self.lock:
                self.conn.commit()
            shutil.copy2(DB_FILE, destino)
            return destino
        except Exception as e:
            self.log_evento('ERROR', 'Backup error: ' + str(e))
            return None

    def obtener_estadisticas(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT ip,COUNT(*),SUM(tamano_mb) FROM descargas GROUP BY ip ORDER BY COUNT(*) DESC LIMIT 10")
            top = c.fetchall()
            c.execute("SELECT ip,nombre_dispositivo,nombre_dueno,ultima_conexion,visitas,bloqueado,motivo_bloqueo FROM dispositivos ORDER BY ultima_conexion DESC LIMIT 30")
            devs = c.fetchall()
            c.execute("SELECT SUM(visitas),SUM(descargas),SUM(gb_descargados) FROM estadisticas_diarias")
            gen = c.fetchone()
            c.execute("SELECT fecha,visitas,descargas,gb_descargados FROM estadisticas_diarias WHERE fecha>=date('now','-7 days') ORDER BY fecha")
            dias = c.fetchall()
            c.execute("SELECT COUNT(*) FROM peticiones WHERE estado='pendiente'")
            pend = c.fetchone()[0]
            c.execute("SELECT COUNT(*) FROM dispositivos WHERE bloqueado=1")
            bloq = c.fetchone()[0]
            c.execute("SELECT SUM(monto) FROM pagos")
            ti = c.fetchone()[0] or 0
            c.execute("SELECT SUM(monto) FROM pagos WHERE fecha>=date('now','-7 days')")
            is7 = c.fetchone()[0] or 0
            return {
                "top_descargadores": [{"ip":r[0],"descargas":r[1],"mb":r[2] or 0} for r in top],
                "dispositivos": [{"ip":r[0],"dispositivo":r[1],"dueno":r[2] or "","ultima_conexion":r[3],"visitas":r[4],"bloqueado":r[5],"motivo":r[6]} for r in devs],
                "generales": {"visitas":gen[0] or 0,"descargas":gen[1] or 0,"gb":round(gen[2] or 0,2)},
                "ultimos_7_dias": [{"fecha":r[0],"visitas":r[1],"descargas":r[2],"gb":r[3]} for r in dias],
                "peticiones_pendientes": pend, "dispositivos_bloqueados": bloq,
                "ingresos_totales": round(ti,2), "ingresos_semana": round(is7,2),
                "ingresos_estimados_mes": round(is7*4.33,2)
            }

    def obtener_peticiones(self, estado='todas'):
        with self.lock:
            c = self.conn.cursor()
            if estado == 'todas': c.execute("SELECT * FROM peticiones ORDER BY fecha DESC")
            else: c.execute("SELECT * FROM peticiones WHERE estado=? ORDER BY fecha DESC", (estado,))
            return c.fetchall()

    def actualizar_peticion(self, id_p, est):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE peticiones SET estado=? WHERE id=?", (est, id_p))
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
            if solo_activos: c.execute("SELECT * FROM anuncios WHERE activo=1 ORDER BY fecha DESC LIMIT 10")
            else: c.execute("SELECT * FROM anuncios ORDER BY fecha DESC LIMIT 20")
            return c.fetchall()

    def obtener_logs(self, limite=100):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT * FROM logs_sistema ORDER BY fecha DESC LIMIT ?", (limite,))
            return c.fetchall()

    def exportar_csv(self, tipo):
        with self.lock:
            c = self.conn.cursor()
            out = io.StringIO()
            w = csv.writer(out)
            if tipo == 'descargas':
                w.writerow(['IP','Archivo','Tamano_MB','Fecha','User_Agent'])
                c.execute("SELECT ip,archivo,tamano_mb,fecha,user_agent FROM descargas")
            elif tipo == 'pagos':
                w.writerow(['IP','Concepto','Monto','Fecha','Notas'])
                c.execute("SELECT ip,concepto,monto,fecha,notas FROM pagos")
            elif tipo == 'dispositivos':
                w.writerow(['IP','Dispositivo','Dueno','Primera','Ultima','Visitas','Bloqueado'])
                c.execute("SELECT ip,nombre_dispositivo,nombre_dueno,primera_conexion,ultima_conexion,visitas,bloqueado FROM dispositivos")
            else: return ""
            for row in c.fetchall(): w.writerow(row)
            return '\ufeff' + out.getvalue()


db = BaseDatos()
db.limpiar_sesiones_viejas()
db.log_evento('INFO', 'Servidor iniciado')

# ============================================================
# ICONO SVG, SERVICE WORKER Y MANIFEST (PWA)
# ============================================================
ICONO_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="100" fill="#0a0e27"/>
<path d="M256 120c-70 0-134 28-180 72l34 36c38-38 90-60 146-60s108 22 146 60l34-36c-46-44-110-72-180-72z" fill="#00ff88"/>
<path d="M256 210c-44 0-84 18-114 46l34 36c21-20 49-32 80-32s59 12 80 32l34-36c-30-28-70-46-114-46z" fill="#00d4ff"/>
<circle cx="256" cy="340" r="36" fill="#ff00ff"/>
<rect x="146" y="396" width="220" height="44" rx="14" fill="#00ff88"/>
</svg>"""

SERVICE_WORKER = """var CACHE='pakete-v1';
self.addEventListener('install',function(e){self.skipWaiting();});
self.addEventListener('activate',function(e){e.waitUntil(self.clients.claim());});
self.addEventListener('fetch',function(e){
if(e.request.method!=='GET')return;
e.respondWith(
fetch(e.request).then(function(resp){
var copia=resp.clone();
caches.open(CACHE).then(function(cache){cache.put(e.request,copia);});
return resp;
}).catch(function(){
return caches.match(e.request);
})
);
});"""

MANIFEST = {
    "name": "Mi Pakete - Centro Multimedia",
    "short_name": "Mi Pakete",
    "description": "Centro multimedia local - Creado por Carlos A Lorenzo Marro",
    "start_url": "/",
    "scope": "/",
    "display": "standalone",
    "orientation": "portrait",
    "background_color": "#050816",
    "theme_color": "#00ff88",
    "icons": [
        {"src": "/icon.svg", "sizes": "any", "type": "image/svg+xml", "purpose": "any"},
        {"src": "/icon.svg", "sizes": "192x192 512x512", "type": "image/svg+xml", "purpose": "maskable"}
    ]
}

# ============================================================
# HTML PAGINA PRINCIPAL
# ============================================================
HTML_PAGINA = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<meta name="theme-color" content="#00ff88">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Mi Pakete">
<link rel="manifest" href="/manifest.json">
<link rel="icon" type="image/svg+xml" href="/icon.svg">
<link rel="apple-touch-icon" href="/icon.svg">
<title>Mi Pakete - Centro Multimedia</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--p:#00ff88;--s:#00d4ff;--a:#ff00ff;--d:#ff3366;--w:#ffaa00;--dk:#050816;--l:#e0e6ed;--g:rgba(10,14,39,0.78)}
body{font-family:'Segoe UI',Arial,sans-serif;background:var(--dk);color:var(--l);min-height:100vh;overflow-x:hidden}
#mc{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-2;opacity:0.1}
#particles{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;pointer-events:none}
.go{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-3;background-image:linear-gradient(rgba(0,255,136,0.02) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,0.02) 1px,transparent 1px);background-size:60px 60px}
.ct{max-width:1200px;margin:0 auto;padding:24px 20px;position:relative;z-index:1}
.hd{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;padding:28px 36px;background:var(--g);backdrop-filter:blur(20px);border-radius:18px;border:1px solid rgba(0,255,136,0.15);box-shadow:0 8px 40px rgba(0,0,0,0.4),0 0 60px rgba(0,255,136,0.05);margin-bottom:44px;position:relative;overflow:hidden}
.hd::before{content:'';position:absolute;top:0;left:-100%;width:100%;height:2px;background:linear-gradient(90deg,transparent,var(--p),var(--s),transparent);animation:sc 4s linear infinite}
@keyframes sc{0%{left:-100%}100%{left:100%}}
.lg h1{font-size:34px;font-weight:800;background:linear-gradient(135deg,var(--p),var(--s),var(--a));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;font-family:'Courier New',monospace;letter-spacing:-1px}
.lg .sub{font-size:13px;color:rgba(0,255,136,0.6);margin-top:6px;font-family:'Courier New',monospace}
.ha{display:flex;gap:12px;align-items:center;flex-wrap:wrap}
.bt{padding:11px 22px;border-radius:10px;border:none;font-weight:600;font-size:14px;cursor:pointer;transition:all 0.3s;font-family:'Courier New',monospace}
.bp{background:linear-gradient(135deg,var(--p),var(--s));color:var(--dk);box-shadow:0 4px 20px rgba(0,255,136,0.3)}
.bp:hover{transform:translateY(-2px);box-shadow:0 8px 30px rgba(0,255,136,0.4)}
.bg2{background:rgba(0,255,136,0.08);color:var(--p);border:1px solid rgba(0,255,136,0.25)}
.bg2:hover{background:rgba(0,255,136,0.15);border-color:var(--p)}
.btnInst{position:fixed;bottom:24px;left:24px;z-index:998;padding:14px 22px;border-radius:50px;font-size:14px;animation:flotar 3s ease-in-out infinite;box-shadow:0 8px 30px rgba(0,255,136,0.4)}
@keyframes flotar{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
.st{margin-bottom:52px}
.stt{display:flex;align-items:center;gap:12px;margin-bottom:24px;font-size:22px;font-weight:700;color:var(--l);font-family:'Courier New',monospace}
.stt::before{content:'>';color:var(--p);animation:bl 1s infinite}
@keyframes bl{0%,50%{opacity:1}51%,100%{opacity:0}}
.bdg{background:linear-gradient(135deg,var(--a),var(--s));font-size:9px;padding:4px 12px;border-radius:4px;color:var(--dk);letter-spacing:1.5px;font-weight:700;text-transform:uppercase}
.cw{position:relative;overflow:hidden;border-radius:18px;background:var(--g);backdrop-filter:blur(15px);border:1px solid rgba(0,255,136,0.15);box-shadow:0 8px 40px rgba(0,0,0,0.3)}
.ctrk{display:flex;transition:transform 0.8s cubic-bezier(0.4,0,0.2,1)}
.csl{min-width:100%;display:flex;align-items:center;gap:36px;padding:44px}
.csl img{width:170px;height:230px;object-fit:cover;border-radius:14px;border:2px solid rgba(0,255,136,0.4);box-shadow:0 8px 40px rgba(0,0,0,0.5),0 0 30px rgba(0,255,136,0.15);transition:all 0.4s;flex-shrink:0;background:rgba(0,0,0,0.3)}
.csl img:hover{transform:scale(1.04) rotate(1deg)}
.ci{flex:1;min-width:0}
.ci h3{font-size:26px;font-weight:700;color:var(--l);margin-bottom:12px;font-family:'Courier New',monospace}
.ci p{color:rgba(224,230,237,0.6);font-size:15px;line-height:1.7;margin-bottom:16px}
.tgs{display:flex;gap:8px;flex-wrap:wrap}
.tg{background:rgba(0,255,136,0.1);color:var(--p);padding:6px 16px;border-radius:6px;font-size:11px;font-weight:600;border:1px solid rgba(0,255,136,0.2);font-family:'Courier New',monospace}
.cds{display:flex;justify-content:center;gap:8px;padding:18px 0 6px 0}
.cds button{width:10px;height:10px;border-radius:50%;border:none;background:rgba(0,255,136,0.25);cursor:pointer;transition:all 0.3s}
.cds button.act{background:var(--p);box-shadow:0 0 15px var(--p);width:30px;border-radius:8px}
.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(170px,1fr));gap:16px}
.sc{background:var(--g);backdrop-filter:blur(15px);border:1px solid rgba(0,255,136,0.12);border-radius:14px;padding:26px 20px;text-align:center;transition:all 0.3s;position:relative;overflow:hidden}
.sc::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--p),var(--s),var(--a));transform:scaleX(0);transition:transform 0.4s;transform-origin:left}
.sc:hover::before{transform:scaleX(1)}
.sc:hover{transform:translateY(-4px);border-color:rgba(0,255,136,0.3)}
.si{font-size:30px;margin-bottom:10px}
.sv{font-size:26px;font-weight:800;color:var(--p);font-family:'Courier New',monospace;text-shadow:0 0 20px rgba(0,255,136,0.4)}
.sl2{font-size:11px;color:rgba(224,230,237,0.5);margin-top:6px;font-family:'Courier New',monospace;text-transform:uppercase;letter-spacing:0.5px}
.ex{background:var(--g);backdrop-filter:blur(15px);border-radius:18px;border:1px solid rgba(0,255,136,0.12);padding:28px;box-shadow:0 8px 40px rgba(0,0,0,0.3)}
.eh{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:16px;margin-bottom:20px}
.eh h2{font-family:'Courier New',monospace;color:var(--p);font-size:18px;margin:0}
.sb{background:rgba(0,0,0,0.4);border:1px solid rgba(0,255,136,0.2);border-radius:10px;padding:10px 20px;display:flex;align-items:center;transition:all 0.3s}
.sb:focus-within{border-color:var(--p);box-shadow:0 0 25px rgba(0,255,136,0.15)}
.sb input{background:transparent;border:none;color:var(--l);padding:6px 12px;width:220px;outline:none;font-size:14px;font-family:'Courier New',monospace}
.flts{display:flex;gap:8px;flex-wrap:wrap;margin-bottom:18px}
.flt{padding:7px 16px;border-radius:8px;background:rgba(0,255,136,0.05);border:1px solid rgba(0,255,136,0.15);cursor:pointer;font-size:12px;font-family:'Courier New',monospace;color:rgba(224,230,237,0.6);transition:all 0.25s}
.flt.act{background:rgba(0,255,136,0.15);border-color:rgba(0,255,136,0.4);color:var(--p)}
.cp{margin:6px 0}
.cpt{cursor:pointer;padding:10px 18px;border-radius:10px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.15);font-weight:600;color:var(--p);transition:all 0.2s;display:inline-block;user-select:none;font-family:'Courier New',monospace;font-size:14px}
.cpt:hover{background:rgba(0,255,136,0.12);transform:translateX(4px)}
.cpc{padding-left:24px;border-left:2px solid rgba(0,255,136,0.15);margin-left:14px;display:none}
.cpc.ab{display:block}
.ar{padding:10px 16px;margin:4px 0;border-radius:10px;transition:all 0.2s;border-left:3px solid transparent;display:flex;align-items:center}
.ar:hover{background:rgba(0,255,136,0.06);border-left-color:var(--p)}
.ar a{color:var(--l);text-decoration:none;display:flex;align-items:center;gap:10px;font-size:14px;font-family:'Courier New',monospace;flex:1}
.ar a:hover{color:var(--p)}
.tm{color:rgba(0,255,136,0.5);font-size:11px;font-family:'Courier New',monospace}
.vt{display:flex;gap:4px;margin-left:auto}
.vt button{background:none;border:1px solid rgba(0,255,136,0.2);color:var(--p);border-radius:6px;padding:3px 10px;cursor:pointer;font-size:12px;transition:all 0.2s}
.vt button:disabled{opacity:0.4;cursor:default}
.anc{background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.2);border-radius:12px;padding:16px 20px;margin-bottom:12px;border-left:4px solid var(--s)}
.anc h4{color:var(--s);font-family:'Courier New',monospace;margin-bottom:6px;font-size:14px}
.anc p{color:rgba(224,230,237,0.6);font-size:13px;font-family:'Courier New',monospace;line-height:1.5}
.vc{text-align:center;color:rgba(224,230,237,0.4);padding:60px 0;font-style:italic;font-family:'Courier New',monospace}
.md{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.92);backdrop-filter:blur(12px);z-index:1000;align-items:center;justify-content:center;padding:20px}
.md.ac{display:flex}
.mdc{background:var(--g);border:1px solid rgba(0,255,136,0.3);border-radius:18px;padding:36px;max-width:480px;width:100%;box-shadow:0 20px 80px rgba(0,0,0,0.6);position:relative;max-height:90vh;overflow-y:auto}
.mdc::before{content:'';position:absolute;top:-1px;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--p),var(--s),var(--a));border-radius:18px 18px 0 0}
.mdc h2{margin-bottom:20px;color:var(--p);font-family:'Courier New',monospace;font-size:20px}
.fg{margin-bottom:16px}
.fg label{display:block;margin-bottom:6px;color:rgba(224,230,237,0.6);font-size:12px;font-weight:600;font-family:'Courier New',monospace;text-transform:uppercase;letter-spacing:0.5px}
.fg input,.fg select,.fg textarea{width:100%;padding:11px 14px;background:rgba(0,0,0,0.4);border:1px solid rgba(0,255,136,0.2);border-radius:10px;color:var(--l);font-family:'Courier New',monospace;font-size:14px}
.fg textarea{resize:vertical;min-height:80px}
.ma{display:flex;gap:12px;margin-top:24px}
.paso{display:flex;gap:14px;align-items:flex-start;padding:14px;background:rgba(0,255,136,0.05);border:1px solid rgba(0,255,136,0.15);border-radius:12px;margin-bottom:10px}
.paso .num{min-width:32px;height:32px;border-radius:50%;background:linear-gradient(135deg,var(--p),var(--s));color:var(--dk);display:flex;align-items:center;justify-content:center;font-weight:800;font-family:'Courier New',monospace}
.paso p{color:rgba(224,230,237,0.7);font-size:13px;font-family:'Courier New',monospace;line-height:1.5}
.ft{margin-top:52px;text-align:center;font-size:13px;color:rgba(224,230,237,0.3);padding-top:24px;border-top:1px solid rgba(0,255,136,0.06);font-family:'Courier New',monospace}
.ft .cr{font-size:14px;color:rgba(0,255,136,0.7);text-shadow:0 0 15px rgba(0,255,136,0.3)}
.ld{display:inline-block;width:20px;height:20px;border:3px solid rgba(0,255,136,0.1);border-radius:50%;border-top-color:var(--p);animation:sp 1s ease-in-out infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.toast{position:fixed;bottom:24px;right:24px;background:var(--g);backdrop-filter:blur(15px);border:1px solid var(--p);border-radius:12px;padding:14px 22px;font-family:'Courier New',monospace;font-size:13px;color:var(--p);z-index:9999;box-shadow:0 8px 30px rgba(0,0,0,0.5);transform:translateY(100px);opacity:0;transition:all 0.4s}
.toast.show{transform:translateY(0);opacity:1}
.toast.err{border-color:var(--d);color:var(--d)}
::-webkit-scrollbar{width:8px}::-webkit-scrollbar-track{background:var(--dk)}::-webkit-scrollbar-thumb{background:rgba(0,255,136,0.4);border-radius:10px}
@media(max-width:768px){
.hd{flex-direction:column;align-items:stretch;gap:16px;padding:20px;margin-bottom:32px}
.st{margin-bottom:36px}
.csl{flex-direction:column;text-align:center;padding:24px;gap:20px}
.csl img{width:130px;height:180px}
.ci h3{font-size:20px}
.ex{padding:20px}
.sg{grid-template-columns:repeat(2,1fr);gap:12px}
.ha{justify-content:center}
.eh{flex-direction:column;align-items:stretch}
.sb{width:100%}.sb input{width:100%}
.btnInst{bottom:16px;left:16px;padding:12px 18px;font-size:13px}
}
@media(max-width:400px){.sg{grid-template-columns:1fr 1fr}.sc{padding:16px 12px}.sv{font-size:20px}.si{font-size:24px}}
</style>
</head>
<body>
<canvas id="mc"></canvas>
<div class="go"></div>
<canvas id="particles"></canvas>
<div class="ct">
<header class="hd">
<div class="lg"><h1>./mi_pakete</h1><div class="sub">root@multimedia:~$ ./start_server.sh</div></div>
<div class="ha">
<button class="bt bg2" id="btnCod">🎫 usar_codigo</button>
<button class="bt bg2" id="btnPet">📝 solicitar_contenido</button>
<button class="bt bp" id="btnAdm">🔐 sudo admin</button>
</div>
</header>
<section class="st" id="secAnuncios" style="display:none">
<div class="stt">📢 ANUNCIOS</div>
<div id="listaAnuncios"></div>
</section>
<section class="st">
<div class="stt">🎬 ESTRENOS_EXCLUSIVOS <span class="bdg">Nuevo</span></div>
<div class="cw"><div class="ctrk" id="ctrk"><div class="csl" style="justify-content:center;min-height:200px"><div class="ld"></div></div></div></div>
<div class="cds" id="cds"></div>
</section>
<section class="st">
<div class="stt">💰 PLANES_Y_PRECIOS</div>
<div class="sg">
<div class="sc"><div class="si">💰</div><div class="sv">6.25 CUP</div><div class="sl2">por GB descargado</div></div>
<div class="sc"><div class="si">🌙</div><div class="sv">50 CUP</div><div class="sl2">dia ilimitado</div></div>
<div class="sc"><div class="si">📅</div><div class="sv">200 CUP</div><div class="sl2">semanal - mejor oferta</div></div>
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
<button class="bt bp btnInst" id="btnInstalar">📱 instalar_app</button>
<div class="md" id="mPet">
<div class="mdc">
<h2>📝 solicitar_contenido.sh</h2>
<p style="color:rgba(224,230,237,0.6);margin-bottom:20px;font-family:'Courier New',monospace;font-size:13px">No encuentras lo que buscas? Dinoslo y lo agregaremos.</p>
<form id="fPet">
<div class="fg"><label>tipo_contenido</label>
<select name="tipo" required><option value="">selecciona...</option><option value="pelicula">🎬 pelicula</option><option value="serie">📺 serie</option><option value="musica">🎵 musica</option><option value="otro">📦 otro</option></select></div>
<div class="fg"><label>nombre</label><input type="text" name="contenido" placeholder="Ej: The Batman 2022" required></div>
<div class="fg"><label>detalles</label><textarea name="detalles" placeholder="temporada, episodio, calidad..."></textarea></div>
<div class="ma"><button type="button" class="bt bg2" id="btnCanPet">cancelar</button><button type="submit" class="bt bp">enviar</button></div>
</form>
</div>
</div>
<div class="md" id="mLog">
<div class="mdc">
<h2>🔐 autenticacion_root</h2>
<form id="fLog">
<div class="fg"><label>usuario</label><input type="text" name="usuario" value="root" required></div>
<div class="fg"><label>contrasena</label><input type="password" name="password" required></div>
<div class="ma"><button type="button" class="bt bg2" id="btnCanLog">cancelar</button><button type="submit" class="bt bp" id="btnSubLog">ingresar</button></div>
</form>
</div>
</div>
<div class="md" id="mCod">
<div class="mdc">
<h2>🎫 canjear_codigo</h2>
<p style="color:rgba(224,230,237,0.6);margin-bottom:20px;font-family:'Courier New',monospace;font-size:13px">Escribe el codigo que te dio el administrador para activar tus descargas.</p>
<div class="fg"><label>codigo de acceso</label><input type="text" id="codInput" placeholder="EJ: A1B2C3D4E5F6" style="text-transform:uppercase"></div>
<div class="ma"><button type="button" class="bt bg2" id="btnCanCod">cancelar</button><button type="button" class="bt bp" id="btnOkCod">activar</button></div>
</div>
</div>
<div class="md" id="mInst">
<div class="mdc">
<h2>📱 instalar_como_app</h2>
<div id="instPasos"></div>
<div class="ma"><button type="button" class="bt bp" id="btnCanInst" style="width:100%">entendido</button></div>
</div>
</div>
<div class="toast" id="toast"></div>
<script>
(function(){
var cv=document.getElementById('mc'),cx=cv.getContext('2d');cv.width=window.innerWidth;cv.height=window.innerHeight;
var ch='01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン';
var fs=14,cl=Math.floor(cv.width/fs),dr=[],i;for(i=0;i<cl;i++)dr[i]=1;
setInterval(function(){cx.fillStyle='rgba(5,8,22,0.05)';cx.fillRect(0,0,cv.width,cv.height);cx.fillStyle='#00ff88';cx.font=fs+'px monospace';for(var j=0;j<dr.length;j++){var t=ch[Math.floor(Math.random()*ch.length)];cx.fillText(t,j*fs,dr[j]*fs);if(dr[j]*fs>cv.height&&Math.random()>0.975)dr[j]=0;dr[j]++;}},50);
var pc=document.getElementById('particles'),px=pc.getContext('2d');pc.width=window.innerWidth;pc.height=window.innerHeight;
var pts=[];for(i=0;i<25;i++){pts.push({x:Math.random()*pc.width,y:Math.random()*pc.height,r:Math.random()*2+1,dx:(Math.random()-0.5)*0.5,dy:(Math.random()-0.5)*0.5});}
setInterval(function(){px.clearRect(0,0,pc.width,pc.height);for(var j=0;j<pts.length;j++){var p=pts[j];p.x+=p.dx;p.y+=p.dy;if(p.x<0||p.x>pc.width)p.dx*=-1;if(p.y<0||p.y>pc.height)p.dy*=-1;px.beginPath();px.arc(p.x,p.y,p.r,0,Math.PI*2);px.fillStyle='rgba(0,255,136,0.15)';px.fill();}},33);
window.addEventListener('resize',function(){cv.width=window.innerWidth;cv.height=window.innerHeight;pc.width=window.innerWidth;pc.height=window.innerHeight;});
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(function(){});}
var toastEl=document.getElementById('toast');
function mostrarToast(msg,err){toastEl.textContent=msg;toastEl.className='toast show'+(err?' err':'');setTimeout(function(){toastEl.className='toast';},3500);}
var deferredPrompt=null;
window.addEventListener('beforeinstallprompt',function(e){e.preventDefault();deferredPrompt=e;});
document.getElementById('btnInstalar').addEventListener('click',function(){
if(deferredPrompt){
deferredPrompt.prompt();
deferredPrompt.userChoice.then(function(r){if(r.outcome==='accepted'){mostrarToast('✅ app instalada');}deferredPrompt=null;});
}else{
var ua=navigator.userAgent.toLowerCase();var h='';
if(ua.indexOf('android')>=0){
h='<div class="paso"><div class="num">1</div><p>Toca el menu de tu navegador (los 3 puntos ⋮ arriba a la derecha)</p></div>';
h+='<div class="paso"><div class="num">2</div><p>Selecciona <strong>"Agregar a pantalla de inicio"</strong> o <strong>"Instalar app"</strong></p></div>';
h+='<div class="paso"><div class="num">3</div><p>Confirma y listo! Tendras el icono de Mi Pakete en tu pantalla como una app 📱</p></div>';
}else if(ua.indexOf('iphone')>=0||ua.indexOf('ipad')>=0){
h='<div class="paso"><div class="num">1</div><p>En Safari, toca el boton Compartir (cuadrado con flecha ↑)</p></div>';
h+='<div class="paso"><div class="num">2</div><p>Desliza y selecciona <strong>"Agregar a pantalla de inicio"</strong></p></div>';
h+='<div class="paso"><div class="num">3</div><p>Toca Agregar y listo! 📱</p></div>';
}else{
h='<div class="paso"><div class="num">1</div><p>En tu navegador, abre el menu (⋮ o ≡)</p></div>';
h+='<div class="paso"><div class="num">2</div><p>Busca <strong>"Instalar Mi Pakete"</strong> o <strong>"Crear acceso directo"</strong></p></div>';
h+='<div class="paso"><div class="num">3</div><p>Confirma y tendras acceso rapido desde tu escritorio 🖥️</p></div>';
}
document.getElementById('instPasos').innerHTML=h;
document.getElementById('mInst').classList.add('ac');
}
});
document.getElementById('btnCanInst').addEventListener('click',function(){document.getElementById('mInst').classList.remove('ac');});
var si2=0,sd=[],api=null;
function cargarCovers(){fetch('/api/covers').then(function(r){return r.json()}).then(function(d){sd=d;var tk=document.getElementById('ctrk'),dt=document.getElementById('cds');if(d.length===0){tk.innerHTML='<div class="csl" style="justify-content:center;min-height:200px"><div style="text-align:center;color:rgba(224,230,237,0.4)"><div style="font-size:48px;margin-bottom:12px">🎬</div><p>Proximamente nuevos estrenos...</p></div></div>';dt.innerHTML='';return;}var h='';for(var k=0;k<d.length;k++){var nb=d[k].name.replace(/\.[^.]+$/,'');h+='<div class="csl"><img src="'+d[k].url+'" alt="'+nb+'" loading="lazy"><div class="ci"><h3>'+nb+'</h3><p>Estreno exclusivo disponible en nuestra biblioteca. Descargalo ahora con la mejor calidad.</p><div class="tgs"><span class="tg">🔥 disponible</span><span class="tg">⭐ exclusivo</span></div></div></div>';}tk.innerHTML=h;var dh='';for(var m=0;m<d.length;m++){dh+='<button class="'+(m===0?'act':'')+'" data-i="'+m+'"></button>';}dt.innerHTML=dh;var btns=dt.querySelectorAll('button');for(var n=0;n<btns.length;n++){(function(btn){btn.addEventListener('click',function(){irA(parseInt(btn.getAttribute('data-i')));});})(btns[n]);}if(d.length>1){if(api)clearInterval(api);api=setInterval(function(){irA((si2+1)%d.length)},5000);}}).catch(function(){});}
function irA(idx){var tk=document.getElementById('ctrk'),dts=document.querySelectorAll('#cds button'),tot=sd.length;if(tot===0)return;if(idx<0)idx=tot-1;if(idx>=tot)idx=0;si2=idx;tk.style.transform='translateX(-'+(idx*100)+'%)';for(var q=0;q<dts.length;q++){if(q===idx)dts[q].className='act';else dts[q].className='';}}
function cargarAnuncios(){fetch('/api/anuncios').then(function(r){return r.json()}).then(function(d){if(d.length===0){document.getElementById('secAnuncios').style.display='none';return;}document.getElementById('secAnuncios').style.display='block';var h='';for(var i=0;i<d.length;i++){h+='<div class="anc"><h4>📢 '+d[i][1]+'</h4><p>'+d[i][2]+'</p></div>';}document.getElementById('listaAnuncios').innerHTML=h;}).catch(function(){});}
var cont=document.getElementById('larch'),bsc=document.getElementById('bsc'),tA=document.getElementById('tArch');
var filtroActual='todos';
function getTipo(n){var e=n.split('.').pop().toLowerCase();if(['mp4','avi','mkv','mov','wmv','webm'].indexOf(e)>=0)return'video';if(['mp3','wav','flac','aac','ogg'].indexOf(e)>=0)return'audio';if(['jpg','jpeg','png','gif','bmp','webp'].indexOf(e)>=0)return'imagen';if(['srt','ass','ssa','sub'].indexOf(e)>=0)return'subtitulo';return'otro';}
function getIco(n){var e=n.split('.').pop().toLowerCase();if(['mp4','avi','mkv','mov','wmv','webm'].indexOf(e)>=0)return'🎬';if(['mp3','wav','flac','aac','ogg'].indexOf(e)>=0)return'🎵';if(['jpg','jpeg','png','gif','bmp','webp'].indexOf(e)>=0)return'🖼️';if(['srt','ass','ssa','sub'].indexOf(e)>=0)return'📝';if(['zip','rar','7z','tar','gz'].indexOf(e)>=0)return'📦';return'📄';}
function esc(t){var d=document.createElement('div');d.textContent=t;return d.innerHTML;}
function renderArbol(items,nv){nv=nv||0;var h='';for(var i=0;i<items.length;i++){var it=items[i],mg=nv*20;if(it.type==='folder'){var id='f'+Date.now()+'_'+Math.random().toString(36).substr(2,5);h+='<div class="cp" style="margin-left:'+mg+'px"><div class="cpt" data-f="'+id+'">📁 '+esc(it.name)+'</div><div class="cpc" id="'+id+'">';if(it.children&&it.children.length>0)h+=renderArbol(it.children,nv+1);else h+='<div style="color:rgba(224,230,237,0.4);font-size:13px;padding:8px 12px;font-family:Courier New,monospace">📭 carpeta vacia</div>';h+='</div></div>';}else{var ic=getIco(it.name);var tp=getTipo(it.name);h+='<div class="ar" style="margin-left:'+mg+'px" data-tipo="'+tp+'"><a href="/download/'+encodeURIComponent(it.path)+'">'+ic+' <span style="flex:1">'+esc(it.name)+'</span> <span class="tm">('+it.size+' MB)</span></a><div class="vt"><button data-voto="1" data-archivo="'+esc(it.name)+'">👍</button><button data-voto="-1" data-archivo="'+esc(it.name)+'">👎</button></div></div>';}}return h;}
document.addEventListener('click',function(e){var el=e.target;while(el&&el!==document.body){if(el.classList&&el.classList.contains('cpt')){var fid=el.getAttribute('data-f'),fc=document.getElementById(fid);if(fc){fc.classList.toggle('ab');var ab=fc.classList.contains('ab');var txt=el.textContent.replace(/[📂📁]\s*/,'');el.textContent=(ab?'📂 ':' ')+txt;}return;}if(el.tagName==='BUTTON'&&el.getAttribute('data-voto')){var arch=el.getAttribute('data-archivo');var voto=parseInt(el.getAttribute('data-voto'));fetch('/api/votar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({archivo:arch,voto:voto})});el.textContent=voto===1?'👍 ✓':'👎 ✓';el.disabled=true;mostrarToast('✅ voto registrado');return;}el=el.parentElement;}});
function aplicarFiltro(){var ars=document.querySelectorAll('.ar');for(var i=0;i<ars.length;i++){var tp=ars[i].getAttribute('data-tipo');if(filtroActual==='todos'||tp===filtroActual){ars[i].style.display='';}else{ars[i].style.display='none';}}}
var flts=document.querySelectorAll('.flt');
for(var f=0;f<flts.length;f++){(function(fl){fl.addEventListener('click',function(){for(var x=0;x<flts.length;x++)flts[x].classList.remove('act');fl.classList.add('act');filtroActual=fl.getAttribute('data-f');aplicarFiltro();});})(flts[f]);}
function filtrar(){var t=bsc.value.toLowerCase().trim();var ars=document.querySelectorAll('.ar'),cps=document.querySelectorAll('.cp');var j;if(t===''){for(j=0;j<ars.length;j++)ars[j].style.display='';for(j=0;j<cps.length;j++)cps[j].style.display='';var ccs=document.querySelectorAll('.cpc');for(j=0;j<ccs.length;j++)ccs[j].classList.remove('ab');aplicarFiltro();return;}for(j=0;j<ars.length;j++)ars[j].style.display='none';for(j=0;j<cps.length;j++)cps[j].style.display='none';for(j=0;j<ars.length;j++){if(ars[j].textContent.toLowerCase().indexOf(t)>=0){ars[j].style.display='';var p=ars[j].parentElement;while(p){if(p.classList&&p.classList.contains('cpc')){p.classList.add('ab');if(p.parentElement&&p.parentElement.classList.contains('cp'))p.parentElement.style.display='';}p=p.parentElement;}}}}
function cargarArchivos(){fetch('/api/list').then(function(r){return r.json()}).then(function(d){if(d.length===0){cont.innerHTML='<div class="vc"><div style="font-size:48px;margin-bottom:12px">📭</div><p>No hay archivos disponibles. Vuelve pronto.</p></div>';tA.textContent='0';}else{cont.innerHTML=renderArbol(d);tA.textContent=document.querySelectorAll('.ar').length;aplicarFiltro();}}).catch(function(e){cont.innerHTML='<div class="vc">❌ error: '+e+'</div>';});}
document.getElementById('btnPet').addEventListener('click',function(){document.getElementById('mPet').classList.add('ac');});
document.getElementById('btnCanPet').addEventListener('click',function(){document.getElementById('mPet').classList.remove('ac');});
document.getElementById('btnCanLog').addEventListener('click',function(){document.getElementById('mLog').classList.remove('ac');});
document.getElementById('btnCod').addEventListener('click',function(){document.getElementById('mCod').classList.add('ac');});
document.getElementById('btnCanCod').addEventListener('click',function(){document.getElementById('mCod').classList.remove('ac');});
document.getElementById('btnOkCod').addEventListener('click',function(){
var cod=document.getElementById('codInput').value;
if(!cod){mostrarToast('❌ escribe el codigo',true);return;}
fetch('/api/codigo/validar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({codigo:cod})})
.then(function(r){return r.json()}).then(function(d){
if(d.success){mostrarToast('✅ '+d.mensaje);document.getElementById('mCod').classList.remove('ac');document.getElementById('codInput').value='';}
else{mostrarToast('❌ '+d.mensaje,true);}
}).catch(function(){mostrarToast('❌ error de conexion',true);});
});
document.getElementById('btnAdm').addEventListener('click',function(){var tk=localStorage.getItem('admin_token');if(tk){fetch('/api/verificar-token?token='+encodeURIComponent(tk)).then(function(r){return r.json()}).then(function(d){if(d.valido){window.location.href='/admin?token='+encodeURIComponent(tk);}else{localStorage.removeItem('admin_token');document.getElementById('mLog').classList.add('ac');}}).catch(function(){localStorage.removeItem('admin_token');document.getElementById('mLog').classList.add('ac');});}else{document.getElementById('mLog').classList.add('ac');}});
bsc.addEventListener('input',filtrar);
document.getElementById('fPet').addEventListener('submit',function(e){e.preventDefault();var fd=new FormData(e.target);fetch('/api/peticion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tipo:fd.get('tipo'),contenido:fd.get('contenido'),detalles:fd.get('detalles')})}).then(function(r){if(r.ok){mostrarToast('✅ solicitud enviada');document.getElementById('mPet').classList.remove('ac');e.target.reset();}}).catch(function(){mostrarToast('❌ error al enviar',true);});});
document.getElementById('fLog').addEventListener('submit',function(e){e.preventDefault();var fd=new FormData(e.target);var btn=document.getElementById('btnSubLog');btn.disabled=true;btn.textContent='verificando...';localStorage.removeItem('admin_token');fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({usuario:fd.get('usuario'),password:fd.get('password')})}).then(function(r){return r.json()}).then(function(d){btn.disabled=false;btn.textContent='ingresar';if(d.success&&d.token){localStorage.setItem('admin_token',d.token);document.getElementById('mLog').classList.remove('ac');setTimeout(function(){window.location.href='/admin?token='+encodeURIComponent(d.token);},200);}else{mostrarToast('❌ credenciales incorrectas',true);}}).catch(function(){btn.disabled=false;btn.textContent='ingresar';mostrarToast('❌ error de conexion',true);});});
cargarCovers();cargarArchivos();cargarAnuncios();fetch('/api/registrar-visita',{method:'POST'});
})();
</script>
</body>
</html>"""

# ============================================================
# HTML PANEL ADMIN
# ============================================================
HTML_ADMIN = """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>root@pakete:~# panel_admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
:root{--p:#00ff88;--s:#00d4ff;--a:#ff00ff;--d:#ff3366;--w:#ffaa00;--dk:#050816;--l:#e0e6ed;--g:rgba(10,14,39,0.78)}
body{font-family:'Segoe UI',Arial,sans-serif;background:var(--dk);color:var(--l);min-height:100vh}
#mc{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;opacity:0.1}
.ct{max-width:1440px;margin:0 auto;padding:24px 20px;position:relative;z-index:1}
.hd{display:flex;justify-content:space-between;align-items:center;padding:20px 28px;background:var(--g);backdrop-filter:blur(20px);border-radius:14px;border:1px solid rgba(0,255,136,0.15);margin-bottom:24px;box-shadow:0 4px 24px rgba(0,0,0,0.3);flex-wrap:wrap;gap:12px}
.hd h1{font-size:22px;background:linear-gradient(135deg,var(--p),var(--a));-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-family:'Courier New',monospace}
.hdr{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.conn{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-family:'Courier New',monospace;color:var(--p);padding:4px 12px;background:rgba(0,255,136,0.08);border-radius:20px;border:1px solid rgba(0,255,136,0.2)}
.conn .dot{width:8px;height:8px;border-radius:50%;background:var(--p);animation:pulse 2s infinite}
.conn.off .dot{background:var(--d)}
.conn.off{color:var(--d);border-color:rgba(255,51,102,0.3)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
.bt{padding:8px 16px;border-radius:8px;border:none;font-weight:600;cursor:pointer;transition:all 0.25s;font-family:'Courier New',monospace;font-size:12px}
.bt:hover{transform:translateY(-1px)}
.bp{background:linear-gradient(135deg,var(--p),var(--s));color:var(--dk);box-shadow:0 3px 12px rgba(0,255,136,0.25)}
.bd{background:rgba(255,51,102,0.15);color:var(--d);border:1px solid rgba(255,51,102,0.3)}
.bg2{background:rgba(0,255,136,0.08);color:var(--p);border:1px solid rgba(0,255,136,0.25)}
.bs2{background:rgba(0,255,136,0.15);color:var(--p);border:1px solid rgba(0,255,136,0.4)}
.nav{display:flex;gap:6px;margin-bottom:20px;flex-wrap:wrap;padding:6px;background:rgba(0,0,0,0.3);border-radius:12px;border:1px solid rgba(0,255,136,0.1)}
.nav button{padding:8px 16px;border-radius:8px;background:transparent;border:1px solid transparent;color:rgba(224,230,237,0.6);cursor:pointer;font-family:'Courier New',monospace;font-size:12px;transition:all 0.25s}
.nav button.act{background:rgba(0,255,136,0.12);border-color:rgba(0,255,136,0.3);color:var(--p)}
.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}
.sc{background:var(--g);backdrop-filter:blur(12px);border:1px solid rgba(0,255,136,0.12);border-radius:12px;padding:18px 16px;position:relative;overflow:hidden;text-align:center;transition:all 0.3s}
.sc::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--p),var(--s),var(--a))}
.si{font-size:24px;margin-bottom:6px}
.sv{font-size:22px;font-weight:800;color:var(--p);font-family:'Courier New',monospace}
.sl2{font-size:10px;color:rgba(224,230,237,0.5);margin-top:4px;font-family:'Courier New',monospace;text-transform:uppercase}
.sec{display:none;animation:fadeIn 0.3s ease}
.sec.act{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.cd{background:var(--g);backdrop-filter:blur(12px);border:1px solid rgba(0,255,136,0.12);border-radius:12px;padding:22px;margin-bottom:20px}
.cd h2{font-size:16px;margin-bottom:14px;color:var(--p);font-family:'Courier New',monospace}
table{width:100%;border-collapse:collapse}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid rgba(0,255,136,0.06);font-family:'Courier New',monospace;font-size:12px}
th{color:rgba(0,255,136,0.7);font-weight:600;text-transform:uppercase;font-size:10px;background:rgba(0,255,136,0.03)}
td{color:var(--l)}
tr:hover td{background:rgba(0,255,136,0.03)}
.db{background:rgba(0,255,136,0.12);color:var(--p);padding:3px 10px;border-radius:4px;font-size:10px;font-weight:600;border:1px solid rgba(0,255,136,0.2)}
.sp{background:rgba(255,170,0,0.12);color:var(--w);padding:3px 10px;border-radius:4px;font-size:10px;border:1px solid rgba(255,170,0,0.2)}
.scc{background:rgba(0,255,136,0.12);color:var(--p);padding:3px 10px;border-radius:4px;font-size:10px;border:1px solid rgba(0,255,136,0.2)}
.sr{background:rgba(255,51,102,0.12);color:var(--d);padding:3px 10px;border-radius:4px;font-size:10px;border:1px solid rgba(255,51,102,0.2)}
.sb2{background:rgba(255,51,102,0.12);color:var(--d);padding:3px 10px;border-radius:4px;font-size:10px;border:1px solid rgba(255,51,102,0.2)}
.sa{background:rgba(0,255,136,0.12);color:var(--p);padding:3px 10px;border-radius:4px;font-size:10px;border:1px solid rgba(0,255,136,0.2)}
.ab2{padding:5px 12px;border-radius:6px;border:none;cursor:pointer;font-size:10px;font-family:'Courier New',monospace;margin:2px;transition:all 0.2s}
.ab2:hover{transform:scale(1.05)}
.fg{margin-bottom:12px}
.fg label{display:block;margin-bottom:5px;color:rgba(224,230,237,0.6);font-size:11px;font-weight:600;font-family:'Courier New',monospace;text-transform:uppercase}
.fg input,.fg select,.fg textarea{width:100%;padding:9px 12px;background:rgba(0,0,0,0.4);border:1px solid rgba(0,255,136,0.2);border-radius:8px;color:var(--l);font-family:'Courier New',monospace;font-size:13px}
.fg textarea{resize:vertical;min-height:60px}
.tbs{display:flex;gap:6px;margin-bottom:14px;flex-wrap:wrap}
.tb{padding:6px 14px;border-radius:6px;background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.15);cursor:pointer;font-size:11px;font-family:'Courier New',monospace;color:rgba(224,230,237,0.7)}
.tb.ac{background:rgba(0,255,136,0.15);border-color:rgba(0,255,136,0.4);color:var(--p)}
.dueno{color:var(--s);font-weight:bold}
.fa{margin-top:24px;text-align:center;font-size:11px;color:rgba(224,230,237,0.25);font-family:'Courier New',monospace;padding-top:16px;border-top:1px solid rgba(0,255,136,0.06)}
.toast{position:fixed;bottom:24px;right:24px;background:var(--g);backdrop-filter:blur(15px);border:1px solid var(--p);border-radius:12px;padding:14px 22px;font-family:'Courier New',monospace;font-size:13px;color:var(--p);z-index:9999;box-shadow:0 8px 30px rgba(0,0,0,0.5);transform:translateY(100px);opacity:0;transition:all 0.4s}
.toast.show{transform:translateY(0);opacity:1}
.toast.err{border-color:var(--d);color:var(--d)}
@media(max-width:768px){.sg{grid-template-columns:repeat(2,1fr)}.hd{padding:16px}.nav button{padding:6px 10px;font-size:11px}}
</style>
</head>
<body>
<canvas id="mc"></canvas>
<div class="ct">
<header class="hd">
<h1>root@pakete:~# panel_admin</h1>
<div class="hdr">
<span class="conn" id="connStatus"><span class="dot"></span> online</span>
<button class="bt bg2" id="btnVol">🏠 volver</button>
<button class="bt bp" id="btnBackup">💾 backup</button>
<button class="bt bd" id="btnOut">🚪 salir</button>
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
<div class="sc"><div class="si">💾</div><div class="sv" id="tGB">0</div><div class="sl2">gb total</div></div>
<div class="sc"><div class="si">💰</div><div class="sv" id="tIng">0</div><div class="sl2">ingresos CUP</div></div>
<div class="sc"><div class="si">📈</div><div class="sv" id="tIngM">0</div><div class="sl2">est. mensual</div></div>
<div class="sc"><div class="si">📝</div><div class="sv" id="tPet">0</div><div class="sl2">peticiones</div></div>
<div class="sc"><div class="si">🚫</div><div class="sv" id="tBloq">0</div><div class="sl2">bloqueados</div></div>
</div>
<div class="sec act" id="sec-dashboard">
<div class="cd"><h2>📊 actividad_7_dias.log</h2><div style="position:relative;height:260px"><canvas id="chA"></canvas></div><div id="chF" style="display:none;text-align:center;padding:40px;color:rgba(224,230,237,0.4);font-family:'Courier New',monospace;font-size:13px">⚠️ Chart.js no cargado</div></div>
<div class="cd"><h2>🏆 top_descargadores</h2><div style="overflow-x:auto"><table id="tTop"><thead><tr><th>IP</th><th>Descargas</th><th>MB</th></tr></thead><tbody></tbody></table></div></div>
</div>
<div class="sec" id="sec-dispositivos">
<div class="cd"><h2>📱 dispositivos_conectados (toca ✏️ para poner nombre del dueño)</h2><div style="overflow-x:auto"><table id="tDev"><thead><tr><th>IP</th><th>Dispositivo</th><th>Dueño</th><th>Ultima conexion</th><th>Visitas</th><th>Estado</th><th>Acciones</th></tr></thead><tbody></tbody></table></div></div>
</div>
<div class="sec" id="sec-peticiones">
<div class="cd"><h2>📝 peticiones_contenido</h2>
<div class="tbs"><div class="tb ac" data-e="todas">todas</div><div class="tb" data-e="pendiente">pendientes</div><div class="tb" data-e="completado">completadas</div><div class="tb" data-e="rechazado">rechazadas</div></div>
<div style="overflow-x:auto"><table id="tPet2"><thead><tr><th>Tipo</th><th>Contenido</th><th>IP</th><th>Estado</th><th>Fecha</th><th>Acciones</th></tr></thead><tbody></tbody></table></div></div>
</div>
<div class="sec" id="sec-pagos">
<div class="cd"><h2>💳 registrar_pago</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px">
<div class="fg"><label>IP del cliente</label><input type="text" id="payIp" placeholder="192.168.137.x"></div>
<div class="fg"><label>Concepto</label><select id="payConcepto"><option value="por_gb">Por GB</option><option value="dia">Acceso diario</option><option value="semana">Acceso semanal</option><option value="otro">Otro</option></select></div>
<div class="fg"><label>Monto (CUP)</label><input type="number" id="payMonto" placeholder="50" step="0.01"></div>
<div class="fg"><label>Notas</label><input type="text" id="payNotas" placeholder="opcional"></div>
</div>
<div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
<button class="bt bp" id="btnAddPago">💾 registrar pago</button>
<button class="bt bg2" id="btnExpPagos">📄 exportar CSV</button>
</div></div>
<div class="cd"><h2>📋 historial_pagos</h2><div style="overflow-x:auto"><table id="tPagos"><thead><tr><th>IP</th><th>Concepto</th><th>Monto</th><th>Fecha</th><th>Notas</th></tr></thead><tbody></tbody></table></div></div>
</div>
<div class="sec" id="sec-codigos">
<div class="cd"><h2>🎫 generar_codigo_acceso</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:12px;align-items:end">
<div class="fg"><label>Tipo</label><select id="codTipo"><option value="descarga">Descarga gratuita</option><option value="dia">Acceso 1 dia</option><option value="semana">Acceso 1 semana</option></select></div>
<div class="fg"><label>Descripcion</label><input type="text" id="codValor" placeholder="descripcion"></div>
<div><button class="bt bp" id="btnGenCod" style="width:100%">🎫 generar</button></div>
</div>
<div id="codResultado" style="margin-top:12px;font-family:'Courier New',monospace;color:var(--p);font-size:14px"></div></div>
<div class="cd"><h2>📋 codigos_generados</h2><div style="overflow-x:auto"><table id="tCodigos"><thead><tr><th>Codigo</th><th>Tipo</th><th>Valor</th><th>Estado</th><th>Fecha</th></tr></thead><tbody></tbody></table></div></div>
</div>
<div class="sec" id="sec-anuncios">
<div class="cd"><h2>📢 nuevo_anuncio</h2>
<div class="fg"><label>Titulo</label><input type="text" id="ancTitulo" placeholder="titulo"></div>
<div class="fg"><label>Contenido</label><textarea id="ancContenido" placeholder="contenido"></textarea></div>
<button class="bt bp" id="btnAddAnc">📢 publicar</button></div>
<div class="cd"><h2>📋 anuncios_publicados</h2><div id="listaAnc"></div></div>
</div>
<div class="sec" id="sec-logs">
<div class="cd"><h2>📋 logs_sistema <button class="bt bg2" id="btnRefreshLogs" style="margin-left:12px;font-size:11px">🔄 actualizar</button></h2><div style="overflow-x:auto"><table id="tLogs"><thead><tr><th>Nivel</th><th>Mensaje</th><th>Fecha</th></tr></thead><tbody></tbody></table></div></div>
</div>
<div class="sec" id="sec-config">
<div class="cd"><h2>⚙️ cambiar_contrasena</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px">
<div class="fg"><label>Nueva contrasena</label><input type="password" id="cfgPass" placeholder="nueva"></div>
<div class="fg"><label>Confirmar</label><input type="password" id="cfgPass2" placeholder="confirmar"></div>
</div>
<button class="bt bp" id="btnCambiarPass" style="margin-top:8px">🔐 cambiar</button></div>
<div class="cd"><h2>📄 exportar_datos</h2>
<div style="display:flex;gap:8px;flex-wrap:wrap">
<button class="bt bg2" data-exp="descargas">📥 descargas.csv</button>
<button class="bt bg2" data-exp="pagos">💳 pagos.csv</button>
<button class="bt bg2" data-exp="dispositivos">📱 dispositivos.csv</button>
</div></div>
</div>
<div class="fa">☕ Creado por Carlos A Lorenzo Marro con cafe, anime e IA 🌸</div>
</div>
<div class="toast" id="toast"></div>
<script>
(function(){
var cv=document.getElementById('mc'),cx=cv.getContext('2d');cv.width=window.innerWidth;cv.height=window.innerHeight;
var ch='01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン';
var fs=14,cl=Math.floor(cv.width/fs),dr=[],i;for(i=0;i<cl;i++)dr[i]=1;
setInterval(function(){cx.fillStyle='rgba(5,8,22,0.05)';cx.fillRect(0,0,cv.width,cv.height);cx.fillStyle='#00ff88';cx.font=fs+'px monospace';for(var j=0;j<dr.length;j++){var t=ch[Math.floor(Math.random()*ch.length)];cx.fillText(t,j*fs,dr[j]*fs);if(dr[j]*fs>cv.height&&Math.random()>0.975)dr[j]=0;dr[j]++;}},50);
window.addEventListener('resize',function(){cv.width=window.innerWidth;cv.height=window.innerHeight;});
var chAct=null,fail=0,maxFail=5,tabActual='todas';
var tok=new URLSearchParams(window.location.search).get('token');
var toastEl=document.getElementById('toast');
function mostrarToast(msg,err){toastEl.textContent=msg;toastEl.className='toast show'+(err?' err':'');setTimeout(function(){toastEl.className='toast';},3500);}
function setConn(on){var el=document.getElementById('connStatus');if(on){el.className='conn';el.innerHTML='<span class="dot"></span> online';}else{el.className='conn off';el.innerHTML='<span class="dot"></span> offline';}}
function escA(t){return String(t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
var navBtns=document.querySelectorAll('.nav button');
for(var n=0;n<navBtns.length;n++){(function(btn){btn.addEventListener('click',function(){for(var x=0;x<navBtns.length;x++)navBtns[x].classList.remove('act');btn.classList.add('act');var secs=document.querySelectorAll('.sec');for(var y=0;y<secs.length;y++)secs[y].classList.remove('act');var target=document.getElementById('sec-'+btn.getAttribute('data-sec'));if(target)target.classList.add('act');});})(navBtns[n]);}
function cargarDatos(){
fetch('/api/admin/stats?token='+encodeURIComponent(tok))
.then(function(r){
if(r.status===401||r.status===403){fail++;if(fail>=maxFail){localStorage.removeItem('admin_token');mostrarToast('⚠️ sesion expirada',true);setTimeout(function(){window.location.href='/';},2000);}return null;}
if(!r.ok){return null;}
fail=0;setConn(true);return r.json();})
.then(function(d){
if(!d)return;
document.getElementById('tVis').textContent=d.generales.visitas;
document.getElementById('tDes').textContent=d.generales.descargas;
document.getElementById('tGB').textContent=d.generales.gb.toFixed(2);
document.getElementById('tIng').textContent=d.ingresos_totales.toFixed(2);
document.getElementById('tIngM').textContent=d.ingresos_estimados_mes.toFixed(2);
document.getElementById('tPet').textContent=d.peticiones_pendientes;
document.getElementById('tBloq').textContent=d.dispositivos_bloqueados;
if(typeof Chart!=='undefined'){
document.getElementById('chF').style.display='none';
document.getElementById('chA').style.display='block';
if(chAct)chAct.destroy();
var ctxC=document.getElementById('chA').getContext('2d');
var lb=[],dv=[],dd=[];
for(var i=0;i<d.ultimos_7_dias.length;i++){lb.push(d.ultimos_7_dias[i].fecha);dv.push(d.ultimos_7_dias[i].visitas);dd.push(d.ultimos_7_dias[i].descargas);}
chAct=new Chart(ctxC,{type:'line',data:{labels:lb,datasets:[{label:'Visitas',data:dv,borderColor:'#00ff88',backgroundColor:'rgba(0,255,136,0.08)',tension:0.4,fill:true,borderWidth:2},{label:'Descargas',data:dd,borderColor:'#00d4ff',backgroundColor:'rgba(0,212,255,0.08)',tension:0.4,fill:true,borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'rgba(224,230,237,0.6)',font:{size:11}}}},scales:{y:{ticks:{color:'rgba(224,230,237,0.5)',font:{size:10}},grid:{color:'rgba(0,255,136,0.06)'}},x:{ticks:{color:'rgba(224,230,237,0.5)',font:{size:10}},grid:{color:'rgba(0,255,136,0.06)'}}}}});
}else{document.getElementById('chA').style.display='none';document.getElementById('chF').style.display='block';}
var th='';for(var a=0;a<d.top_descargadores.length;a++){var tp=d.top_descargadores[a];th+='<tr><td>'+escA(tp.ip)+'</td><td>'+tp.descargas+'</td><td>'+tp.mb.toFixed(2)+'</td></tr>';}
document.querySelector('#tTop tbody').innerHTML=th||'<tr><td colspan="3" style="text-align:center;color:rgba(224,230,237,0.4)">sin datos</td></tr>';
var dh='';for(var b=0;b<d.dispositivos.length;b++){var dv2=d.dispositivos[b];
dh+='<tr><td>'+escA(dv2.ip)+'</td><td><span class="db">'+escA(dv2.dispositivo)+'</span></td>';
dh+='<td>'+(dv2.dueno?'<span class="dueno">👤 '+escA(dv2.dueno)+'</span>':'<span style="opacity:0.4">sin nombre</span>')+' <button class="ab2 bg2" data-ip="'+escA(dv2.ip)+'" data-acc="nombre" data-nombre="'+escA(dv2.dueno||'')+'">✏️</button></td>';
dh+='<td>'+dv2.ultima_conexion+'</td><td>'+dv2.visitas+'</td><td>';
if(dv2.bloqueado===1){dh+='<span class="sb2">BLOQUEADO</span>';}else{dh+='<span class="sa">ACTIVO</span>';}
if(dv2.motivo){dh+='<br><small style="color:rgba(224,230,237,0.4)">'+escA(dv2.motivo)+'</small>';}
dh+='</td><td>';
if(dv2.bloqueado===1){dh+='<button class="ab2 bs2" data-ip="'+escA(dv2.ip)+'" data-acc="unblock">✓ desbloquear</button>';}
else{dh+='<button class="ab2 bd" data-ip="'+escA(dv2.ip)+'" data-acc="block">✗ bloquear</button>';}
dh+='</td></tr>';}
document.querySelector('#tDev tbody').innerHTML=dh||'<tr><td colspan="7" style="text-align:center;color:rgba(224,230,237,0.4)">sin dispositivos</td></tr>';
cargarPeticiones(tabActual);cargarPagos();cargarCodigos();cargarAnunciosAdmin();cargarLogs();
}).catch(function(e){setConn(false);});
}
function cargarPeticiones(est){tabActual=est;var tabs=document.querySelectorAll('.tb');for(var i=0;i<tabs.length;i++)tabs[i].classList.remove('ac');var ta=document.querySelector('.tb[data-e="'+est+'"]');if(ta)ta.classList.add('ac');
fetch('/api/admin/peticiones?token='+encodeURIComponent(tok)+'&estado='+est).then(function(r){return r.json()}).then(function(pts){var h='';for(var i=0;i<pts.length;i++){var p=pts[i];var cls='sp';if(p[5]==='completado')cls='scc';if(p[5]==='rechazado')cls='sr';h+='<tr><td>'+escA(p[2])+'</td><td>'+escA(p[3])+'</td><td>'+escA(p[1])+'</td><td><span class="'+cls+'">'+p[5]+'</span></td><td>'+p[6]+'</td><td>';if(p[5]==='pendiente'){h+='<button class="ab2 bs2" data-pid="'+p[0]+'" data-acc="ok">✓</button> <button class="ab2 bd" data-pid="'+p[0]+'" data-acc="no">✗</button>';}else{h+='-';}h+='</td></tr>';}document.querySelector('#tPet2 tbody').innerHTML=h||'<tr><td colspan="6" style="text-align:center;color:rgba(224,230,237,0.4)">sin peticiones</td></tr>';}).catch(function(){});}
function cargarPagos(){fetch('/api/admin/pagos?token='+encodeURIComponent(tok)).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){h+='<tr><td>'+escA(d[i][1])+'</td><td>'+escA(d[i][2])+'</td><td style="color:var(--p);font-weight:bold">'+d[i][3]+' CUP</td><td>'+d[i][4]+'</td><td>'+escA(d[i][5]||'-')+'</td></tr>';}document.querySelector('#tPagos tbody').innerHTML=h||'<tr><td colspan="5" style="text-align:center;color:rgba(224,230,237,0.4)">sin pagos</td></tr>';}).catch(function(){});}
function cargarCodigos(){fetch('/api/admin/codigos?token='+encodeURIComponent(tok)).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){h+='<tr><td style="color:var(--p);font-weight:bold;font-size:13px">'+escA(d[i][1])+'</td><td>'+escA(d[i][2])+'</td><td>'+escA(d[i][3])+'</td><td>'+(d[i][4]===1?'<span class="sr">usado</span>':'<span class="sa">disponible</span>')+'</td><td>'+d[i][5]+'</td></tr>';}document.querySelector('#tCodigos tbody').innerHTML=h||'<tr><td colspan="5" style="text-align:center;color:rgba(224,230,237,0.4)">sin codigos</td></tr>';}).catch(function(){});}
function cargarAnunciosAdmin(){fetch('/api/admin/anuncios?token='+encodeURIComponent(tok)).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){h+='<div style="background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.2);border-radius:8px;padding:12px 16px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px"><div><strong style="color:var(--s);font-family:Courier New,monospace">'+escA(d[i][1])+'</strong><br><small style="color:rgba(224,230,237,0.5)">'+escA(d[i][2])+'</small></div><button class="ab2 '+(d[i][3]===1?'bd':'bs2')+'" data-aid="'+d[i][0]+'" data-acc="toggleAnc">'+(d[i][3]===1?'desactivar':'activar')+'</button></div>';}document.getElementById('listaAnc').innerHTML=h||'<p style="color:rgba(224,230,237,0.4)">sin anuncios</p>';}).catch(function(){});}
function cargarLogs(){fetch('/api/admin/logs?token='+encodeURIComponent(tok)).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){var cls=d[i][1]==='ERROR'?'sr':(d[i][1]==='WARN'?'sp':'scc');h+='<tr><td><span class="'+cls+'">'+d[i][1]+'</span></td><td>'+escA(d[i][2])+'</td><td style="color:rgba(224,230,237,0.4)">'+d[i][3]+'</td></tr>';}document.querySelector('#tLogs tbody').innerHTML=h||'<tr><td colspan="3" style="text-align:center;color:rgba(224,230,237,0.4)">sin logs</td></tr>';}).catch(function(){});}
document.getElementById('tDev').addEventListener('click',function(e){var el=e.target;while(el&&el!==this){if(el.tagName==='BUTTON'&&el.getAttribute('data-acc')){var ip=el.getAttribute('data-ip');var acc=el.getAttribute('data-acc');
if(acc==='nombre'){
var nom=prompt('nombre del dueño del dispositivo '+ip+':',el.getAttribute('data-nombre')||'');
if(nom===null)return;
fetch('/api/admin/dispositivo/nombre',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip:ip,nombre:nom,token:tok})}).then(function(){mostrarToast('✅ nombre guardado');cargarDatos();});
}else if(acc==='block'){
var mot=prompt('motivo del bloqueo (opcional):','');if(mot===null)return;
fetch('/api/admin/dispositivo/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip:ip,bloquear:true,motivo:mot,token:tok})}).then(function(){mostrarToast(' dispositivo bloqueado - no podra descargar');cargarDatos();});
}else{
fetch('/api/admin/dispositivo/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip:ip,bloquear:false,motivo:'',token:tok})}).then(function(){mostrarToast('✅ dispositivo desbloqueado');cargarDatos();});
}
return;}el=el.parentElement;}});
document.getElementById('tPet2').addEventListener('click',function(e){var el=e.target;while(el&&el!==this){if(el.tagName==='BUTTON'&&el.getAttribute('data-acc')){var pid=el.getAttribute('data-pid');var acc=el.getAttribute('data-acc');var est=acc==='ok'?'completado':'rechazado';fetch('/api/admin/peticion/actualizar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:parseInt(pid),estado:est,token:tok})}).then(function(){mostrarToast('✅ peticion actualizada');cargarDatos();});return;}el=el.parentElement;}});
document.getElementById('listaAnc').addEventListener('click',function(e){var el=e.target;while(el&&el!==this){if(el.tagName==='BUTTON'&&el.getAttribute('data-aid')){fetch('/api/admin/anuncio/toggle',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({id:parseInt(el.getAttribute('data-aid')),token:tok})}).then(function(){mostrarToast('✅ anuncio actualizado');cargarDatos();});return;}el=el.parentElement;}});
var tabs=document.querySelectorAll('.tb');for(var t=0;t<tabs.length;t++){(function(tab){tab.addEventListener('click',function(){cargarPeticiones(tab.getAttribute('data-e'));});})(tabs[t]);}
document.getElementById('btnAddPago').addEventListener('click',function(){var ip=document.getElementById('payIp').value;var concepto=document.getElementById('payConcepto').value;var monto=document.getElementById('payMonto').value;var notas=document.getElementById('payNotas').value;if(!monto){mostrarToast('❌ ingresa el monto',true);return;}fetch('/api/admin/pago/registrar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ip:ip,concepto:concepto,monto:parseFloat(monto),notas:notas,token:tok})}).then(function(){mostrarToast('✅ pago registrado');document.getElementById('payIp').value='';document.getElementById('payMonto').value='';document.getElementById('payNotas').value='';cargarDatos();});});
document.getElementById('btnGenCod').addEventListener('click',function(){var tipo=document.getElementById('codTipo').value;var valor=document.getElementById('codValor').value;fetch('/api/admin/codigo/generar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tipo:tipo,valor:valor,token:tok})}).then(function(r){return r.json()}).then(function(d){document.getElementById('codResultado').innerHTML='✅ Codigo: <strong style="font-size:20px;letter-spacing:3px">'+escA(d.codigo)+'</strong> (compártelo con el cliente)';mostrarToast('✅ codigo generado');cargarDatos();});});
document.getElementById('btnAddAnc').addEventListener('click',function(){var titulo=document.getElementById('ancTitulo').value;var contenido=document.getElementById('ancContenido').value;if(!titulo||!contenido){mostrarToast('❌ completa los campos',true);return;}fetch('/api/admin/anuncio/agregar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({titulo:titulo,contenido:contenido,token:tok})}).then(function(){mostrarToast('✅ anuncio publicado');document.getElementById('ancTitulo').value='';document.getElementById('ancContenido').value='';cargarDatos();});});
document.getElementById('btnCambiarPass').addEventListener('click',function(){var p1=document.getElementById('cfgPass').value;var p2=document.getElementById('cfgPass2').value;if(p1!==p2){mostrarToast('❌ no coinciden',true);return;}if(p1.length<4){mostrarToast('❌ minimo 4 caracteres',true);return;}fetch('/api/admin/cambiar-password',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({password:p1,token:tok})}).then(function(){mostrarToast('✅ contrasena cambiada');document.getElementById('cfgPass').value='';document.getElementById('cfgPass2').value='';});});
document.getElementById('btnBackup').addEventListener('click',function(){fetch('/api/admin/backup',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({token:tok})}).then(function(r){return r.json()}).then(function(d){mostrarToast('✅ backup: '+d.archivo);});});
document.getElementById('btnRefreshLogs').addEventListener('click',function(){cargarLogs();});
document.getElementById('btnExpPagos').addEventListener('click',function(){window.location.href='/api/admin/exportar?tipo=pagos&token='+encodeURIComponent(tok);});
var expBtns=document.querySelectorAll('[data-exp]');for(var e2=0;e2<expBtns.length;e2++){(function(btn){btn.addEventListener('click',function(){window.location.href='/api/admin/exportar?tipo='+btn.getAttribute('data-exp')+'&token='+encodeURIComponent(tok);});})(expBtns[e2]);}
document.getElementById('btnVol').addEventListener('click',function(){window.location.href='/';});
document.getElementById('btnOut').addEventListener('click',function(){fetch('/api/logout?token='+encodeURIComponent(tok),{method:'POST'});localStorage.removeItem('admin_token');window.location.href='/';});
function cargarChart(){var s=document.createElement('script');s.src='/static/js/chart.min.js';s.onload=function(){cargarDatos();};s.onerror=function(){cargarDatos();};document.head.appendChild(s);}
cargarChart();
setInterval(cargarDatos,30000);
})();
</script>
</body>
</html>"""

# ============================================================
# SERVIDOR HTTP
# ============================================================
class ManejadorPersonalizado(http.server.BaseHTTPRequestHandler):
    def log_message(self, format, *args): pass
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
        self.send_header('Set-Cookie', name+'='+value+'; Max-Age=86400; Path=/; HttpOnly')
    def verificar_admin(self):
        token = self.get_cookie('admin_token')
        if not token:
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            token = params.get('token', [None])[0]
        if token and db.verificar_sesion(token): return True, token
        return False, None
    def leer_json(self):
        cl = int(self.headers.get('Content-Length', 0))
        return json.loads(self.rfile.read(cl).decode('utf-8'))
    def enviar_archivo(self, ruta_completa, attachment=None):
        try:
            tamano = os.path.getsize(ruta_completa)
            self.send_response(200)
            tipo, _ = mimetypes.guess_type(ruta_completa)
            if tipo is None: tipo = 'application/octet-stream'
            self.send_header('Content-type', tipo)
            self.send_header('Content-Length', str(tamano))
            self.send_header('Cache-Control', 'public, max-age=3600')
            if attachment:
                self.send_header('Content-Disposition', 'attachment; filename="'+attachment+'"')
            self.end_headers()
            with open(ruta_completa, 'rb') as f:
                while True:
                    chunk = f.read(1024*1024)
                    if not chunk: break
                    self.wfile.write(chunk)
        except (BrokenPipeError, ConnectionResetError):
            pass
    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        ruta = parsed.path
        params = urllib.parse.parse_qs(parsed.query)
        if ruta == '/' or ruta == '':
            self.enviar_html(200, HTML_PAGINA); return
        if ruta == '/manifest.json':
            self.enviar_json(200, MANIFEST); return
        if ruta == '/sw.js':
            self.send_response(200)
            self.send_header('Content-type', 'application/javascript; charset=utf-8')
            self.send_header('Cache-Control', 'no-cache')
            self.end_headers()
            self.wfile.write(SERVICE_WORKER.encode('utf-8')); return
        if ruta == '/icon.svg':
            self.send_response(200)
            self.send_header('Content-type', 'image/svg+xml')
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            self.wfile.write(ICONO_SVG.encode('utf-8')); return
        if ruta == '/api/verificar-token':
            token = params.get('token', [None])[0]
            self.enviar_json(200, {"valido": bool(token and db.verificar_sesion(token))}); return
        if ruta == '/admin':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_html(200, HTML_PAGINA); return
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
                        if ext in ['jpg','jpeg','png','gif','webp']:
                            covers.append({"name":f,"url":"/covers/"+urllib.parse.quote(f)})
                self.enviar_json(200, covers)
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/anuncios':
            try: self.enviar_json(200, db.obtener_anuncios(True))
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/stats':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try: self.enviar_json(200, db.obtener_estadisticas())
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/peticiones':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            estado = params.get('estado', ['todas'])[0]
            try: self.enviar_json(200, db.obtener_peticiones(estado))
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/pagos':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try: self.enviar_json(200, db.obtener_pagos())
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/codigos':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try: self.enviar_json(200, db.obtener_codigos())
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/anuncios':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try: self.enviar_json(200, db.obtener_anuncios(False))
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/logs':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try: self.enviar_json(200, db.obtener_logs(100))
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/exportar':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            tipo = params.get('tipo', ['descargas'])[0]
            try:
                csv_data = db.exportar_csv(tipo)
                self.send_response(200)
                self.send_header('Content-type', 'text/csv; charset=utf-8')
                self.send_header('Content-Disposition', 'attachment; filename="'+tipo+'.csv"')
                self.end_headers()
                self.wfile.write(csv_data.encode('utf-8'))
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta.startswith('/covers/'):
            nombre = ruta[len('/covers/'):]
            ruta_segura = os.path.normpath(urllib.parse.unquote(nombre))
            if ruta_segura.startswith('..') or os.path.isabs(ruta_segura):
                self.enviar_error(403, "Acceso denegado"); return
            ruta_completa = os.path.join(CARPETA_COVERS, ruta_segura)
            if not os.path.exists(ruta_completa) or os.path.isdir(ruta_completa):
                self.enviar_error(404, "Imagen no encontrada"); return
            self.enviar_archivo(ruta_completa); return
        if ruta.startswith('/static/'):
            nombre = ruta[len('/static/'):]
            ruta_segura = os.path.normpath(urllib.parse.unquote(nombre))
            if ruta_segura.startswith('..') or os.path.isabs(ruta_segura):
                self.enviar_error(403, "Acceso denegado"); return
            ruta_completa = os.path.join(CARPETA_STATIC, ruta_segura)
            if not os.path.exists(ruta_completa) or os.path.isdir(ruta_completa):
                self.enviar_error(404, "No encontrado"); return
            self.enviar_archivo(ruta_completa); return
        if ruta.startswith('/download/'):
            ip = self.obtener_ip()
            ua = self.headers.get('User-Agent', 'Unknown')
            if db.dispositivo_bloqueado(ip):
                self.enviar_error(403, "⛔ Dispositivo bloqueado. Contacta al administrador o canjea un codigo para activar tus descargas."); return
            ruta_rel = urllib.parse.unquote(ruta[len('/download/'):])
            ruta_segura = os.path.normpath(ruta_rel)
            if ruta_segura.startswith('..') or os.path.isabs(ruta_segura):
                self.enviar_error(403, "Acceso denegado"); return
            ruta_completa = os.path.join(CARPETA_BASE, ruta_segura)
            if not os.path.exists(ruta_completa) or os.path.isdir(ruta_completa):
                self.enviar_error(404, "Archivo no encontrado"); return
            try:
                tamano = os.path.getsize(ruta_completa)
                tamano_mb = round(tamano/(1024*1024), 2)
                db.registrar_descarga(ip, ruta_segura, tamano_mb, ua)
                self.enviar_archivo(ruta_completa, attachment=os.path.basename(ruta_completa))
            except Exception as e:
                try: self.enviar_error(500, str(e))
                except Exception: pass
            return
        # Cualquier ruta desconocida muestra la pagina principal (captive portal)
        self.enviar_html(200, HTML_PAGINA)
    def do_POST(self):
        ruta = urllib.parse.urlparse(self.path).path
        if ruta == '/api/login':
            try:
                data = self.leer_json()
                if db.verificar_credenciales(data.get('usuario',''), data.get('password','')):
                    token = db.crear_sesion(data['usuario'])
                    self.send_response(200)
                    self.send_header('Content-type', 'application/json; charset=utf-8')
                    self.set_cookie('admin_token', token)
                    self.end_headers()
                    self.wfile.write(json.dumps({"success":True,"token":token}).encode('utf-8'))
                else: self.enviar_json(401, {"success":False,"error":"Credenciales invalidas"})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/logout':
            params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            token = params.get('token', [None])[0]
            if token: db.eliminar_sesion(token)
            self.enviar_json(200, {"success":True}); return
        if ruta == '/api/registrar-visita':
            try:
                ip = self.obtener_ip(); ua = self.headers.get('User-Agent','Unknown')
                db.registrar_dispositivo(ip, ua); db.registrar_visita(ip)
                self.enviar_json(200, {"success":True})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/peticion':
            try:
                data = self.leer_json(); ip = self.obtener_ip()
                db.agregar_peticion(ip, data.get('tipo',''), data.get('contenido',''), data.get('detalles',''))
                self.enviar_json(200, {"success":True})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/votar':
            try:
                data = self.leer_json(); ip = self.obtener_ip()
                db.votar(ip, data.get('archivo',''), data.get('voto',0))
                self.enviar_json(200, {"success":True})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/codigo/validar':
            try:
                data = self.leer_json(); ip = self.obtener_ip()
                ok, msg = db.validar_codigo(data.get('codigo',''), ip)
                self.enviar_json(200, {"success":ok, "mensaje":msg})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/peticion/actualizar':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try:
                data = self.leer_json()
                db.actualizar_peticion(data.get('id'), data.get('estado'))
                self.enviar_json(200, {"success":True})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/dispositivo/toggle':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try:
                data = self.leer_json(); ip = data.get('ip')
                if data.get('bloquear'): db.bloquear_dispositivo(ip, data.get('motivo',''))
                else: db.desbloquear_dispositivo(ip)
                self.enviar_json(200, {"success":True})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/dispositivo/nombre':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try:
                data = self.leer_json()
                db.set_nombre_dueno(data.get('ip'), data.get('nombre',''))
                self.enviar_json(200, {"success":True})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/pago/registrar':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try:
                data = self.leer_json()
                db.registrar_pago(data.get('ip',''), data.get('concepto',''), data.get('monto',0), data.get('notas',''))
                self.enviar_json(200, {"success":True})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/codigo/generar':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try:
                data = self.leer_json()
                codigo = db.generar_codigo(data.get('tipo',''), data.get('valor',''))
                self.enviar_json(200, {"success":True,"codigo":codigo})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/anuncio/agregar':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try:
                data = self.leer_json()
                db.agregar_anuncio(data.get('titulo',''), data.get('contenido',''))
                self.enviar_json(200, {"success":True})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/anuncio/toggle':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try:
                data = self.leer_json()
                db.toggle_anuncio(data.get('id'))
                self.enviar_json(200, {"success":True})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/cambiar-password':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try:
                data = self.leer_json()
                db.cambiar_password(data.get('password',''))
                self.enviar_json(200, {"success":True})
            except Exception as e: self.enviar_error(500, str(e))
            return
        if ruta == '/api/admin/backup':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error":"No autorizado"}); return
            try:
                archivo = db.backup_db()
                if archivo: self.enviar_json(200, {"success":True,"archivo":os.path.basename(archivo)})
                else: self.enviar_json(500, {"success":False,"error":"Error en backup"})
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
        self.wfile.write(("Error "+str(codigo)+": "+mensaje).encode('utf-8'))
    def obtener_arbol(self, ruta_actual, ruta_relativa=""):
        items = []
        try: entradas = sorted(os.listdir(ruta_actual), key=lambda x: x.lower())
        except (PermissionError, FileNotFoundError): return []
        for entrada in entradas:
            ruta_completa = os.path.join(ruta_actual, entrada)
            if ruta_relativa == "": ruta_rel_web = entrada
            else: ruta_rel_web = os.path.join(ruta_relativa, entrada).replace("\\", "/")
            if os.path.isdir(ruta_completa):
                items.append({"name":entrada,"type":"folder","path":ruta_rel_web,"children":self.obtener_arbol(ruta_completa, ruta_rel_web)})
            else:
                tamano_mb = round(os.path.getsize(ruta_completa)/(1024*1024), 2)
                items.append({"name":entrada,"type":"file","path":ruta_rel_web,"size":tamano_mb})
        return items

IP_SERVIDOR = "192.168.137.1"

# ============================================================
# SERVIDOR DNS (CAPTIVE PORTAL)
# ============================================================
class ManejadorDNS(socketserver.BaseRequestHandler):
    def handle(self):
        try:
            data = self.request[0]
            sock = self.request[1]
            if len(data) < 12: return
            tid = data[0:2]
            idx = 12
            while idx < len(data) and data[idx] != 0:
                idx += data[idx] + 1
            if idx + 5 > len(data): return
            qtype = data[idx+1:idx+3]
            idx += 5
            question = data[12:idx]
            if qtype == b'\x00\x01':
                header = tid + b'\x81\x80' + b'\x00\x01\x00\x01\x00\x00\x00\x00'
                answer = b'\xc0\x0c\x00\x01\x00\x01\x00\x00\x00\x3c\x00\x04' + socket.inet_aton(IP_SERVIDOR)
            else:
                header = tid + b'\x81\x80' + b'\x00\x01\x00\x00\x00\x00\x00\x00'
                answer = b''
            sock.sendto(header + question + answer, self.client_address)
        except Exception:
            pass

def iniciar_todo():
    global IP_SERVIDOR
    hostname = socket.gethostname()
    try:
        IP_SERVIDOR = socket.gethostbyname(hostname)
    except Exception:
        IP_SERVIDOR = "192.168.137.1"
    try:
        import subprocess
        resultado = subprocess.run(['ipconfig'], capture_output=True, text=True)
        for linea in resultado.stdout.split('\n'):
            if "IPv4" in linea and "192.168.137" in linea:
                IP_SERVIDOR = linea.split(":")[-1].strip()
                break
    except Exception:
        pass
    servidores = []
    s1 = http.server.ThreadingHTTPServer(('0.0.0.0', PUERTO), ManejadorPersonalizado)
    servidores.append(s1)
    print("  ✅ Web activa en puerto " + str(PUERTO))
    try:
        s2 = http.server.ThreadingHTTPServer(('0.0.0.0', 80), ManejadorPersonalizado)
        servidores.append(s2)
        print("  ✅ Puerto 80 activo (los clientes escriben solo: " + IP_SERVIDOR + ")")
    except Exception as e:
        print("  ⚠️ Puerto 80 ocupado (" + str(e) + ") - usaran :8000")
    try:
        socketserver.ThreadingUDPServer.allow_reuse_address = True
        dns = socketserver.ThreadingUDPServer(('0.0.0.0', 53), ManejadorDNS)
        t = threading.Thread(target=dns.serve_forever, daemon=True)
        t.start()
        print("  ✅ CAPTIVE PORTAL activo: la web se abrira SOLA al conectarse")
    except Exception as e:
        print("  ⚠️ Puerto 53 ocupado (" + str(e) + ")")
        print("     El portal automatico puede no abrir solo.")
        print("     Los clientes pueden escribir: http://" + IP_SERVIDOR)
    return servidores

def main():
    os.chdir(BASE_DIR)
    print("\n" + "=" * 70)
    print("  🚀 MI PAKETE v9.0 - Centro Multimedia + Captive Portal")
    print("  ☕ Creado por Carlos A Lorenzo Marro con cafe, anime e IA")
    print("=" * 70)
    print("  📂 Archivos:   " + CARPETA_BASE)
    print("  🖼️ Covers:      " + CARPETA_COVERS)
    print("\n  🔥 IMPORTANTE: Ejecuta este programa COMO ADMINISTRADOR")
    print("     y enciende mHotspot ANTES de iniciar.")
    print("=" * 70 + "\n")
    servidores = iniciar_todo()
    print("\n  🌐 Tus clientes pueden entrar en:")
    print("     ➜ http://" + IP_SERVIDOR)
    print("     ➜ http://" + IP_SERVIDOR + ":8000")
    print("\n  🔐 Admin: " + (db.obtener_config('admin_user') or 'root') + " / " + (db.obtener_config('admin_pass') or 'admin123'))
    print("  🛑 Ctrl + C para detener\n")
    try:
        for s in servidores:
            t = threading.Thread(target=s.serve_forever, daemon=True)
            t.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\n⏹️ Servidor detenido.")
        for s in servidores:
            s.shutdown()

if __name__ == "__main__":
    main()