# app_flask_combinado.py - API combinada SUNARP y SCPPP
from flask import Flask, request, jsonify
from flask_mysqldb import MySQL
from datetime import datetime
import os
import time
import re
import google.generativeai as genai
from seleniumbase import SB
from PIL import Image
import requests
import easyocr
from io import BytesIO
from bs4 import BeautifulSoup
import urllib3 
import numpy as np

app = Flask(__name__)

# --- CONFIGURACIÓN MYSQL ---
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'root'  # Cambia por tu contraseña
app.config['MYSQL_DB'] = 'vehiculos_db'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# ==============================================
# SECCIÓN 1: CONFIGURACIÓN Y UTILIDADES COMUNES
# ==============================================

# --- CONFIGURACIÓN GEMINI API ---
GEMINI_API_KEY = "TU_API_KEY_AQUÍ"
if not GEMINI_API_KEY or GEMINI_API_KEY == "TU_API_KEY_AQUÍ":
    print("❌ ERROR: Configura tu API Key de Gemini")
    print("1. Obtén una API Key en: https://makersuite.google.com/app/apikey")
    print("2. Reemplaza 'TU_API_KEY_AQUÍ' con tu clave")
    exit(1)

try:
    genai.configure(api_key=GEMINI_API_KEY)
    print("✅ Gemini API configurada correctamente")
except Exception as e:
    print(f"❌ Error configurando Gemini: {e}")
    exit(1)

# --- CONFIGURACIÓN SCPPP ---
URL_BASE_SCPPP = "https://scppp.mtc.gob.pe/"

# Inicializar EasyOCR (solo una vez)
print("🔧 Inicializando EasyOCR...")
reader = easyocr.Reader(['en'], gpu=False)
print("✅ EasyOCR listo\n")

# Deshabilitar advertencias SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ==============================================
# SECCIÓN 2: CREACIÓN DE TABLAS EN MYSQL
# ==============================================

def crear_tablas_mysql():
    try:
        # Usar el contexto de aplicación directamente
        with app.app_context():
            cur = mysql.connection.cursor()
            
            # Verificar si la base de datos existe, si no, crearla
            cur.execute("CREATE DATABASE IF NOT EXISTS vehiculos_db")
            cur.execute("USE vehiculos_db")
            
            # Tabla para datos SUNARP (vehículos)
            cur.execute('''CREATE TABLE IF NOT EXISTS sunarp_vehiculos (
                id INT AUTO_INCREMENT PRIMARY KEY,
                placa VARCHAR(20) NOT NULL UNIQUE,
                numero_serie VARCHAR(100),
                numero_vin VARCHAR(100),
                numero_motor VARCHAR(100),
                color VARCHAR(50),
                marca VARCHAR(100),
                modelo VARCHAR(100),
                placa_vigente VARCHAR(20),
                placa_anterior VARCHAR(20),
                estado VARCHAR(50),
                anotaciones TEXT,
                consultas_realizadas INT DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                deleted_at TIMESTAMP NULL,
                INDEX idx_placa (placa),
                INDEX idx_marca (marca),
                INDEX idx_estado (estado)
            )''')
            
            # Tabla para datos SCPPP (conductores)
            cur.execute('''CREATE TABLE IF NOT EXISTS scppp_conductores (
                id INT AUTO_INCREMENT PRIMARY KEY,
                licencia_dni VARCHAR(20) NOT NULL UNIQUE,
                estado_licencia VARCHAR(100),
                nombre_completo VARCHAR(200),
                dni VARCHAR(20),
                licencia VARCHAR(50),
                clase_categoria VARCHAR(100),
                vigencia VARCHAR(50),
                papeletas_estado VARCHAR(50),
                papeletas_cantidad INT DEFAULT 0,
                consultas_realizadas INT DEFAULT 1,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                deleted_at TIMESTAMP NULL,
                INDEX idx_licencia_dni (licencia_dni),
                INDEX idx_estado (estado_licencia)
            )''')
            
            mysql.connection.commit()
            cur.close()
            print("✅ Tablas 'sunarp_vehiculos' y 'scppp_conductores' creadas/verificadas en base de datos 'vehiculos_db'")
    except Exception as e:
        print(f"❌ Error creando tablas: {e}")
        # Intentar nuevamente sin contexto si falla
        try:
            import pymysql
            connection = pymysql.connect(
                host='localhost',
                user='root',
                password='root',
                database='vehiculos_db',
                charset='utf8mb4',
                cursorclass=pymysql.cursors.DictCursor
            )
            
            with connection.cursor() as cur:
                # Tabla SUNARP
                cur.execute('''CREATE TABLE IF NOT EXISTS sunarp_vehiculos (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    placa VARCHAR(20) NOT NULL UNIQUE,
                    numero_serie VARCHAR(100),
                    numero_vin VARCHAR(100),
                    numero_motor VARCHAR(100),
                    color VARCHAR(50),
                    marca VARCHAR(100),
                    modelo VARCHAR(100),
                    placa_vigente VARCHAR(20),
                    placa_anterior VARCHAR(20),
                    estado VARCHAR(50),
                    anotaciones TEXT,
                    consultas_realizadas INT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP NULL,
                    INDEX idx_placa (placa),
                    INDEX idx_marca (marca),
                    INDEX idx_estado (estado)
                )''')
                
                # Tabla SCPPP
                cur.execute('''CREATE TABLE IF NOT EXISTS scppp_conductores (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    licencia_dni VARCHAR(20) NOT NULL UNIQUE,
                    estado_licencia VARCHAR(100),
                    nombre_completo VARCHAR(200),
                    dni VARCHAR(20),
                    licencia VARCHAR(50),
                    clase_categoria VARCHAR(100),
                    vigencia VARCHAR(50),
                    papeletas_estado VARCHAR(50),
                    papeletas_cantidad INT DEFAULT 0,
                    consultas_realizadas INT DEFAULT 1,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    deleted_at TIMESTAMP NULL,
                    INDEX idx_licencia_dni (licencia_dni),
                    INDEX idx_estado (estado_licencia)
                )''')
                
            connection.commit()
            connection.close()
            print("✅ Tablas creadas usando pymysql directamente")
        except Exception as e2:
            print(f"❌ Error crítico creando tablas: {e2}")

# ==============================================
# SECCIÓN 3: FUNCIONES SUNARP
# ==============================================

# --- FUNCIONES GEMINI OCR ---
def obtener_datos_vehiculo_con_gemini(ruta_imagen: str) -> dict:
    try:
        print(f"🔍 Enviando imagen a Gemini para extraer datos del vehículo: {os.path.basename(ruta_imagen)}")
        
        if not os.path.exists(ruta_imagen):
            print("❌ La imagen no existe")
            return {"datos_vehiculo": "", "error": "Imagen no encontrada"}
        
        try:
            imagen = Image.open(ruta_imagen)
        except Exception as e:
            print(f"❌ Error cargando imagen: {e}")
            return {"datos_vehiculo": "", "error": f"Error cargando imagen: {e}"}
        
        try:
            model = genai.GenerativeModel("gemini-2.5-flash")
        except:
            model = genai.GenerativeModel("gemini-1.5-flash")
        
        prompt = """Analiza esta imagen de una consulta vehicular de SUNARP (Registro Público Peruano).

Busca específicamente la sección que dice "DATOS DEL VEHÍCULO" y extrae SOLO la información contenida en esa sección.

Extrae EXACTAMENTE estos campos en el formato original:

Nº PLACA: [valor]
Nº SERIE: [valor]
Nº VIN: [valor]
Nº MOTOR: [valor]
COLOR: [valor]
MARCA: [valor]
MODELO: [valor]
PLACA VIGENTE: [valor]
PLACA ANTERIOR: [valor]
ESTADO: [valor]
ANOTACIONES: [valor]

INSTRUCCIONES IMPORTANTES:
1. Extrae SOLO los datos de la sección "DATOS DEL VEHÍCULO"
2. IGNORA completamente todo el texto de fondo/watermark que dice "sunarp", "Superintendencia Nacional de los Registros Públicos", "Esta información no constituye Publicidad Registral", etc.
3. IGNORA los encabezados, títulos y logotipos
4. IGNORA el texto repetido del watermark
5. Devuelve SOLO los 11 campos listados arriba, uno por línea
6. Mantén el formato exacto con los dos puntos (:)
7. Si algún campo no está presente, escríbelo igual pero déjalo vacío

Ejemplo de lo que quiero:
Nº PLACA: A3V315
Nº SERIE: JS3TA04V9A4601578
Nº VIN: JS3TA04V9A4601578
Nº MOTOR: J24B1068781
COLOR: GRIS
MARCA: SUZUKI
MODELO: GRAND VITARA
PLACA VIGENTE: A3V315
PLACA ANTERIOR: NINGUNA
ESTADO: EN CIRCULACION
ANOTACIONES: NINGUNA"""

        print("⏳ Enviando a Gemini (extracción específica de datos)...")
        try:
            response = model.generate_content([prompt, imagen])
            texto_datos = response.text.strip()
            print(f"✅ Gemini devolvió datos del vehículo")
            
            datos_limpios = limpiar_datos_gemini(texto_datos)
            
            return {
                "datos_vehiculo_crudo": texto_datos,
                "datos_vehiculo_limpio": datos_limpios,
                "campos_encontrados": contar_campos_encontrados(datos_limpios),
                "error": None
            }
            
        except Exception as e:
            print(f"❌ Error en Gemini: {e}")
            return {"datos_vehiculo_crudo": "", "datos_vehiculo_limpio": "", "error": str(e)}
        
    except Exception as e:
        print(f"❌ Error general en Gemini: {e}")
        return {"datos_vehiculo_crudo": "", "datos_vehiculo_limpio": "", "error": str(e)}

def limpiar_datos_gemini(texto_gemini: str) -> str:
    if not texto_gemini:
        return ""
    
    campos_esperados = [
        "Nº PLACA:", "Nº SERIE:", "Nº VIN:", "Nº MOTOR:", 
        "COLOR:", "MARCA:", "MODELO:", "PLACA VIGENTE:", 
        "PLACA ANTERIOR:", "ESTADO:", "ANOTACIONES:"
    ]
    
    lineas = texto_gemini.strip().split('\n')
    lineas_limpias = []
    
    for linea in lineas:
        linea = linea.strip()
        if not linea:
            continue
        
        for campo in campos_esperados:
            if linea.upper().startswith(campo.upper()):
                if ':' not in linea:
                    partes = linea.split()
                    if len(partes) >= 2:
                        campo_nombre = ' '.join(partes[:-1])
                        valor = partes[-1]
                        linea = f"{campo_nombre}: {valor}"
                    else:
                        linea = f"{campo} {linea.replace(campo, '').strip()}"
                
                lineas_limpias.append(linea)
                break
    
    resultado_final = []
    for campo in campos_esperados:
        encontrado = False
        for linea in lineas_limpias:
            if linea.upper().startswith(campo.upper()):
                resultado_final.append(linea)
                encontrado = True
                break
        
        if not encontrado:
            resultado_final.append(f"{campo} ")
    
    return '\n'.join(resultado_final)

def contar_campos_encontrados(texto_datos: str) -> int:
    if not texto_datos:
        return 0
    
    campos_con_valor = 0
    lineas = texto_datos.strip().split('\n')
    
    for linea in lineas:
        if ':' in linea:
            partes = linea.split(':', 1)
            if len(partes) == 2:
                valor = partes[1].strip()
                if valor and valor != "":
                    campos_con_valor += 1
    
    return campos_con_valor

def parsear_datos_vehiculo(texto_datos: str) -> dict:
    datos = {}
    
    if not texto_datos:
        return datos
    
    lineas = texto_datos.strip().split('\n')
    
    for linea in lineas:
        if ':' in linea:
            partes = linea.split(':', 1)
            if len(partes) == 2:
                clave = partes[0].strip()
                valor = partes[1].strip()
                
                clave_normalizada = clave.upper().replace('Nº ', '').replace('N° ', '').replace('º', '')
                clave_normalizada = clave_normalizada.replace(' ', '_')
                
                datos[clave_normalizada] = valor
    
    return datos

# --- FUNCIÓN PARA GUARDAR SUNARP EN BASE DE DATOS ---
def guardar_placa_sunarp_en_db(placa: str, datos_parseados: dict):
    """Guarda o actualiza la placa en la base de datos SUNARP"""
    try:
        # Asegurar que estamos en el contexto de la aplicación
        with app.app_context():
            cur = mysql.connection.cursor()
            
            # Verificar si la placa ya existe
            cur.execute("SELECT id, consultas_realizadas FROM sunarp_vehiculos WHERE placa = %s AND deleted_at IS NULL", (placa,))
            registro = cur.fetchone()
            
            if registro:
                # Actualizar registro existente
                cur.execute('''UPDATE sunarp_vehiculos SET 
                    numero_serie = %s,
                    numero_vin = %s,
                    numero_motor = %s,
                    color = %s,
                    marca = %s,
                    modelo = %s,
                    placa_vigente = %s,
                    placa_anterior = %s,
                    estado = %s,
                    anotaciones = %s,
                    consultas_realizadas = consultas_realizadas + 1,
                    updated_at = CURRENT_TIMESTAMP
                    WHERE placa = %s AND deleted_at IS NULL''',
                    (
                        datos_parseados.get('SERIE', ''),
                        datos_parseados.get('VIN', ''),
                        datos_parseados.get('MOTOR', ''),
                        datos_parseados.get('COLOR', ''),
                        datos_parseados.get('MARCA', ''),
                        datos_parseados.get('MODELO', ''),
                        datos_parseados.get('PLACA_VIGENTE', ''),
                        datos_parseados.get('PLACA_ANTERIOR', ''),
                        datos_parseados.get('ESTADO', ''),
                        datos_parseados.get('ANOTACIONES', ''),
                        placa
                    ))
                accion = "actualizado"
                placa_id = registro['id']
                consultas_realizadas = registro['consultas_realizadas'] + 1
            else:
                # Insertar nueva placa
                cur.execute('''INSERT INTO sunarp_vehiculos (
                    placa, numero_serie, numero_vin, numero_motor, color, 
                    marca, modelo, placa_vigente, placa_anterior, estado, anotaciones
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                    (
                        placa,
                        datos_parseados.get('SERIE', ''),
                        datos_parseados.get('VIN', ''),
                        datos_parseados.get('MOTOR', ''),
                        datos_parseados.get('COLOR', ''),
                        datos_parseados.get('MARCA', ''),
                        datos_parseados.get('MODELO', ''),
                        datos_parseados.get('PLACA_VIGENTE', ''),
                        datos_parseados.get('PLACA_ANTERIOR', ''),
                        datos_parseados.get('ESTADO', ''),
                        datos_parseados.get('ANOTACIONES', '')
                    ))
                placa_id = cur.lastrowid
                accion = "creado"
                consultas_realizadas = 1
            
            mysql.connection.commit()
            cur.close()
            
            print(f"✅ Registro SUNARP {accion} en la base de datos")
            print(f"   Placa: {placa}")
            print(f"   Consultas realizadas: {consultas_realizadas}")
            
            return {
                'success': True,
                'accion': accion,
                'placa_id': placa_id,
                'consultas_realizadas': consultas_realizadas,
                'placa': placa
            }
        
    except Exception as e:
        print(f"❌ Error guardando en DB SUNARP: {e}")
        # Intentar crear la tabla si no existe
        if "doesn't exist" in str(e):
            print("⚠️ La tabla no existe, intentando crear...")
            crear_tablas_mysql()
            # Reintentar después de crear la tabla
            return guardar_placa_sunarp_en_db(placa, datos_parseados)
        return {'success': False, 'error': str(e)}

# --- FUNCIÓN DE CONSULTA SUNARP (OPTIMIZADA) ---
def consultar_sunarp_con_gemini(placa: str):
    print("=" * 80)
    print("🚗 CONSULTA SUNARP - GEMINI (SOLO DATOS DEL VEHÍCULO)")
    print("=" * 80)
    print(f"🎯 Consultando placa: {placa}")
    
    with SB(
        uc=True,
        headless=False,
        page_load_strategy="normal",
        disable_csp=True,
        agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        undetectable=True,
    ) as sb:
        try:
            # Configurar navegador
            sb.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
            
            # 1) Abrir SUNARP
            print("\n🌐 Navegando a SUNARP...")
            sb.open("https://consultavehicular.sunarp.gob.pe/consulta-vehicular/")
            print(f"📄 Título: {sb.get_title()}")
            time.sleep(5)
            
            # 2) Detectar CAPTCHA
            print("\n🔍 Verificando CAPTCHA...")
            captcha_detectado = False
            try:
                time.sleep(3)
                captcha_selectors = [
                    "div.cf-turnstile",
                    "iframe[src*='cloudflare.com']",
                    ".cf-turnstile",
                ]
                for selector in captcha_selectors:
                    try:
                        elements = sb.find_elements(selector)
                        if elements:
                            captcha_detectado = True
                            print(f"🛡️ CAPTCHA detectado con selector: {selector}")
                            break
                    except:
                        continue
                
                if not captcha_detectado:
                    page_source = sb.get_page_source().lower()
                    if "turnstile" in page_source or "cloudflare" in page_source:
                        captcha_detectado = True
                        print("🛡️ CAPTCHA detectado en código fuente")
            except Exception as e:
                print(f"⚠️ Error verificando CAPTCHA: {e}")
            
            if captcha_detectado:
                print("\n👤 CAPTCHA detectado - Requiere intervención manual")
                print("=" * 60)
                print("INSTRUCCIONES:")
                print("1. Busque el widget de Cloudflare en la página")
                print("2. Resuelva el CAPTCHA manualmente")
                print("3. El script continuará automáticamente")
                print("=" * 60)
                
                print("\n⏳ Esperando a que resuelva el CAPTCHA (máximo 90 segundos)...")
                for i in range(90):
                    try:
                        token_value = sb.get_attribute("input[name='cf-turnstile-response']", "value")
                        if token_value and len(token_value) > 20:
                            print("✅ CAPTCHA resuelto exitosamente")
                            break
                    except:
                        pass
                    
                    if i % 10 == 0 and i > 0:
                        minutos = i // 60
                        segundos = i % 60
                        print(f"⏳ Esperando... {minutos}:{segundos:02d} / 1:30")
                    
                    time.sleep(1)
                
                time.sleep(2)
            else:
                print("✅ No se detectó CAPTCHA, continuando...")
            
            # 3) Consultar placa
            print(f"\n📝 CONSULTANDO PLACA: {placa}")
            sb.wait_for_element("#nroPlaca", timeout=20)
            sb.clear("#nroPlaca")
            time.sleep(0.5)
            sb.type("#nroPlaca", placa)
            print(f"✅ Placa '{placa}' ingresada")
            
            sb.wait_for_element("button.btn-sunarp-green", timeout=5)
            sb.click("button.btn-sunarp-green")
            print("✅ Consulta enviada")
            
            # 4) Esperar resultados
            print("\n⏳ Esperando resultados...")
            for i in range(5):
                try:
                    if sb.is_element_visible(".swal2-popup"):
                        alert_text = sb.get_text(".swal2-title")
                        if "captcha" in alert_text.lower() or "verificación" in alert_text.lower():
                            print("❌ Error de CAPTCHA - Intente nuevamente")
                            try:
                                sb.click(".swal2-confirm")
                                time.sleep(2)
                            except:
                                pass
                            return {"success": False, "error": "CAPTCHA no resuelto"}
                except:
                    pass
                
                try:
                    page_text = sb.get_page_source()
                    if "DATOS DEL VEH" in page_text.upper():
                        print("✅ Sección 'DATOS DEL VEHÍCULO' detectada")
                        break
                except:
                    pass
                
                print(f"  Esperando... {i+1}/5 segundos", end="\r")
                time.sleep(1)
            print()
            
            # 5) Capturar screenshot
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            screenshot_filename = f"temp_sunarp_{placa}_{timestamp}.png"
            
            # Guardar screenshot temporal
            sb.save_screenshot(screenshot_filename)
            print(f"📸 Screenshot temporal guardado: {screenshot_filename}")
            
            # 6) Extraer datos con Gemini
            print("\n🔍 EXTRACIENDO SOLO DATOS DEL VEHÍCULO CON GEMINI...")
            resultado_gemini = obtener_datos_vehiculo_con_gemini(screenshot_filename)
            
            datos_vehiculo = resultado_gemini.get("datos_vehiculo_limpio", "")
            
            # 7) Parsear datos
            datos_parseados = parsear_datos_vehiculo(datos_vehiculo)
            
            # 8) Guardar en base de datos
            db_resultado = guardar_placa_sunarp_en_db(placa, datos_parseados)
            
            # 9) Eliminar archivo temporal
            if os.path.exists(screenshot_filename):
                os.remove(screenshot_filename)
                print(f"🗑️ Archivo temporal eliminado: {screenshot_filename}")
            
            print("\n⏳ Navegador se mantendrá abierto 3 segundos...")
            time.sleep(3)
            
            return {
                "success": True,
                "placa": placa,
                "datos_vehiculo_texto": datos_vehiculo,
                "datos_vehiculo_estructurado": datos_parseados,
                "base_datos": db_resultado,
                "estadisticas": {
                    "campos_encontrados": resultado_gemini.get("campos_encontrados", 0),
                    "exito_extraccion": bool(datos_vehiculo),
                    "error_gemini": resultado_gemini.get("error")
                }
            }
            
        except Exception as e:
            print(f"❌ Error general: {e}")
            import traceback
            traceback.print_exc()
            
            try:
                timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                sb.save_screenshot(f"error_sunarp_{placa}_{timestamp}.png")
                print(f"📸 Screenshot del error guardado")
            except:
                pass
            
            return {"success": False, "error": str(e)}

# ==============================================
# SECCIÓN 4: FUNCIONES SCPPP
# ==============================================

def obtener_texto_con_easyocr(imagen_bytes):
    """Envía la imagen a EasyOCR para extraer el texto"""
    try:
        img = Image.open(BytesIO(imagen_bytes))
        img_array = np.array(img)
        resultados = reader.readtext(img_array, detail=0)
        texto_limpio = ''.join(resultados).strip().replace(" ", "").upper()
        texto_limpio = ''.join(c for c in texto_limpio if c.isalnum())
        return texto_limpio
    except Exception as e:
        print(f"⚠️ Error en EasyOCR: {e}")
        return None

def extraer_campos_formulario(soup):
    """Extrae todos los campos hidden del formulario"""
    form_data = {}
    for hidden_field in soup.find_all('input', type='hidden'):
        if hidden_field.get('name') and hidden_field.get('value') is not None:
            form_data[hidden_field['name']] = hidden_field['value']
    
    # Agregar campos visibles vacíos
    form_data['rbtnlBuqueda'] = '0'
    form_data['ddlTipoDocumento'] = ''
    form_data['txtNroDocumento'] = ''
    form_data['txtCaptcha'] = ''
    form_data['hdCodAdministrado'] = ''
    form_data['hdNumTipoDoc'] = ''
    form_data['hdNumDocumento'] = ''
    form_data['txtNroResolucion'] = ''
    form_data['txtFechaResolucion'] = ''
    form_data['txtIniSancion'] = ''
    form_data['txtFinSancion'] = ''
    form_data['txtSancion'] = ''
    form_data['txtTipSancion'] = ''
    
    return form_data

def analizar_resultados_scppp(html_content, valor_consultado):
    """Analiza exhaustivamente los resultados de la consulta SCPPP"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    resultado = {
        'valor_consultado': valor_consultado,
        'fecha_consulta': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'fuente': 'SCPPP - MTC',
        'estado': 'CONSULTA_REALIZADA',
        'datos_personales': {},
        'papeletas': {}
    }
    
    # 1. DATOS PERSONALES
    try:
        resultado['datos_personales'] = {
            'nombre_completo': soup.find('span', {'id': 'lblAdministrado'}).text.strip() if soup.find('span', {'id': 'lblAdministrado'}) else 'No encontrado',
            'dni': soup.find('span', {'id': 'lblDni'}).text.strip() if soup.find('span', {'id': 'lblDni'}) else 'No encontrado',
            'licencia': soup.find('span', {'id': 'lblLicencia'}).text.strip() if soup.find('span', {'id': 'lblLicencia'}) else 'No encontrado',
            'clase_categoria': soup.find('span', {'id': 'lblClaseCategoria'}).text.strip() if soup.find('span', {'id': 'lblClaseCategoria'}) else 'No encontrado',
            'vigencia': soup.find('span', {'id': 'lblVigencia'}).text.strip() if soup.find('span', {'id': 'lblVigencia'}) else 'No encontrado',
            'estado_licencia': soup.find('span', {'id': 'lblEstadoLicencia'}).text.strip() if soup.find('span', {'id': 'lblEstadoLicencia'}) else 'No encontrado'
        }
    except Exception as e:
        print(f"⚠️ Error extrayendo datos personales: {e}")
    
    # 2. INFORMACIÓN DE PAPELETAS
    try:
        tabla_papeletas = soup.find('table', {'id': 'gvPapeletas'})
        if tabla_papeletas:
            mensaje_no_papeletas = tabla_papeletas.find('span', {'id': lambda x: x and 'vacio' in x})
            if mensaje_no_papeletas:
                resultado['papeletas'] = {
                    'estado': 'SIN_PAPELETAS',
                    'mensaje': mensaje_no_papeletas.text.strip(),
                    'cantidad': 0
                }
                resultado['estado'] = 'SIN_PAPELETAS'
            else:
                filas_papeletas = tabla_papeletas.find_all('tr')[1:]
                resultado['papeletas'] = {
                    'estado': 'CON_PAPELETAS',
                    'cantidad': len(filas_papeletas),
                    'detalles': 'Se encontraron papeletas pendientes'
                }
                resultado['estado'] = 'CON_PAPELETAS'
    except Exception as e:
        print(f"⚠️ Error analizando papeletas: {e}")
    
    return resultado

# --- FUNCIÓN PARA GUARDAR SCPPP EN BASE DE DATOS ---
def guardar_scppp_en_db(licencia_dni: str, resultado: dict):
    """Guarda o actualiza la información en la base de datos SCPPP"""
    try:
        # Asegurar que estamos en el contexto de la aplicación
        with app.app_context():
            cur = mysql.connection.cursor()
            
            # Verificar si ya existe
            cur.execute("SELECT id, consultas_realizadas FROM scppp_conductores WHERE licencia_dni = %s AND deleted_at IS NULL", (licencia_dni,))
            registro = cur.fetchone()
            
            datos_personales = resultado['datos_personales']
            papeletas = resultado['papeletas']
            
            if registro:
                # Actualizar registro existente
                cur.execute('''UPDATE scppp_conductores SET 
                    estado_licencia = %s,
                    nombre_completo = %s,
                    dni = %s,
                    licencia = %s,
                    clase_categoria = %s,
                    vigencia = %s,
                    papeletas_estado = %s,
                    papeletas_cantidad = %s,
                    consultas_realizadas = consultas_realizadas + 1,
                    updated_at = CURRENT_TIMESTAMP
                    WHERE licencia_dni = %s AND deleted_at IS NULL''',
                    (
                        datos_personales.get('estado_licencia'),
                        datos_personales.get('nombre_completo'),
                        datos_personales.get('dni'),
                        datos_personales.get('licencia'),
                        datos_personales.get('clase_categoria'),
                        datos_personales.get('vigencia'),
                        papeletas.get('estado'),
                        papeletas.get('cantidad', 0),
                        licencia_dni
                    ))
                accion = "actualizado"
                consultas_realizadas = registro['consultas_realizadas'] + 1
                registro_id = registro['id']
            else:
                # Insertar nuevo registro
                cur.execute('''INSERT INTO scppp_conductores (
                    licencia_dni, estado_licencia, nombre_completo, dni, licencia, 
                    clase_categoria, vigencia, papeletas_estado, papeletas_cantidad
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                    (
                        licencia_dni,
                        datos_personales.get('estado_licencia'),
                        datos_personales.get('nombre_completo'),
                        datos_personales.get('dni'),
                        datos_personales.get('licencia'),
                        datos_personales.get('clase_categoria'),
                        datos_personales.get('vigencia'),
                        papeletas.get('estado'),
                        papeletas.get('cantidad', 0)
                    ))
                accion = "creado"
                consultas_realizadas = 1
                registro_id = cur.lastrowid
            
            mysql.connection.commit()
            cur.close()
            
            print(f"✅ Registro SCPPP {accion} en la base de datos")
            print(f"   Licencia/DNI: {licencia_dni}")
            print(f"   Consultas realizadas: {consultas_realizadas}")
            
            return {
                'success': True,
                'accion': accion,
                'registro_id': registro_id,
                'consultas_realizadas': consultas_realizadas,
                'licencia_dni': licencia_dni
            }
        
    except Exception as e:
        print(f"❌ Error guardando en DB SCPPP: {e}")
        # Intentar crear la tabla si no existe
        if "doesn't exist" in str(e):
            print("⚠️ La tabla no existe, intentando crear...")
            crear_tablas_mysql()
            # Reintentar después de crear la tabla
            return guardar_scppp_en_db(licencia_dni, resultado)
        return {'success': False, 'error': str(e)}

# --- FUNCIÓN DE CONSULTA SCPPP ---
def consultar_scppp(valor: str, tipo: str = '1'):
    """Consulta en el sistema SCPPP"""
    try:
        print(f"🚀 Iniciando consulta SCPPP para: {valor} (tipo: {tipo})")
        
        session = requests.Session()
        
        # PASO 1: Obtener página inicial
        print(f"🔍 PASO 1: Cargando página inicial...")
        response = session.get(URL_BASE_SCPPP, timeout=15, verify=False)
        
        if response.status_code != 200:
            return {"success": False, "error": f"Error al cargar página: {response.status_code}"}
        
        soup = BeautifulSoup(response.text, 'html.parser')
        form_data = extraer_campos_formulario(soup)
        
        if '__VIEWSTATE' not in form_data:
            return {"success": False, "error": "No se encontró VIEWSTATE"}
        
        print(f"✅ VIEWSTATE obtenido ({len(form_data['__VIEWSTATE'])} chars)")
        
        # PASO 2: Cambiar a opción de búsqueda según tipo
        print(f"\n🔄 PASO 2: Configurando tipo de búsqueda...")
        
        form_data['rbtnlBuqueda'] = tipo
        form_data['ddlTipoDocumento'] = '2' if tipo == '1' else ''
        form_data['__EVENTTARGET'] = 'rbtnlBuqueda$1'
        form_data['__EVENTARGUMENT'] = ''
        form_data['__LASTFOCUS'] = ''
        form_data['__ASYNCPOST'] = 'true'
        form_data['ScriptManager'] = 'UpdatePanel|rbtnlBuqueda$1'
        
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
            'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
            'X-Requested-With': 'XMLHttpRequest',
            'X-MicrosoftAjax': 'Delta=true',
            'Referer': URL_BASE_SCPPP,
            'Origin': URL_BASE_SCPPP.rstrip('/')
        }
        
        response2 = session.post(URL_BASE_SCPPP, data=form_data, headers=headers, verify=False)
        
        if response2.status_code != 200:
            return {"success": False, "error": f"Error en cambio de opción: {response2.status_code}"}
        
        print(f"✅ Opción configurada correctamente")
        
        # PASO 3: Parsear respuesta AJAX y extraer VIEWSTATE actualizado
        ajax_content = response2.text
        
        # Buscar el VIEWSTATE en la respuesta AJAX
        viewstate_match = re.search(r'\|__VIEWSTATE\|(.*?)\|', ajax_content)
        eventvalidation_match = re.search(r'\|__EVENTVALIDATION\|(.*?)\|', ajax_content)
        
        if viewstate_match:
            form_data['__VIEWSTATE'] = viewstate_match.group(1)
            print(f"✅ Nuevo VIEWSTATE extraído del AJAX")
        
        if eventvalidation_match:
            form_data['__EVENTVALIDATION'] = eventvalidation_match.group(1)
            print(f"✅ Nuevo EVENTVALIDATION extraído del AJAX")
        
        # PASO 4: Descargar y resolver CAPTCHA
        print(f"\n🖼️  PASO 3: Descargando CAPTCHA...")
        url_captcha = URL_BASE_SCPPP + "Captcha.aspx"
        resp_img = session.get(url_captcha, verify=False)
        
        if resp_img.status_code != 200:
            return {"success": False, "error": "Error descargando CAPTCHA"}
        
        print("🤖 Resolviendo CAPTCHA con EasyOCR...")
        texto_captcha = obtener_texto_con_easyocr(resp_img.content)
        
        if not texto_captcha:
            return {"success": False, "error": "Error resolviendo CAPTCHA"}
        
        print(f"✅ CAPTCHA: {texto_captcha}")
        
        # PASO 5: Enviar búsqueda final
        print(f"\n📡 PASO 4: Buscando {valor}...")
        
        # Determinar campo a usar según tipo de búsqueda
        campo_busqueda = 'txtNroLicencia' if tipo == '1' else 'txtNroDocumento'
        
        search_data = {
            '__VIEWSTATE': form_data['__VIEWSTATE'],
            '__VIEWSTATEGENERATOR': form_data.get('__VIEWSTATEGENERATOR', '90059987'),
            '__VIEWSTATEENCRYPTED': form_data.get('__VIEWSTATEENCRYPTED', ''),
            '__EVENTVALIDATION': form_data['__EVENTVALIDATION'],
            'rbtnlBuqueda': tipo,
            campo_busqueda: valor,
            'txtCaptcha': texto_captcha,
            'hdCodAdministrado': '',
            'hdNumTipoDoc': '',
            'hdNumDocumento': '',
            'txtNroResolucion': '',
            'txtFechaResolucion': '',
            'txtIniSancion': '',
            'txtFinSancion': '',
            'txtSancion': '',
            'txtTipSancion': '',
            '__EVENTTARGET': 'ibtnBusqNroDoc',
            '__EVENTARGUMENT': '',
            '__LASTFOCUS': '',
            '__ASYNCPOST': 'true',
            'ScriptManager': 'UpdatePanel|ibtnBusqNroDoc'
        }
        
        final_response = session.post(URL_BASE_SCPPP, data=search_data, headers=headers, verify=False, timeout=30)
        
        print(f"\n{'='*70}")
        print(f"📊 Status Code: {final_response.status_code}")
        print(f"📏 Respuesta: {len(final_response.text)} bytes")
        print(f"{'='*70}")
        
        if final_response.status_code == 500:
            return {"success": False, "error": "Error 500 del servidor"}
        
        if final_response.status_code == 200:
            print("\n✅ CONSULTA SCPPP EXITOSA")
            resultado = analizar_resultados_scppp(final_response.text, valor)
            
            # Guardar en base de datos
            db_resultado = guardar_scppp_en_db(valor, resultado)
            
            return {
                "success": True,
                "valor": valor,
                "datos": resultado,
                "base_datos": db_resultado
            }
        else:
            return {"success": False, "error": f"Error en la consulta: {final_response.status_code}"}
        
    except Exception as e:
        print(f"\n❌ ERROR SCPPP: {e}")
        import traceback
        traceback.print_exc()
        
        return {"success": False, "error": f"Error interno: {str(e)}"}

# ==============================================
# SECCIÓN 5: ENDPOINTS FLASK
# ==============================================

# --- ENDPOINTS SUNARP ---
@app.route('/sunarp/consultar', methods=['POST'])
def sunarp_consultar():
    """Endpoint para consultar SUNARP"""
    try:
        data = request.json
        
        if not data or 'placa' not in data:
            return jsonify({
                'success': False,
                'error': 'Se requiere el parámetro "placa"'
            }), 400
        
        placa = data['placa'].strip().upper()
        
        print(f"\n{'='*60}")
        print(f"🚗 NUEVA CONSULTA SUNARP: {placa}")
        print(f"{'='*60}")
        
        # Ejecutar consulta
        resultado = consultar_sunarp_con_gemini(placa)
        
        if resultado['success']:
            return jsonify({
                'success': True,
                'message': 'Consulta SUNARP realizada exitosamente',
                'placa': placa,
                'datos_vehiculo_texto': resultado['datos_vehiculo_texto'],
                'datos_vehiculo_estructurado': resultado['datos_vehiculo_estructurado'],
                'base_datos': resultado['base_datos'],
                'estadisticas': resultado['estadisticas']
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': resultado.get('error', 'Error desconocido'),
                'placa': placa
            }), 500
            
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error interno: {str(e)}'
        }), 500

@app.route('/sunarp/placas', methods=['GET'])
def sunarp_listar_placas():
    """Lista todas las placas registradas en SUNARP"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            offset = (page - 1) * per_page
            
            cur.execute("SELECT COUNT(*) as total FROM sunarp_vehiculos WHERE deleted_at IS NULL")
            total = cur.fetchone()['total']
            
            cur.execute("""
                SELECT id, placa, marca, modelo, color, estado, 
                       numero_serie, numero_vin, numero_motor,
                       placa_vigente, placa_anterior, anotaciones,
                       consultas_realizadas, created_at, updated_at
                FROM sunarp_vehiculos 
                WHERE deleted_at IS NULL 
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
            """, (per_page, offset))
            placas = cur.fetchall()
            
            cur.close()
            
            return jsonify({
                'success': True,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
                'placas': placas
            })
    except Exception as e:
        # Intentar crear la tabla si no existe
        if "doesn't exist" in str(e):
            crear_tablas_mysql()
            return jsonify({
                'success': True,
                'total': 0,
                'page': 1,
                'per_page': 20,
                'total_pages': 0,
                'placas': [],
                'message': 'Tabla creada, no hay registros aún'
            })
        return jsonify({
            'success': False,
            'error': f'Error obteniendo placas SUNARP: {str(e)}'
        }), 500

@app.route('/sunarp/placas/<placa>', methods=['GET'])
def sunarp_obtener_placa(placa):
    """Obtiene información específica de una placa SUNARP"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            cur.execute("""
                SELECT id, placa, marca, modelo, color, estado, 
                       numero_serie, numero_vin, numero_motor,
                       placa_vigente, placa_anterior, anotaciones,
                       consultas_realizadas, created_at, updated_at
                FROM sunarp_vehiculos 
                WHERE placa = %s AND deleted_at IS NULL
            """, (placa,))
            placa_info = cur.fetchone()
            cur.close()
            
            if placa_info:
                return jsonify({
                    'success': True,
                    'placa': placa_info
                })
            else:
                return jsonify({
                    'success': False,
                    'error': f'Placa {placa} no encontrada en SUNARP'
                }), 404
    except Exception as e:
        # Intentar crear la tabla si no existe
        if "doesn't exist" in str(e):
            crear_tablas_mysql()
            return jsonify({
                'success': False,
                'error': f'Placa {placa} no encontrada en SUNARP (tabla recién creada)'
            }), 404
        return jsonify({
            'success': False,
            'error': f'Error obteniendo placa SUNARP: {str(e)}'
        }), 500

@app.route('/sunarp/placas/<placa>', methods=['DELETE'])
def sunarp_eliminar_placa(placa):
    """Elimina lógicamente una placa SUNARP (soft delete)"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            cur.execute("""
                UPDATE sunarp_vehiculos 
                SET deleted_at = CURRENT_TIMESTAMP 
                WHERE placa = %s AND deleted_at IS NULL
            """, (placa,))
            mysql.connection.commit()
            filas_afectadas = cur.rowcount
            cur.close()
            
            if filas_afectadas > 0:
                return jsonify({
                    'success': True,
                    'message': f'Placa {placa} eliminada lógicamente de SUNARP'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': f'Placa {placa} no encontrada en SUNARP'
                }), 404
    except Exception as e:
        # Intentar crear la tabla si no existe
        if "doesn't exist" in str(e):
            crear_tablas_mysql()
            return jsonify({
                'success': False,
                'error': f'Placa {placa} no encontrada en SUNARP (tabla recién creada)'
            }), 404
        return jsonify({
            'success': False,
            'error': f'Error eliminando placa SUNARP: {str(e)}'
        }), 500

@app.route('/sunarp/estadisticas', methods=['GET'])
def sunarp_obtener_estadisticas():
    """Obtiene estadísticas de la base de datos SUNARP"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            
            # Totales
            cur.execute("SELECT COUNT(*) as total FROM sunarp_vehiculos WHERE deleted_at IS NULL")
            total = cur.fetchone()['total']
            
            # Por marca
            cur.execute("""
                SELECT marca, COUNT(*) as cantidad 
                FROM sunarp_vehiculos 
                WHERE deleted_at IS NULL AND marca != ''
                GROUP BY marca 
                ORDER BY cantidad DESC 
                LIMIT 10
            """)
            por_marca = cur.fetchall()
            
            # Por estado
            cur.execute("""
                SELECT estado, COUNT(*) as cantidad 
                FROM sunarp_vehiculos 
                WHERE deleted_at IS NULL AND estado != ''
                GROUP BY estado 
                ORDER BY cantidad DESC
            """)
            por_estado = cur.fetchall()
            
            cur.close()
            
            return jsonify({
                'success': True,
                'estadisticas': {
                    'total_placas': total,
                    'por_marca': por_marca,
                    'por_estado': por_estado
                }
            })
    except Exception as e:
        # Intentar crear la tabla si no existe
        if "doesn't exist" in str(e):
            crear_tablas_mysql()
            return jsonify({
                'success': True,
                'estadisticas': {
                    'total_placas': 0,
                    'por_marca': [],
                    'por_estado': []
                },
                'message': 'Tabla creada, no hay estadísticas aún'
            })
        return jsonify({
            'success': False,
            'error': f'Error obteniendo estadísticas SUNARP: {str(e)}'
        }), 500

# --- ENDPOINTS SCPPP ---
@app.route('/scppp/consultar', methods=['POST'])
def scppp_consultar():
    """Endpoint principal para consultar en el SCPPP"""
    try:
        data = request.json
        
        if not data or 'valor' not in data:
            return jsonify({
                'success': False,
                'error': 'Se requiere el parámetro "valor" (licencia o DNI)'
            }), 400
        
        valor = data['valor']
        tipo = data.get('tipo', '1')  # 1=Licencia, 0=Documento
        
        # Ejecutar consulta SCPPP
        resultado = consultar_scppp(valor, tipo)
        
        if resultado['success']:
            return jsonify({
                'success': True,
                'message': 'Consulta SCPPP realizada y guardada en base de datos',
                'valor': valor,
                'datos': resultado['datos'],
                'base_datos': resultado['base_datos']
            }), 200
        else:
            return jsonify({
                'success': False,
                'error': resultado.get('error', 'Error desconocido en SCPPP'),
                'valor': valor
            }), 500
        
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error interno SCPPP: {str(e)}'
        }), 500

@app.route('/scppp/conductores', methods=['GET'])
def scppp_listar_conductores():
    """Lista todos los conductores registrados en SCPPP"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            offset = (page - 1) * per_page
            
            cur.execute("SELECT COUNT(*) as total FROM scppp_conductores WHERE deleted_at IS NULL")
            total = cur.fetchone()['total']
            
            cur.execute("""
                SELECT id, licencia_dni, estado_licencia, nombre_completo, dni, 
                       licencia, clase_categoria, vigencia, papeletas_estado,
                       papeletas_cantidad, consultas_realizadas,
                       created_at, updated_at
                FROM scppp_conductores 
                WHERE deleted_at IS NULL 
                ORDER BY updated_at DESC
                LIMIT %s OFFSET %s
            """, (per_page, offset))
            conductores = cur.fetchall()
            
            cur.close()
            
            return jsonify({
                'success': True,
                'total': total,
                'page': page,
                'per_page': per_page,
                'total_pages': (total + per_page - 1) // per_page,
                'conductores': conductores
            })
    except Exception as e:
        # Intentar crear la tabla si no existe
        if "doesn't exist" in str(e):
            crear_tablas_mysql()
            return jsonify({
                'success': True,
                'total': 0,
                'page': 1,
                'per_page': 20,
                'total_pages': 0,
                'conductores': [],
                'message': 'Tabla creada, no hay registros aún'
            })
        return jsonify({
            'success': False,
            'error': f'Error obteniendo conductores SCPPP: {str(e)}'
        }), 500

@app.route('/scppp/conductores/<licencia_dni>', methods=['GET'])
def scppp_obtener_conductor(licencia_dni):
    """Obtiene información específica de un conductor SCPPP"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            cur.execute("""
                SELECT id, licencia_dni, estado_licencia, nombre_completo, dni, 
                       licencia, clase_categoria, vigencia, papeletas_estado,
                       papeletas_cantidad, consultas_realizadas,
                       created_at, updated_at
                FROM scppp_conductores 
                WHERE licencia_dni = %s AND deleted_at IS NULL
            """, (licencia_dni,))
            conductor_info = cur.fetchone()
            cur.close()
            
            if conductor_info:
                return jsonify({
                    'success': True,
                    'conductor': conductor_info
                })
            else:
                return jsonify({
                    'success': False,
                    'error': f'Conductor {licencia_dni} no encontrado en SCPPP'
                }), 404
    except Exception as e:
        # Intentar crear la tabla si no existe
        if "doesn't exist" in str(e):
            crear_tablas_mysql()
            return jsonify({
                'success': False,
                'error': f'Conductor {licencia_dni} no encontrado en SCPPP (tabla recién creada)'
            }), 404
        return jsonify({
            'success': False,
            'error': f'Error obteniendo conductor SCPPP: {str(e)}'
        }), 500

@app.route('/scppp/conductores/<licencia_dni>', methods=['DELETE'])
def scppp_eliminar_conductor(licencia_dni):
    """Elimina lógicamente un conductor SCPPP (soft delete)"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            cur.execute("""
                UPDATE scppp_conductores 
                SET deleted_at = CURRENT_TIMESTAMP 
                WHERE licencia_dni = %s AND deleted_at IS NULL
            """, (licencia_dni,))
            mysql.connection.commit()
            filas_afectadas = cur.rowcount
            cur.close()
            
            if filas_afectadas > 0:
                return jsonify({
                    'success': True,
                    'message': f'Conductor {licencia_dni} eliminado lógicamente de SCPPP'
                })
            else:
                return jsonify({
                    'success': False,
                    'error': f'Conductor {licencia_dni} no encontrado en SCPPP'
                }), 404
    except Exception as e:
        # Intentar crear la tabla si no existe
        if "doesn't exist" in str(e):
            crear_tablas_mysql()
            return jsonify({
                'success': False,
                'error': f'Conductor {licencia_dni} no encontrado en SCPPP (tabla recién creada)'
            }), 404
        return jsonify({
            'success': False,
            'error': f'Error eliminando conductor SCPPP: {str(e)}'
        }), 500

@app.route('/scppp/estadisticas', methods=['GET'])
def scppp_obtener_estadisticas():
    """Obtiene estadísticas de la base de datos SCPPP"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            
            # Total de conductores
            cur.execute("SELECT COUNT(*) as total FROM scppp_conductores WHERE deleted_at IS NULL")
            total = cur.fetchone()['total']
            
            # Por estado de licencia
            cur.execute("""
                SELECT estado_licencia, COUNT(*) as cantidad 
                FROM scppp_conductores 
                WHERE deleted_at IS NULL 
                GROUP BY estado_licencia
            """)
            por_estado = cur.fetchall()
            
            # Por estado de papeletas
            cur.execute("""
                SELECT papeletas_estado, COUNT(*) as cantidad 
                FROM scppp_conductores 
                WHERE deleted_at IS NULL 
                GROUP BY papeletas_estado
            """)
            por_papeletas = cur.fetchall()
            
            # Últimas consultas
            cur.execute("""
                SELECT licencia_dni, estado_licencia, updated_at 
                FROM scppp_conductores 
                WHERE deleted_at IS NULL 
                ORDER BY updated_at DESC 
                LIMIT 10
            """)
            ultimas = cur.fetchall()
            
            cur.close()
            
            return jsonify({
                'success': True,
                'estadisticas': {
                    'total_conductores': total,
                    'por_estado_licencia': por_estado,
                    'por_estado_papeletas': por_papeletas,
                    'ultimas_consultas': ultimas
                }
            })
    except Exception as e:
        # Intentar crear la tabla si no existe
        if "doesn't exist" in str(e):
            crear_tablas_mysql()
            return jsonify({
                'success': True,
                'estadisticas': {
                    'total_conductores': 0,
                    'por_estado_licencia': [],
                    'por_estado_papeletas': [],
                    'ultimas_consultas': []
                },
                'message': 'Tabla creada, no hay estadísticas aún'
            })
        return jsonify({
            'success': False,
            'error': f'Error obteniendo estadísticas SCPPP: {str(e)}'
        }), 500

# --- ENDPOINTS COMUNES ---
@app.route('/estado', methods=['GET'])
def estado():
    """Endpoint para verificar estado del servicio completo"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            
            # SUNARP
            cur.execute("SELECT COUNT(*) as total_sunarp FROM sunarp_vehiculos WHERE deleted_at IS NULL")
            total_sunarp = cur.fetchone()['total_sunarp']
            
            # SCPPP
            cur.execute("SELECT COUNT(*) as total_scppp FROM scppp_conductores WHERE deleted_at IS NULL")
            total_scppp = cur.fetchone()['total_scppp']
            
            cur.close()
            
            return jsonify({
                'success': True,
                'estado': 'online',
                'servicio': 'API Combinada SUNARP + SCPPP',
                'base_datos': 'conectada',
                'estadisticas': {
                    'sunarp_total_vehiculos': total_sunarp,
                    'scppp_total_conductores': total_scppp,
                    'total_registros': total_sunarp + total_scppp
                },
                'apis': {
                    'gemini': 'configurada',
                    'easyocr': 'listo'
                },
                'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            })
    except Exception as e:
        # Si hay error, intentar crear las tablas
        crear_tablas_mysql()
        return jsonify({
            'success': True,
            'estado': 'online',
            'servicio': 'API Combinada SUNARP + SCPPP',
            'base_datos': f'error: {str(e)} - Tablas recreadas',
            'apis': {
                'gemini': 'configurada',
                'easyocr': 'listo'
            },
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

# ==============================================
# SECCIÓN 6: INICIALIZACIÓN DEL SERVIDOR
# ==============================================

# Crear tablas al inicio
print("🔧 Creando tablas en la base de datos...")
crear_tablas_mysql()

if __name__ == "__main__":
    print("🚀 Iniciando servidor Flask API Combinada SUNARP + SCPPP...")
    print("📌 Endpoints SUNARP disponibles:")
    print("   POST /sunarp/consultar      - Consultar vehículo en SUNARP")
    print("   GET  /sunarp/placas         - Listar todas las placas SUNARP")
    print("   GET  /sunarp/placas/<placa> - Obtener placa específica SUNARP")
    print("   DELETE /sunarp/placas/<placa> - Eliminar placa SUNARP")
    print("   GET  /sunarp/estadisticas   - Estadísticas SUNARP")
    print("\n📌 Endpoints SCPPP disponibles:")
    print("   POST /scppp/consultar           - Consultar conductor en SCPPP")
    print("   GET  /scppp/conductores         - Listar todos los conductores SCPPP")
    print("   GET  /scppp/conductores/<id>    - Obtener conductor específico SCPPP")
    print("   DELETE /scppp/conductores/<id>  - Eliminar conductor SCPPP")
    print("   GET  /scppp/estadisticas        - Estadísticas SCPPP")
    print("\n📌 Endpoints comunes:")
    print("   GET  /estado                   - Estado del servicio completo")
    print(f"\n🔗 Servidor en: http://localhost:5000")
    
    app.run(debug=True, host='0.0.0.0', port=5000)