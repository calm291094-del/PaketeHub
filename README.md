<div align="center">

# 📦 PaketeHub

### Centro Multimedia Local con estética Cyberpunk

![Version](https://img.shields.io/badge/version-5.0-00ff88?style=for-the-badge)
![Python](https://img.shields.io/badge/Python-3.8+-3776ab?style=for-the-badge&logo=python&logoColor=white)
![License](https://img.shields.io/badge/license-MIT-ff00ff?style=for-the-badge)
![Platform](https://img.shields.io/badge/platform-Windows-00d4ff?style=for-the-badge&logo=windows)
![Status](https://img.shields.io/badge/status-activo-00ff88?style=for-the-badge)

**Servidor multimedia local para distribuir películas, series y música por WiFi.**
**Sin internet. Sin nubes. Sin límites.**

☕ *Creado por **Carlos A Lorenzo Marro** con cafe, anime e IA* 🌸🤖

[Características](#-características) • [Instalación](#-instalación) • [Uso](#-uso) • [Panel Admin](#-panel-de-administrador) • [Portable](#-crear-version-portable-exe) • [Estructura](#-estructura-del-proyecto)

</div>

---

## 🎯 ¿Qué es PaketeHub?

PaketeHub es un servidor multimedia local que permite distribuir contenido (películas, series, música, archivos) a través de una red WiFi local. Ideal para negocios de "paquetes" multimedia donde los clientes se conectan al WiFi y descargan contenido directamente.
```bash
┌─────────────────────────────────────────────────────┐
│                   PaketeHub                         │
│                                                     │
│   📱 Cliente 1 ──┐                                  │
│   📱 Cliente 2 ──┼──► WiFi Local ──► 🖥️ Servidor    │
│   📱 Cliente 3 ──┘         (sin internet)           │
│                                                     │
│   ✅ Sin internet necesario                         │
│   ✅ Control de dispositivos                        │
│   ✅ Estadísticas en tiempo real                    │
│   ✅ Sistema de peticiones                          │
└─────────────────────────────────────────────────────┘
```

---

## ✨ Características

### 🎨 Interfaz Cyberpunk
- Fondo animado estilo **Matrix Rain**
- Paleta de colores neón (verde `#00ff88`, cyan `#00d4ff`, magenta `#ff00ff`)
- Diseño glassmorphism con efectos de vidrio
- Tipografía monoespaciada estilo terminal
- 100% responsive (PC, tablets, móviles)

### 🎬 Carrusel de Estrenos
- Muestra pósters de películas/series nuevas
- Auto-rotación cada 5 segundos
- Solo agrega imágenes a la carpeta `covers/`

### 📂 Explorador de Archivos
- Navegación por carpetas y subcarpetas
- Búsqueda en tiempo real
- Iconos según tipo de archivo
- Tamaños en MB

### 🔐 Panel de Administrador
- **Estadísticas**: visitas, descargas, GB transferidos
- **Gráficos**: actividad de los últimos 7 días (Chart.js)
- **Top descargadores**: ranking por IP
- **Dispositivos conectados**: ver quién está en línea
- **Bloqueo de dispositivos**: permite/bloquea descargas por IP
- **Gestión de peticiones**: aprobar/rechazar solicitudes de contenido

### 📝 Sistema de Peticiones
- Los clientes pueden solicitar contenido que no encuentran
- El admin ve las peticiones y las gestiona
- Estados: pendiente, completado, rechazado

### 🚫 Control de Acceso
- Bloquea dispositivos sin cambiar la contraseña WiFi
- Asigna motivos de bloqueo
- Los dispositivos bloqueados reciben error 403 al intentar descargar

✅ Resumen de todo lo implementado:
```bash
Característica                                                   Estado
🎬 Carrusel de estrenos                                         ✅
💰 Precios: 6.25 CUP/GB, 50 CUP/día, 200 CUP/semana             ✅
🔐 Login admin con verificación de token                        ✅
📊 Dashboard con gráficos (Chart.js opcional)                   ✅
📱 Control de dispositivos (bloquear/desbloquear)                ✅
📝 Sistema de peticiones                                        ✅
💳 Registro de pagos                                            ✅
🎫 Códigos de acceso                                            ✅
📢 Anuncios visibles para clientes                              ✅
📋 Logs del sistema                                             ✅
💾 Backup de base de datos                                      ✅
⚙️ Cambiar contraseña desde el panel                            ✅
📄 Exportar CSV (descargas, pagos, dispositivos)                ✅
🔍 Filtros por tipo de archivo                                  ✅
👍👎 Votaciones por archivo                                     ✅
📈 Predicción de ingresos mensuales                             ✅
🟢 Indicador de conexión online/offline                          ✅
🔔 Toast notifications (sin alert())                             ✅
🎨 Fondo Matrix Rain + partículas flotantes                      ✅
🛡️ Sesión expirada: solo tras 5 fallos 401/403                   ✅
🧹 Limpieza automática de sesiones viejas                        ✅
📦 Compatible con EXE (PyInstaller)                             ✅
☕ Crédito: Carlos A Lorenzo Marro                              ✅
```
---

## 📋 Requisitos

- **Python 3.8+** (solo para desarrollo)
- **MyPublicWiFi** o similar (para crear el hotspot WiFi)
- **No requiere internet** para funcionar

---

## 🚀 Instalación

### 1. Clonar el repositorio
```bash
git clone https://github.com/TU_USUARIO/PaketeHub.git
cd PaketeHub
```

2. Ejecutar el servidor:
```bash
   python server_v3.py
```

3. Abrir en el navegador
```bash
   [python server_v3.py](http://localhost:8000)
```
💡 Las carpetas Pakete/, covers/ y static/ se crean automáticamente al primer arranque.

📱 Uso
Para el administrador

Acción                             Detalle
Agregar contenido                  Copia archivos a la carpeta Pakete/
Agregar pósters                    Copia imágenes a covers/ (JPG, PNG, WebP)
Acceder al panel                   Clic en sudo admin → usuario: root / pass: admin123
Bloquear dispositivo               Panel admin → sección dispositivos → botón ✗ bloquear
Ver estadísticas                   Panel admin → dashboard principal
Gestionar peticiones               Panel admin → sección peticiones

Para los clientes:

    Conectarse al WiFi del hotspot
    Abrir el navegador (se abre automáticamente si hay captive portal)
    Explorar la biblioteca y descargar archivos
    Solicitar contenido con el botón solicitar_contenido

Configurar Captive Portal (MyPublicWiFi)
Para que la página se abra automáticamente al conectarse:

    Abre MyPublicWiFi → pestaña Management
    Activa Launch Captive Portal
    En URL de redirección pon: http://192.168.137.1:8000
    Listo, los clientes verán la página al conectarse

🔐 Panel de Administrador
Credenciales por defecto
```bash
Usuario:    root
Contraseña: admin123
```
⚠️ IMPORTANTE: Cambia las credenciales en server_v3.py antes de usar en producción
```bash
ADMIN_USER = "root"
ADMIN_PASS = "admin123"  # ← Cambia esto
```

Secciones del panel
Sección                              Descripción
📊 Actividad 7 días                 Gráfico de visitas y descargas diarias
🏆 Top descargadores                Ranking de IPs con más descargas
📱 Dispositivos                      Lista de dispositivos conectados con opciones de bloqueo
📝 Peticiones                       Solicitudes de contenido de los clientes

📦 Crear versión portable (EXE)
Para usar en una PC sin Python instalado:
1. Instalar PyInstaller
```bash
pip install pyinstaller
```
3. Ejecutar el script de compilación
```bash
python crear_portable.py
```

4. Resultado
Se creará la carpeta dist/MiPakete_v5/ con
```bash
MiPakete_v5/
├── MiPakete_v5.exe          ← Ejecutable principal
├── Iniciar_MiPakete.bat     ← Acceso directo
├── LEEME.txt                ← Instrucciones
├── Pakete/                  ← Contenido multimedia
├── covers/                  ← Pósters de estrenos
└── static/                  ← Archivos estáticos
```
💡 Copia TODA la carpeta a la PC destino. Las carpetas Pakete/ y covers/ se crean automáticamente al ejecutar.

Descargar Chart.js (opcional, para gráficos)
Si quieres gráficos en el panel admin:
```bash
Descarga: https://cdn.jsdelivr.net/npm/chart.js@4.4.0/dist/chart.umd.min.js?spm=a2ty_o01.29997173.0.0.3d9a55fbZKM9p0&file=chart.umd.min.js 
Guárdalo como: static/js/chart.min.js
```

📁 Estructura del proyecto:
```bash
PaketeHub/
├── server_v3.py              ← Servidor principal (todo el código)
├── crear_portable.py         ← Script para compilar a EXE
├── README.md                 ← Este archivo
├── LICENSE                   ← Licencia MIT
├── .gitignore                ← Ignorar archivos generados
│
├── Pakete/                   ← Contenido multimedia (auto-creada)
│   ├── peliculas/
│   ├── series/
│   └── musica/
│
├── covers/                   ← Pósters de estrenos (auto-creada)
│   ├── movie1.jpg
│   └── serie2.png
│
├── static/                   ← Archivos estáticos (auto-creada)
│   ├── js/
│   │   └── chart.min.js     ← Chart.js (opcional)
│   ├── css/
│   └── fonts/
│
└── pakete.db                 ← Base de datos SQLite (auto-creada)
```

🗄️ Base de Datos
PaketeHub usa SQLite para almacenar:
```bash
Tabla                  Contenido
sesiones               Tokens de autenticación del admin
dispositivos           IPs conectadas, tipo de dispositivo, estado de bloqueo
descargas              Historial de descargas por IP
peticiones             Solicitudes de contenido de clientes
estadisticas_diarias   Métricas agregadas por día
```

🔧 Tecnologías
```bash
Tecnología         Uso
Python             Servidor HTTP (sin frameworks externos)
SQLite             Base de datos embebida
HTML/CSS/JS        Interfaz (sin frameworks, todo vanilla)
Chart.js           Gráficos (opcional)
PyInstaller        Compilación a EXE
Canvas API         Efecto Matrix Rain
```

🛡️ Seguridad

    ✅ Autenticación por token con expiración (24h)
    ✅ Cookies HttpOnly para prevenir XSS
    ✅ Validación de rutas (previene directory traversal)
    ✅ Bloqueo de dispositivos por IP
    ✅ Sesiones con secrets.token_urlsafe()

💡 Estrategia de precios sugerida
```bash
Servicio         Precio           Descripción
Por GB           10-15 CUP        Pago por descarga
Diario           50 CUP           Acceso ilimitado 24h
Semanal          200 CUP          Mejor oferta
Mensual          800 CUP          Cliente VIP
```
💰 Con 6 clientes diarios a 50 CUP = 300 CUP/día

🤝 Contribuir
Las contribuciones son bienvenidas. Para contribuir:

    Fork el proyecto
    Crea una rama (git checkout -b feature/nueva-funcion)
    Commit tus cambios (git commit -m 'Agregar nueva funcion')
    Push a la rama (git push origin feature/nueva-funcion)
    Abre un Pull Request

📜 Licencia
```bash
Este proyecto está bajo la licencia MIT. Ver el archivo LICENSE
 para más detalles.
👤 Autor
<div align="center">
Carlos A Lorenzo Marro
☕ Hecho con cafe, anime e IA 🌸🤖
</div>
```
⭐ Apoya el proyecto
```bash
Si este proyecto te fue útil, dale una ⭐ en GitHub.
<div align="center">
  ╔═══════════════════════════════════════╗
  ║   root@pakete:~$ ./start_server.sh    ║
  ║   ✅ Servidor iniciado en :8000       ║
  ║   ☕ Creado con cafe, anime e IA      ║
  ╚═══════════════════════════════════════╝
  </div>
```
---

## 📄 **Archivo .gitignore:**

```gitignore
# Python
__pycache__/
*.py[cod]
*$py.class
*.so
.Python
build/
dist/
*.spec

# Base de datos
*.db

# Carpetas de contenido
Pakete/
covers/
static/js/chart.min.js
static/fonts/*.woff2

# Sistema
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
*.swp
*.swo
```

📄 Archivo LICENSE:
MIT License

Copyright (c) 2025 Carlos A Lorenzo Marro

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.

🚀 Comandos para subir a GitHub:
# 1. Inicializar repo
git init

# 2. Agregar archivos
git add .

# 3. Primer commit
git commit -m "🚀 PaketeHub v5.0 - Centro Multimedia Cyberpunk"

# 4. Crear repo en GitHub y conectar
git remote add origin https://github.com/TU_USUARIO/PaketeHub.git

# 5. Subir
git branch -M main
git push -u origin main
