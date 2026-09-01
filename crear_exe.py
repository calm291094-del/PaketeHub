"""
☕ Creado por Carlos A Lorenzo Marro con cafe, anime e IA
Convierte server_v6.py en un UNICO EXE portable
"""
import os
import sys
import shutil
import subprocess

SERVER = "server_v6.py"
NOMBRE_EXE = "MiPakete"

def verificar_codigo():
    print("\n🔎 Paso 1/5: Verificando que el codigo compila...")
    r = subprocess.run([sys.executable, "-m", "py_compile", SERVER], capture_output=True, text=True)
    if r.returncode != 0:
        print("   ❌ ERROR: " + SERVER + " tiene errores de sintaxis:")
        print(r.stderr)
        input("\nPresiona ENTER para salir...")
        sys.exit(1)
    print("   ✅ Codigo correcto, sin errores de sintaxis")

def instalar_pyinstaller():
    print("\n📦 Paso 2/5: Verificando PyInstaller...")
    r = subprocess.run([sys.executable, "-m", "PyInstaller", "--version"], capture_output=True, text=True)
    if r.returncode != 0:
        print("   ⬇️ Instalando PyInstaller (necesita internet solo esta vez)...")
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller"])
        print("   ✅ PyInstaller instalado")
    else:
        print("   ✅ PyInstaller listo (version " + r.stdout.strip() + ")")

def limpiar():
    print("\n🧹 Paso 3/5: Limpiando compilaciones anteriores...")
    for carpeta in ["build", "dist", "__pycache__"]:
        if os.path.exists(carpeta):
            shutil.rmtree(carpeta, ignore_errors=True)
            print("   ✅ Eliminada: " + carpeta)
    if os.path.exists(NOMBRE_EXE + ".spec"):
        os.remove(NOMBRE_EXE + ".spec")

def compilar(uac):
    print("\n🔨 Paso 4/5: Compilando a EXE unico (tarda 1-3 minutos, espera)...")
    cmd = [sys.executable, "-m", "PyInstaller",
           "--onefile", "--console", "--clean", "--noconfirm",
           "--name", NOMBRE_EXE]
    if uac:
        cmd.append("--uac-admin")
    cmd.append(SERVER)
    r = subprocess.run(cmd)
    if r.returncode != 0:
        print("\n❌ ERROR en la compilacion. Revisa el mensaje de arriba.")
        input("\nPresiona ENTER para salir...")
        sys.exit(1)
    print("   ✅ Compilacion exitosa")

def preparar_portable():
    print("\n📁 Paso 5/5: Preparando carpeta portable...")
    dist = "dist"
    # Copiar static/ si existe (para que el EXE tenga los graficos Chart.js)
    if os.path.exists("static") and os.listdir("static"):
        destino = os.path.join(dist, "static")
        if os.path.exists(destino):
            shutil.rmtree(destino, ignore_errors=True)
        shutil.copytree("static", destino)
        print("   ✅ static/ copiado junto al EXE (graficos incluidos)")
    print("   ✅ EXE listo: " + os.path.abspath(os.path.join(dist, NOMBRE_EXE + ".exe")))

def main():
    print("\n" + "=" * 70)
    print("  🚀 CREADOR DE EXE PORTABLE - Mi Pakete")
    print("  ☕ Creado por Carlos A Lorenzo Marro con cafe, anime e IA")
    print("=" * 70)

    if not os.path.exists(SERVER):
        print("\n❌ No se encontro " + SERVER + " en esta carpeta.")
        print("   Copia este script junto a server_v6.py y vuelve a ejecutarlo.")
        input("\nPresiona ENTER para salir...")
        sys.exit(1)
    print("\n   Archivo a compilar: " + os.path.abspath(SERVER))

    resp = input("\n¿Quieres que el EXE pida permisos de administrador\n   al abrirse? (recomendado para el captive portal) (s/n) [s]: ").strip().lower()
    uac = resp != "n"

    verificar_codigo()
    instalar_pyinstaller()
    limpiar()
    compilar(uac)
    preparar_portable()

    print("\n" + "=" * 70)
    print("  ✅ ¡EXE PORTABLE CREADO CON EXITO!")
    print("=" * 70)
    print("\n  📂 Ubicacion: " + os.path.abspath(os.path.join("dist", NOMBRE_EXE + ".exe")))
    print("\n  🚀 COMO USARLO:")
    print("     1. Copia MiPakete.exe a cualquier PC o pendrive")
    print("        (recomendado: escritorio o C:\\MiPakete, NO en Program Files)")
    print("     2. Haz doble clic (pedira permisos de administrador)")
    print("     3. Las carpetas Pakete/, covers/, static/, backups/ y logs/")
    print("        se crean SOLAS al lado del EXE la primera vez")
    print("     4. Enciende mHotspot ANTES de abrir el EXE")
    print("\n  💡 NOTAS:")
    print("     - La primera apertura tarda unos segundos (se descomprime)")
    print("     - Si tu antivirus lo marca como falso positivo, agregalo")
    print("       a exclusiones (es normal en EXE hechos con PyInstaller)")
    print("     - El EXE funciona SIN Python y SIN internet instalados")
    print("=" * 70)

    resp2 = input("\n¿Abrir la carpeta dist ahora? (s/n): ").strip().lower()
    if resp2 == "s":
        ruta = os.path.abspath("dist")
        if sys.platform == "win32":
            os.startfile(ruta)
        elif sys.platform == "darwin":
            subprocess.call(["open", ruta])
        else:
            subprocess.call(["xdg-open", ruta])
    input("\nPresiona ENTER para salir...")

if __name__ == "__main__":
    main()