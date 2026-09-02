# 📦 PaketeHub

<div align="center">

![Mi Pakete Banner](https://img.shields.io/badge/Mi_Pakete-Centro_Multimedia_Local-00ff88?style=for-the-badge)

**Centro Multimedia Local con estética Cyberpunk**

![Version](https://img.shields.io/badge/version-10.0-00ff88?style=flat-square)
![Python](https://img.shields.io/badge/Python-3.8+-blue?style=flat-square)
![License](https://img.shields.io/badge/license-MIT-green?style=flat-square)
![Platform](https://img.shields.io/badge/platform-Windows-lightgrey?style=flat-square)
![Status](https://img.shields.io/badge/status-Active-success?style=flat-square)

</div>

Servidor multimedia local para distribuir películas, series y música por WiFi. Sin internet. Sin nubes. Sin límites.

☕ **Creado por Carlos A Lorenzo Marro** con cafe, anime e IA 🌸🤖

---

## 📑 Tabla de Contenidos

- [¿Qué es PaketeHub?](#-qué-es-paketehub)
- [Características](#-características)
- [Resumen de Implementación](#-resumen-de-todo-lo-implementado)
- [Requisitos](#-requisitos)
- [Instalación](#-instalación)
- [Uso](#-uso)
- [Panel de Administrador](#-panel-de-administrador)
- [Crear versión portable (EXE)](#-crear-versión-portable-exe)
- [Autoarranque con Windows](#-autoarranque-con-windows)
- [Estructura del proyecto](#-estructura-del-proyecto)
- [Base de Datos](#️-base-de-datos)
- [Tecnologías](#-tecnologías)
- [Seguridad](#️-seguridad)
- [Estrategia de precios](#-estrategia-de-precios-sugerida)
- [Contribuir](#-contribuir)
- [Licencia](#-licencia)

---

## 🎯 ¿Qué es PaketeHub?

PaketeHub es un servidor multimedia local que permite distribuir contenido (películas, series, música, archivos) a través de una red WiFi local. Ideal para negocios de "paquetes" multimedia donde los clientes se conectan al WiFi y descargan contenido directamente.

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
│   ✅ Autoarranque con Windows                       │
│   ✅ Modal de bloqueo con canje de códigos          │
└─────────────────────────────────────────────────────


---

## ✨ Características

### 🎨 Interfaz Cyberpunk

- Fondo animado estilo **Matrix Rain** con letras japonesas
- Paleta de colores neón (verde `#00ff88`, cyan `#00d4ff`, magenta `#ff00ff`)
- Diseño **glassmorphism** con efectos de vidrio
- Tipografía monoespaciada estilo terminal
- **100% responsive** (PC, tablets, móviles)
- **Sin espacios en blanco** ni scroll innecesario

### 🎬 Carrusel de Estrenos

- Muestra pósters de películas/series nuevas
- Auto-rotación cada 5 segundos
- Solo agrega imágenes a la carpeta `covers/`

### 📂 Explorador de Archivos

- Navegación por carpetas y subcarpetas
- Búsqueda en tiempo real
- Iconos según tipo de archivo (🎬 🎵 🖼️ 📝 📦 📄)
- Tamaños en MB
- **Filtros por categoría** (videos, música, imágenes, subtítulos)

### 🎚️ Switch Android para Control de Descargas (NUEVO)

- **Switch estilo Android** en el panel admin
- Bolita deslizante: verde (activo) ↔ rojo (bloqueado)
- **Control instantáneo** de descargas por dispositivo
- Sin necesidad de cambiar la contraseña WiFi
- Estados visuales claros: **ON/OFF**

### 🚫 Modal de Bloqueo Elegante (NUEVO)

- Cuando un usuario bloqueado intenta descargar, ve un **modal bonito** en lugar de Error 403
- **Planes de precios visibles** para incentivar el pago
- **Caja de canje de código** integrada
- Al canjear código válido, **se reactivan las descargas automáticamente**
- Fondo Matrix en **rojo** para indicar restricción
- Totalmente responsive y con animaciones suaves

### 🔐 Panel de Administrador

- **Estadísticas**: visitas, descargas, GB transferidos
- **Gráficos**: actividad de los últimos 7 días (Chart.js)
- **Top descargadores**: ranking por IP
- **Dispositivos conectados**: ver quién está en línea
- **Switch Android**: activa/desactiva descargas con un clic
- **Gestión de peticiones**: aprobar/rechazar solicitudes
- **Sin advertencia de contraseña HTTP**: inputs enmascarados con CSS

### 📝 Sistema de Peticiones

- Los clientes pueden solicitar contenido que no encuentran
- El admin ve las peticiones y las gestiona
- Estados: pendiente, completado, rechazado

### 💰 Sistema de Pagos y Códigos

- **Registro de pagos** por IP con conceptos (por GB, diario, semanal)
- **Generación de códigos** de acceso de un solo uso
- **Canje automático** que desbloquea el dispositivo
- **Historial completo** de transacciones

### 📢 Anuncios

- Publica anuncios visibles para todos los clientes
- Activa/desactiva anuncios con un clic
- Ideal para promociones y avisos importantes

### 🔄 Autoarranque con Windows (NUEVO)

- El servidor **se inicia automáticamente** al encender Windows
- Modo **silencioso** (sin ventana visible)
- **Instalación/desinstalación** con un clic desde `.bat`
- No requiere permisos de administrador
- Registro en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`

### 📦 Portable Automatizado (NUEVO)

- Script Python que **crea el ejecutable portable automáticamente**
- Incluye todas las carpetas necesarias
- Genera `.bat` de instalación/desinstalación
- Crea archivo `LEEME.txt` con instrucciones
- Empaqueta todo en un `.zip` listo para distribuir

---

## ✅ Resumen de todo lo implementado

| Característica                                          | Estado |
|---------------------------------------------------------|--------|
| 🎬 Carrusel de estrenos                                 | ✅ |
| 💰 Precios: 6.25 CUP/GB, 50 CUP/día, 200 CUP/semana     | ✅ |
| 🔐 Login admin con verificación de token                | ✅ |
| 📊 Dashboard con gráficos (Chart.js opcional)           | ✅ |
| 🎚️ **Switch Android** para activar/desactivar descargas  | ✅ **NUEVO** |
| 🚫 **Modal bonito** de bloqueo con canje de códigos     | ✅ **NUEVO** |
| 🔒 **Sin advertencia HTTP** en campos de contraseña      | ✅ **NUEVO** |
| 📝 Sistema de peticiones                                | ✅ |
| 💳 Registro de pagos                                    | ✅ |
| 🎫 Códigos de acceso                                    | ✅ |
| 📢 Anuncios visibles para clientes                      | ✅ |
| 📋 Logs del sistema                                     | ✅ |
| 💾 Backup de base de datos                              | ✅ |
| ⚙️ Cambiar contraseña desde el panel                    | ✅ |
| 📄 Exportar CSV (descargas, pagos, dispositivos)         | ✅ |
| 🔍 Filtros por tipo de archivo                          | ✅ |
| 👍👎 Votaciones por archivo                             | ✅ |
| 📈 Predicción de ingresos mensuales                     | ✅ |
| 🟢 Indicador de conexión online/offline                  | ✅ |
| 🔔 Toast notifications (sin `alert()`)                  | ✅ |
| 🎨 Fondo Matrix Rain + partículas flotantes             | ✅ |
| 🛡️ Sesión expirada: solo tras 5 fallos 401/403           | ✅ |
| 🧹 Limpieza automática de sesiones viejas                | ✅ |
| 📦 Compatible con EXE (PyInstaller)                     | ✅ |
| 🪟 **Autoarranque con Windows**                          | ✅ **NUEVO** |
| 🤖 **Script automático** de compilación portable        | ✅ **NUEVO** |
| ☕ Crédito: Carlos A Lorenzo Marro                      | ✅ |

---

## 📋 Requisitos

- **Python 3.8+** (solo para desarrollo)
- **MyPublicWiFi** o similar (para crear el hotspot WiFi)
- **No requiere internet** para funcionar
- **Windows** (para autoarranque y portable)

---

## 🚀 Instalación

### 1. Clonar el repositorio
```bash
git clone https://github.com/TU_USUARIO/PaketeHub.git
cd PaketeHub
```

2. Ejecutar el servidor
```bash
python server_v6.py
```

3. Abrir en el navegador
```bash
[python server_v6.py](http://localhost:8000)
```
💡 Las carpetas Pakete/, covers/ y static/ se crean automáticamente al primer arranque.

📱 Uso
Para el administrador
Acción                                        Detalle
Agregar contenido                Copia archivos a la carpeta Pakete/
Agregar pósters                  Copia imágenes a covers/ (JPG, PNG, WebP)
Acceder al panel                 Clic en sudo admin → usuario: root / pass: admin123
Activar/desactivar descargas     Panel admin → Dispositivos → Switch ON/OFF
Ver estadísticas                 Panel admin → dashboard principal
Gestionar peticiones             Panel admin → sección peticiones
Generar códigos                  Panel admin → sección códigos

Para los clientes

    Conectarse al WiFi del hotspot
    Abrir el navegador (se abre automáticamente si hay captive portal)
    Explorar la biblioteca y descargar archivos
    Solicitar contenido con el botón solicitar_contenido
    Canjear código si están bloqueados (desde el modal de bloqueo)

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
⚠️ IMPORTANTE: Cambia las credenciales desde el panel: Config → Cambiar contraseña

Secciones del panel
Sección                            Descripción
📊 Actividad 7 días               Gráfico de visitas y descargas diarias
🏆 Top descargadores              Ranking de IPs con más descargas
📱 Dispositivos                    Lista con switch Android para control de descargas
📝 Peticiones                     Solicitudes de contenido de los clientes
💳 Pagos                          Registro y exportación de pagos
🎫 Códigos                        Generación de códigos de acceso
📢 Anuncios                       Gestión de anuncios visibles
📋 Logs                           Historial de eventos del sistema
⚙️ Config                         Cambiar contraseña y exportar datos

📦 Crear versión portable (EXE)
Método automático (recomendado) 🤖
```bash
python crear_portable.py
```

Este script automáticamente:

    ✅ Verifica Python y PyInstaller
    ✅ Inyecta funciones de autoarranque en el servidor
    ✅ Compila el ejecutable .exe
    ✅ Crea estructura de carpetas
    ✅ Genera archivos .bat de instalación
    ✅ Crea LEEME.txt con instrucciones
    ✅ Empaqueta todo en un .zip

Resultado
```bash
MiPakete_Portable/
├── MiPakete.exe                    ← Ejecutable principal
├── Pakete/                         ← Contenido multimedia
├── covers/                         ← Pósters de estrenos
├── static/                         ← Archivos estáticos
├── backups/                        ← Respaldos de BD
├── logs/                           ← Logs del servidor
├── Iniciar_Servidor.bat            ← Iniciar con ventana
├── Iniciar_Silencioso.bat          ← Iniciar sin ventana
├── Instalar_Autoarranque.bat       ← Activar inicio con Windows
├── Desinstalar_Autoarranque.bat    ← Desactivar autoarranque
└── LEEME.txt                       ← Instrucciones
```
💡 Copia TODA la carpeta a la PC destino. Las carpetas se crean automáticamente al ejecutar.

Método manual
```bash
# 1. Instalar PyInstaller
pip install pyinstaller

# 2. Compilar manualmente
pyinstaller --onefile --console --name MiPakete server_v6.py
```

🪟 Autoarranque con Windows
Instalar autoarranque
```bash
# Desde la carpeta portable:
doble clic en "Instalar_Autoarranque.bat"

# O desde línea de comandos:
MiPakete.exe --install
```
El servidor se iniciará automáticamente al encender Windows, en modo silencioso (sin ventana visible).

Desinstalar autoarranque
```bash
# Desde la carpeta portable:
doble clic en "Desinstalar_Autoarranque.bat"

# O desde línea de comandos:
MiPakete.exe --remove
```

Comandos disponibles del EXE
  Comando                           Función
MiPakete.exe                Inicia normal con consola
MiPakete.exe --silent       Inicia sin ventana visible
MiPakete.exe --minimized    Inicia minimizado
MiPakete.exe --install      Instala autoarranque
MiPakete.exe --remove       Desinstala autoarranque

📁 Estructura del proyecto
```bash
PaketeHub/
├── server_v6.py              ← Servidor principal (todo el código)
├── crear_portable.py         ← Script automático de compilación
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
├── backups/                  ← Respaldos de BD (auto-creada)
├── logs/                     ← Logs del servidor (auto-creada)
│
└── pakete.db                 ← Base de datos SQLite (auto-creada)
```

🗄️ Base de Datos
PaketeHub usa SQLite para almacenar:
Tabla                               Contenido
config                Configuración del sistema (admin, etc.)
sesiones              Tokens de autenticación del admin
dispositivos          IPs conectadas, tipo, dueño, estado de bloqueo
descargas             Historial de descargas por IP
peticiones            Solicitudes de contenido de clientes
pagos                 Registro de pagos recibidos
codigos               Códigos de acceso generados
anuncios              Anuncios publicados
votos                 Votaciones de archivos
estadisticas_diarias  Métricas agregadas por día
logs_sistema          Logs de eventos del sistema

🔧 Tecnologías
Tecnología                           Uso
Python                Servidor HTTP (sin frameworks externos)
SQLite                Base de datos embebida
HTML/CSS/JS           Interfaz (sin frameworks, todo vanilla)
Chart.js              Gráficos (opcional)
PyInstaller           Compilación a EXE
Canvas API            Efecto Matrix Rain
Windows Registry      Autoarranque con Windows

🛡️ Seguridad

    ✅ Autenticación por token con expiración (24h)
    ✅ Cookies HttpOnly para prevenir XSS
    ✅ Validación de rutas (previene directory traversal)
    ✅ Bloqueo de dispositivos por IP
    ✅ Sesiones con secrets.token_urlsafe()
    ✅ Inputs de contraseña sin advertencia HTTP (enmascarados con CSS)
    ✅ Migración automática de base de datos
    ✅ Backup automático de BD

💡 Estrategia de precios sugerida
Servicio           Precio          Descripción
Por GB             6.25 CUP        Pago por descarga
Diario             50 CUP          Acceso ilimitado 24h
Semanal            200 CUP         Mejor oferta
Mensual            800 CUP         Cliente VIP
💰 Con 6 clientes diarios a 50 CUP = 300 CUP/día = 9,000 CUP/mes

🤝 Contribuir
Las contribuciones son bienvenidas. Para contribuir:

    Fork el proyecto
    Crea una rama (git checkout -b feature/nueva-funcion)
    Commit tus cambios (git commit -m 'Agregar nueva funcion')
    Push a la rama (git push origin feature/nueva-funcion)
    Abre un Pull Request

📜 Licencia
Este proyecto está bajo la licencia MIT. Ver el archivo LICENSE para más detalles.

👤 Autor
<div align="center">

Carlos A Lorenzo Marro
☕ Hecho con cafe, anime e IA 🌸🤖
</div>

⭐ Apoya el proyecto
Si este proyecto te fue útil, dale una ⭐ en GitHub.
<div align="center">
╔═══════════════════════════════════════════╗
║   root@pakete:~$ ./start_server.sh        ║
║   ✅ Servidor iniciado en :8000           ║
║   🎚️ Switch Android activado              ║
║   🚫 Modal de bloqueo elegante            ║
║   🪟 Autoarranque con Windows             ║
║   ☕ Creado con cafe, anime e IA          ║
╚═══════════════════════════════════════════╝
</div>

📄 Archivo .gitignore
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

# Compilación
MiPakete_Portable/
*.zip

# Sistema
.DS_Store
Thumbs.db

# IDE
.vscode/
.idea/
*.swp
*.swo

🚀 Comandos para subir a GitHub
1. Inicializar repo
```bash
git init
```

2. Agregar archivos
```bash
git add .
```

3. Primer commit
```bash
git commit -m "🚀 PaketeHub v10.0 - Centro Multimedia Cyberpunk con Switch Android"
```

4. Crear repo en GitHub y conectar
```bash
git remote add origin https://github.com/TU_USUARIO/PaketeHub.git
```

5. Subir
```bash
git branch -M main
git push -u origin main
```

<div align="center">

© 2026 Carlos A Lorenzo Marro
Centro Multimedia Local - Sin internet, sin nubes, sin límites
</div>
```

✅ Cambios principales en esta actualización:

    Versión actualizada a v10.0
    Nuevas características destacadas:
        🎚️ Switch Android para control de descargas
        🚫 Modal de bloqueo elegante con canje de códigos
        🔒 Sin advertencia HTTP en campos de contraseña
        🪟 Autoarranque con Windows
        🤖 Script automático de compilación portable
    Tabla de resumen actualizada con las nuevas funciones marcadas como NUEVO
    Sección de Autoarranque con instrucciones completas
    Método automático de creación del portable
    Comandos del EXE documentados
    Estructura actualizada con las nuevas carpetas (backups/, logs/)
    Nuevas tablas en la base de datos (pagos, codigos, anuncios, votos, logs_sistema)
