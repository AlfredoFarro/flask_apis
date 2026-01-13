# app_sunarp_flask.py - Versión optimizada (sin archivos JSON/TXT)
from flask import Flask, request, jsonify
from flask_mysqldb import MySQL
from datetime import datetime
import os
import time
import re
import google.generativeai as genai
from seleniumbase import SB
from PIL import Image

app = Flask(__name__)

# --- CONFIGURACIÓN MYSQL ---
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'root'  # Cambia por tu contraseña
app.config['MYSQL_DB'] = 'sunarp_db'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# --- CONFIGURACIÓN GEMINI API ---
GEMINI_API_KEY = "AIzaSyDQDKaaDFdVQrUvHs6sEhunwQJQqjnWLgM"

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

# --- CREAR TABLAS EN MYSQL ---
def crear_tablas_mysql():
    with app.app_context():
        try:
            cur = mysql.connection.cursor()
            
            # Tabla principal de vehículos (SUNARP)
            cur.execute('''CREATE TABLE IF NOT EXISTS placas (
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
            
            mysql.connection.commit()
            cur.close()
            print("✅ Tabla 'placas' creada/verificada")
        except Exception as e:
            print(f"❌ Error creando tabla: {e}")

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

# --- FUNCIÓN PARA GUARDAR EN BASE DE DATOS ---
def guardar_placa_en_db(placa: str, datos_parseados: dict):
    """Guarda o actualiza la placa en la base de datos"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            
            # Verificar si la placa ya existe
            cur.execute("SELECT id, consultas_realizadas FROM placas WHERE placa = %s AND deleted_at IS NULL", (placa,))
            registro = cur.fetchone()
            
            if registro:
                # Actualizar registro existente
                cur.execute('''UPDATE placas SET 
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
                cur.execute('''INSERT INTO placas (
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
            
            return {
                'success': True,
                'accion': accion,
                'placa_id': placa_id,
                'consultas_realizadas': consultas_realizadas,
                'placa': placa
            }
        
    except Exception as e:
        print(f"❌ Error guardando en DB: {e}")
        return {'success': False, 'error': str(e)}

# --- FUNCIÓN DE CONSULTA SUNARP (OPTIMIZADA) ---
def modo_undetected_directo_con_gemini(placa: str):
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
            screenshot_filename = f"temp_{placa}_{timestamp}.png"
            
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
            db_resultado = guardar_placa_en_db(placa, datos_parseados)
            
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
                sb.save_screenshot(f"error_{placa}_{timestamp}.png")
                print(f"📸 Screenshot del error guardado")
            except:
                pass
            
            return {"success": False, "error": str(e)}

# --- ENDPOINTS FLASK ---
@app.route('/consultar-sunarp', methods=['POST'])
def consultar_sunarp():
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
        resultado = modo_undetected_directo_con_gemini(placa)
        
        if resultado['success']:
            return jsonify({
                'success': True,
                'message': 'Consulta realizada exitosamente',
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

@app.route('/estado', methods=['GET'])
def estado():
    """Endpoint para verificar estado del servicio"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            cur.execute("SELECT COUNT(*) as total FROM placas WHERE deleted_at IS NULL")
            total_placas = cur.fetchone()['total']
            cur.close()
        
        return jsonify({
            'success': True,
            'estado': 'online',
            'servicio': 'SUNARP Consulta API',
            'base_datos': 'conectada',
            'total_placas': total_placas,
            'gemini_api': 'configurada',
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception as e:
        return jsonify({
            'success': True,
            'estado': 'online',
            'servicio': 'SUNARP Consulta API',
            'base_datos': f'error: {str(e)}',
            'gemini_api': 'configurada',
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

@app.route('/placas', methods=['GET'])
def listar_placas():
    """Lista todas las placas registradas"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            
            page = request.args.get('page', 1, type=int)
            per_page = request.args.get('per_page', 20, type=int)
            offset = (page - 1) * per_page
            
            cur.execute("SELECT COUNT(*) as total FROM placas WHERE deleted_at IS NULL")
            total = cur.fetchone()['total']
            
            cur.execute("""
                SELECT id, placa, marca, modelo, color, estado, 
                       numero_serie, numero_vin, numero_motor,
                       placa_vigente, placa_anterior, anotaciones,
                       consultas_realizadas, created_at, updated_at
                FROM placas 
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
        return jsonify({
            'success': False,
            'error': f'Error obteniendo placas: {str(e)}'
        }), 500

@app.route('/placas/<placa>', methods=['GET'])
def obtener_placa(placa):
    """Obtiene información específica de una placa"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            
            cur.execute("""
                SELECT id, placa, marca, modelo, color, estado, 
                       numero_serie, numero_vin, numero_motor,
                       placa_vigente, placa_anterior, anotaciones,
                       consultas_realizadas, created_at, updated_at
                FROM placas 
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
                'error': f'Placa {placa} no encontrada'
            }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error obteniendo placa: {str(e)}'
        }), 500

@app.route('/placas/<placa>', methods=['DELETE'])
def eliminar_placa(placa):
    """Elimina lógicamente una placa (soft delete)"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            cur.execute("""
                UPDATE placas 
                SET deleted_at = CURRENT_TIMESTAMP 
                WHERE placa = %s AND deleted_at IS NULL
            """, (placa,))
            mysql.connection.commit()
            filas_afectadas = cur.rowcount
            cur.close()
        
        if filas_afectadas > 0:
            return jsonify({
                'success': True,
                'message': f'Placa {placa} eliminada lógicamente'
            })
        else:
            return jsonify({
                'success': False,
                'error': f'Placa {placa} no encontrada'
            }), 404
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error eliminando placa: {str(e)}'
        }), 500

@app.route('/estadisticas', methods=['GET'])
def obtener_estadisticas():
    """Obtiene estadísticas de la base de datos"""
    try:
        with app.app_context():
            cur = mysql.connection.cursor()
            
            # Totales
            cur.execute("SELECT COUNT(*) as total FROM placas WHERE deleted_at IS NULL")
            total = cur.fetchone()['total']
            
            # Por marca
            cur.execute("""
                SELECT marca, COUNT(*) as cantidad 
                FROM placas 
                WHERE deleted_at IS NULL AND marca != ''
                GROUP BY marca 
                ORDER BY cantidad DESC 
                LIMIT 10
            """)
            por_marca = cur.fetchall()
            
            # Por estado
            cur.execute("""
                SELECT estado, COUNT(*) as cantidad 
                FROM placas 
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
        return jsonify({
            'success': False,
            'error': f'Error obteniendo estadísticas: {str(e)}'
        }), 500

# --- ANTES DE INICIAR EL SERVIDOR, CREAR LAS TABLAS ---
with app.app_context():
    try:
        crear_tablas_mysql()
    except Exception as e:
        print(f"⚠️ Advertencia: No se pudo crear la tabla al inicio: {e}")
        print("⚠️ La tabla se intentará crear cuando se haga la primera consulta")

if __name__ == "__main__":
    print("🚀 Iniciando servidor Flask SUNARP API...")
    print("📌 Endpoints disponibles:")
    print("   POST /consultar-sunarp - Consultar vehículo en SUNARP")
    print("   GET  /estado          - Estado del servicio")
    print("   GET  /placas          - Listar todas las placas")
    print("   GET  /placas/<placa>  - Obtener placa específica")
    print("   DELETE /placas/<placa> - Eliminar placa (soft delete)")
    print("   GET  /estadisticas    - Estadísticas de la base de datos")
    print(f"🔗 Servidor en: http://localhost:5000")
    
    app.run(debug=True, host='0.0.0.0', port=5000)