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
import argparse
import gzip as gzip_mod

try:
    import winreg
except ImportError:
    winreg = None

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
# AUTOARRANQUE Y MODO SILENCIOSO (sin cambios)
# ============================================================
APP_NAME = "MiPakete"

def obtener_ruta_ejecutable():
    if getattr(sys, 'frozen', False):
        return os.path.abspath(sys.executable)
    else:
        return os.path.abspath(__file__)

def ocultar_consola():
    try:
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32')
        user32 = ctypes.WinDLL('user32')
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 0)
    except Exception:
        pass

def minimizar_consola():
    try:
        import ctypes
        kernel32 = ctypes.WinDLL('kernel32')
        user32 = ctypes.WinDLL('user32')
        hwnd = kernel32.GetConsoleWindow()
        if hwnd:
            user32.ShowWindow(hwnd, 6)
    except Exception:
        pass

def instalar_autoarranque():
    if winreg is None:
        print("  ❌ No disponible en este sistema operativo")
        return False
    try:
        ruta = obtener_ruta_ejecutable()
        if getattr(sys, 'frozen', False):
            comando = '"' + ruta + '" --silent'
        else:
            comando = 'pythonw "' + ruta + '" --silent'
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, comando)
        winreg.CloseKey(key)
        print("  ✅ Autoarranque instalado")
        return True
    except Exception as e:
        print("  ❌ Error: " + str(e))
        return False

def desinstalar_autoarranque():
    if winreg is None:
        print("  ❌ No disponible en este sistema operativo")
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_SET_VALUE)
        try:
            winreg.DeleteValue(key, APP_NAME)
            print("  ✅ Autoarranque desinstalado")
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            print("  ℹ️ No estaba instalado")
            winreg.CloseKey(key)
            return True
    except Exception as e:
        print("  ❌ Error: " + str(e))
        return False

def verificar_autoarranque():
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run", 0, winreg.KEY_READ)
        try:
            winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False

# ============================================================
# BASE DE DATOS (extendida: chat, favoritos, comentarios,
# tablon, auditoria + modo WAL)
# ============================================================
class BaseDatos:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE, check_same_thread=False)
        try:
            self.conn.execute("PRAGMA journal_mode=WAL")
        except Exception:
            pass
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
            # ===== NUEVAS TABLAS v11 =====
            c.execute("CREATE TABLE IF NOT EXISTS comentarios (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, archivo TEXT, nombre TEXT, texto TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS favoritos (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, archivo TEXT, path TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP, UNIQUE(ip,archivo))")
            c.execute("CREATE TABLE IF NOT EXISTS chat (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, nombre TEXT, texto TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS tablon (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, nombre TEXT, titulo TEXT, texto TEXT, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
            c.execute("CREATE TABLE IF NOT EXISTS intentos_login (id INTEGER PRIMARY KEY AUTOINCREMENT, ip TEXT, usuario TEXT, exito INTEGER, fecha TIMESTAMP DEFAULT CURRENT_TIMESTAMP)")
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
        self.log_evento('INFO', 'Dueno de ' + str(ip) + ' -> ' + str(nombre))

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
        self.log_evento('WARN', 'Bloqueado: ' + str(ip))

    def desbloquear_dispositivo(self, ip):
        with self.lock:
            c = self.conn.cursor()
            c.execute("UPDATE dispositivos SET bloqueado=0, motivo_bloqueo=NULL, fecha_bloqueo=NULL WHERE ip=?", (ip,))
            self.conn.commit()
        self.log_evento('INFO', 'Desbloqueado: ' + str(ip))

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
        self.log_evento('INFO', 'Codigo canjeado por ' + str(ip))
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

    # ===== NUEVAS: estadisticas publicas =====
    def obtener_stats_publicas(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT SUM(visitas),SUM(descargas),SUM(gb_descargados) FROM estadisticas_diarias")
            g = c.fetchone()
            c.execute("SELECT COUNT(*) FROM dispositivos WHERE bloqueado=0")
            act = c.fetchone()[0]
            return {"visitas": g[0] or 0, "descargas": g[1] or 0, "gb": round(g[2] or 0, 2), "dispositivos_activos": act}

    # ===== NUEVAS: votos, tendencias, ranking =====
    def votos_agregados(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT archivo, SUM(CASE WHEN voto>0 THEN 1 ELSE 0 END), SUM(CASE WHEN voto<0 THEN 1 ELSE 0 END) FROM votos GROUP BY archivo")
            return [{"a": r[0], "u": r[1] or 0, "d": r[2] or 0} for r in c.fetchall()]

    def tendencias_semana(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT archivo, COUNT(*), SUM(tamano_mb) FROM descargas WHERE fecha>=datetime('now','-7 days') GROUP BY archivo ORDER BY COUNT(*) DESC LIMIT 8")
            return [{"a": r[0], "c": r[1], "mb": r[2] or 0} for r in c.fetchall()]

    def ranking_top(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT x.ip, d.nombre_dueno, d.nombre_dispositivo, COUNT(x.id), SUM(x.tamano_mb) FROM descargas x LEFT JOIN dispositivos d ON d.ip=x.ip GROUP BY x.ip ORDER BY COUNT(x.id) DESC LIMIT 10")
            return [{"ip": r[0], "dueno": r[1] or "", "disp": r[2] or "", "c": r[3], "mb": r[4] or 0} for r in c.fetchall()]

    # ===== NUEVAS: comentarios =====
    def comentarios_por(self, archivo):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT nombre,texto,fecha FROM comentarios WHERE archivo=? ORDER BY fecha DESC LIMIT 50", (archivo,))
            return [{"n": r[0], "t": r[1], "f": r[2]} for r in c.fetchall()]

    def agregar_comentario(self, ip, archivo, nombre, texto):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO comentarios (ip,archivo,nombre,texto) VALUES (?,?,?,?)", (ip, archivo, nombre, texto))
            self.conn.commit()

    # ===== NUEVAS: favoritos =====
    def toggle_favorito(self, ip, archivo, path):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT id FROM favoritos WHERE ip=? AND archivo=?", (ip, archivo))
            r = c.fetchone()
            if r:
                c.execute("DELETE FROM favoritos WHERE id=?", (r[0],))
                self.conn.commit()
                return False
            else:
                c.execute("INSERT INTO favoritos (ip,archivo,path) VALUES (?,?,?)", (ip, archivo, path))
                self.conn.commit()
                return True

    def favoritos_de(self, ip):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT archivo,path FROM favoritos WHERE ip=? ORDER BY fecha DESC", (ip,))
            return [{"a": r[0], "p": r[1]} for r in c.fetchall()]

    # ===== NUEVAS: chat =====
    def chat_reciente(self, desde=0):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT id,nombre,texto,fecha FROM chat WHERE id>? ORDER BY id ASC LIMIT 50", (desde,))
            return [{"id": r[0], "n": r[1], "t": r[2], "f": r[3]} for r in c.fetchall()]

    def agregar_chat(self, ip, nombre, texto):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO chat (ip,nombre,texto) VALUES (?,?,?)", (ip, nombre, texto))
            self.conn.commit()

    # ===== NUEVAS: tablon =====
    def tablon_reciente(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT id,nombre,titulo,texto,fecha FROM tablon ORDER BY fecha DESC LIMIT 30")
            return [{"id": r[0], "n": r[1], "ti": r[2], "tx": r[3], "f": r[4]} for r in c.fetchall()]

    def agregar_tablon(self, ip, nombre, titulo, texto):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO tablon (ip,nombre,titulo,texto) VALUES (?,?,?,?)", (ip, nombre, titulo, texto))
            self.conn.commit()

    # ===== NUEVAS: auditoria de login =====
    def registrar_intento_login(self, ip, usuario, exito):
        with self.lock:
            c = self.conn.cursor()
            c.execute("INSERT INTO intentos_login (ip,usuario,exito) VALUES (?,?,?)", (ip, usuario, 1 if exito else 0))
            self.conn.commit()

    def intentos_login(self):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT ip,usuario,exito,fecha FROM intentos_login ORDER BY fecha DESC LIMIT 100")
            return [{"ip": r[0], "u": r[1], "e": r[2], "f": r[3]} for r in c.fetchall()]

    def intentos_fallidos_recientes(self, ip, minutos=15):
        with self.lock:
            c = self.conn.cursor()
            c.execute("SELECT COUNT(*) FROM intentos_login WHERE ip=? AND exito=0 AND fecha>=datetime('now','-' || ? || ' minutes')", (ip, minutos))
            return c.fetchone()[0]

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
                "top_descargadores": [{"ip": r[0], "descargas": r[1], "mb": r[2] or 0} for r in top],
                "dispositivos": [{"ip": r[0], "dispositivo": r[1], "dueno": (r[2] or ""), "ultima_conexion": r[3], "visitas": r[4], "bloqueado": r[5], "motivo": r[6]} for r in devs],
                "generales": {"visitas": gen[0] or 0, "descargas": gen[1] or 0, "gb": round(gen[2] or 0, 2)},
                "ultimos_7_dias": [{"fecha": r[0], "visitas": r[1], "descargas": r[2], "gb": r[3]} for r in dias],
                "peticiones_pendientes": pend, "dispositivos_bloqueados": bloq,
                "ingresos_totales": round(ti, 2), "ingresos_semana": round(is7, 2),
                "ingresos_estimados_mes": round(is7 * 4.33, 2)
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
                w.writerow(['IP', 'Archivo', 'Tamano_MB', 'Fecha', 'User_Agent'])
                c.execute("SELECT ip,archivo,tamano_mb,fecha,user_agent FROM descargas")
            elif tipo == 'pagos':
                w.writerow(['IP', 'Concepto', 'Monto', 'Fecha', 'Notas'])
                c.execute("SELECT ip,concepto,monto,fecha,notas FROM pagos")
            elif tipo == 'dispositivos':
                w.writerow(['IP', 'Dispositivo', 'Dueno', 'Primera', 'Ultima', 'Visitas', 'Bloqueado'])
                c.execute("SELECT ip,nombre_dispositivo,nombre_dueno,primera_conexion,ultima_conexion,visitas,bloqueado FROM dispositivos")
            else: return ""
            for row in c.fetchall(): w.writerow(row)
            return '\ufeff' + out.getvalue()

db = BaseDatos()
db.limpiar_sesiones_viejas()
db.log_evento('INFO', 'Servidor iniciado v11')

# ============================================================
# REGISTRO DE TRANSFERENCIAS ACTIVAS (descargas en vivo)
# ============================================================
TRANSFERENCIAS = {}
TR_LOCK = threading.Lock()
_TR_ID = 0

def transfer_iniciar(ip, archivo, total, ua):
    global _TR_ID
    with TR_LOCK:
        _TR_ID += 1
        tid = _TR_ID
        TRANSFERENCIAS[tid] = {"ip": ip, "archivo": archivo, "total": total, "enviado": 0, "inicio": time.time(), "ua": ua}
    return tid

def transfer_progreso(tid, enviado):
    with TR_LOCK:
        t = TRANSFERENCIAS.get(tid)
        if t: t["enviado"] = enviado

def transfer_fin(tid):
    with TR_LOCK:
        TRANSFERENCIAS.pop(tid, None)

def transfer_snapshot():
    ahora = time.time()
    out = []
    with TR_LOCK:
        for tid, t in list(TRANSFERENCIAS.items()):
            dur = max(0.5, ahora - t["inicio"])
            vel = t["enviado"] / dur
            out.append({
                "ip": t["ip"],
                "archivo": os.path.basename(t["archivo"]),
                "total": round(t["total"] / (1024 * 1024), 2),
                "enviado": round(t["enviado"] / (1024 * 1024), 2),
                "vel": round(vel / (1024 * 1024), 2),
                "seg": int(ahora - t["inicio"]),
                "pct": (t["enviado"] * 100 // t["total"]) if t["total"] else 0
            })
    return out

# ============================================================
# ICONO SVG, SERVICE WORKER Y MANIFEST
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
# HTML PAGINA PRINCIPAL v11
# ============================================================
HTML_PAGINA = r"""<!DOCTYPE html>
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
html,body{margin:0!important;padding:0!important;width:100%;overflow-x:hidden;-webkit-text-size-adjust:100%}
body{font-family:'Segoe UI',Arial,sans-serif;background:#050816;color:#e0e6ed;min-height:100vh;min-height:100dvh}
:root{--p:#00ff88;--s:#00d4ff;--a:#ff00ff;--d:#ff3366;--w:#ffaa00;--dk:#050816;--l:#e0e6ed;--g:rgba(10,14,39,0.78)}
#mc{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-2;opacity:0.1}
.go{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-3;background-image:linear-gradient(rgba(0,255,136,0.02) 1px,transparent 1px),linear-gradient(90deg,rgba(0,255,136,0.02) 1px,transparent 1px);background-size:60px 60px}
.ct{max-width:1240px;margin:0 auto;padding:20px 18px;position:relative;z-index:1}
.hd{display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:14px;padding:20px 26px;background:var(--g);backdrop-filter:blur(20px);border-radius:18px;border:1px solid rgba(0,255,136,0.15);box-shadow:0 8px 40px rgba(0,0,0,0.4);margin-bottom:20px;position:relative;overflow:hidden}
.hd::before{content:'';position:absolute;top:0;left:-100%;width:100%;height:2px;background:linear-gradient(90deg,transparent,var(--p),var(--s),transparent);animation:sc 4s linear infinite}
@keyframes sc{0%{left:-100%}100%{left:100%}}
.lg h1{font-size:28px;font-weight:800;background:linear-gradient(135deg,var(--p),var(--s),var(--a));-webkit-background-clip:text;-webkit-text-fill-color:transparent;background-clip:text;font-family:'Courier New',monospace}
.lg .sub{font-size:11px;color:rgba(0,255,136,0.6);margin-top:4px;font-family:'Courier New',monospace}
.live{display:inline-flex;align-items:center;gap:7px;font-size:11px;font-family:'Courier New',monospace;color:var(--p);padding:4px 12px;background:rgba(0,255,136,0.08);border-radius:20px;border:1px solid rgba(0,255,136,0.25);margin-top:8px}
.live .dot{width:8px;height:8px;border-radius:50%;background:var(--p);animation:pu 1.6s infinite}
@keyframes pu{0%,100%{opacity:1}50%{opacity:.4}}
.ha{display:flex;gap:8px;align-items:center;flex-wrap:wrap}
.bt{padding:10px 18px;border-radius:10px;border:none;font-weight:600;font-size:13px;cursor:pointer;transition:all 0.3s;font-family:'Courier New',monospace}
.bp{background:linear-gradient(135deg,var(--p),var(--s));color:var(--dk);box-shadow:0 4px 20px rgba(0,255,136,0.3)}
.bp:hover{transform:translateY(-2px)}
.bg2{background:rgba(0,255,136,0.08);color:var(--p);border:1px solid rgba(0,255,136,0.25)}
.bg2:hover{background:rgba(0,255,136,0.15)}
.ticker{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:22px}
.tk{background:var(--g);border:1px solid rgba(0,255,136,0.12);border-radius:14px;padding:14px 12px;text-align:center;position:relative;overflow:hidden}
.tk::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--p),var(--s))}
.tk .tv{font-size:20px;font-weight:800;color:var(--p);font-family:'Courier New',monospace}
.tk .tl{font-size:10px;color:rgba(224,230,237,.55);text-transform:uppercase;letter-spacing:.6px;margin-top:3px;font-family:'Courier New',monospace}
.st{margin-bottom:40px}
.stt{display:flex;align-items:center;gap:12px;margin-bottom:18px;font-size:18px;font-weight:700;color:var(--l);font-family:'Courier New',monospace}
.stt::before{content:'>';color:var(--p);animation:bl 1s infinite}
@keyframes bl{0%,50%{opacity:1}51%,100%{opacity:0}}
.bdg{background:linear-gradient(135deg,var(--a),var(--s));font-size:9px;padding:4px 12px;border-radius:4px;color:var(--dk);letter-spacing:1.5px;font-weight:700;text-transform:uppercase}
.cw{position:relative;overflow:hidden;border-radius:18px;background:var(--g);border:1px solid rgba(0,255,136,0.15)}
.ctrk{display:flex;transition:transform 0.8s cubic-bezier(0.4,0,0.2,1)}
.csl{min-width:100%;display:flex;align-items:center;gap:32px;padding:36px}
.csl img{width:160px;height:220px;object-fit:cover;border-radius:14px;border:2px solid rgba(0,255,136,0.4);flex-shrink:0;background:rgba(0,0,0,0.3)}
.ci{flex:1;min-width:0}
.ci h3{font-size:22px;font-weight:700;color:var(--l);margin-bottom:10px;font-family:'Courier New',monospace}
.ci p{color:rgba(224,230,237,0.6);font-size:14px;line-height:1.6;margin-bottom:14px}
.tgs{display:flex;gap:8px;flex-wrap:wrap}
.tg{background:rgba(0,255,136,0.1);color:var(--p);padding:5px 14px;border-radius:6px;font-size:11px;font-weight:600;border:1px solid rgba(0,255,136,0.2);font-family:'Courier New',monospace}
.cds{display:flex;justify-content:center;gap:8px;padding:14px 0 4px 0}
.cds button{width:10px;height:10px;border-radius:50%;border:none;background:rgba(0,255,136,0.25);cursor:pointer;transition:all 0.3s}
.cds button.act{background:var(--p);box-shadow:0 0 15px var(--p);width:26px;border-radius:8px}
.hscroll{display:flex;gap:14px;overflow-x:auto;padding-bottom:10px}
.hcard{min-width:150px;max-width:150px;background:var(--g);border:1px solid rgba(0,255,136,0.15);border-radius:14px;overflow:hidden;cursor:pointer;transition:.25s;flex-shrink:0}
.hcard:hover{transform:translateY(-4px);border-color:var(--p)}
.hcard .himg{height:90px;display:flex;align-items:center;justify-content:center;font-size:34px;background:rgba(0,255,136,0.04)}
.hcard .himg img{width:100%;height:100%;object-fit:cover}
.hcard .hname{padding:8px 10px;font-size:11px;font-family:'Courier New',monospace;color:var(--l);white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.hcard .hmeta{padding:0 10px 8px;font-size:10px;color:rgba(0,255,136,.7);font-family:'Courier New',monospace}
.fc{background:var(--g);border:1px solid rgba(0,255,136,0.18);border-radius:16px;overflow:hidden}
.fc-top{display:flex;align-items:center;gap:8px;padding:10px 12px;background:rgba(0,0,0,.35);border-bottom:1px solid rgba(0,255,136,.12);flex-wrap:wrap}
.fc-btn{padding:7px 12px;border-radius:8px;background:rgba(0,255,136,.07);border:1px solid rgba(0,255,136,.2);color:var(--l);font-family:'Courier New',monospace;font-size:12px;cursor:pointer;transition:.2s;display:inline-flex;align-items:center;gap:6px}
.fc-btn:hover{background:rgba(0,255,136,.16);color:var(--p)}
.fc-btn.act{background:rgba(0,255,136,.2);color:var(--p);border-color:var(--p)}
.fc-path{flex:1;min-width:140px;display:flex;align-items:center;gap:6px;background:rgba(0,0,0,.4);border:1px solid rgba(0,255,136,.18);border-radius:8px;padding:7px 12px;font-family:'Courier New',monospace;font-size:12px;color:var(--p);overflow-x:auto;white-space:nowrap}
.bc-item{cursor:pointer;padding:2px 6px;border-radius:5px;color:rgba(224,230,237,.8)}
.bc-item:hover{background:rgba(0,255,136,.15);color:var(--p)}
.bc-item.bc-active{color:var(--p);font-weight:700;cursor:default}
.bc-sep{color:rgba(0,255,136,.4)}
.fc-search{display:flex;align-items:center;background:rgba(0,0,0,.4);border:1px solid rgba(0,255,136,.2);border-radius:8px;padding:0 10px;position:relative}
.fc-search input{background:transparent;border:none;color:var(--l);padding:8px;width:180px;outline:none;font-size:13px;font-family:'Courier New',monospace}
.sugs{position:absolute;top:100%;left:0;right:0;background:#0a0e27;border:1px solid rgba(0,255,136,.3);border-radius:8px;margin-top:4px;z-index:50;max-height:220px;overflow-y:auto;display:none}
.sugs div{padding:8px 12px;font-size:12px;font-family:'Courier New',monospace;cursor:pointer;color:var(--l);border-bottom:1px solid rgba(0,255,136,.06)}
.sugs div:hover{background:rgba(0,255,136,.12);color:var(--p)}
.fc-head{display:grid;grid-template-columns:minmax(0,1fr) 80px 90px 120px 150px;gap:8px;padding:10px 16px;background:rgba(0,255,136,.05);border-bottom:1px solid rgba(0,255,136,.15);font-family:'Courier New',monospace;font-size:11px;text-transform:uppercase;color:rgba(0,255,136,.8)}
.fc-hc{cursor:pointer;display:flex;align-items:center;gap:5px}
.fc-hc:hover{color:var(--p)}
.fc-body{max-height:520px;overflow-y:auto}
.fc-row{display:grid;grid-template-columns:minmax(0,1fr) 80px 90px 120px 150px;gap:8px;padding:9px 16px;border-bottom:1px solid rgba(0,255,136,.05);align-items:center;font-family:'Courier New',monospace;font-size:13px}
.fc-row:hover{background:rgba(0,255,136,.06)}
.fc-folder{cursor:pointer}
.fc-folder .fc-name{color:var(--p);font-weight:600}
.fc-cell{overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.fc-name{display:flex;align-items:center;gap:9px}
.fc-ico{font-size:16px;flex-shrink:0}
.fc-size,.fc-type,.fc-date{color:rgba(224,230,237,.6);font-size:12px}
.fc-acts{display:flex;gap:6px;justify-content:flex-end}
.mini{padding:4px 8px;border-radius:6px;font-size:11px;font-family:'Courier New',monospace;cursor:pointer;border:1px solid rgba(0,255,136,.25);background:rgba(0,255,136,.06);color:var(--p);text-decoration:none;display:inline-block;transition:.15s}
.mini:hover{background:rgba(0,255,136,.18)}
.mini.dl{background:linear-gradient(135deg,var(--p),var(--s));color:var(--dk);font-weight:700;border:none}
.mini.heart.on{color:var(--d);border-color:var(--d)}
.fc-status{display:flex;justify-content:space-between;flex-wrap:wrap;gap:8px;padding:10px 16px;background:rgba(0,0,0,.35);border-top:1px solid rgba(0,255,136,.12);font-family:'Courier New',monospace;font-size:12px;color:rgba(0,255,136,.8)}
.grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:14px}
.card{background:var(--g);border:1px solid rgba(0,255,136,.15);border-radius:14px;overflow:hidden;transition:.25s}
.card:hover{transform:translateY(-4px);border-color:rgba(0,255,136,.4);box-shadow:0 10px 30px rgba(0,255,136,.12)}
.card-img{height:180px;position:relative;background:rgba(0,255,136,.03);display:flex;align-items:center;justify-content:center;font-size:44px;overflow:hidden}
.card-img img{width:100%;height:100%;object-fit:cover}
.card-img .play{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;background:rgba(0,0,0,.35);opacity:0;transition:.2s}
.card:hover .play{opacity:1}
.play span{width:52px;height:52px;border-radius:50%;background:rgba(0,255,136,.9);color:#050816;display:flex;align-items:center;justify-content:center;font-size:20px}
.card-body{padding:10px 12px}
.card-title{font-size:13px;font-weight:600;color:var(--l);font-family:'Courier New',monospace;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}
.badges{display:flex;gap:6px;flex-wrap:wrap;margin-top:6px}
.badge{font-size:9px;padding:3px 8px;border-radius:4px;font-family:'Courier New',monospace;font-weight:700}
.b-anio{background:rgba(0,212,255,.12);color:var(--s);border:1px solid rgba(0,212,255,.3)}
.b-cal{background:rgba(255,0,255,.12);color:var(--a);border:1px solid rgba(255,0,255,.3)}
.b-voto{background:rgba(255,170,0,.12);color:var(--w);border:1px solid rgba(255,170,0,.3)}
.b-size{background:rgba(0,255,136,.1);color:var(--p);border:1px solid rgba(0,255,136,.25)}
.card-acts{display:flex;gap:6px;margin-top:8px;align-items:center}
.serie-h{font-family:'Courier New',monospace;color:var(--s);font-size:14px;margin:16px 0 10px;padding-left:4px;border-left:3px solid var(--s)}
.anc{background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.2);border-radius:12px;padding:15px 19px;margin-bottom:11px;border-left:4px solid var(--s)}
.anc h4{color:var(--s);font-family:'Courier New',monospace;margin-bottom:5px;font-size:14px}
.anc p{color:rgba(224,230,237,0.6);font-size:13px;font-family:'Courier New',monospace}
.doscol{display:grid;grid-template-columns:1fr 1fr;gap:18px}
.panel{background:var(--g);border:1px solid rgba(0,255,136,.15);border-radius:16px;padding:18px;display:flex;flex-direction:column}
.panel h3{font-family:'Courier New',monospace;color:var(--p);font-size:15px;margin-bottom:12px}
.chatbox{flex:1;min-height:220px;max-height:300px;overflow-y:auto;background:rgba(0,0,0,.3);border-radius:10px;padding:12px;margin-bottom:10px}
.msg{margin-bottom:10px;font-size:13px;font-family:'Courier New',monospace;line-height:1.4}
.msg .who{color:var(--s);font-weight:700}
.msg .me .who{color:var(--p)}
.msg .txt{color:var(--l)}
.msg .hora{color:rgba(224,230,237,.3);font-size:10px;margin-left:6px}
.chatin{display:flex;gap:8px}
.chatin input{flex:1;background:rgba(0,0,0,.4);border:1px solid rgba(0,255,136,.2);border-radius:8px;padding:10px;color:var(--l);font-family:'Courier New',monospace;outline:none}
.tb-post{background:rgba(0,255,136,.04);border:1px solid rgba(0,255,136,.12);border-radius:10px;padding:12px;margin-bottom:10px}
.tb-post h5{color:var(--p);font-family:'Courier New',monospace;font-size:13px;margin-bottom:4px}
.tb-post p{color:rgba(224,230,237,.6);font-size:12px;font-family:'Courier New',monospace}
.tb-post small{color:rgba(224,230,237,.3);font-size:10px;font-family:'Courier New',monospace}
.rank-row{display:flex;align-items:center;gap:12px;padding:9px 12px;border-bottom:1px solid rgba(0,255,136,.06);font-family:'Courier New',monospace;font-size:13px}
.rank-row .med{font-size:18px;width:28px;text-align:center}
.rank-row .nm{flex:1;color:var(--l)}
.rank-row .st{color:var(--p);font-size:12px}
.stbar{height:10px;border-radius:6px;background:rgba(0,255,136,.1);overflow:hidden;margin-top:8px}
.stbar div{height:100%;background:linear-gradient(90deg,var(--p),var(--s));width:0%;transition:width .3s;border-radius:6px}
.stres{font-family:'Courier New',monospace;color:var(--p);font-size:20px;font-weight:800;margin-top:8px}
.plans{display:grid;grid-template-columns:repeat(3,1fr);gap:16px}
.plan{position:relative;background:var(--g);border:1px solid rgba(0,255,136,.15);border-radius:18px;padding:26px 22px;text-align:center;transition:.3s;overflow:hidden}
.plan::before{content:'';position:absolute;top:0;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--p),var(--s))}
.plan:hover{transform:translateY(-5px);border-color:rgba(0,255,136,.4)}
.plan.hot{border-color:rgba(255,0,255,.4)}
.plan.hot::before{background:linear-gradient(90deg,var(--a),var(--w))}
.plan .pi{font-size:34px;margin-bottom:8px}
.plan .pname{font-size:12px;text-transform:uppercase;letter-spacing:1.2px;color:rgba(224,230,237,.55);font-family:'Courier New',monospace;margin-bottom:8px}
.plan .pprice{font-size:32px;font-weight:800;color:var(--p);font-family:'Courier New',monospace}
.plan.hot .pprice{color:var(--a)}
.plan .pdesc{font-size:12px;color:rgba(224,230,237,.5);margin-top:8px;font-family:'Courier New',monospace}
.plan .hot-tag{position:absolute;top:14px;right:-30px;transform:rotate(38deg);background:linear-gradient(135deg,var(--a),var(--w));color:var(--dk);font-size:9px;font-weight:800;padding:4px 36px;letter-spacing:1px;font-family:'Courier New',monospace}
.md{display:none;position:fixed;top:0;left:0;width:100%;height:100%;background:rgba(0,0,0,0.92);backdrop-filter:blur(12px);z-index:1000;align-items:center;justify-content:center;padding:20px}
.md.ac{display:flex}
.mdc{background:var(--g);border:1px solid rgba(0,255,136,0.3);border-radius:18px;padding:30px;max-width:480px;width:100%;box-shadow:0 20px 80px rgba(0,0,0,0.6);position:relative;max-height:90vh;overflow-y:auto}
.mdc.wide{max-width:820px}
.mdc::before{content:'';position:absolute;top:-1px;left:0;right:0;height:3px;background:linear-gradient(90deg,var(--p),var(--s),var(--a));border-radius:18px 18px 0 0}
.mdc h2{margin-bottom:16px;color:var(--p);font-family:'Courier New',monospace;font-size:18px}
.fg{margin-bottom:15px}
.fg label{display:block;margin-bottom:6px;color:rgba(224,230,237,0.6);font-size:12px;font-weight:600;font-family:'Courier New',monospace;text-transform:uppercase}
.fg input,.fg select,.fg textarea{width:100%;padding:11px 14px;background:rgba(0,0,0,0.4);border:1px solid rgba(0,255,136,0.2);border-radius:10px;color:var(--l);font-family:'Courier New',monospace;font-size:14px}
.fg textarea{resize:vertical;min-height:80px}
.ma{display:flex;gap:12px;margin-top:20px}
.videoWrap{background:#000;border-radius:12px;overflow:hidden}
.videoWrap video{width:100%;max-height:60vh;display:block}
.clist{max-height:260px;overflow-y:auto;margin-bottom:12px}
.cmsg{background:rgba(0,255,136,.05);border:1px solid rgba(0,255,136,.1);border-radius:8px;padding:8px 12px;margin-bottom:8px;font-size:13px;font-family:'Courier New',monospace}
.cmsg b{color:var(--s)}
.cmsg small{color:rgba(224,230,237,.35);float:right}
.ft{margin-top:44px;text-align:center;font-size:13px;color:rgba(224,230,237,0.3);padding-top:22px;border-top:1px solid rgba(0,255,136,0.06);font-family:'Courier New',monospace}
.ft .cr{font-size:14px;color:rgba(0,255,136,0.7)}
.ld{display:inline-block;width:20px;height:20px;border:3px solid rgba(0,255,136,0.1);border-radius:50%;border-top-color:var(--p);animation:sp 1s linear infinite}
@keyframes sp{to{transform:rotate(360deg)}}
.toast{position:fixed;bottom:24px;right:24px;background:var(--g);border:1px solid var(--p);border-radius:12px;padding:14px 22px;font-family:'Courier New',monospace;font-size:13px;color:var(--p);z-index:9999;transform:translateY(100px);opacity:0;transition:all 0.4s}
.toast.show{transform:translateY(0);opacity:1}
.toast.err{border-color:var(--d);color:var(--d)}
.btnInst{position:fixed;bottom:22px;left:22px;z-index:998;padding:13px 20px;border-radius:50px;font-size:13px;animation:flotar 3s ease-in-out infinite;box-shadow:0 8px 30px rgba(0,255,136,0.4)}
@keyframes flotar{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}
::-webkit-scrollbar{width:8px;height:8px}::-webkit-scrollbar-track{background:var(--dk)}::-webkit-scrollbar-thumb{background:rgba(0,255,136,0.4);border-radius:10px}
@media(max-width:900px){.plans{grid-template-columns:1fr 1fr}.plan.hot{grid-column:span 2}.doscol{grid-template-columns:1fr}}
@media(max-width:768px){
.hd{flex-direction:column;align-items:stretch;gap:14px;padding:18px}
.csl{flex-direction:column;text-align:center;padding:22px;gap:18px}
.csl img{width:130px;height:180px}
.ticker{grid-template-columns:repeat(3,1fr)}
.fc-head{grid-template-columns:minmax(0,1fr) 70px 110px}
.fc-row{grid-template-columns:minmax(0,1fr) 70px 110px}
.fc-type,.fc-date{display:none}
}
@media(max-width:560px){
.ticker{grid-template-columns:repeat(2,1fr)}
.plans{grid-template-columns:1fr}
.plan.hot{grid-column:span 1}
.grid{grid-template-columns:repeat(auto-fill,minmax(130px,1fr))}
.card-img{height:140px}
}
</style>
</head>
<body>
<canvas id="mc"></canvas>
<div class="go"></div>
<div class="ct">

<header class="hd">
<div class="lg">
<h1>./mi_pakete</h1>
<div class="sub">root@multimedia:~$ ./start_server.sh</div>
<span class="live"><span class="dot"></span> SISTEMA ACTIVO · <span id="reloj">--:--:--</span></span>
</div>
<div class="ha">
<button class="bt bg2" id="btnCod">🎫 codigo</button>
<button class="bt bg2" id="btnPet">📝 solicitar</button>
<button class="bt bg2" id="btnNick">👤 <span id="nickLbl">anon</span></button>
<button class="bt bp" id="btnAdm">🔐 admin</button>
</div>
</header>

<div class="ticker">
<div class="tk"><div class="tv" id="tkArch">0</div><div class="tl">📂 archivos</div></div>
<div class="tk"><div class="tv" id="tkCarp">0</div><div class="tl">📁 carpetas</div></div>
<div class="tk"><div class="tv" id="tkGB">0</div><div class="tl">💾 GB</div></div>
<div class="tk"><div class="tv" id="tkVis">0</div><div class="tl">👁 visitas</div></div>
<div class="tk"><div class="tv" id="tkDes">0</div><div class="tl">📥 descargas</div></div>
<div class="tk"><div class="tv" id="tkDev">0</div><div class="tl">📱 conectados</div></div>
</div>

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
<div class="stt">🔥 TENDENCIAS_DE_LA_SEMANA <span class="bdg">Lo mas pedido</span></div>
<div class="hscroll" id="trendRow"><div class="ld"></div></div>
</section>

<section class="st">
<div class="stt">✨ NOVEDADES_DE_LA_SEMANA <span class="bdg">Recien agregado</span></div>
<div class="hscroll" id="noveRow"><div class="ld"></div></div>
</section>

<section class="st">
<div class="stt">📂 EXPLORADOR_DE_ARCHIVOS</div>
<div class="fc">
<div class="fc-top">
<button class="fc-btn" id="fcAtras">←</button>
<button class="fc-btn" id="fcSubir">↑ Subir</button>
<button class="fc-btn" id="fcHome">🏠</button>
<button class="fc-btn act" id="vLista">📋 Lista</button>
<button class="fc-btn" id="vGaleria">🎬 Galería</button>
<button class="fc-btn" id="vFav">❤️ Favoritos (<span id="favCount">0</span>)</button>
<div class="fc-path" id="fc-breadcrumb"></div>
<div class="fc-search"><span style="color:var(--p)">🔍</span><input type="text" id="fcBusq" placeholder="buscar..." autocomplete="off"><div class="sugs" id="sugs"></div></div>
</div>
<div class="fc-head" id="fcHead">
<div class="fc-hc" data-sort="name">Nombre <span id="arw-name">▼</span></div>
<div class="fc-hc" data-sort="size">Tamaño <span id="arw-size"></span></div>
<div class="fc-hc fc-type">Tipo</div>
<div class="fc-hc fc-date" data-sort="date">Fecha <span id="arw-date"></span></div>
<div class="fc-hc" style="justify-content:flex-end">Acciones</div>
</div>
<div class="fc-body" id="fc-rows"><div style="text-align:center;padding:50px"><div class="ld"></div></div></div>
<div class="fc-status"><span id="fc-status-left">—</span><span id="fc-status-right" style="color:rgba(224,230,237,.5)">Mi Pakete v11</span></div>
</div>
</section>

<section class="st">
<div class="stt">🏆 RANKING_DESCARGADORES</div>
<div class="panel" id="rankBox"><div class="ld"></div></div>
</section>

<section class="st">
<div class="doscol">
<div class="panel">
<h3>💬 CHAT_LOCAL <span style="font-size:10px;color:rgba(224,230,237,.4)">entre conectados</span></h3>
<div class="chatbox" id="chatBox"></div>
<div class="chatin"><input type="text" id="chatIn" placeholder="escribe un mensaje..." maxlength="200"><button class="bt bp" id="chatSend">➤</button></div>
</div>
<div class="panel">
<h3>📌 TABLON_DEL_BARRIO <span style="font-size:10px;color:rgba(224,230,237,.4)">avisos y recados</span></h3>
<div id="tablonBox" style="flex:1;max-height:240px;overflow-y:auto"></div>
<div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
<input type="text" id="tabTitulo" placeholder="titulo" style="flex:1;min-width:100px;background:rgba(0,0,0,.4);border:1px solid rgba(0,255,136,.2);border-radius:8px;padding:9px;color:var(--l);font-family:'Courier New',monospace">
<input type="text" id="tabTexto" placeholder="mensaje..." style="flex:2;min-width:140px;background:rgba(0,0,0,.4);border:1px solid rgba(0,255,136,.2);border-radius:8px;padding:9px;color:var(--l);font-family:'Courier New',monospace">
<button class="bt bp" id="tabSend">📌 publicar</button>
</div>
</div>
</div>
</section>

<section class="st">
<div class="stt">🚀 TEST_DE_VELOCIDAD <span class="bdg">Local</span></div>
<div class="panel">
<p style="font-family:'Courier New',monospace;font-size:13px;color:rgba(224,230,237,.6)">Mide cuantos MB por segundo te llegan desde el servidor. Ideal para saber cuanto tardara una pelicula.</p>
<button class="bt bp" id="btnSpeed" style="margin-top:12px;align-self:flex-start">▶ iniciar test (3 MB)</button>
<div class="stbar"><div id="speedBar"></div></div>
<div class="stres" id="speedRes">—</div>
</div>
</section>

<section class="st">
<div class="stt">💰 PLANES_Y_PRECIOS</div>
<div class="plans">
<div class="plan"><div class="pi">💾</div><div class="pname">Por GB</div><div class="pprice">6.25 CUP</div><div class="pdesc">Pagas solo por lo que descargas.</div></div>
<div class="plan"><div class="pi">🌙</div><div class="pname">Día ilimitado</div><div class="pprice">50 CUP</div><div class="pdesc">Descarga todo durante 24 horas.</div></div>
<div class="plan hot"><div class="hot-tag">MEJOR OFERTA</div><div class="pi">📅</div><div class="pname">Semanal</div><div class="pprice">200 CUP</div><div class="pdesc">7 días de descargas ilimitadas.</div></div>
</div>
</section>

<div class="ft"><div class="cr">☕ Creado por <strong>Carlos A Lorenzo Marro</strong> con cafe, anime e IA 🌸🤖</div></div>
</div>

<button class="bt bp btnInst" id="btnInstalar">📱 instalar_app</button>

<!-- MODALES -->
<div class="md" id="mPet"><div class="mdc">
<h2>📝 solicitar_contenido.sh</h2>
<form id="fPet">
<div class="fg"><label>tipo</label>
<select name="tipo" required><option value="">selecciona...</option><option value="pelicula">🎬 pelicula</option><option value="serie">📺 serie</option><option value="musica">🎵 musica</option><option value="otro">📦 otro</option></select></div>
<div class="fg"><label>nombre</label><input type="text" name="contenido" placeholder="Ej: The Batman 2022" required></div>
<div class="fg"><label>detalles</label><textarea name="detalles" placeholder="temporada, calidad..."></textarea></div>
<div class="ma"><button type="button" class="bt bg2" id="btnCanPet">cancelar</button><button type="submit" class="bt bp">enviar</button></div>
</form>
</div></div>

<div class="md" id="mLog"><div class="mdc">
<h2>🔐 autenticacion_root</h2>
<form id="fLog">
<div class="fg"><label>usuario</label><input type="text" name="usuario" value="root" autocomplete="username" required></div>
<div class="fg"><label>contrasena</label><input type="password" name="password" autocomplete="current-password" required></div>
<div class="ma"><button type="button" class="bt bg2" id="btnCanLog">cancelar</button><button type="submit" class="bt bp" id="btnSubLog">ingresar</button></div>
</form>
</div></div>

<div class="md" id="mCod"><div class="mdc">
<h2>🎫 canjear_codigo</h2>
<div class="fg"><label>codigo</label><input type="text" id="codInput" placeholder="A1B2C3D4E5F6" style="text-transform:uppercase"></div>
<div class="ma"><button type="button" class="bt bg2" id="btnCanCod">cancelar</button><button type="button" class="bt bp" id="btnOkCod">activar</button></div>
</div></div>

<div class="md" id="mNick"><div class="mdc">
<h2>👤 tu_nombre</h2>
<p style="color:rgba(224,230,237,.6);font-size:13px;font-family:'Courier New',monospace;margin-bottom:14px">Asi te veran en el chat y el tablon.</p>
<div class="fg"><label>nombre / apodo</label><input type="text" id="nickInput" maxlength="20" placeholder="Ej: Carlos"></div>
<div class="ma"><button type="button" class="bt bp" id="btnOkNick">guardar</button></div>
</div></div>

<div class="md" id="mPlay"><div class="mdc wide">
<h2 id="playTitle">▶ reproduciendo</h2>
<div class="videoWrap"><video id="playerV" controls autoplay playsinline></video></div>
<div class="ma"><button type="button" class="bt bg2" id="btnClosePlay">cerrar</button></div>
</div></div>

<div class="md" id="mComm"><div class="mdc">
<h2>💬 comentarios</h2>
<p id="commFile" style="color:var(--s);font-size:12px;font-family:'Courier New',monospace;margin-bottom:10px"></p>
<div class="clist" id="commList"></div>
<div class="fg"><label>tu reseña</label><textarea id="commText" placeholder="ya la viste? que tal?"></textarea></div>
<div class="ma"><button type="button" class="bt bg2" id="btnCanComm">cerrar</button><button type="button" class="bt bp" id="btnOkComm">publicar</button></div>
</div></div>

<div class="md" id="mInst"><div class="mdc">
<h2>📱 instalar_como_app</h2>
<div id="instPasos"></div>
<div class="ma"><button type="button" class="bt bp" id="btnCanInst" style="width:100%">entendido</button></div>
</div></div>

<div class="toast" id="toast"></div>

<script>
(function(){
/* fondo matrix */
var cv=document.getElementById('mc'),cx=cv.getContext('2d');cv.width=innerWidth;cv.height=innerHeight;
var ch='01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン';
var fs=14,cl=Math.floor(cv.width/fs),dr=[],i;for(i=0;i<cl;i++)dr[i]=1;
setInterval(function(){cx.fillStyle='rgba(5,8,22,0.05)';cx.fillRect(0,0,cv.width,cv.height);cx.fillStyle='#00ff88';cx.font=fs+'px monospace';for(var j=0;j<dr.length;j++){var t=ch[Math.floor(Math.random()*ch.length)];cx.fillText(t,j*fs,dr[j]*fs);if(dr[j]*fs>cv.height&&Math.random()>0.975)dr[j]=0;dr[j]++;}},50);
addEventListener('resize',function(){cv.width=innerWidth;cv.height=innerHeight;});
if(window.top!==window.self){try{if(window.top.location.hostname!==window.self.location.hostname){document.body.innerHTML='<h1 style="color:#fff;text-align:center;margin-top:40vh">Acceso bloqueado</h1>';}}catch(e){document.body.innerHTML='<h1 style="color:#fff">Acceso bloqueado</h1>';}}
document.addEventListener('dragstart',function(e){if(e.target.tagName==='IMG')e.preventDefault();});
function tick(){var d=new Date();var el=document.getElementById('reloj');if(el)el.textContent=('0'+d.getHours()).slice(-2)+':'+('0'+d.getMinutes()).slice(-2)+':'+('0'+d.getSeconds()).slice(-2);}
setInterval(tick,1000);tick();
if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(function(){});}
var toastEl=document.getElementById('toast');
function toast(msg,err){toastEl.textContent=msg;toastEl.className='toast show'+(err?' err':'');setTimeout(function(){toastEl.className='toast';},3500);}

/* ===== NICKNAME ===== */
var nick=localStorage.getItem('mp_nick')||'';
function updNick(){document.getElementById('nickLbl').textContent=nick||'anon';}
updNick();
document.getElementById('btnNick').addEventListener('click',function(){document.getElementById('nickInput').value=nick;document.getElementById('mNick').classList.add('ac');});
document.getElementById('btnOkNick').addEventListener('click',function(){var v=document.getElementById('nickInput').value.trim();nick=v;localStorage.setItem('mp_nick',v);updNick();document.getElementById('mNick').classList.remove('ac');toast('✅ nombre guardado');});

/* ===== HELPERS ===== */
function esc(t){var d=document.createElement('div');d.textContent=t==null?'':t;return d.innerHTML;}
function getExt(n){var p=n.split('.');return p.length>1?p.pop().toLowerCase():'';}
function isVideo(n){return['mp4','avi','mkv','mov','wmv','webm'].indexOf(getExt(n))>=0;}
function getIco(n){var e=getExt(n);if(isVideo(n))return'🎬';if(['mp3','wav','flac','aac','ogg'].indexOf(e)>=0)return'🎵';if(['jpg','jpeg','png','gif','bmp','webp'].indexOf(e)>=0)return'🖼️';if(['srt','ass','ssa','sub'].indexOf(e)>=0)return'📝';if(['zip','rar','7z','tar','gz'].indexOf(e)>=0)return'📦';if(e==='apk')return'🤖';return'📄';}
function getTipo(n){var e=getExt(n);if(isVideo(n))return'Video';if(['mp3','wav','flac','aac','ogg'].indexOf(e)>=0)return'Audio';if(['jpg','jpeg','png','gif','bmp','webp'].indexOf(e)>=0)return'Imagen';if(['srt','ass','ssa','sub'].indexOf(e)>=0)return'Subtitulo';if(['zip','rar','7z','tar','gz'].indexOf(e)>=0)return'Comprimido';return'Archivo';}
function fmtSize(mb){if(mb==null)return'—';if(mb<1)return Math.round(mb*1024)+' KB';if(mb>=1024)return(mb/1024).toFixed(2)+' GB';return mb.toFixed(2)+' MB';}

/* ===== METADATOS DESDE NOMBRE ===== */
var CALIDADES=['2160p','1080p','720p','480p','4k','1080','720','brrip','bluray','webrip','hdtv','dvd','cam','hdts'];
function parseMeta(nombre){
var base=nombre.replace(/\.[^.]+$/,'');
var anio=null,calidad=null;
var m=base.match(/\b(19|20)\d{2}\b/);if(m)anio=m[0];
var low=base.toLowerCase();
for(var q=0;q<CALIDADES.length;q++){if(low.indexOf(CALIDADES[q])>=0){calidad=CALIDADES[q].toUpperCase();if(/^\d+$/.test(calidad))calidad+='p';break;}}
var titulo=base.replace(/[._]/g,' ').replace(/\b(19|20)\d{2}\b/gi,' ');
for(var c=0;c<CALIDADES.length;c++){titulo=titulo.replace(new RegExp('\\b'+CALIDADES[c]+'\\b','gi'),'');}
titulo=titulo.replace(/[sS]\d{1,2}[eE]\d{1,3}/g,'').replace(/\d{1,2}x\d{2,3}/g,'').replace(/\b(temporada|season)\s*\d{1,2}\b/gi,'').replace(/\s+/g,' ').trim();
if(!titulo)titulo=base;
return{titulo:titulo,anio:anio,calidad:calidad};
}
function matchSerie(nombre){
var base=nombre.replace(/\.[^.]+$/,'');
var m=base.match(/^(.+?)[._\s-]*[Ss](\d{1,2})[._\s-]*[Ee](\d{1,3})/);
if(m)return{serie:m[1].replace(/[._]/g,' ').trim(),t:parseInt(m[2]),e:parseInt(m[3])};
m=base.match(/^(.+?)[._\s-]+(\d{1,2})x(\d{2,3})/);
if(m)return{serie:m[1].replace(/[._]/g,' ').trim(),t:parseInt(m[2]),e:parseInt(m[3])};
m=base.match(/^(.+?)[._\s-]*(?:temporada|season)[._\s-]*(\d{1,2})/i);
if(m)return{serie:m[1].replace(/[._]/g,' ').trim(),t:parseInt(m[2]),e:0};
return null;
}
function scoreStr(nombre){
var v=votosMap[nombre];if(!v)return'';
var total=v.u+v.d;if(total===0)return'';
var score=(1+4*(v.u/total)).toFixed(1);
return'⭐'+score+' ('+total+')';
}

/* ===== ESTADO ===== */
var tree=[],votosMap={},flatFiles=[],favoritos={},vista='lista';
var ruta=[],sortKey='name',sortAsc=true,busqueda='',historial=[];

function flatten(nodes,prefix){for(var i=0;i<nodes.length;i++){var n=nodes[i];var fp=prefix?prefix+'/'+n.name:n.name;if(n.type==='folder'){flatten(n.children||[],fp);}else{flatFiles.push({name:n.name,path:n.path,size:n.size,mtime:n.mtime,mts:n.mts,poster:n.poster,fullpath:fp});}}}

/* ===== EXPLORADOR ===== */
function childrenActuales(){var nodes=tree;for(var i=0;i<ruta.length;i++){var f=null;for(var j=0;j<nodes.length;j++){if(nodes[j].type==='folder'&&nodes[j].name===ruta[i]){f=nodes[j];break;}}if(!f)return[];nodes=f.children||[];}return nodes;}
function buscarEn(nodes,prefix,out,q){for(var i=0;i<nodes.length;i++){var n=nodes[i];var fp=prefix?prefix+'/'+n.name:n.name;if(n.type==='folder'){buscarEn(n.children||[],fp,out,q);}else{if(n.name.toLowerCase().indexOf(q)>=0){out.push({name:n.name,type:'file',path:n.path,size:n.size,mtime:n.mtime,mts:n.mts,poster:n.poster,fullpath:fp});}}}}

function accHtml(it,compact){
var h='';
var fav=favoritos[it.name]?' on':'';
if(isVideo(it.name)){h+='<a class="mini" data-act="play" data-path="'+esc(it.path)+'" data-name="'+esc(it.name)+'">▶</a>';}
h+='<a class="mini dl" href="/download/'+encodeURIComponent(it.path)+'">⬇</a>';
h+='<a class="mini heart'+fav+'" data-act="fav" data-name="'+esc(it.name)+'" data-path="'+esc(it.path)+'">'+(favoritos[it.name]?'❤️':'🤍')+'</a>';
h+='<a class="mini" data-act="comm" data-name="'+esc(it.name)+'">💬</a>';
return h;
}

function renderLista(items){
var h='',totalSize=0,nF=0,nC=0;
for(var i=0;i<items.length;i++){var it=items[i];
if(it.type==='folder'){nC++;
h+='<div class="fc-row fc-folder" data-fpath="'+esc(it.path)+'">';
h+='<div class="fc-cell fc-name"><span class="fc-ico">📁</span>'+esc(it.name)+'</div>';
h+='<div class="fc-cell fc-size">—</div><div class="fc-cell fc-type">Carpeta</div>';
h+='<div class="fc-cell fc-date">'+(it.mtime||'—')+'</div><div class="fc-cell"></div></div>';
}else{nF++;totalSize+=(it.size||0);
var meta=parseMeta(it.name),sc=scoreStr(it.name);
h+='<div class="fc-row fc-file">';
h+='<div class="fc-cell fc-name"><span class="fc-ico">'+getIco(it.name)+'</span><span>'+esc(it.name)+(sc?' <span style="color:var(--w);font-size:11px">'+sc+'</span>':'')+'</span></div>';
h+='<div class="fc-cell fc-size">'+fmtSize(it.size)+'</div><div class="fc-cell fc-type">'+getTipo(it.name)+'</div>';
h+='<div class="fc-cell fc-date">'+(it.mtime||'—')+'</div>';
h+='<div class="fc-cell fc-acts">'+accHtml(it)+'</div></div>';
}}
if(items.length===0)h='<div style="text-align:center;color:rgba(224,230,237,.4);padding:50px;font-family:\'Courier New\',monospace">📭 '+(busqueda?'Sin resultados':'Carpeta vacia')+'</div>';
document.getElementById('fc-rows').innerHTML=h;
document.getElementById('fcHead').style.display='';
document.getElementById('fc-status-left').innerHTML=(busqueda?'🔍 '+items.length+' resultados':'📁 '+nC+' carpetas, 📄 '+nF+' archivos')+' — 💾 '+fmtSize(totalSize);
}

function cardHtml(it){
var meta=parseMeta(it.name),sc=scoreStr(it.name);
var fav=favoritos[it.name];
var h='<div class="card" data-name="'+esc(it.name)+'">';
h+='<div class="card-img">';
if(it.poster){h+='<img src="'+it.poster+'" alt="" loading="lazy">';}else{h+=getIco(it.name);}
if(isVideo(it.name)){h+='<div class="play" data-act="play" data-path="'+esc(it.path)+'" data-name="'+esc(it.name)+'"><span>▶</span></div>';}
h+='</div><div class="card-body">';
h+='<div class="card-title" title="'+esc(it.name)+'">'+esc(meta.titulo)+'</div>';
h+='<div class="badges">';
if(meta.anio)h+='<span class="badge b-anio">'+meta.anio+'</span>';
if(meta.calidad)h+='<span class="badge b-cal">'+meta.calidad+'</span>';
if(sc)h+='<span class="badge b-voto">'+sc+'</span>';
h+='<span class="badge b-size">'+fmtSize(it.size)+'</span>';
h+='</div><div class="card-acts">';
if(isVideo(it.name))h+='<a class="mini" data-act="play" data-path="'+esc(it.path)+'" data-name="'+esc(it.name)+'">▶ Ver</a>';
h+='<a class="mini dl" href="/download/'+encodeURIComponent(it.path)+'">⬇</a>';
h+='<a class="mini heart'+(fav?' on':'')+'" data-act="fav" data-name="'+esc(it.name)+'" data-path="'+esc(it.path)+'">'+(fav?'❤️':'🤍')+'</a>';
h+='<a class="mini" data-act="comm" data-name="'+esc(it.name)+'">💬</a>';
h+='</div></div></div>';
return h;
}

function renderGaleria(items){
var carpetas=[],series={},sueltos=[];
for(var i=0;i<items.length;i++){var it=items[i];
if(it.type==='folder'){carpetas.push(it);continue;}
var sm=matchSerie(it.name);
if(sm){var k=sm.serie.toLowerCase();if(!series[k])series[k]={nombre:sm.serie,temp:{}};var tk='T'+sm.t;if(!series[k].temp[tk])series[k].temp[tk]=[];series[k].temp[tk].push(it);}
else sueltos.push(it);
}
var h='';
if(carpetas.length){h+='<div class="grid">';for(i=0;i<carpetas.length;i++){h+='<div class="card fc-folder" data-fpath="'+esc(carpetas[i].path)+'"><div class="card-img">'+(carpetas[i].poster?'<img src="'+carpetas[i].poster+'" loading="lazy">':'📁')+'</div><div class="card-body"><div class="card-title">'+esc(carpetas[i].name)+'</div></div></div>';}h+='</div>';}
var keys=Object.keys(series).sort();
for(var s=0;s<keys.length;s++){var ser=series[keys[s]];
var tks=Object.keys(ser.temp).sort(function(a,b){return parseInt(a.slice(1))-parseInt(b.slice(1));});
for(var t2=0;t2<tks.length;t2++){
h+='<div class="serie-h">📺 '+esc(ser.nombre)+' — Temporada '+tks[t2].slice(1)+'</div><div class="grid">';
var eps=ser.temp[tks[t2]].sort(function(a,b){var ma=matchSerie(a.name),mb=matchSerie(b.name);return(ma?ma.e:0)-(mb?mb.e:0);});
for(var e2=0;e2<eps.length;e2++)h+=cardHtml(eps[e2]);
h+='</div>';}}
if(sueltos.length){h+='<div class="grid">';for(i=0;i<sueltos.length;i++)h+=cardHtml(sueltos[i]);h+='</div>';}
if(!carpetas.length&&!keys.length&&!sueltos.length)h='<div style="text-align:center;color:rgba(224,230,237,.4);padding:50px;font-family:\'Courier New\',monospace">📭 vacio</div>';
document.getElementById('fc-rows').innerHTML=h;
document.getElementById('fcHead').style.display='none';
document.getElementById('fc-status-left').innerHTML='🎬 vista galería — '+items.length+' elementos';
}

function renderFavoritos(){
var items=[];for(var i=0;i<flatFiles.length;i++){if(favoritos[flatFiles[i].name])items.push(flatFiles[i]);}
var h='';
if(items.length===0){h='<div style="text-align:center;color:rgba(224,230,237,.4);padding:50px;font-family:\'Courier New\',monospace">🤍 Aún no tienes favoritos.<br>Toca el corazón en cualquier archivo.</div>';}
else{h+='<div class="grid">';for(i=0;i<items.length;i++)h+=cardHtml(items[i]);h+='</div>';}
document.getElementById('fc-rows').innerHTML=h;
document.getElementById('fcHead').style.display='none';
document.getElementById('fc-status-left').innerHTML='❤️ '+items.length+' favoritos';
}

function renderExplorer(){
if(vista==='fav'){renderFavoritos();renderBreadcrumb();return;}
var items;
if(busqueda){items=[];buscarEn(tree,'',items,busqueda.toLowerCase());}
else{items=childrenActuales().slice();}
items.sort(function(a,b){
if(a.type!==b.type)return a.type==='folder'?-1:1;
var va,vb;
if(sortKey==='size'){va=a.size||0;vb=b.size||0;}
else if(sortKey==='date'){va=a.mts||0;vb=b.mts||0;}
else{va=a.name.toLowerCase();vb=b.name.toLowerCase();}
if(va<vb)return sortAsc?-1:1;if(va>vb)return sortAsc?1:-1;return 0;
});
if(vista==='galeria')renderGaleria(items);else renderLista(items);
renderBreadcrumb();
}
function renderBreadcrumb(){
var bc=document.getElementById('fc-breadcrumb');
var h='<span class="bc-item'+(ruta.length===0?' bc-active':'')+'" data-idx="-1">🏠 Pakete</span>';
for(var i=0;i<ruta.length;i++){h+='<span class="bc-sep">›</span><span class="bc-item'+(i===ruta.length-1?' bc-active':'')+'" data-idx="'+i+'">'+esc(ruta[i])+'</span>';}
bc.innerHTML=h;
}
function navegarA(nr){if(ruta.join('/')!==nr.join('/'))historial.push(ruta.slice());ruta=nr;busqueda='';document.getElementById('fcBusq').value='';if(vista==='fav')setVista('lista');renderExplorer();}
function setVista(v){vista=v;
document.getElementById('vLista').className='fc-btn'+(v==='lista'?' act':'');
document.getElementById('vGaleria').className='fc-btn'+(v==='galeria'?' act':'');
document.getElementById('vFav').className='fc-btn'+(v==='fav'?' act':'');
renderExplorer();}

document.getElementById('vLista').addEventListener('click',function(){setVista('lista');});
document.getElementById('vGaleria').addEventListener('click',function(){setVista('galeria');});
document.getElementById('vFav').addEventListener('click',function(){setVista('fav');});
document.getElementById('fcSubir').addEventListener('click',function(){if(ruta.length>0)navegarA(ruta.slice(0,-1));});
document.getElementById('fcHome').addEventListener('click',function(){navegarA([]);});
document.getElementById('fcAtras').addEventListener('click',function(){if(historial.length>0){ruta=historial.pop();busqueda='';renderExplorer();}});

document.getElementById('fc-rows').addEventListener('click',function(e){
var el=e.target;
while(el&&el!==this){
if(el.classList&&el.classList.contains('fc-folder')&&el.getAttribute('data-fpath')!=null){var fp=el.getAttribute('data-fpath');navegarA(fp?fp.split('/'):[]);return;}
if(el.getAttribute&&el.getAttribute('data-act')){
var act=el.getAttribute('data-act');
if(act==='play'){abrirPlayer(el.getAttribute('data-path'),el.getAttribute('data-name'));return;}
if(act==='comm'){abrirComentarios(el.getAttribute('data-name'));return;}
if(act==='fav'){toggleFav(el.getAttribute('data-name'),el.getAttribute('data-path'));return;}
}
el=el.parentElement;
}});
document.getElementById('fc-breadcrumb').addEventListener('click',function(e){
var el=e.target;while(el&&el!==this){
if(el.classList&&el.classList.contains('bc-item')&&!el.classList.contains('bc-active')){
var idx=parseInt(el.getAttribute('data-idx'));if(idx===-1)navegarA([]);else navegarA(ruta.slice(0,idx+1));return;}
el=el.parentElement;}});

/* sugerencias de busqueda */
var busqEl=document.getElementById('fcBusq'),sugsEl=document.getElementById('sugs');
busqEl.addEventListener('input',function(){
busqueda=this.value.trim();
if(busqueda.length>=1){
var q=busqueda.toLowerCase(),h='',c=0;
for(var i=0;i<flatFiles.length&&c<8;i++){if(flatFiles[i].name.toLowerCase().indexOf(q)>=0){h+='<div data-name="'+esc(flatFiles[i].name)+'">'+getIco(flatFiles[i].name)+' '+esc(flatFiles[i].name)+'</div>';c++;}}
sugsEl.innerHTML=h;sugsEl.style.display=c?'block':'none';
}else{sugsEl.style.display='none';}
renderExplorer();});
sugsEl.addEventListener('click',function(e){var el=e.target;if(el.getAttribute&&el.getAttribute('data-name')){busqEl.value=el.getAttribute('data-name');busqueda=busqEl.value;sugsEl.style.display='none';renderExplorer();}});
document.addEventListener('click',function(e){if(!e.target.closest('.fc-search'))sugsEl.style.display='none';});

var heads=document.querySelectorAll('.fc-hc[data-sort]');
for(var hh=0;hh<heads.length;hh++){(function(hd){hd.addEventListener('click',function(){var k=hd.getAttribute('data-sort');if(sortKey===k)sortAsc=!sortAsc;else{sortKey=k;sortAsc=true;}
var arr=['name','size','date'];for(var x=0;x<arr.length;x++){var e=document.getElementById('arw-'+arr[x]);if(e)e.textContent=(arr[x]===sortKey)?(sortAsc?'▲':'▼'):'';}
renderExplorer();});})(heads[hh]);}

/* ===== FAVORITOS ===== */
function cargarFavoritos(){fetch('/api/favoritos').then(function(r){return r.json()}).then(function(d){favoritos={};for(var i=0;i<d.length;i++)favoritos[d[i].a]=d[i].p;document.getElementById('favCount').textContent=d.length;}).catch(function(){});}
function toggleFav(nombre,path){
fetch('/api/favorito',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({archivo:nombre,path:path})})
.then(function(r){return r.json()}).then(function(d){
if(d.agregado){favoritos[nombre]=path;toast('❤️ agregado a favoritos');}
else{delete favoritos[nombre];toast('🤍 quitado de favoritos');}
document.getElementById('favCount').textContent=Object.keys(favoritos).length;
renderExplorer();
}).catch(function(){});
}

/* ===== REPRODUCTOR ===== */
function abrirPlayer(path,nombre){
var meta=parseMeta(nombre);
document.getElementById('playTitle').textContent='▶ '+meta.titulo+(meta.anio?' ('+meta.anio+')':'');
var v=document.getElementById('playerV');
v.src='/stream/'+encodeURIComponent(path);
document.getElementById('mPlay').classList.add('ac');
v.play().catch(function(){});
}
document.getElementById('btnClosePlay').addEventListener('click',function(){var v=document.getElementById('playerV');v.pause();v.removeAttribute('src');v.load();document.getElementById('mPlay').classList.remove('ac');});

/* ===== COMENTARIOS ===== */
var commArchivo='';
function abrirComentarios(nombre){
commArchivo=nombre;
document.getElementById('commFile').textContent='📄 '+nombre;
document.getElementById('commList').innerHTML='<div class="ld"></div>';
document.getElementById('mComm').classList.add('ac');
fetch('/api/comentarios?archivo='+encodeURIComponent(nombre)).then(function(r){return r.json()}).then(function(d){
var h='';if(d.length===0)h='<p style="color:rgba(224,230,237,.4);font-family:\'Courier New\',monospace;font-size:12px">Sin comentarios aún. Sé el primero!</p>';
for(var i=0;i<d.length;i++){h+='<div class="cmsg"><b>'+esc(d[i].n||'anon')+'</b><small>'+esc(d[i].f)+'</small><br>'+esc(d[i].t)+'</div>';}
document.getElementById('commList').innerHTML=h;
}).catch(function(){});
}
document.getElementById('btnCanComm').addEventListener('click',function(){document.getElementById('mComm').classList.remove('ac');});
document.getElementById('btnOkComm').addEventListener('click',function(){
var txt=document.getElementById('commText').value.trim();
if(!txt){toast('❌ escribe algo',true);return;}
fetch('/api/comentario',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({archivo:commArchivo,texto:txt,nombre:nick})})
.then(function(r){if(r.ok){toast('✅ comentario publicado');document.getElementById('commText').value='';abrirComentarios(commArchivo);}}).catch(function(){toast('❌ error',true);});
});

/* ===== VOTOS/TENDENCIAS/NOVEDADES/RANKING ===== */
function cargarVotos(){fetch('/api/votos').then(function(r){return r.json()}).then(function(d){votosMap={};for(var i=0;i<d.length;i++)votosMap[d[i].a]={u:d[i].u,d:d[i].d};}).catch(function(){});}
function miniCard(it,extra){
var h='<div class="hcard" data-path="'+esc(it.path||'')+'" data-name="'+esc(it.name)+'">';
h+='<div class="himg">'+(it.poster?'<img src="'+it.poster+'" loading="lazy">':getIco(it.name))+'</div>';
h+='<div class="hname">'+esc(it.name)+'</div>';
h+='<div class="hmeta">'+extra+'</div></div>';
return h;
}
function cargarTendencias(){fetch('/api/tendencias').then(function(r){return r.json()}).then(function(d){
var box=document.getElementById('trendRow');
if(d.length===0){box.innerHTML='<p style="color:rgba(224,230,237,.4);font-family:\'Courier New\',monospace;font-size:13px">Aún no hay descargas esta semana.</p>';return;}
var h='';for(var i=0;i<d.length;i++){var t=d[i];var info=flatMap[t.a];
var item=info?info:{name:t.a,path:''};
h+=miniCard(item,'📥 '+t.c+' descargas · '+fmtSize(t.mb));}
box.innerHTML=h;
}).catch(function(){document.getElementById('trendRow').innerHTML='';});}
function renderNovedades(){
var ahora=Date.now()/1000,semana=7*24*3600;
var rec=[];for(var i=0;i<flatFiles.length;i++){if(flatFiles[i].mts&&(ahora-flatFiles[i].mts)<semana)rec.push(flatFiles[i]);}
rec.sort(function(a,b){return b.mts-a.mts;});rec=rec.slice(0,8);
var box=document.getElementById('noveRow');
if(rec.length===0){box.innerHTML='<p style="color:rgba(224,230,237,.4);font-family:\'Courier New\',monospace;font-size:13px">Nada nuevo esta semana.</p>';return;}
var h='';for(i=0;i<rec.length;i++){h+=miniCard(rec[i],'✨ '+esc(rec[i].mtime));}
box.innerHTML=h;
}
function cargarRanking(){fetch('/api/ranking').then(function(r){return r.json()}).then(function(d){
var box=document.getElementById('rankBox');
if(d.length===0){box.innerHTML='<p style="color:rgba(224,230,237,.4);font-family:\'Courier New\',monospace">Sin descargas todavía.</p>';return;}
var med=['🥇','🥈','🥉'],h='';
for(var i=0;i<d.length;i++){var r=d[i];
var nombre=r.dueno||('Anónimo ('+r.ip.split('.').slice(0,3).join('.')+'.*)');
h+='<div class="rank-row"><span class="med">'+(med[i]||'🎖️')+'</span><span class="nm">'+esc(nombre)+'</span><span class="st">'+r.c+' descargas · '+fmtSize(r.mb)+'</span></div>';}
box.innerHTML=h;
}).catch(function(){});}

/* click en hcards (tendencias/novedades) -> reproducir o descargar */
document.addEventListener('click',function(e){
var el=e.target;while(el&&el!==document.body){
if(el.classList&&el.classList.contains('hcard')){
var p=el.getAttribute('data-path'),n=el.getAttribute('data-name');
if(p&&isVideo(n)){abrirPlayer(p,n);}else if(p){window.location.href='/download/'+encodeURIComponent(p);}
return;}
el=el.parentElement;}
});

/* ===== CHAT ===== */
var lastChatId=0;
function cargarChat(){fetch('/api/chat?desde='+lastChatId).then(function(r){return r.json()}).then(function(d){
if(d.length===0)return;
var box=document.getElementById('chatBox');
for(var i=0;i<d.length;i++){var m=d[i];lastChatId=Math.max(lastChatId,m.id);
var div=document.createElement('div');div.className='msg';
var hora=(m.f||'').substring(11,16);
div.innerHTML='<span class="who">'+esc(m.n||'anon')+':</span> <span class="txt">'+esc(m.t)+'</span><span class="hora">'+hora+'</span>';
box.appendChild(div);}
box.scrollTop=box.scrollHeight;
}).catch(function(){});}
function enviarChat(){
var inp=document.getElementById('chatIn'),t=inp.value.trim();
if(!t)return;
if(!nick){document.getElementById('mNick').classList.add('ac');return;}
fetch('/api/chat',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({texto:t,nombre:nick})})
.then(function(){inp.value='';cargarChat();}).catch(function(){});
}
document.getElementById('chatSend').addEventListener('click',enviarChat);
document.getElementById('chatIn').addEventListener('keypress',function(e){if(e.key==='Enter')enviarChat();});
setInterval(cargarChat,3000);

/* ===== TABLON ===== */
function cargarTablon(){fetch('/api/tablon').then(function(r){return r.json()}).then(function(d){
var box=document.getElementById('tablonBox');
if(d.length===0){box.innerHTML='<p style="color:rgba(224,230,237,.4);font-family:\'Courier New\',monospace;font-size:12px">El tablon esta vacio. Publica el primer aviso!</p>';return;}
var h='';for(var i=0;i<d.length;i++){var p=d[i];
h+='<div class="tb-post"><h5>📌 '+esc(p.ti)+'</h5><p>'+esc(p.tx)+'</p><small>por '+esc(p.n||'anon')+' · '+esc(p.f)+'</small></div>';}
box.innerHTML=h;
}).catch(function(){});}
document.getElementById('tabSend').addEventListener('click',function(){
var ti=document.getElementById('tabTitulo').value.trim(),tx=document.getElementById('tabTexto').value.trim();
if(!ti||!tx){toast('❌ completa titulo y mensaje',true);return;}
fetch('/api/tablon',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({titulo:ti,texto:tx,nombre:nick})})
.then(function(){document.getElementById('tabTitulo').value='';document.getElementById('tabTexto').value='';toast('✅ publicado en el tablon');cargarTablon();}).catch(function(){});
});
setInterval(cargarTablon,15000);

/* ===== SPEEDTEST ===== */
document.getElementById('btnSpeed').addEventListener('click',function(){
var btn=this;btn.disabled=true;btn.textContent='midiendo...';
var bar=document.getElementById('speedBar'),res=document.getElementById('speedRes');
res.textContent='...';bar.style.width='0%';
var total=3*1024*1024,recibido=0,t0=performance.now();
fetch('/api/speedtest?mb=3',{cache:'no-store'}).then(function(r){
var reader=r.body.getReader();
function pump(){return reader.read().then(function(x){
if(x.done){fin();return;}
recibido+=x.value.length;
bar.style.width=Math.min(100,recibido*100/total)+'%';
var elapsed=(performance.now()-t0)/1000;
if(elapsed>0.2)res.textContent=(recibido/1024/1024/elapsed).toFixed(2)+' MB/s';
return pump();});}
return pump();
}).catch(function(){res.textContent='error';btn.disabled=false;btn.textContent='▶ reintentar';});
function fin(){
var seg=(performance.now()-t0)/1000;
var mbps=(total/1024/1024)/seg;
res.textContent=mbps.toFixed(2)+' MB/s ('+(mbps*8).toFixed(1)+' Mbps)';
bar.style.width='100%';
btn.disabled=false;btn.textContent='▶ repetir test';
toast('🚀 Velocidad: '+mbps.toFixed(2)+' MB/s');
}
});

/* ===== CARGA DE ARBOL ===== */
var flatMap={};
function cargarArchivos(){fetch('/api/list').then(function(r){return r.json()}).then(function(d){
tree=d||[];flatFiles=[];flatten(tree,'');flatMap={};
for(var i=0;i<flatFiles.length;i++)flatMap[flatFiles[i].name]=flatFiles[i];
var nf=flatFiles.length,nc=0,gb=0;
(function contar(nodes){for(var j=0;j<nodes.length;j++){if(nodes[j].type==='folder'){nc++;contar(nodes[j].children||[]);}else gb+=(nodes[j].size||0);}})(tree);
document.getElementById('tkArch').textContent=nf;
document.getElementById('tkCarp').textContent=nc;
document.getElementById('tkGB').textContent=gb.toFixed(1);
renderExplorer();renderNovedades();cargarTendencias();
}).catch(function(e){document.getElementById('fc-rows').innerHTML='<div style="text-align:center;padding:40px;color:var(--d)">❌ '+e+'</div>';});}

/* ===== CARRUSEL / ANUNCIOS / STATS ===== */
var si2=0,sd=[],api2=null;
function cargarCovers(){fetch('/api/covers').then(function(r){return r.json()}).then(function(d){sd=d;var tk=document.getElementById('ctrk'),dt=document.getElementById('cds');
if(d.length===0){tk.innerHTML='<div class="csl" style="justify-content:center;min-height:200px"><div style="text-align:center;color:rgba(224,230,237,0.4)"><div style="font-size:48px;margin-bottom:12px">🎬</div><p>Proximamente nuevos estrenos...</p></div></div>';dt.innerHTML='';return;}
var h='';for(var k=0;k<d.length;k++){var nb=d[k].name.replace(/\.[^.]+$/,'');h+='<div class="csl"><img src="'+d[k].url+'" alt="'+nb+'" loading="lazy" draggable="false"><div class="ci"><h3>'+nb+'</h3><p>Estreno exclusivo disponible en nuestra biblioteca. ¡Míralo ahora sin descargar!</p><div class="tgs"><span class="tg">🔥 disponible</span><span class="tg">▶ streaming</span></div></div></div>';}
tk.innerHTML=h;var dh='';for(var m=0;m<d.length;m++){dh+='<button class="'+(m===0?'act':'')+'" data-i="'+m+'"></button>';}dt.innerHTML=dh;
var btns=dt.querySelectorAll('button');for(var n=0;n<btns.length;n++){(function(btn){btn.addEventListener('click',function(){irA(parseInt(btn.getAttribute('data-i')));});})(btns[n]);}
if(d.length>1){if(api2)clearInterval(api2);api2=setInterval(function(){irA((si2+1)%d.length)},5000);}}).catch(function(){});}
function irA(idx){var tk=document.getElementById('ctrk'),dts=document.querySelectorAll('#cds button'),tot=sd.length;if(tot===0)return;if(idx<0)idx=tot-1;if(idx>=tot)idx=0;si2=idx;tk.style.transform='translateX(-'+(idx*100)+'%)';for(var q=0;q<dts.length;q++){dts[q].className=(q===idx)?'act':'';}}
function cargarAnuncios(){fetch('/api/anuncios').then(function(r){return r.json()}).then(function(d){
if(d.length===0){document.getElementById('secAnuncios').style.display='none';return;}
document.getElementById('secAnuncios').style.display='block';var h='';for(var i=0;i<d.length;i++){h+='<div class="anc"><h4>📢 '+esc(d[i][1])+'</h4><p>'+esc(d[i][2])+'</p></div>';}
document.getElementById('listaAnuncios').innerHTML=h;}).catch(function(){});}
function cargarStatsPublicas(){fetch('/api/public-stats').then(function(r){return r.json()}).then(function(d){
document.getElementById('tkVis').textContent=d.visitas;
document.getElementById('tkDes').textContent=d.descargas;
document.getElementById('tkDev').textContent=d.dispositivos_activos;
}).catch(function(){});}

/* ===== MODALES ===== */
document.getElementById('btnPet').addEventListener('click',function(){document.getElementById('mPet').classList.add('ac');});
document.getElementById('btnCanPet').addEventListener('click',function(){document.getElementById('mPet').classList.remove('ac');});
document.getElementById('btnCanLog').addEventListener('click',function(){document.getElementById('mLog').classList.remove('ac');});
document.getElementById('btnCod').addEventListener('click',function(){document.getElementById('mCod').classList.add('ac');});
document.getElementById('btnCanCod').addEventListener('click',function(){document.getElementById('mCod').classList.remove('ac');});
document.getElementById('btnOkCod').addEventListener('click',function(){
var cod=document.getElementById('codInput').value;
if(!cod){toast('❌ escribe el codigo',true);return;}
fetch('/api/codigo/validar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({codigo:cod})})
.then(function(r){return r.json()}).then(function(d){
if(d.success){toast('✅ '+d.mensaje);document.getElementById('mCod').classList.remove('ac');document.getElementById('codInput').value='';}
else{toast('❌ '+d.mensaje,true);}}).catch(function(){toast('❌ error de conexion',true);});});
document.getElementById('btnAdm').addEventListener('click',function(){var tk=localStorage.getItem('admin_token');
if(tk){fetch('/api/verificar-token?token='+encodeURIComponent(tk)).then(function(r){return r.json()}).then(function(d){if(d.valido){window.location.href='/admin?token='+encodeURIComponent(tk);}else{localStorage.removeItem('admin_token');document.getElementById('mLog').classList.add('ac');}}).catch(function(){document.getElementById('mLog').classList.add('ac');});}
else{document.getElementById('mLog').classList.add('ac');}});
document.getElementById('fPet').addEventListener('submit',function(e){e.preventDefault();var fd=new FormData(e.target);
fetch('/api/peticion',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({tipo:fd.get('tipo'),contenido:fd.get('contenido'),detalles:fd.get('detalles')})}).then(function(r){if(r.ok){toast('✅ solicitud enviada');document.getElementById('mPet').classList.remove('ac');e.target.reset();}else{toast('❌ error',true);}}).catch(function(){toast('❌ error',true);});});
document.getElementById('fLog').addEventListener('submit',function(e){e.preventDefault();var fd=new FormData(e.target);var btn=document.getElementById('btnSubLog');btn.disabled=true;btn.textContent='verificando...';localStorage.removeItem('admin_token');
fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({usuario:fd.get('usuario'),password:fd.get('password')})}).then(function(r){return r.json()}).then(function(d){btn.disabled=false;btn.textContent='ingresar';
if(d.success&&d.token){localStorage.setItem('admin_token',d.token);document.getElementById('mLog').classList.remove('ac');setTimeout(function(){window.location.href='/admin?token='+encodeURIComponent(d.token);},200);}
else{toast('❌ '+(d.error||'credenciales incorrectas'),true);}}).catch(function(){btn.disabled=false;btn.textContent='ingresar';toast('❌ error de conexion',true);});});

/* instalar app */
var deferredPrompt=null;
addEventListener('beforeinstallprompt',function(e){e.preventDefault();deferredPrompt=e;});
document.getElementById('btnInstalar').addEventListener('click',function(){
if(deferredPrompt){deferredPrompt.prompt();deferredPrompt.userChoice.then(function(r){if(r.outcome==='accepted')toast('✅ app instalada');deferredPrompt=null;});}
else{var ua=navigator.userAgent.toLowerCase(),h='';
if(ua.indexOf('android')>=0)h='<p style="color:var(--l);font-family:\'Courier New\',monospace;font-size:13px;line-height:1.7">1️⃣ Menu ⋮ del navegador<br>2️⃣ "Agregar a pantalla de inicio"<br>3️⃣ Confirma y listo 📱</p>';
else if(ua.indexOf('iphone')>=0||ua.indexOf('ipad')>=0)h='<p style="color:var(--l);font-family:\'Courier New\',monospace;font-size:13px;line-height:1.7">1️⃣ En Safari, boton Compartir ↑<br>2️⃣ "Agregar a pantalla de inicio"<br>3️⃣ Toca Agregar 📱</p>';
else h='<p style="color:var(--l);font-family:\'Courier New\',monospace;font-size:13px;line-height:1.7">1️⃣ Menu del navegador (⋮)<br>2️⃣ "Instalar Mi Pakete"<br>3️⃣ Confirma 🖥️</p>';
document.getElementById('instPasos').innerHTML=h;document.getElementById('mInst').classList.add('ac');}
});
document.getElementById('btnCanInst').addEventListener('click',function(){document.getElementById('mInst').classList.remove('ac');});

/* ===== INIT ===== */
cargarVotos();cargarCovers();cargarAnuncios();cargarStatsPublicas();cargarRanking();cargarTablon();cargarChat();cargarFavoritos();
cargarArchivos();
fetch('/api/registrar-visita',{method:'POST'});
})();
</script>
</body>
</html>"""

# ============================================================
# HTML MODAL DE BLOQUEO (sin cambios funcionales)
# ============================================================
HTML_BLOQUEO = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Acceso Restringido - Mi Pakete</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{margin:0!important;padding:0!important;width:100%;height:100%;overflow:hidden}
body{font-family:'Segoe UI',Arial,sans-serif;background:#050816;color:#e0e6ed;display:flex;align-items:center;justify-content:center;min-height:100vh;position:relative}
#mc{position:fixed;top:0;left:0;width:100%;height:100%;z-index:0;opacity:0.15}
.overlay{position:fixed;inset:0;background:radial-gradient(ellipse at center,rgba(5,8,22,0.85) 0%,rgba(5,8,22,0.98) 100%);z-index:1}
.modal{position:relative;z-index:2;background:rgba(10,14,39,0.85);backdrop-filter:blur(20px);border:1px solid rgba(255,51,102,0.3);border-radius:24px;padding:40px 32px;max-width:460px;width:92%;text-align:center;box-shadow:0 20px 80px rgba(0,0,0,0.7);max-height:95vh;overflow-y:auto}
.icon{width:90px;height:90px;margin:0 auto 20px;border-radius:50%;background:radial-gradient(circle,rgba(255,51,102,0.25),rgba(255,51,102,0.05));border:2px solid rgba(255,51,102,0.4);display:flex;align-items:center;justify-content:center;font-size:46px}
.modal h1{font-size:24px;color:#ff3366;margin-bottom:10px;font-family:'Courier New',monospace}
.modal .msg{color:rgba(224,230,237,0.75);font-size:14px;line-height:1.7;margin-bottom:24px;font-family:'Courier New',monospace}
.divider{height:1px;background:linear-gradient(90deg,transparent,rgba(255,51,102,0.3),transparent);margin:20px 0}
.plan-box{background:rgba(0,255,136,0.06);border:1px solid rgba(0,255,136,0.25);border-radius:14px;padding:18px;margin-bottom:20px;text-align:left}
.plan-box h3{color:#00ff88;font-family:'Courier New',monospace;font-size:13px;margin-bottom:12px}
.plan{display:flex;justify-content:space-between;padding:8px 0;font-family:'Courier New',monospace;font-size:13px;color:rgba(224,230,237,0.8)}
.plan strong{color:#00ff88}
.fg{margin-bottom:14px;text-align:left}
.fg label{display:block;margin-bottom:6px;color:rgba(224,230,237,0.6);font-size:11px;font-family:'Courier New',monospace}
.fg input{width:100%;padding:12px 14px;background:rgba(0,0,0,0.4);border:1px solid rgba(0,255,136,0.25);border-radius:10px;color:#e0e6ed;font-family:'Courier New',monospace;font-size:14px;text-transform:uppercase;letter-spacing:2px;text-align:center}
.bt{padding:13px 22px;border-radius:10px;border:none;font-weight:700;font-size:14px;cursor:pointer;font-family:'Courier New',monospace;width:100%;margin-top:8px}
.bp{background:linear-gradient(135deg,#00ff88,#00d4ff);color:#050816}
.bg{background:transparent;color:rgba(224,230,237,0.5);border:1px solid rgba(224,230,237,0.15);margin-top:10px}
.toast{position:fixed;bottom:24px;left:50%;transform:translateX(-50%) translateY(100px);background:rgba(10,14,39,0.95);border:1px solid #00ff88;border-radius:12px;padding:14px 22px;font-family:'Courier New',monospace;font-size:13px;color:#00ff88;z-index:9999;opacity:0;transition:all 0.4s}
.toast.show{opacity:1;transform:translateX(-50%) translateY(0)}
.toast.err{border-color:#ff3366;color:#ff3366}
.contact{text-align:center;margin-top:16px;font-family:'Courier New',monospace;font-size:12px;color:rgba(224,230,237,0.5)}
.contact strong{color:#00d4ff}
</style>
</head>
<body>
<canvas id="mc"></canvas>
<div class="overlay"></div>
<div class="modal">
<div class="icon">🚫</div>
<h1>ACCESO_RESTRINGIDO</h1>
<p class="msg">Tu dispositivo tiene las descargas <strong style="color:#ff3366">desactivadas</strong>.<br>Canjea un codigo o contacta al administrador.</p>
<div class="plan-box">
<h3>💰 Planes disponibles</h3>
<div class="plan"><span>Por GB descargado</span><strong>6.25 CUP</strong></div>
<div class="plan"><span>Dia ilimitado</span><strong>50 CUP</strong></div>
<div class="plan"><span>Semanal (mejor oferta)</span><strong>200 CUP</strong></div>
</div>
<div class="divider"></div>
<div class="fg"><label>🎫 Codigo de acceso</label><input type="text" id="codInput" placeholder="A1B2C3D4E5F6" maxlength="20"></div>
<button class="bt bp" id="btnActivar">activar_descargas</button>
<button class="bt bg" onclick="window.location.href='/'">volver_al_inicio</button>
<div class="contact">Contacta a <strong>el administrador</strong> para obtener tu codigo</div>
</div>
<div class="toast" id="toast"></div>
<script>
(function(){
var cv=document.getElementById('mc'),cx=cv.getContext('2d');cv.width=innerWidth;cv.height=innerHeight;
var ch='01アイウエオカキクケコ',fs=14,cl=Math.floor(cv.width/fs),dr=[];for(var i=0;i<cl;i++)dr[i]=1;
setInterval(function(){cx.fillStyle='rgba(5,8,22,0.05)';cx.fillRect(0,0,cv.width,cv.height);cx.fillStyle='#ff3366';cx.font=fs+'px monospace';for(var j=0;j<dr.length;j++){cx.fillText(ch[Math.floor(Math.random()*ch.length)],j*fs,dr[j]*fs);if(dr[j]*fs>cv.height&&Math.random()>0.975)dr[j]=0;dr[j]++;}},50);
var toastEl=document.getElementById('toast');
function mostrarToast(msg,err){toastEl.textContent=msg;toastEl.className='toast show'+(err?' err':'');setTimeout(function(){toastEl.className='toast';},3500);}
document.getElementById('codInput').addEventListener('keypress',function(e){if(e.key==='Enter')document.getElementById('btnActivar').click();});
document.getElementById('btnActivar').addEventListener('click',function(){
var cod=document.getElementById('codInput').value.trim();
if(!cod){mostrarToast('❌ escribe tu codigo',true);return;}
var btn=this;btn.disabled=true;btn.textContent='verificando...';
fetch('/api/codigo/validar',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({codigo:cod})})
.then(function(r){return r.json()}).then(function(d){
btn.disabled=false;btn.textContent='activar_descargas';
if(d.success){mostrarToast('✅ '+d.mensaje);setTimeout(function(){window.location.href='/';},1500);}
else{mostrarToast('❌ '+d.mensaje,true);}})
.catch(function(){btn.disabled=false;btn.textContent='activar_descargas';mostrarToast('❌ error de conexion',true);});});
})();
</script>
</body>
</html>"""

# ============================================================
# HTML PANEL ADMIN v11 (kanban, activas, disco, auditoria, sonido)
# ============================================================
HTML_ADMIN = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>root@pakete:~# panel_admin</title>
<style>
*{margin:0;padding:0;box-sizing:border-box}
html,body{margin:0!important;padding:0!important;width:100%;overflow-x:hidden}
body{font-family:'Segoe UI',Arial,sans-serif;background:#050816;color:#e0e6ed;min-height:100vh}
:root{--p:#00ff88;--s:#00d4ff;--a:#ff00ff;--d:#ff3366;--w:#ffaa00;--dk:#050816;--l:#e0e6ed;--g:rgba(10,14,39,0.78)}
#mc{position:fixed;top:0;left:0;width:100%;height:100%;z-index:-1;opacity:0.15}
.ct{max-width:1440px;margin:0 auto;padding:24px 20px;position:relative;z-index:1}
.hd{display:flex;justify-content:space-between;align-items:center;padding:20px 28px;background:var(--g);border-radius:14px;border:1px solid rgba(0,255,136,0.15);margin-bottom:24px;flex-wrap:wrap;gap:12px}
.hd h1{font-size:20px;background:linear-gradient(135deg,var(--p),var(--a));-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-family:'Courier New',monospace}
.hdr{display:flex;gap:10px;align-items:center;flex-wrap:wrap}
.conn{display:inline-flex;align-items:center;gap:6px;font-size:11px;font-family:'Courier New',monospace;color:var(--p);padding:4px 12px;background:rgba(0,255,136,0.08);border-radius:20px;border:1px solid rgba(0,255,136,0.2)}
.conn .dot{width:8px;height:8px;border-radius:50%;background:var(--p);animation:pulse 2s infinite}
.conn.off{color:var(--d);border-color:rgba(255,51,102,0.3)}
.conn.off .dot{background:var(--d)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:0.3}}
.bt{padding:8px 16px;border-radius:8px;border:none;font-weight:600;cursor:pointer;transition:all 0.25s;font-family:'Courier New',monospace;font-size:12px}
.bt:hover{transform:translateY(-1px)}
.bp{background:linear-gradient(135deg,var(--p),var(--s));color:var(--dk)}
.bd{background:rgba(255,51,102,0.15);color:var(--d);border:1px solid rgba(255,51,102,0.3)}
.bg2{background:rgba(0,255,136,0.08);color:var(--p);border:1px solid rgba(0,255,136,0.25)}
.bs2{background:rgba(0,255,136,0.15);color:var(--p);border:1px solid rgba(0,255,136,0.4)}
.nav{display:flex;gap:6px;margin-bottom:20px;flex-wrap:wrap;padding:6px;background:rgba(0,0,0,0.3);border-radius:12px;border:1px solid rgba(0,255,136,0.1)}
.nav button{padding:8px 14px;border-radius:8px;background:transparent;border:1px solid transparent;color:rgba(224,230,237,0.6);cursor:pointer;font-family:'Courier New',monospace;font-size:12px;transition:all 0.25s}
.nav button.act{background:rgba(0,255,136,0.12);border-color:rgba(0,255,136,0.3);color:var(--p)}
.sg{display:grid;grid-template-columns:repeat(auto-fit,minmax(150px,1fr));gap:12px;margin-bottom:24px}
.sc{background:var(--g);border:1px solid rgba(0,255,136,0.12);border-radius:12px;padding:18px 16px;text-align:center;position:relative;overflow:hidden}
.sc::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--p),var(--s),var(--a))}
.si{font-size:24px;margin-bottom:6px}
.sv{font-size:22px;font-weight:800;color:var(--p);font-family:'Courier New',monospace}
.sl2{font-size:10px;color:rgba(224,230,237,0.5);margin-top:4px;font-family:'Courier New',monospace;text-transform:uppercase}
.sec{display:none;animation:fadeIn 0.3s ease}
.sec.act{display:block}
@keyframes fadeIn{from{opacity:0;transform:translateY(8px)}to{opacity:1;transform:translateY(0)}}
.cd{background:var(--g);border:1px solid rgba(0,255,136,0.12);border-radius:12px;padding:22px;margin-bottom:20px}
.cd h2{font-size:16px;margin-bottom:14px;color:var(--p);font-family:'Courier New',monospace}
table{width:100%;border-collapse:collapse}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid rgba(0,255,136,0.06);font-family:'Courier New',monospace;font-size:12px}
th{color:rgba(0,255,136,0.7);font-weight:600;text-transform:uppercase;font-size:10px;background:rgba(0,255,136,0.03)}
tr:hover td{background:rgba(0,255,136,0.03)}
.db{background:rgba(0,255,136,0.12);color:var(--p);padding:3px 10px;border-radius:4px;font-size:10px;font-weight:600;border:1px solid rgba(0,255,136,0.2)}
.sp{background:rgba(255,170,0,0.12);color:var(--w);padding:3px 10px;border-radius:4px;font-size:10px;border:1px solid rgba(255,170,0,0.2)}
.scc{background:rgba(0,255,136,0.12);color:var(--p);padding:3px 10px;border-radius:4px;font-size:10px;border:1px solid rgba(0,255,136,0.2)}
.sr{background:rgba(255,51,102,0.12);color:var(--d);padding:3px 10px;border-radius:4px;font-size:10px;border:1px solid rgba(255,51,102,0.2)}
.sb2{background:rgba(255,51,102,0.12);color:var(--d);padding:3px 10px;border-radius:4px;font-size:10px;border:1px solid rgba(255,51,102,0.2)}
.sa{background:rgba(0,255,136,0.12);color:var(--p);padding:3px 10px;border-radius:4px;font-size:10px;border:1px solid rgba(0,255,136,0.2)}
.ab2{padding:5px 12px;border-radius:6px;border:none;cursor:pointer;font-size:10px;font-family:'Courier New',monospace;margin:2px;transition:all 0.2s}
.switch{position:relative;display:inline-block;width:54px;height:30px;vertical-align:middle}
.switch input{opacity:0;width:0;height:0}
.slider{position:absolute;cursor:pointer;top:0;left:0;right:0;bottom:0;background:rgba(255,51,102,0.25);border:2px solid rgba(255,51,102,0.45);transition:.35s;border-radius:30px}
.slider:before{position:absolute;content:"";height:22px;width:22px;left:3px;bottom:2px;background:#fff;transition:.35s;border-radius:50%}
input:checked+.slider{background:linear-gradient(135deg,var(--p),var(--s));border-color:var(--p)}
input:checked+.slider:before{transform:translateX(24px)}
.estTxt{font-size:11px;font-weight:700;margin-top:6px;text-align:center}
.estTxt.on{color:var(--p)}.estTxt.off{color:var(--d)}
.fg{margin-bottom:12px}
.fg label{display:block;margin-bottom:5px;color:rgba(224,230,237,0.6);font-size:11px;font-weight:600;font-family:'Courier New',monospace;text-transform:uppercase}
.fg input,.fg select,.fg textarea{width:100%;padding:9px 12px;background:rgba(0,0,0,0.4);border:1px solid rgba(0,255,136,0.2);border-radius:8px;color:var(--l);font-family:'Courier New',monospace;font-size:13px}
.fg textarea{resize:vertical;min-height:60px}
.dueno{color:var(--s);font-weight:bold}
.fa{margin-top:24px;text-align:center;font-size:11px;color:rgba(224,230,237,0.25);font-family:'Courier New',monospace;padding-top:16px;border-top:1px solid rgba(0,255,136,0.06)}
.toast{position:fixed;bottom:24px;right:24px;background:var(--g);border:1px solid var(--p);border-radius:12px;padding:14px 22px;font-family:'Courier New',monospace;font-size:13px;color:var(--p);z-index:9999;transform:translateY(100px);opacity:0;transition:all 0.4s}
.toast.show{transform:translateY(0);opacity:1}
.toast.err{border-color:var(--d);color:var(--d)}
/* kanban */
.kb{display:grid;grid-template-columns:repeat(5,1fr);gap:12px;align-items:start}
.kcol{background:rgba(0,0,0,.3);border:1px solid rgba(0,255,136,.12);border-radius:12px;padding:10px;min-height:120px}
.kcol h4{font-family:'Courier New',monospace;font-size:11px;text-transform:uppercase;color:rgba(0,255,136,.8);margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid rgba(0,255,136,.1)}
.kcard{background:var(--g);border:1px solid rgba(0,255,136,.15);border-radius:8px;padding:10px;margin-bottom:8px;font-family:'Courier New',monospace;font-size:12px}
.kcard .kc-t{color:var(--l);font-weight:600;margin-bottom:4px}
.kcard .kc-d{color:rgba(224,230,237,.45);font-size:10px;margin-bottom:8px}
.kcard .kc-a{display:flex;gap:6px}
.kbtn{padding:4px 10px;border-radius:6px;border:1px solid rgba(0,255,136,.25);background:rgba(0,255,136,.06);color:var(--p);font-size:10px;cursor:pointer;font-family:'Courier New',monospace}
.kbtn:hover{background:rgba(0,255,136,.15)}
.kbtn.rej{border-color:rgba(255,51,102,.3);color:var(--d);background:rgba(255,51,102,.06)}
/* barra progreso */
.pbar{height:8px;background:rgba(0,255,136,.1);border-radius:5px;overflow:hidden;min-width:120px}
.pbar div{height:100%;background:linear-gradient(90deg,var(--p),var(--s));border-radius:5px;transition:width .5s}
/* disco */
.dbar{height:22px;background:rgba(0,255,136,.08);border-radius:12px;overflow:hidden;margin:12px 0}
.dbar div{height:100%;background:linear-gradient(90deg,var(--p),var(--w),var(--d));border-radius:12px;transition:width 1s}
.dlbl{display:flex;justify-content:space-between;font-family:'Courier New',monospace;font-size:12px;color:rgba(224,230,237,.6)}
@media(max-width:900px){.kb{grid-template-columns:repeat(2,1fr)}}
@media(max-width:768px){.sg{grid-template-columns:repeat(2,1fr)}.hd{padding:16px}.kb{grid-template-columns:1fr}}
</style>
</head>
<body>
<canvas id="mc"></canvas>
<div class="ct">
<header class="hd">
<h1>root@pakete:~# panel_admin</h1>
<div class="hdr">
<span class="conn" id="connStatus"><span class="dot"></span> online</span>
<button class="bt bg2" id="btnSound">🔔 sonido: ON</button>
<button class="bt bg2" id="btnVol">🏠 volver</button>
<button class="bt bp" id="btnBackup">💾 backup</button>
<button class="bt bd" id="btnOut">🚪 salir</button>
</div>
</header>
<div class="nav">
<button class="act" data-sec="dashboard">📊 dashboard</button>
<button data-sec="activas">📡 en_vivo</button>
<button data-sec="dispositivos">📱 dispositivos</button>
<button data-sec="peticiones">📝 kanban</button>
<button data-sec="pagos">💳 pagos</button>
<button data-sec="codigos">🎫 codigos</button>
<button data-sec="anuncios">📢 anuncios</button>
<button data-sec="auditoria">🕵️ auditoria</button>
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
<div class="cd"><h2>💽 monitor_disco</h2>
<div class="dbar"><div id="diskBar" style="width:0%"></div></div>
<div class="dlbl"><span id="diskUsed">—</span><span id="diskFree">—</span></div>
</div>
<div class="cd"><h2>📊 actividad_7_dias.log</h2><div style="position:relative;height:260px"><canvas id="chA"></canvas></div><div id="chF" style="display:none;text-align:center;padding:40px;color:rgba(224,230,237,0.4);font-family:'Courier New',monospace;font-size:13px">⚠️ Chart.js no cargado</div></div>
<div class="cd"><h2>🏆 top_descargadores</h2><div style="overflow-x:auto"><table id="tTop"><thead><tr><th>IP</th><th>Descargas</th><th>MB</th></tr></thead><tbody></tbody></table></div></div>
</div>

<div class="sec" id="sec-activas">
<div class="cd"><h2>📡 descargas_en_vivo <span style="font-size:10px;color:rgba(224,230,237,.4)">se actualiza cada 2s</span></h2>
<div style="overflow-x:auto"><table id="tAct"><thead><tr><th>IP</th><th>Archivo</th><th>Progreso</th><th>Enviado</th><th>Velocidad</th><th>Tiempo</th></tr></thead><tbody></tbody></table></div>
</div>
</div>

<div class="sec" id="sec-dispositivos">
<div class="cd"><h2>📱 dispositivos_conectados</h2><div style="overflow-x:auto"><table id="tDev"><thead><tr><th>IP</th><th>Dispositivo</th><th>Dueño</th><th>Ultima conexion</th><th>Visitas</th><th>Estado</th><th>Descargas</th></tr></thead><tbody></tbody></table></div></div>
</div>

<div class="sec" id="sec-peticiones">
<div class="cd"><h2>📝 kanban_peticiones</h2>
<div class="kb" id="kanban"></div>
</div>
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

<div class="sec" id="sec-auditoria">
<div class="cd"><h2>🕵️ intentos_de_login <span style="font-size:10px;color:rgba(224,230,237,.4)">quien intenta entrar al admin</span></h2>
<div style="overflow-x:auto"><table id="tAudit"><thead><tr><th>IP</th><th>Usuario</th><th>Resultado</th><th>Fecha</th></tr></thead><tbody></tbody></table></div>
</div>
</div>

<div class="sec" id="sec-logs">
<div class="cd"><h2>📋 logs_sistema <button class="bt bg2" id="btnRefreshLogs" style="margin-left:12px;font-size:11px">🔄 actualizar</button></h2><div style="overflow-x:auto"><table id="tLogs"><thead><tr><th>Nivel</th><th>Mensaje</th><th>Fecha</th></tr></thead><tbody></tbody></table></div></div>
</div>

<div class="sec" id="sec-config">
<div class="cd"><h2>⚙️ cambiar_contrasena</h2>
<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(200px,1fr));gap:12px">
<div class="fg"><label>Nueva contrasena</label><input type="password" id="cfgPass" placeholder="nueva" autocomplete="new-password"></div>
<div class="fg"><label>Confirmar</label><input type="password" id="cfgPass2" placeholder="confirmar" autocomplete="new-password"></div>
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
var cv=document.getElementById('mc'),cx=cv.getContext('2d');cv.width=innerWidth;cv.height=innerHeight;
var ch='01アイウエオカキクケコ',fs=14,cl=Math.floor(cv.width/fs),dr=[],i;for(i=0;i<cl;i++)dr[i]=1;
setInterval(function(){cx.fillStyle='rgba(5,8,22,0.05)';cx.fillRect(0,0,cv.width,cv.height);cx.fillStyle='#00ff88';cx.font=fs+'px monospace';for(var j=0;j<dr.length;j++){cx.fillText(ch[Math.floor(Math.random()*ch.length)],j*fs,dr[j]*fs);if(dr[j]*fs>cv.height&&Math.random()>0.975)dr[j]=0;dr[j]++;}},50);
addEventListener('resize',function(){cv.width=innerWidth;cv.height=innerHeight;});

var chAct=null,fail=0,maxFail=5;
var tok=new URLSearchParams(window.location.search).get('token');
var toastEl=document.getElementById('toast');
function mostrarToast(msg,err){toastEl.textContent=msg;toastEl.className='toast show'+(err?' err':'');setTimeout(function(){toastEl.className='toast';},3500);}
function setConn(on){var el=document.getElementById('connStatus');if(on){el.className='conn';el.innerHTML='<span class="dot"></span> online';}else{el.className='conn off';el.innerHTML='<span class="dot"></span> offline';}}
function escA(t){return String(t==null?'':t).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;');}
function api(u){return u+(u.indexOf('?')>=0?'&':'?')+'token='+encodeURIComponent(tok||'');}
function postJSON(u,body){return fetch(api(u),{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(body||{})}).then(function(r){if(!r.ok)throw new Error('HTTP '+r.status);return r.json();});}

/* ===== SONIDO DE NOTIFICACION ===== */
var sonidoActivo=true,prevPend=-1;
document.getElementById('btnSound').addEventListener('click',function(){sonidoActivo=!sonidoActivo;this.textContent='🔔 sonido: '+(sonidoActivo?'ON':'OFF');});
function beep(){if(!sonidoActivo)return;try{var ac=window.__ac||(window.__ac=new (window.AudioContext||window.webkitAudioContext)());var o=ac.createOscillator(),g=ac.createGain();o.connect(g);g.connect(ac.destination);o.frequency.value=880;o.type='sine';g.gain.setValueAtTime(0.15,ac.currentTime);g.gain.exponentialRampToValueAtTime(0.001,ac.currentTime+0.4);o.start();o.stop(ac.currentTime+0.4);}catch(e){}}

var navBtns=document.querySelectorAll('.nav button');
for(var n=0;n<navBtns.length;n++){(function(btn){btn.addEventListener('click',function(){for(var x=0;x<navBtns.length;x++)navBtns[x].classList.remove('act');btn.classList.add('act');var secs=document.querySelectorAll('.sec');for(var y=0;y<secs.length;y++)secs[y].classList.remove('act');var t=document.getElementById('sec-'+btn.getAttribute('data-sec'));if(t)t.classList.add('act');});})(navBtns[n]);}

/* ===== DISCO ===== */
function cargarDisco(){fetch(api('/api/admin/disco')).then(function(r){return r.json()}).then(function(d){
document.getElementById('diskBar').style.width=d.pct+'%';
document.getElementById('diskUsed').textContent='Usado: '+(d.usado/1073741824).toFixed(1)+' GB ('+d.pct+'%)';
document.getElementById('diskFree').textContent='Libre: '+(d.libre/1073741824).toFixed(1)+' GB';
if(d.libre/1048576<1024)mostrarToast('⚠️ poco espacio en disco!',true);
}).catch(function(){});}

/* ===== TRANSFERENCIAS ACTIVAS ===== */
function cargarActivas(){fetch(api('/api/admin/activas')).then(function(r){return r.json()}).then(function(d){
var h='';
if(d.length===0)h='<tr><td colspan="6" style="text-align:center;color:rgba(224,230,237,.4)">😴 nadie esta descargando ahora</td></tr>';
for(var i=0;i<d.length;i++){var t=d[i];
h+='<tr><td>'+escA(t.ip)+'</td><td>'+escA(t.archivo)+'</td>';
h+='<td><div class="pbar"><div style="width:'+t.pct+'%"></div></div></td>';
h+='<td>'+t.enviado+' / '+t.total+' MB ('+t.pct+'%)</td>';
h+='<td style="color:var(--p)">'+t.vel+' MB/s</td>';
h+='<td>'+t.seg+'s</td></tr>';}
document.querySelector('#tAct tbody').innerHTML=h;
}).catch(function(){});}
setInterval(cargarActivas,2000);

/* ===== KANBAN ===== */
var ESTADOS=['pendiente','buscando','agregado','avisado','rechazado'];
var ESTCOL={pendiente:'📥 Pendiente',buscando:'🔍 Buscando',agregado:'✅ Agregado',avisado:'📢 Avisado',rechazado:'❌ Rechazado'};
function cargarKanban(){fetch(api('/api/admin/peticiones')+'&estado=todas').then(function(r){return r.json()}).then(function(pts){
var grupos={};for(var e=0;e<ESTADOS.length;e++)grupos[ESTADOS[e]]=[];
for(var i=0;i<pts.length;i++){var p=pts[i];var st=ESTADOS.indexOf(p[5])>=0?p[5]:'pendiente';grupos[st].push(p);}
var h='';
for(e=0;e<ESTADOS.length;e++){var est=ESTADOS[e];
h+='<div class="kcol"><h4>'+ESTCOL[est]+' ('+grupos[est].length+')</h4>';
for(i=0;i<grupos[est].length;i++){var pp=grupos[est][i];
h+='<div class="kcard"><div class="kc-t">'+escA(pp[3])+'</div>';
h+='<div class="kc-d">'+escA(pp[2])+' · '+escA(pp[1])+' · '+(pp[6]||'').substring(0,10)+'</div>';
h+='<div class="kc-a">';
var idx=ESTADOS.indexOf(est);
if(idx>0&&est!=='rechazado')h+='<button class="kbtn" data-pid="'+pp[0]+'" data-est="'+ESTADOS[idx-1]+'">◀</button>';
if(idx<3)h+='<button class="kbtn" data-pid="'+pp[0]+'" data-est="'+ESTADOS[idx+1]+'">▶</button>';
if(est!=='rechazado')h+='<button class="kbtn rej" data-pid="'+pp[0]+'" data-est="rechazado">✗</button>';
h+='</div></div>';}
h+='</div>';}
document.getElementById('kanban').innerHTML=h;
}).catch(function(){});}
document.getElementById('kanban').addEventListener('click',function(e){
var el=e.target;while(el&&el!==this){
if(el.tagName==='BUTTON'&&el.getAttribute('data-pid')){
var pid=parseInt(el.getAttribute('data-pid')),est=el.getAttribute('data-est');
postJSON('/api/admin/peticion/actualizar',{id:pid,estado:est}).then(function(){mostrarToast('✅ movido a '+est);cargarKanban();cargarDatos();}).catch(function(err){mostrarToast('❌ '+err.message,true);});
return;}
el=el.parentElement;}});

/* ===== STATS ===== */
function cargarDatos(){
fetch(api('/api/admin/stats'))
.then(function(r){
if(r.status===401||r.status===403){fail++;if(fail>=maxFail){localStorage.removeItem('admin_token');mostrarToast('⚠️ sesion expirada',true);setTimeout(function(){window.location.href='/';},2000);}return null;}
if(!r.ok)return null;
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
/* sonido si hay peticiones nuevas */
if(prevPend>=0&&d.peticiones_pendientes>prevPend){beep();mostrarToast('🔔 Nueva peticion recibida!');cargarKanban();}
prevPend=d.peticiones_pendientes;
if(typeof Chart!=='undefined'){
document.getElementById('chF').style.display='none';document.getElementById('chA').style.display='block';
if(chAct)chAct.destroy();
var lb=[],dv=[],dd=[];
for(var i=0;i<d.ultimos_7_dias.length;i++){lb.push(d.ultimos_7_dias[i].fecha);dv.push(d.ultimos_7_dias[i].visitas);dd.push(d.ultimos_7_dias[i].descargas);}
chAct=new Chart(document.getElementById('chA').getContext('2d'),{type:'line',data:{labels:lb,datasets:[{label:'Visitas',data:dv,borderColor:'#00ff88',backgroundColor:'rgba(0,255,136,0.08)',tension:0.4,fill:true,borderWidth:2},{label:'Descargas',data:dd,borderColor:'#00d4ff',backgroundColor:'rgba(0,212,255,0.08)',tension:0.4,fill:true,borderWidth:2}]},options:{responsive:true,maintainAspectRatio:false,plugins:{legend:{labels:{color:'rgba(224,230,237,0.6)',font:{size:11}}}},scales:{y:{ticks:{color:'rgba(224,230,237,0.5)'},grid:{color:'rgba(0,255,136,0.06)'}},x:{ticks:{color:'rgba(224,230,237,0.5)'},grid:{color:'rgba(0,255,136,0.06)'}}}}});
}else{document.getElementById('chA').style.display='none';document.getElementById('chF').style.display='block';}
var th='';for(var a=0;a<d.top_descargadores.length;a++){var tp=d.top_descargadores[a];th+='<tr><td>'+escA(tp.ip)+'</td><td>'+tp.descargas+'</td><td>'+tp.mb.toFixed(2)+'</td></tr>';}
document.querySelector('#tTop tbody').innerHTML=th||'<tr><td colspan="3" style="text-align:center;color:rgba(224,230,237,.4)">sin datos</td></tr>';
renderDispositivos(d.dispositivos);
cargarKanban();cargarPagos();cargarCodigos();cargarAnunciosAdmin();cargarLogs();cargarAuditoria();cargarDisco();
}).catch(function(){setConn(false);});
}

function renderDispositivos(list){
var dh='';
for(var b=0;b<list.length;b++){var dv2=list[b];
var dueno=(dv2.dueno||'').trim();
dh+='<tr><td>'+escA(dv2.ip)+'</td><td><span class="db">'+escA(dv2.dispositivo)+'</span></td>';
dh+='<td>'+(dueno?'<span class="dueno">👤 '+escA(dueno)+'</span>':'<span style="opacity:0.4">sin nombre</span>')+' <button class="ab2 bg2" data-ip="'+escA(dv2.ip)+'" data-acc="nombre" data-nombre="'+escA(dueno)+'">✏️</button></td>';
dh+='<td>'+escA(dv2.ultima_conexion)+'</td><td>'+dv2.visitas+'</td><td>';
if(dv2.bloqueado===1)dh+='<span class="sb2">BLOQUEADO</span>';else dh+='<span class="sa">ACTIVO</span>';
if(dv2.motivo)dh+='<br><small style="color:rgba(224,230,237,0.4)">'+escA(dv2.motivo)+'</small>';
dh+='</td><td style="text-align:center">';
var activo=dv2.bloqueado!==1,ipId=escA(dv2.ip).replace(/\./g,'-');
dh+='<label class="switch"><input type="checkbox" data-ip="'+escA(dv2.ip)+'" data-acc="switch" '+(activo?'checked':'')+'><span class="slider"></span></label>';
dh+='<div class="estTxt '+(activo?'on':'off')+'" id="est-'+ipId+'">'+(activo?'ON':'OFF')+'</div></td></tr>';}
document.querySelector('#tDev tbody').innerHTML=dh||'<tr><td colspan="7" style="text-align:center;color:rgba(224,230,237,.4)">sin dispositivos</td></tr>';
}

function cargarPagos(){fetch(api('/api/admin/pagos')).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){h+='<tr><td>'+escA(d[i][1])+'</td><td>'+escA(d[i][2])+'</td><td style="color:var(--p);font-weight:bold">'+d[i][3]+' CUP</td><td>'+d[i][4]+'</td><td>'+escA(d[i][5]||'-')+'</td></tr>';}document.querySelector('#tPagos tbody').innerHTML=h||'<tr><td colspan="5" style="text-align:center;color:rgba(224,230,237,.4)">sin pagos</td></tr>';}).catch(function(){});}
function cargarCodigos(){fetch(api('/api/admin/codigos')).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){h+='<tr><td style="color:var(--p);font-weight:bold">'+escA(d[i][1])+'</td><td>'+escA(d[i][2])+'</td><td>'+escA(d[i][3])+'</td><td>'+(d[i][4]===1?'<span class="sr">usado</span>':'<span class="sa">disponible</span>')+'</td><td>'+d[i][5]+'</td></tr>';}document.querySelector('#tCodigos tbody').innerHTML=h||'<tr><td colspan="5" style="text-align:center;color:rgba(224,230,237,.4)">sin codigos</td></tr>';}).catch(function(){});}
function cargarAnunciosAdmin(){fetch(api('/api/admin/anuncios')).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){h+='<div style="background:rgba(0,212,255,0.06);border:1px solid rgba(0,212,255,0.2);border-radius:8px;padding:12px 16px;margin-bottom:10px;display:flex;justify-content:space-between;align-items:center;flex-wrap:wrap;gap:8px"><div><strong style="color:var(--s);font-family:Courier New,monospace">'+escA(d[i][1])+'</strong><br><small style="color:rgba(224,230,237,0.5)">'+escA(d[i][2])+'</small></div><button class="ab2 '+(d[i][3]===1?'bd':'bs2')+'" data-aid="'+d[i][0]+'" data-acc="toggleAnc">'+(d[i][3]===1?'desactivar':'activar')+'</button></div>';}document.getElementById('listaAnc').innerHTML=h||'<p style="color:rgba(224,230,237,0.4)">sin anuncios</p>';}).catch(function(){});}
function cargarLogs(){fetch(api('/api/admin/logs')).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){var cls=d[i][1]==='ERROR'?'sr':(d[i][1]==='WARN'?'sp':'scc');h+='<tr><td><span class="'+cls+'">'+d[i][1]+'</span></td><td>'+escA(d[i][2])+'</td><td style="color:rgba(224,230,237,0.4)">'+d[i][3]+'</td></tr>';}document.querySelector('#tLogs tbody').innerHTML=h||'<tr><td colspan="3" style="text-align:center;color:rgba(224,230,237,.4)">sin logs</td></tr>';}).catch(function(){});}
function cargarAuditoria(){fetch(api('/api/admin/auditoria')).then(function(r){return r.json()}).then(function(d){var h='';for(var i=0;i<d.length;i++){var a=d[i];h+='<tr><td>'+escA(a.ip)+'</td><td>'+escA(a.u)+'</td><td>'+(a.e===1?'<span class="sa">EXITOSO</span>':'<span class="sr">FALLIDO</span>')+'</td><td style="color:rgba(224,230,237,.4)">'+a.f+'</td></tr>';}document.querySelector('#tAudit tbody').innerHTML=h||'<tr><td colspan="4" style="text-align:center;color:rgba(224,230,237,.4)">sin intentos registrados</td></tr>';}).catch(function(){});}

document.getElementById('tDev').addEventListener('click',function(e){var el=e.target;while(el&&el!==this){
if(el.tagName==='INPUT'&&el.getAttribute('data-acc')==='switch'){
var ip=el.getAttribute('data-ip'),permitir=el.checked;
var ipId=ip.replace(/\./g,'-'),est=document.getElementById('est-'+ipId);
var motivo='';
if(!permitir){motivo=prompt('motivo del bloqueo (opcional):','');if(motivo===null){el.checked=false;return;}}
postJSON('/api/admin/dispositivo/toggle',{ip:ip,bloquear:!permitir,motivo:motivo})
.then(function(){if(est){est.textContent=permitir?'ON':'OFF';est.className='estTxt '+(permitir?'on':'off');}mostrarToast(permitir?'✅ activado '+ip:'⛔ bloqueado '+ip,!permitir);setTimeout(cargarDatos,400);})
.catch(function(err){el.checked=!permitir;mostrarToast('❌ '+err.message,true);});
return;}
if(el.tagName==='BUTTON'&&el.getAttribute('data-acc')==='nombre'){
var ip2=el.getAttribute('data-ip');
var nom=prompt('nombre del dueño del dispositivo '+ip2+':',el.getAttribute('data-nombre')||'');
if(nom===null)return;
postJSON('/api/admin/dispositivo/nombre',{ip:ip2,nombre:nom})
.then(function(){mostrarToast('✅ nombre guardado');cargarDatos();})
.catch(function(err){mostrarToast('❌ no se pudo guardar ('+err.message+')',true);});
return;}
el=el.parentElement;}});

document.getElementById('listaAnc').addEventListener('click',function(e){var el=e.target;while(el&&el!==this){if(el.tagName==='BUTTON'&&el.getAttribute('data-aid')){
postJSON('/api/admin/anuncio/toggle',{id:parseInt(el.getAttribute('data-aid'))}).then(function(){mostrarToast('✅ anuncio actualizado');cargarDatos();}).catch(function(err){mostrarToast('❌ '+err.message,true);});return;}el=el.parentElement;}});

document.getElementById('btnAddPago').addEventListener('click',function(){var ip=document.getElementById('payIp').value;var concepto=document.getElementById('payConcepto').value;var monto=document.getElementById('payMonto').value;var notas=document.getElementById('payNotas').value;if(!monto){mostrarToast('❌ ingresa el monto',true);return;}
postJSON('/api/admin/pago/registrar',{ip:ip,concepto:concepto,monto:parseFloat(monto),notas:notas}).then(function(){mostrarToast('✅ pago registrado');document.getElementById('payIp').value='';document.getElementById('payMonto').value='';document.getElementById('payNotas').value='';cargarDatos();}).catch(function(err){mostrarToast('❌ '+err.message,true);});});
document.getElementById('btnGenCod').addEventListener('click',function(){
postJSON('/api/admin/codigo/generar',{tipo:document.getElementById('codTipo').value,valor:document.getElementById('codValor').value}).then(function(d){document.getElementById('codResultado').innerHTML='✅ Codigo: <strong style="font-size:20px;letter-spacing:3px">'+escA(d.codigo)+'</strong>';mostrarToast('✅ codigo generado');cargarDatos();}).catch(function(err){mostrarToast('❌ '+err.message,true);});});
document.getElementById('btnAddAnc').addEventListener('click',function(){var titulo=document.getElementById('ancTitulo').value;var contenido=document.getElementById('ancContenido').value;if(!titulo||!contenido){mostrarToast('❌ completa los campos',true);return;}
postJSON('/api/admin/anuncio/agregar',{titulo:titulo,contenido:contenido}).then(function(){mostrarToast('✅ anuncio publicado');document.getElementById('ancTitulo').value='';document.getElementById('ancContenido').value='';cargarDatos();}).catch(function(err){mostrarToast('❌ '+err.message,true);});});
document.getElementById('btnCambiarPass').addEventListener('click',function(){var p1=document.getElementById('cfgPass').value;var p2=document.getElementById('cfgPass2').value;if(p1!==p2){mostrarToast('❌ no coinciden',true);return;}if(p1.length<4){mostrarToast('❌ minimo 4 caracteres',true);return;}
postJSON('/api/admin/cambiar-password',{password:p1}).then(function(){mostrarToast('✅ contrasena cambiada');document.getElementById('cfgPass').value='';document.getElementById('cfgPass2').value='';}).catch(function(err){mostrarToast('❌ '+err.message,true);});});
document.getElementById('btnBackup').addEventListener('click',function(){postJSON('/api/admin/backup',{}).then(function(d){mostrarToast('✅ backup: '+d.archivo);}).catch(function(err){mostrarToast('❌ '+err.message,true);});});
document.getElementById('btnRefreshLogs').addEventListener('click',function(){cargarLogs();});
document.getElementById('btnExpPagos').addEventListener('click',function(){window.location.href=api('/api/admin/exportar')+'&tipo=pagos';});
var expBtns=document.querySelectorAll('[data-exp]');for(var e2=0;e2<expBtns.length;e2++){(function(btn){btn.addEventListener('click',function(){window.location.href=api('/api/admin/exportar')+'&tipo='+btn.getAttribute('data-exp');});})(expBtns[e2]);}
document.getElementById('btnVol').addEventListener('click',function(){window.location.href='/';});
document.getElementById('btnOut').addEventListener('click',function(){fetch(api('/api/logout'),{method:'POST'});localStorage.removeItem('admin_token');window.location.href='/';});

function cargarChart(){var s=document.createElement('script');s.src='/static/js/chart.min.js';s.onload=function(){cargarDatos();};s.onerror=function(){cargarDatos();};document.head.appendChild(s);}
cargarChart();
cargarActivas();
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

    # ===== gzip helper =====
    def _gzip(self, data):
        ae = self.headers.get('Accept-Encoding', '')
        if 'gzip' in ae and len(data) > 700:
            return gzip_mod.compress(data), True
        return data, False

    # ===== ENVIO DE ARCHIVO CON SOPORTE RANGE (206) =====
    def enviar_archivo(self, ruta_completa, attachment=None, track=None):
        try:
            tamano = os.path.getsize(ruta_completa)
            rango = self.headers.get('Range')
            inicio, fin = 0, tamano - 1
            parcial = False
            if rango and '=' in rango:
                try:
                    spec = rango.split('=', 1)[1].strip()
                    if spec.startswith('-'):
                        inicio = max(0, tamano - int(spec[1:]))
                    else:
                        ps = spec.split('-')
                        inicio = int(ps[0])
                        if len(ps) > 1 and ps[1]: fin = int(ps[1])
                    if inicio > fin or inicio >= tamano:
                        self.send_response(416)
                        self.send_header('Content-Range', 'bytes */' + str(tamano))
                        self.end_headers()
                        return
                    fin = min(fin, tamano - 1)
                    parcial = True
                except Exception:
                    inicio, fin, parcial = 0, tamano - 1, False
            longitud = fin - inicio + 1
            self.send_response(206 if parcial else 200)
            tipo, _ = mimetypes.guess_type(ruta_completa)
            if tipo is None: tipo = 'application/octet-stream'
            self.send_header('Content-type', tipo)
            self.send_header('Accept-Ranges', 'bytes')
            if parcial:
                self.send_header('Content-Range', 'bytes %d-%d/%d' % (inicio, fin, tamano))
            self.send_header('Content-Length', str(longitud))
            self.send_header('Cache-Control', 'public, max-age=3600')
            if attachment:
                self.send_header('Content-Disposition', 'attachment; filename="'+attachment+'"')
            self.end_headers()
            tid = None
            if track:
                tid = transfer_iniciar(track['ip'], track['archivo'], tamano, self.headers.get('User-Agent', ''))
            try:
                with open(ruta_completa, 'rb') as f:
                    f.seek(inicio)
                    restante = longitud
                    while restante > 0:
                        chunk = f.read(min(128 * 1024, restante))
                        if not chunk: break
                        self.wfile.write(chunk)
                        restante -= len(chunk)
                        if tid: transfer_progreso(tid, longitud - restante)
            finally:
                if tid: transfer_fin(tid)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    # ===== IMAGEN CON ETAG (covers y posters) =====
    def enviar_imagen_etag(self, ruta_completa):
        try:
            tam = os.path.getsize(ruta_completa)
            etag = '"%x-%x"' % (int(os.path.getmtime(ruta_completa)), tam)
            if self.headers.get('If-None-Match') == etag:
                self.send_response(304)
                self.end_headers()
                return
            self.send_response(200)
            tipo, _ = mimetypes.guess_type(ruta_completa)
            self.send_header('Content-type', tipo or 'image/jpeg')
            self.send_header('Content-Length', str(tam))
            self.send_header('ETag', etag)
            self.send_header('Cache-Control', 'public, max-age=86400')
            self.end_headers()
            with open(ruta_completa, 'rb') as f:
                self.wfile.write(f.read())
        except (BrokenPipeError, OSError):
            pass

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        ruta = parsed.path
        params = urllib.parse.parse_qs(parsed.query)

        # ===== CAPTIVE PORTAL: endpoints para que la pagina abra sola =====
        if ruta in ('/generate_204', '/gen_204', '/hotspot-detect.html', '/library/test/success.html', '/redirect', '/ncsi.txt', '/connecttest.txt'):
            host = self.headers.get('Host', '192.168.137.1')
            self.send_response(302)
            self.send_header('Location', 'http://' + host + '/')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return

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

        if ruta == '/api/public-stats':
            try: self.enviar_json(200, db.obtener_stats_publicas())
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/votos':
            try: self.enviar_json(200, db.votos_agregados())
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/tendencias':
            try: self.enviar_json(200, db.tendencias_semana())
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/ranking':
            try: self.enviar_json(200, db.ranking_top())
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/comentarios':
            arch = params.get('archivo', [''])[0]
            try: self.enviar_json(200, db.comentarios_por(arch))
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/favoritos':
            try: self.enviar_json(200, db.favoritos_de(self.obtener_ip()))
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/chat':
            desde = int(params.get('desde', ['0'])[0] or 0)
            try: self.enviar_json(200, db.chat_reciente(desde))
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/tablon':
            try: self.enviar_json(200, db.tablon_reciente())
            except Exception as e: self.enviar_error(500, str(e))
            return

        # ===== TEST DE VELOCIDAD =====
        if ruta == '/api/speedtest':
            try:
                mb = min(int(params.get('mb', ['3'])[0]), 20)
            except Exception:
                mb = 3
            total = mb * 1024 * 1024
            self.send_response(200)
            self.send_header('Content-type', 'application/octet-stream')
            self.send_header('Content-Length', str(total))
            self.send_header('Cache-Control', 'no-store')
            self.end_headers()
            chunk = b'\x00' * (64 * 1024)
            restante = total
            try:
                while restante > 0:
                    b = chunk[:restante] if restante < len(chunk) else chunk
                    self.wfile.write(b)
                    restante -= len(b)
            except (BrokenPipeError, OSError):
                pass
            return

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
                        if ext in ['jpg', 'jpeg', 'png', 'gif', 'webp']:
                            covers.append({"name": f, "url": "/covers/" + urllib.parse.quote(f)})
                self.enviar_json(200, covers)
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/anuncios':
            try: self.enviar_json(200, db.obtener_anuncios(True))
            except Exception as e: self.enviar_error(500, str(e))
            return

        # ===== ENDPOINTS ADMIN =====
        if ruta == '/api/admin/stats':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try: self.enviar_json(200, db.obtener_estadisticas())
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/activas':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            self.enviar_json(200, transfer_snapshot()); return

        if ruta == '/api/admin/disco':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try:
                ruta_d = CARPETA_BASE if os.path.exists(CARPETA_BASE) else BASE_DIR
                u = shutil.disk_usage(ruta_d)
                self.enviar_json(200, {"total": u.total, "usado": u.used, "libre": u.free, "pct": round(u.used * 100 / u.total, 1)})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/auditoria':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try: self.enviar_json(200, db.intentos_login())
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
            try: self.enviar_json(200, db.obtener_anuncios(False))
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
            self.enviar_imagen_etag(ruta_completa); return

        # ===== POSTERS AUTOMATICOS (con ETag) =====
        if ruta.startswith('/poster/'):
            nombre = urllib.parse.unquote(ruta[len('/poster/'):])
            ruta_segura = os.path.normpath(nombre)
            if ruta_segura.startswith('..') or os.path.isabs(ruta_segura):
                self.enviar_error(403, "Acceso denegado"); return
            rc = os.path.join(CARPETA_BASE, ruta_segura)
            if not os.path.exists(rc) or os.path.isdir(rc):
                self.enviar_error(404, "Poster no encontrado"); return
            self.enviar_imagen_etag(rc); return

        if ruta.startswith('/static/'):
            nombre = ruta[len('/static/'):]
            ruta_segura = os.path.normpath(urllib.parse.unquote(nombre))
            if ruta_segura.startswith('..') or os.path.isabs(ruta_segura):
                self.enviar_error(403, "Acceso denegado"); return
            ruta_completa = os.path.join(CARPETA_STATIC, ruta_segura)
            if not os.path.exists(ruta_completa) or os.path.isdir(ruta_completa):
                self.enviar_error(404, "No encontrado"); return
            self.enviar_archivo(ruta_completa); return

        # ===== STREAMING (registra transferencia en vivo, no cuenta descarga) =====
        if ruta.startswith('/stream/'):
            ip = self.obtener_ip()
            if db.dispositivo_bloqueado(ip):
                self.enviar_html(200, HTML_BLOQUEO); return
            ruta_rel = urllib.parse.unquote(ruta[len('/stream/'):])
            ruta_segura = os.path.normpath(ruta_rel)
            if ruta_segura.startswith('..') or os.path.isabs(ruta_segura):
                self.enviar_error(403, "Acceso denegado"); return
            ruta_completa = os.path.join(CARPETA_BASE, ruta_segura)
            if not os.path.exists(ruta_completa) or os.path.isdir(ruta_completa):
                self.enviar_error(404, "Archivo no encontrado"); return
            self.enviar_archivo(ruta_completa, track={"ip": ip, "archivo": ruta_segura})
            return

        # ===== DESCARGA (cuenta estadisticas) =====
        if ruta.startswith('/download/'):
            ip = self.obtener_ip()
            ua = self.headers.get('User-Agent', 'Unknown')
            if db.dispositivo_bloqueado(ip):
                self.enviar_html(200, HTML_BLOQUEO); return
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
                self.enviar_archivo(ruta_completa, attachment=os.path.basename(ruta_completa), track={"ip": ip, "archivo": ruta_segura})
            except Exception as e:
                try: self.enviar_error(500, str(e))
                except Exception: pass
            return

        self.enviar_html(200, HTML_PAGINA)

    def do_POST(self):
        ruta = urllib.parse.urlparse(self.path).path

        if ruta == '/api/login':
            try:
                ip = self.obtener_ip()
                # Anti fuerza bruta: max 10 intentos fallidos en 15 min
                if db.intentos_fallidos_recientes(ip, 15) >= 10:
                    db.registrar_intento_login(ip, '-', False)
                    self.enviar_json(429, {"success": False, "error": "demasiados intentos, espera 15 minutos"})
                    return
                data = self.leer_json()
                ok = db.verificar_credenciales(data.get('usuario', ''), data.get('password', ''))
                db.registrar_intento_login(ip, data.get('usuario', ''), ok)
                if ok:
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
                ip = self.obtener_ip(); ua = self.headers.get('User-Agent', 'Unknown')
                db.registrar_dispositivo(ip, ua); db.registrar_visita(ip)
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/peticion':
            try:
                data = self.leer_json(); ip = self.obtener_ip()
                db.agregar_peticion(ip, data.get('tipo', ''), data.get('contenido', ''), data.get('detalles', ''))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/votar':
            try:
                data = self.leer_json(); ip = self.obtener_ip()
                db.votar(ip, data.get('archivo', ''), data.get('voto', 0))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/codigo/validar':
            try:
                data = self.leer_json(); ip = self.obtener_ip()
                ok, msg = db.validar_codigo(data.get('codigo', ''), ip)
                self.enviar_json(200, {"success": ok, "mensaje": msg})
            except Exception as e: self.enviar_error(500, str(e))
            return

        # ===== NUEVOS POSTS PUBLICOS =====
        if ruta == '/api/comentario':
            try:
                data = self.leer_json(); ip = self.obtener_ip()
                db.agregar_comentario(ip, data.get('archivo', ''), data.get('nombre', 'anon'), data.get('texto', ''))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/favorito':
            try:
                data = self.leer_json(); ip = self.obtener_ip()
                agregado = db.toggle_favorito(ip, data.get('archivo', ''), data.get('path', ''))
                self.enviar_json(200, {"success": True, "agregado": agregado})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/chat':
            try:
                data = self.leer_json(); ip = self.obtener_ip()
                db.agregar_chat(ip, data.get('nombre', 'anon'), data.get('texto', ''))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/tablon':
            try:
                data = self.leer_json(); ip = self.obtener_ip()
                db.agregar_tablon(ip, data.get('nombre', 'anon'), data.get('titulo', ''), data.get('texto', ''))
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        # ===== POSTS ADMIN =====
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
                data = self.leer_json(); ip = data.get('ip')
                if data.get('bloquear'): db.bloquear_dispositivo(ip, data.get('motivo', ''))
                else: db.desbloquear_dispositivo(ip)
                self.enviar_json(200, {"success": True})
            except Exception as e: self.enviar_error(500, str(e))
            return

        if ruta == '/api/admin/dispositivo/nombre':
            es_admin, token = self.verificar_admin()
            if not es_admin: self.enviar_json(403, {"error": "No autorizado"}); return
            try:
                data = self.leer_json()
                db.set_nombre_dueno(data.get('ip'), data.get('nombre', ''))
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
                if archivo: self.enviar_json(200, {"success": True, "archivo": os.path.basename(archivo)})
                else: self.enviar_json(500, {"success": False, "error": "Error en backup"})
            except Exception as e: self.enviar_error(500, str(e))
            return

        self.enviar_error(404, "Endpoint no encontrado")

    # ===== HTML Y JSON CON GZIP =====
    def enviar_html(self, codigo, contenido):
        body = contenido.encode('utf-8')
        body, gz = self._gzip(body)
        self.send_response(codigo)
        self.send_header('Content-type', 'text/html; charset=utf-8')
        self.send_header('X-Frame-Options', 'SAMEORIGIN')
        self.send_header('Cache-Control', 'no-cache')
        if gz: self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def enviar_json(self, codigo, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        body, gz = self._gzip(body)
        self.send_response(codigo)
        self.send_header('Content-type', 'application/json; charset=utf-8')
        self.send_header('Cache-Control', 'no-cache')
        if gz: self.send_header('Content-Encoding', 'gzip')
        self.send_header('Content-Length', str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def enviar_error(self, codigo, mensaje):
        self.send_response(codigo)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(("Error "+str(codigo)+": "+mensaje).encode('utf-8'))

    # ===== ARBOL CON POSTERS AUTOMATICOS Y FECHAS =====
    def obtener_arbol(self, ruta_actual, ruta_relativa=""):
        items = []
        try: entradas = sorted(os.listdir(ruta_actual), key=lambda x: x.lower())
        except (PermissionError, FileNotFoundError): return []
        img_map = {}
        for e in entradas:
            if e.lower().endswith(('.jpg', '.jpeg', '.png', '.webp')):
                img_map[e.lower()] = e
        dirpref = '' if ruta_relativa == '' else ruta_relativa + '/'
        for entrada in entradas:
            ruta_completa = os.path.join(ruta_actual, entrada)
            ruta_rel_web = entrada if ruta_relativa == "" else ruta_relativa + "/" + entrada
            try: mt = os.path.getmtime(ruta_completa)
            except Exception: mt = 0
            mtime_str = datetime.fromtimestamp(mt).strftime('%d/%m/%Y %H:%M') if mt else ''
            if os.path.isdir(ruta_completa):
                poster = None
                for cand in ('poster.jpg', 'cover.jpg', 'folder.jpg', 'poster.png', 'cover.png'):
                    if cand in img_map:
                        poster = '/poster/' + urllib.parse.quote(dirpref + entrada + '/' + img_map[cand])
                        break
                items.append({"name": entrada, "type": "folder", "path": ruta_rel_web, "mtime": mtime_str, "mts": int(mt), "poster": poster, "children": self.obtener_arbol(ruta_completa, ruta_rel_web)})
            else:
                tamano_mb = round(os.path.getsize(ruta_completa)/(1024*1024), 2)
                poster = None
                base = os.path.splitext(entrada)[0].lower()
                for ext in ('.jpg', '.jpeg', '.png', '.webp'):
                    if (base + ext) in img_map:
                        poster = '/poster/' + urllib.parse.quote(dirpref + img_map[base + ext])
                        break
                items.append({"name": entrada, "type": "file", "path": ruta_rel_web, "size": tamano_mb, "mtime": mtime_str, "mts": int(mt), "poster": poster})
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
        print("     Los clientes pueden escribir: http://" + IP_SERVIDOR)
    return servidores

def main():
    parser = argparse.ArgumentParser(description='Mi Pakete - Servidor Multimedia')
    parser.add_argument('--install', action='store_true', help='Instalar autoarranque con Windows')
    parser.add_argument('--remove', action='store_true', help='Desinstalar autoarranque')
    parser.add_argument('--silent', action='store_true', help='Modo silencioso (sin consola visible)')
    parser.add_argument('--minimized', action='store_true', help='Iniciar minimizado')
    args = parser.parse_args()

    if args.install:
        print("\n  ⚙️ Instalando autoarranque con Windows...\n")
        instalar_autoarranque()
        print()
        input("  Presiona ENTER para salir...")
        return
    if args.remove:
        print("\n  ⚙️ Desinstalando autoarranque...\n")
        desinstalar_autoarranque()
        print()
        input("  Presiona ENTER para salir...")
        return

    if args.silent:
        ocultar_consola()

    os.chdir(BASE_DIR)

    print("\n" + "=" * 70)
    print("  🚀 MI PAKETE v11.0 - Centro Multimedia Portable")
    print("  ☕ Creado por Carlos A Lorenzo Marro con cafe, anime e IA")
    print("=" * 70)
    print("  📂 Archivos:    " + CARPETA_BASE)
    print("  🖼️  Covers:      " + CARPETA_COVERS)
    print("  💾 Portable:    " + obtener_ruta_ejecutable())
    print("  📡 Streaming:   ACTIVO (Range/206)")
    print("  🗜️  Compresion:  gzip + ETag")
    print("  💽 Base datos:  SQLite WAL")
    print("=" * 70 + "\n")

    if verificar_autoarranque():
        print("  ✅ Autoarranque: ACTIVO (se inicia con Windows)")
    else:
        print("  ⬜ Autoarranque: INACTIVO")
        print("     Tip: Ejecuta con --install para activarlo")
    print()

    servidores = iniciar_todo()
    print("\n  🌐 Tus clientes pueden entrar en:")
    print("     ➜ http://" + IP_SERVIDOR)
    print("     ➜ http://" + IP_SERVIDOR + ":8000")
    print("\n  🔐 Admin: " + (db.obtener_config('admin_user') or 'root') + " / " + (db.obtener_config('admin_pass') or 'admin123'))
    print("  🛑 Ctrl + C para detener\n")

    if args.minimized:
        minimizar_consola()

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