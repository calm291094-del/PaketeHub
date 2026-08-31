"""
☕ Creado por Carlos A Lorenzo Marro con cafe, anime e IA
Script para compilar Mi Pakete a EXE portable
"""
import os
import sys
import subprocess
import shutil


def main():
    print("\n" + "=" * 70)
    print("  🚀 MI PAKETE - Creador de Portable")
    print("  ☕ Creado por Carlos A Lorenzo Marro con cafe, anime e IA")
    print("=" * 70)

    if not os.path.exists("server_v3.py"):
        print("\n❌ ERROR: No se encontro server_v3.py en esta carpeta.")
        print("   Ejecuta este script en la misma carpeta que server_v3.py")
        input("\nPresiona ENTER para salir...")
        sys.exit(1)

    # Paso 1: Instalar PyInstaller
    print("\n📦 Paso 1/4: Verificando PyInstaller...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "pyinstaller", "--quiet"])
        print("   ✅ PyInstaller listo")
    except subprocess.CalledProcessError:
        print("   ⚠️ PyInstaller ya instalado o error menor, continuando...")

    # Paso 2: Limpiar
    print("\n🧹 Paso 2/4: Limpiando compilaciones anteriores...")
    for carpeta in ['build', 'dist', '__pycache__']:
        if os.path.exists(carpeta):
            shutil.rmtree(carpeta)
            print("   ✅ Eliminada: " + carpeta)
    if os.path.exists('MiPakete_v5.spec'):
        os.remove('MiPakete_v5.spec')

    # Paso 3: Compilar
    print("\n🔨 Paso 3/4: Compilando a EXE (puede tardar unos minutos)...")
    sep = ";" if sys.platform == "win32" else ":"

    cmd = [
        sys.executable, "-m", "PyInstaller",
        "--name", "MiPakete_v5",
        "--console",
        "--noconfirm",
        "--clean",
    ]

    if os.path.exists("static") and os.listdir("static"):
        cmd.extend(["--add-data", "static" + sep + "static"])

    cmd.append("server_v3.py")

    try:
        subprocess.check_call(cmd)
        print("   ✅ Compilacion exitosa")
    except subprocess.CalledProcessError as e:
        print("\n❌ ERROR en la compilacion: " + str(e))
        input("\nPresiona ENTER para salir...")
        sys.exit(1)

    # Paso 4: Crear estructura
    print("\n📁 Paso 4/4: Creando estructura de carpetas...")
    dist_dir = os.path.join("dist", "MiPakete_v5")

    carpetas = ["Pakete", "covers",
                os.path.join("static", "js"),
                os.path.join("static", "css"),
                os.path.join("static", "fonts")]

    for carpeta in carpetas:
        ruta = os.path.join(dist_dir, carpeta)
        os.makedirs(ruta, exist_ok=True)
        print("   ✅ Creada: " + carpeta)

    # README
    readme = """
============================================================
  MI PAKETE v5.0 - Centro Multimedia
  Creado por Carlos A Lorenzo Marro con cafe, anime e IA
============================================================

INSTRUCCIONES:

1. Ejecuta "MiPakete_v5.exe" para iniciar el servidor.

2. Abre tu navegador en: http://localhost:8000

3. Para acceder desde otros dispositivos:
   Mira la consola del programa, ahi aparece la IP.
   Normalmente es: http://192.168.137.1:8000

4. Para agregar contenido:
   - Copia archivos multimedia a la carpeta "Pakete"
   - Copia posters de estrenos a "covers" (JPG/PNG)
   - Actualiza la pagina web (F5)

5. Panel de Administrador:
   - Usuario: root
   - Contrasena: admin123

6. Para detener: Cierra la ventana o Ctrl+C

NOTAS:
- Si quieres graficos, descarga Chart.js:
  https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js
  Guardalo como: static/js/chart.min.js
- El programa funciona sin Chart.js, solo no muestra graficos.
"""

    with open(os.path.join(dist_dir, "LEEME.txt"), "w", encoding="utf-8") as f:
        f.write(readme)
    print("   ✅ Creado: LEEME.txt")

    # BAT de inicio
    bat = '@echo off\ntitle Mi Pakete v5.0\necho ========================================\necho   Mi Pakete - Centro Multimedia\necho   Creado por Carlos A Lorenzo Marro\necho   con cafe, anime e IA\necho ========================================\necho.\necho   Iniciando servidor...\necho   Abre tu navegador en: http://localhost:8000\necho.\ncd /d "%~dp0"\nstart "" "MiPakete_v5.exe"\ntimeout /t 3 >nul\nstart http://localhost:8000\n'

    with open(os.path.join(dist_dir, "Iniciar_MiPakete.bat"), "w", encoding="utf-8") as f:
        f.write(bat)
    print("   ✅ Creado: Iniciar_MiPakete.bat")

    print("\n" + "=" * 70)
    print("  ✅ ¡PORTABLE CREADO EXITOSAMENTE!")
    print("=" * 70)
    print("\n  📂 Ubicacion: " + os.path.abspath(dist_dir))
    print("\n  📋 Contenido:")
    print("     ├── MiPakete_v5.exe")
    print("     ├── Iniciar_MiPakete.bat")
    print("     ├── LEEME.txt")
    print("     ├── Pakete/")
    print("     ├── covers/")
    print("     └── static/")
    print("\n  🚀 Copia TODA la carpeta a la PC destino y ejecuta el EXE")
    print("\n  ☕ Creado por Carlos A Lorenzo Marro con cafe, anime e IA")
    print("=" * 70)

    resp = input("\n¿Abrir la carpeta del portable? (s/n): ").strip().lower()
    if resp == 's':
        if sys.platform == "win32":
            os.startfile(dist_dir)
        elif sys.platform == "darwin":
            subprocess.call(["open", dist_dir])
        else:
            subprocess.call(["xdg-open", dist_dir])

    input("\nPresiona ENTER para salir...")


if __name__ == "__main__":
    main()