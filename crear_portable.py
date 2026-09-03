# -*- coding: utf-8 -*-
"""
🚀 MI PAKETE - CREADOR DE PORTABLE v2
☕ Carlos A Lorenzo Marro

Ejecuta este script para crear automáticamente el
ejecutable portable con autoarranque para Windows.

NUEVO v2: Incluye chart.min.js automáticamente para que
las gráficas del panel de administración funcionen.

Requisitos: Python 3.x instalado
Uso:  python crear_portable.py
"""

import os
import sys
import subprocess
import shutil
import zipfile
import time
import platform
import urllib.request
import ssl

# ============================================================
# CONFIGURACIÓN
# ============================================================
NOMBRE_APP = "MiPakete"
ARCHIVO_SERVIDOR = "server_v6.py"
ARCHIVO_PARCHEADO = "server_v6_portable.py"
CARPETA_SALIDA = "MiPakete_Portable"
CARPETA_DIST = "dist"
CARPETA_BUILD = "build"
ARCHIVO_SPEC = NOMBRE_APP + ".spec"
ARCHIVO_ZIP = NOMBRE_APP + "_Portable.zip"
IS_WINDOWS = platform.system() == "Windows"

# ============================================================
# CHART.JS (gráficas del panel admin)
# ============================================================
CHART_JS_RELATIVO = os.path.join("static", "js", "chart.min.js")
# Ubicaciones donde buscar una copia local
CHART_JS_CANDIDATOS = [
    CHART_JS_RELATIVO,
    "chart.min.js",
    "chart.umd.min.js",
    os.path.join("static", "chart.min.js"),
    os.path.join("js", "chart.min.js"),
]
# CDN a intentar (en orden). La v2.9.4 es la más liviana y compatible.
CHART_JS_URLS = [
    "https://cdnjs.cloudflare.com/ajax/libs/Chart.js/2.9.4/Chart.min.js",
    "https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js",
    "https://unpkg.com/chart.js@4.4.1/dist/chart.umd.min.js",
]

# ============================================================
# COLORES PARA CONSOLA
# ============================================================
class C:
    RESET = "\033[0m"
    BOLD = "\033[1m"
    VERDE = "\033[92m"
    ROJO = "\033[91m"
    AMARILLO = "\033[93m"
    CYAN = "\033[96m"
    MAGENTA = "\033[95m"
    AZUL = "\033[94m"

def ok(msg):    print(f"  {C.VERDE}✅ {msg}{C.RESET}")
def err(msg):   print(f"  {C.ROJO}❌ {msg}{C.RESET}")
def warn(msg):  print(f"  {C.AMARILLO}⚠️  {msg}{C.RESET}")
def info(msg):  print(f"  {C.CYAN}ℹ️  {msg}{C.RESET}")
def paso(msg):  print(f"\n  {C.MAGENTA}🔧 {msg}{C.RESET}")

def banner():
    print(f"""
{C.VERDE}{C.BOLD}
╔══════════════════════════════════════════════╗
║   🚀  MI PAKETE - CREADOR DE PORTABLE v2 🚀  ║
║   ☕  Carlos A Lorenzo Marro                 ║
╚══════════════════════════════════════════════╝
{C.RESET}""")

# ============================================================
# CÓDIGO DE AUTOARRANQUE PARA INYECTAR
# ============================================================
IMPORTS_EXTRA = '''import argparse
try:
    import winreg
except ImportError:
    winreg = None
'''

FUNCIONES_AUTOARRANQUE = '''
# ============================================================
# AUTOARRANQUE Y MODO SILENCIOSO (inyectado por crear_portable.py)
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
        print("  No disponible en este sistema operativo")
        return False
    try:
        ruta = obtener_ruta_ejecutable()
        if getattr(sys, 'frozen', False):
            comando = '"' + ruta + '" --silent'
        else:
            comando = 'pythonw "' + ruta + '" --silent'
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
            0, winreg.KEY_SET_VALUE
        )
        winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, comando)
        winreg.CloseKey(key)
        print("  Autoarranque instalado correctamente")
        return True
    except Exception as e:
        print("  Error al instalar autoarranque: " + str(e))
        return False

def desinstalar_autoarranque():
    if winreg is None:
        print("  No disponible en este sistema operativo")
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
            0, winreg.KEY_SET_VALUE
        )
        try:
            winreg.DeleteValue(key, APP_NAME)
            print("  Autoarranque desinstalado")
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            print("  No estaba instalado")
            winreg.CloseKey(key)
            return True
    except Exception as e:
        print("  Error: " + str(e))
        return False

def verificar_autoarranque():
    if winreg is None:
        return False
    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\\Microsoft\\Windows\\CurrentVersion\\Run",
            0, winreg.KEY_READ
        )
        try:
            winreg.QueryValueEx(key, APP_NAME)
            winreg.CloseKey(key)
            return True
        except FileNotFoundError:
            winreg.CloseKey(key)
            return False
    except Exception:
        return False
'''

NUEVA_MAIN = '''
def main():
    parser = argparse.ArgumentParser(description='Mi Pakete - Servidor Multimedia')
    parser.add_argument('--install', action='store_true', help='Instalar autoarranque con Windows')
    parser.add_argument('--remove', action='store_true', help='Desinstalar autoarranque')
    parser.add_argument('--silent', action='store_true', help='Modo silencioso')
    parser.add_argument('--minimized', action='store_true', help='Iniciar minimizado')
    args = parser.parse_args()

    if args.install:
        print("")
        print("  Instalando autoarranque con Windows...")
        print("")
        instalar_autoarranque()
        print("")
        input("  Presiona ENTER para salir...")
        return

    if args.remove:
        print("")
        print("  Desinstalando autoarranque...")
        print("")
        desinstalar_autoarranque()
        print("")
        input("  Presiona ENTER para salir...")
        return

    if args.silent:
        ocultar_consola()

    os.chdir(BASE_DIR)

    print("")
    print("=" * 70)
    print("  MI PAKETE v11.0 - Centro Multimedia Portable")
    print("  Creado por Carlos A Lorenzo Marro con cafe, anime e IA")
    print("=" * 70)
    print("  Archivos:    " + CARPETA_BASE)
    print("  Covers:      " + CARPETA_COVERS)
    print("  Portable:    " + obtener_ruta_ejecutable())
    print("=" * 70)
    print("")

    if verificar_autoarranque():
        print("  Autoarranque: ACTIVO (se inicia con Windows)")
    else:
        print("  Autoarranque: INACTIVO")
        print("     Tip: Ejecuta con --install para activarlo")

    print("")
    servidores = iniciar_todo()

    print("")
    print("  Tus clientes pueden entrar en:")
    print("     http://" + IP_SERVIDOR)
    print("     http://" + IP_SERVIDOR + ":8000")
    print("")
    print("  Admin: " + (db.obtener_config('admin_user') or 'root') + " / " + (db.obtener_config('admin_pass') or 'admin123'))
    print("  Ctrl + C para detener")
    print("")

    if args.minimized:
        minimizar_consola()

    try:
        for s in servidores:
            t = threading.Thread(target=s.serve_forever, daemon=True)
            t.start()
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("")
        print("  Servidor detenido.")
        for s in servidores:
            s.shutdown()

if __name__ == "__main__":
    main()
'''

# ============================================================
# FUNCIONES DEL SCRIPT
# ============================================================
def verificar_python():
    paso("Verificando Python...")
    v = sys.version_info
    info(f"Python {v.major}.{v.minor}.{v.micro} detectado")
    if v.major < 3 or (v.major == 3 and v.minor < 7):
        err("Se requiere Python 3.7 o superior")
        return False
    ok("Python OK")
    return True

def verificar_pyinstaller():
    paso("Verificando PyInstaller...")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "PyInstaller", "--version"],
            capture_output=True, text=True, timeout=30
        )
        if r.returncode == 0:
            ok(f"PyInstaller {r.stdout.strip()} ya instalado")
            return True
    except Exception:
        pass

    info("PyInstaller no encontrado. Instalando...")
    try:
        r = subprocess.run(
            [sys.executable, "-m", "pip", "install", "pyinstaller", "--upgrade"],
            capture_output=True, text=True, timeout=300
        )
        if r.returncode == 0:
            ok("PyInstaller instalado correctamente")
            return True
        else:
            err("Error al instalar PyInstaller:")
            print(r.stderr[-500:] if len(r.stderr) > 500 else r.stderr)
            return False
    except Exception as e:
        err(f"Error instalando PyInstaller: {e}")
        return False

def verificar_servidor():
    paso("Verificando archivo del servidor...")
    if not os.path.exists(ARCHIVO_SERVIDOR):
        err(f"No se encontró '{ARCHIVO_SERVIDOR}' en esta carpeta")
        err("Asegúrate de que crear_portable.py esté en la misma carpeta que server_v6.py")
        return False
    ok(f"{ARCHIVO_SERVIDOR} encontrado")
    # Aviso temprano sobre Chart.js
    if buscar_chart_local():
        info("Chart.js local detectado: se incluirá en el portable")
    else:
        info("Chart.js local NO encontrado: se intentará descargar (requiere internet)")
    return True

# ============================================================
# CHART.JS: BUSCAR, DESCARGAR E INCLUIR
# ============================================================
def buscar_chart_local():
    """Busca una copia local de chart.min.js en ubicaciones comunes."""
    for cand in CHART_JS_CANDIDATOS:
        try:
            if os.path.isfile(cand) and os.path.getsize(cand) > 10000:
                return cand
        except Exception:
            pass
    return None

def descargar_chart_js(destino):
    """Intenta descargar chart.min.js desde varios CDN, con validación."""
    for url in CHART_JS_URLS:
        info("Intentando descargar de: " + url)
        try:
            ctx = ssl.create_default_context()
            req = urllib.request.Request(
                url,
                headers={"User-Agent": "Mozilla/5.0 (MiPakete Portable Builder)"}
            )
            with urllib.request.urlopen(req, timeout=30, context=ctx) as resp:
                data = resp.read()

            # Validación 1: tamaño razonable (Chart.js pesa >100 KB)
            if len(data) < 20000:
                warn(f"Respuesta muy pequeña ({len(data)} bytes), probando otro CDN...")
                continue

            # Validación 2: el contenido debe mencionar Chart
            inicio = data[:3000].decode('utf-8', errors='ignore').lower()
            if 'chart' not in inicio:
                warn("El contenido no parece ser Chart.js, probando otro CDN...")
                continue

            with open(destino, 'wb') as f:
                f.write(data)
            ok(f"Chart.js descargado ({len(data)//1024} KB)")
            return True
        except Exception as e:
            warn(f"Fallo con ese CDN: {e}")
    return False

def incluir_chart_js():
    """Paso principal: garantiza chart.min.js dentro del portable."""
    paso("Incluyendo Chart.js (gráficas del panel admin)...")
    destino = os.path.join(CARPETA_SALIDA, "static", "js", "chart.min.js")
    os.makedirs(os.path.dirname(destino), exist_ok=True)

    # 1. Buscar copia local (funciona sin internet)
    local = buscar_chart_local()
    if local:
        shutil.copy2(local, destino)
        ok(f"Chart.js copiado desde: {local}")
        return True

    # 2. Intentar descargar desde internet
    info("No se encontró chart.min.js localmente")
    if descargar_chart_js(destino):
        # Guardar copia local para futuras compilaciones sin internet
        try:
            os.makedirs(os.path.dirname(CHART_JS_RELATIVO), exist_ok=True)
            shutil.copy2(destino, CHART_JS_RELATIVO)
            info(f"Copia guardada en {CHART_JS_RELATIVO} (futuras compilaciones sin internet)")
        except Exception:
            pass
        return True

    # 3. Fallo total (no es fatal: el admin funciona sin gráficas)
    warn("No se pudo obtener chart.min.js (sin internet y sin copia local)")
    warn("El panel admin funcionará, pero SIN las gráficas")
    warn("Solución manual: descarga Chart.js y ponlo en static/js/chart.min.js")
    return False

def parchear_servidor():
    paso("Preparando servidor con autoarranque...")
    with open(ARCHIVO_SERVIDOR, 'r', encoding='utf-8') as f:
        codigo = f.read()

    # Verificar si ya tiene las modificaciones
    if 'instalar_autoarranque' in codigo and 'argparse' in codigo:
        ok("El servidor ya tiene las funciones de autoarranque")
        shutil.copy2(ARCHIVO_SERVIDOR, ARCHIVO_PARCHEADO)
        return True

    info("Inyectando funciones de autoarranque...")

    # 1. Inyectar imports después de "import time"
    if 'import time' in codigo:
        codigo = codigo.replace('import time', 'import time\n' + IMPORTS_EXTRA, 1)
        ok("Imports inyectados")
    else:
        warn("No se encontró 'import time', agregando imports al inicio")
        codigo = IMPORTS_EXTRA + '\n' + codigo

    # 2. Inyectar funciones antes de "class BaseDatos:"
    if 'class BaseDatos:' in codigo:
        codigo = codigo.replace('class BaseDatos:', FUNCIONES_AUTOARRANQUE + '\nclass BaseDatos:', 1)
        ok("Funciones de autoarranque inyectadas")
    else:
        err("No se encontró 'class BaseDatos:' - no se puede parchear")
        return False

    # 3. Reemplazar la función main()
    idx_main = codigo.find('def main():')
    if idx_main == -1:
        err("No se encontró 'def main():' - no se puede parchear")
        return False

    codigo = codigo[:idx_main] + NUEVA_MAIN
    ok("Función main() reemplazada")

    with open(ARCHIVO_PARCHEADO, 'w', encoding='utf-8') as f:
        f.write(codigo)
    ok(f"Archivo parcheado guardado como '{ARCHIVO_PARCHEADO}'")
    return True

def limpiar_anterior():
    paso("Limpiando compilaciones anteriores...")
    for item in [CARPETA_BUILD, CARPETA_DIST, CARPETA_SALIDA, ARCHIVO_SPEC, ARCHIVO_ZIP]:
        if os.path.isdir(item):
            try:
                shutil.rmtree(item)
                info(f"Eliminado: {item}/")
            except Exception as e:
                warn(f"No se pudo eliminar {item}: {e}")
        elif os.path.isfile(item):
            try:
                os.remove(item)
                info(f"Eliminado: {item}")
            except Exception as e:
                warn(f"No se pudo eliminar {item}: {e}")
    ok("Limpieza completada")

def compilar_exe():
    paso("Compilando ejecutable (esto puede tardar 1-3 minutos)...")
    print(f"  {C.AMARILLO}Por favor espera, no cierres esta ventana...{C.RESET}")
    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--onefile",
        "--console",
        "--name", NOMBRE_APP,
        "--clean",
        "--noconfirm",
        "--log-level", "WARN"
    ]

    if os.path.exists("icon.ico"):
        cmd.extend(["--icon", "icon.ico"])
        info("Usando icono: icon.ico")
    elif os.path.exists("icon.png"):
        info("Se encontró icon.png pero PyInstaller necesita .ico")
        info("Compilando sin icono (puedes agregar icon.ico después)")

    cmd.append(ARCHIVO_PARCHEADO)

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600)
        if r.returncode == 0:
            ruta_exe = os.path.join(CARPETA_DIST, NOMBRE_APP + ".exe")
            if os.path.exists(ruta_exe):
                tamano = os.path.getsize(ruta_exe) / (1024 * 1024)
                ok(f"Ejecutable compilado: {ruta_exe} ({tamano:.1f} MB)")
                return True
            else:
                err("La compilación terminó pero no se encontró el exe")
                return False
        else:
            err("Error en la compilación:")
            stderr = r.stderr.strip()
            ultimas = stderr.split('\n')[-10:]
            for linea in ultimas:
                print(f"    {C.ROJO}{linea}{C.RESET}")
            return False
    except subprocess.TimeoutExpired:
        err("La compilación tardó demasiado (>10 min)")
        return False
    except Exception as e:
        err(f"Error compilando: {e}")
        return False

def crear_estructura():
    paso("Creando estructura de carpetas...")
    os.makedirs(CARPETA_SALIDA, exist_ok=True)

    src = os.path.join(CARPETA_DIST, NOMBRE_APP + ".exe")
    dst = os.path.join(CARPETA_SALIDA, NOMBRE_APP + ".exe")
    shutil.copy2(src, dst)
    ok(f"{NOMBRE_APP}.exe copiado")

    carpetas = ["Pakete", "covers", "static", "backups", "logs"]
    for carp in carpetas:
        os.makedirs(os.path.join(CARPETA_SALIDA, carp), exist_ok=True)
        if carp == "static":
            os.makedirs(os.path.join(CARPETA_SALIDA, carp, "js"), exist_ok=True)
            os.makedirs(os.path.join(CARPETA_SALIDA, carp, "css"), exist_ok=True)
    ok(f"Carpetas creadas: {', '.join(carpetas)}")

    for ico in ["icon.ico", "icon.png", "icon.svg"]:
        if os.path.exists(ico):
            shutil.copy2(ico, os.path.join(CARPETA_SALIDA, ico))
            info(f"Icono copiado: {ico}")
    return True

def generar_bats():
    paso("Generando archivos .bat...")

    with open(os.path.join(CARPETA_SALIDA, "Iniciar_Servidor.bat"), 'w', encoding='utf-8') as f:
        f.write('@echo off\n')
        f.write('title Mi Pakete - Servidor Multimedia\n')
        f.write('cd /d "%~dp0"\n')
        f.write(f'start "" "{NOMBRE_APP}.exe"\n')
    ok("Iniciar_Servidor.bat")

    with open(os.path.join(CARPETA_SALIDA, "Instalar_Autoarranque.bat"), 'w', encoding='utf-8') as f:
        f.write('@echo off\n')
        f.write('title Mi Pakete - Instalar Autoarranque\n')
        f.write('cd /d "%~dp0"\n')
        f.write(f'"{NOMBRE_APP}.exe" --install\n')
    ok("Instalar_Autoarranque.bat")

    with open(os.path.join(CARPETA_SALIDA, "Desinstalar_Autoarranque.bat"), 'w', encoding='utf-8') as f:
        f.write('@echo off\n')
        f.write('title Mi Pakete - Desinstalar Autoarranque\n')
        f.write('cd /d "%~dp0"\n')
        f.write(f'"{NOMBRE_APP}.exe" --remove\n')
    ok("Desinstalar_Autoarranque.bat")

    with open(os.path.join(CARPETA_SALIDA, "Iniciar_Silencioso.bat"), 'w', encoding='utf-8') as f:
        f.write('@echo off\n')
        f.write('cd /d "%~dp0"\n')
        f.write(f'start /min "" "{NOMBRE_APP}.exe" --silent\n')
    ok("Iniciar_Silencioso.bat")
    return True

def generar_leeme(chart_ok):
    paso("Generando LEEME.txt...")
    chart_txt = "✅ Incluido" if chart_ok else "❌ NO incluido (descargar manualmente)"
    contenido = f"""
{'=' * 60}
MI PAKETE - Servidor Multimedia Portable
Creado por Carlos A Lorenzo Marro
{'=' * 60}

INSTRUCCIONES DE USO:
1. Copia esta carpeta completa a cualquier PC con Windows
2. Pon tus archivos multimedia en la carpeta "Pakete"
3. Pon las portadas en la carpeta "covers"
4. Enciende mHotspot ANTES de iniciar el servidor
5. Ejecuta "Iniciar_Servidor.bat"
6. Los clientes se conectan a: http://192.168.137.1

AUTOARRANQUE CON WINDOWS:
- Doble clic en "Instalar_Autoarranque.bat"
- El servidor se iniciara solo al encender Windows
- Se ejecuta en modo silencioso (sin ventana visible)
- Para quitarlo: "Desinstalar_Autoarranque.bat"

ACCESO ADMINISTRADOR:
- Usuario: root
- Contrasena: admin123
- Cambiar en: Panel Admin > Config

GRAFICAS DEL PANEL ADMIN:
- Chart.js: {chart_txt}
- Ubicacion: static/js/chart.min.js
- Si no esta, el admin funciona pero sin graficas.
  Descarga Chart.js y colocalo en esa ruta para activarlas.

ESTRUCTURA DE CARPETAS:
MiPakete_Portable/
├── {NOMBRE_APP}.exe        ← Servidor (este archivo)
├── Pakete/                 ← Tus archivos multimedia
├── covers/                 ← Portadas de estrenos
├── static/
│   ├── js/
│   │   └── chart.min.js    ← Libreria de graficas ({chart_txt})
│   └── css/
├── backups/                ← Respaldos de la base de datos
├── logs/                   ← Logs del servidor
├── Iniciar_Servidor.bat    ← Iniciar con ventana
├── Iniciar_Silencioso.bat  ← Iniciar sin ventana
├── Instalar_Autoarranque.bat
├── Desinstalar_Autoarranque.bat
└── LEEME.txt               ← Este archivo

COMANDOS DEL EJECUTABLE:
{NOMBRE_APP}.exe              → Inicia normal con consola
{NOMBRE_APP}.exe --silent     → Inicia sin ventana visible
{NOMBRE_APP}.exe --minimized  → Inicia minimizado
{NOMBRE_APP}.exe --install    → Instala autoarranque
{NOMBRE_APP}.exe --remove     → Desinstala autoarranque

NOTAS IMPORTANTES:
- El servidor necesita permisos de administrador para
  usar los puertos 80 y 53 (captive portal completo)
- Si no tiene permisos de admin, funciona solo en :8000
- La base de datos (pakete.db) se crea automaticamente
- Los datos persisten entre reinicios

{'=' * 60}
Generado el: {time.strftime('%Y-%m-%d %H:%M:%S')}
{'=' * 60}
"""
    with open(os.path.join(CARPETA_SALIDA, "LEEME.txt"), 'w', encoding='utf-8') as f:
        f.write(contenido)
    ok("LEEME.txt creado")
    return True

def crear_zip():
    paso("Comprimiendo en ZIP...")
    try:
        with zipfile.ZipFile(ARCHIVO_ZIP, 'w', zipfile.ZIP_DEFLATED, compresslevel=9) as zipf:
            for root, dirs, files in os.walk(CARPETA_SALIDA):
                for file in files:
                    ruta_completa = os.path.join(root, file)
                    arcname = os.path.relpath(ruta_completa, os.path.dirname(CARPETA_SALIDA))
                    zipf.write(ruta_completa, arcname)
        tamano = os.path.getsize(ARCHIVO_ZIP) / (1024 * 1024)
        ok(f"ZIP creado: {ARCHIVO_ZIP} ({tamano:.1f} MB)")
        return True
    except Exception as e:
        warn(f"No se pudo crear el ZIP: {e}")
        warn("La carpeta portable está disponible de todas formas")
        return False

def limpiar_temporales():
    paso("Limpiando archivos temporales...")
    for item in [CARPETA_BUILD, ARCHIVO_SPEC, ARCHIVO_PARCHEADO]:
        if os.path.isdir(item):
            try:
                shutil.rmtree(item)
            except Exception:
                pass
        elif os.path.isfile(item):
            try:
                os.remove(item)
            except Exception:
                pass
    ok("Temporales eliminados")

def resumen_final(zip_creado, chart_ok):
    print(f"""
{C.VERDE}{C.BOLD}
╔══════════════════════════════════════════════╗
║        ✅  PORTABLE CREADO CON ÉXITO  ✅     ║
╚══════════════════════════════════════════════╝
{C.RESET}""")
    print(f"  📦 Carpeta:   {C.CYAN}{CARPETA_SALIDA}/{C.RESET}")
    if zip_creado:
        print(f"  📦 ZIP:       {C.CYAN}{ARCHIVO_ZIP}{C.RESET}")
    if chart_ok:
        print(f"  📊 Chart.js:  {C.VERDE}✅ incluido (gráficas del admin activas){C.RESET}")
    else:
        print(f"  📊 Chart.js:  {C.AMARILLO}⚠️ NO incluido (el admin funcionará sin gráficas){C.RESET}")
        print(f"     {C.AMARILLO}→ Descarga Chart.js y ponlo en {CARPETA_SALIDA}/static/js/chart.min.js{C.RESET}")
    print(f"""
{C.AMARILLO}Próximos pasos:{C.RESET}
1. Copia la carpeta {C.BOLD}{CARPETA_SALIDA}/{C.RESET} a donde quieras
2. Agrega tus archivos en {C.BOLD}Pakete/{C.RESET}
3. Ejecuta {C.BOLD}Iniciar_Servidor.bat{C.RESET}
4. Para autoarranque: {C.BOLD}Instalar_Autoarranque.bat{C.RESET}
""")

# ============================================================
# MAIN
# ============================================================
def main():
    banner()

    if not IS_WINDOWS:
        warn("Este script está optimizado para Windows")
        warn("El autoarranque solo funcionará en Windows")
        r = input("  ¿Continuar de todas formas? (s/n): ")
        if r.lower() not in ('s', 'si', 'sí', 'y', 'yes'):
            info("Cancelado por el usuario")
            return

    # Paso 1: Verificar Python
    if not verificar_python():
        return

    # Paso 2: Verificar archivo del servidor
    if not verificar_servidor():
        return

    # Paso 3: Verificar/Instalar PyInstaller
    if not verificar_pyinstaller():
        return

    # Paso 4: Limpiar compilaciones anteriores
    limpiar_anterior()

    # Paso 5: Parchear el servidor con autoarranque
    if not parchear_servidor():
        err("No se pudo parchear el servidor")
        return

    # Paso 6: Compilar
    if not compilar_exe():
        err("La compilación falló")
        return

    # Paso 7: Crear estructura de carpetas
    crear_estructura()

    # Paso 8: ✨ NUEVO — Incluir Chart.js (local o descargado)
    chart_ok = incluir_chart_js()

    # Paso 9: Generar archivos .bat
    generar_bats()

    # Paso 10: Generar LEEME.txt
    generar_leeme(chart_ok)

    # Paso 11: Crear ZIP
    zip_creado = crear_zip()

    # Paso 12: Limpiar temporales
    limpiar_temporales()

    # Resumen final
    resumen_final(zip_creado, chart_ok)

    input(f"  {C.VERDE}Presiona ENTER para salir...{C.RESET}")

if __name__ == "__main__":
    main()