# app_flask_mysql.py
from flask import Flask, request, jsonify
from flask_mysqldb import MySQL
from datetime import datetime
import requests
import easyocr
from PIL import Image
from io import BytesIO
from bs4 import BeautifulSoup
import urllib3 
import numpy as np
import re

app = Flask(__name__)

# --- CONFIGURACIÓN MYSQL ---
app.config['MYSQL_HOST'] = 'localhost'
app.config['MYSQL_USER'] = 'root'
app.config['MYSQL_PASSWORD'] = 'root'  # Cambia por tu contraseña
app.config['MYSQL_DB'] = 'scppp_db'
app.config['MYSQL_CURSORCLASS'] = 'DictCursor'

mysql = MySQL(app)

# --- CONFIGURACIÓN SCPPP ---
URL_BASE = "https://scppp.mtc.gob.pe/"

# Inicializar EasyOCR (solo una vez)
print("🔧 Inicializando EasyOCR...")
reader = easyocr.Reader(['en'], gpu=False)
print("✅ EasyOCR listo\n")

# Deshabilitar advertencias SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Crear tabla si no existe
def crear_tabla_placas():
    try:
        cur = mysql.connection.cursor()
        cur.execute('''CREATE TABLE IF NOT EXISTS placas (
            id INT AUTO_INCREMENT PRIMARY KEY,
            placa VARCHAR(20) NOT NULL UNIQUE,
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
            INDEX idx_placa (placa),
            INDEX idx_estado (estado_licencia)
        )''')
        mysql.connection.commit()
        cur.close()
        print("✅ Tabla 'placas' creada/verificada")
    except Exception as e:
        print(f"❌ Error creando tabla: {e}")

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

def analizar_resultados_completos(html_content, valor_consultado):
    """Analiza exhaustivamente los resultados de la consulta"""
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

def guardar_en_db(placa, resultado):
    """Guarda o actualiza la información en la base de datos"""
    try:
        cur = mysql.connection.cursor()
        
        # Verificar si la placa ya existe
        cur.execute("SELECT id, consultas_realizadas FROM placas WHERE placa = %s AND deleted_at IS NULL", (placa,))
        registro = cur.fetchone()
        
        datos_personales = resultado['datos_personales']
        papeletas = resultado['papeletas']
        
        if registro:
            # Actualizar registro existente
            cur.execute('''UPDATE placas SET 
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
                WHERE placa = %s AND deleted_at IS NULL''',
                (
                    datos_personales.get('estado_licencia'),
                    datos_personales.get('nombre_completo'),
                    datos_personales.get('dni'),
                    datos_personales.get('licencia'),
                    datos_personales.get('clase_categoria'),
                    datos_personales.get('vigencia'),
                    papeletas.get('estado'),
                    papeletas.get('cantidad', 0),
                    placa
                ))
            accion = "actualizado"
            consultas_realizadas = registro['consultas_realizadas'] + 1
            placa_id = registro['id']
        else:
            # Insertar nuevo registro
            cur.execute('''INSERT INTO placas (
                placa, estado_licencia, nombre_completo, dni, licencia, 
                clase_categoria, vigencia, papeletas_estado, papeletas_cantidad
            ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)''',
                (
                    placa,
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
            placa_id = cur.lastrowid
        
        mysql.connection.commit()
        cur.close()
        
        print(f"✅ Registro {accion} en la base de datos")
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
        print(f"❌ Error guardando en DB: {e}")
        return {'success': False, 'error': str(e)}

@app.route('/consultar', methods=['POST'])
def consultar():
    """Endpoint principal para consultar en el SCPPP y guardar en DB"""
    try:
        # Obtener datos del request
        data = request.json
        
        if not data or 'valor' not in data:
            return jsonify({
                'success': False,
                'error': 'Se requiere el parámetro "valor" (licencia o DNI)'
            }), 400
        
        valor = data['valor']
        tipo = data.get('tipo', '1')  # 1=Licencia, 0=Documento
        
        print(f"🚀 Iniciando consulta para: {valor} (tipo: {tipo})")
        
        session = requests.Session()
        
        # PASO 1: Obtener página inicial
        print(f"🔍 PASO 1: Cargando página inicial...")
        response = session.get(URL_BASE, timeout=15, verify=False)
        
        if response.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'Error al cargar página: {response.status_code}'
            }), 500

        soup = BeautifulSoup(response.text, 'html.parser')
        form_data = extraer_campos_formulario(soup)
        
        if '__VIEWSTATE' not in form_data:
            return jsonify({
                'success': False,
                'error': 'No se encontró VIEWSTATE'
            }), 500
        
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
            'Referer': URL_BASE,
            'Origin': URL_BASE.rstrip('/')
        }
        
        response2 = session.post(URL_BASE, data=form_data, headers=headers, verify=False)
        
        if response2.status_code != 200:
            return jsonify({
                'success': False,
                'error': f'Error en cambio de opción: {response2.status_code}'
            }), 500
        
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
        url_captcha = URL_BASE + "Captcha.aspx"
        resp_img = session.get(url_captcha, verify=False)
        
        if resp_img.status_code != 200:
            return jsonify({
                'success': False,
                'error': 'Error descargando CAPTCHA'
            }), 500
        
        print("🤖 Resolviendo CAPTCHA con EasyOCR...")
        texto_captcha = obtener_texto_con_easyocr(resp_img.content)
        
        if not texto_captcha:
            return jsonify({
                'success': False,
                'error': 'Error resolviendo CAPTCHA'
            }), 500
        
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
        
        final_response = session.post(URL_BASE, data=search_data, headers=headers, verify=False, timeout=30)
        
        print(f"\n{'='*70}")
        print(f"📊 Status Code: {final_response.status_code}")
        print(f"📏 Respuesta: {len(final_response.text)} bytes")
        print(f"{'='*70}")
        
        if final_response.status_code == 500:
            return jsonify({
                'success': False,
                'error': 'Error 500 del servidor'
            }), 500
        
        if final_response.status_code == 200:
            print("\n✅ CONSULTA EXITOSA")
            resultado = analizar_resultados_completos(final_response.text, valor)
            
            # Guardar en base de datos
            db_resultado = guardar_en_db(valor, resultado)
            
            if db_resultado['success']:
                return jsonify({
                    'success': True,
                    'message': 'Consulta realizada y guardada en base de datos',
                    'placa': valor,
                    'datos': resultado,
                    'base_datos': db_resultado
                }), 200
            else:
                return jsonify({
                    'success': False,
                    'error': f'Error guardando en base de datos: {db_resultado.get("error", "Error desconocido")}'
                }), 500
        else:
            return jsonify({
                'success': False,
                'error': f'Error en la consulta: {final_response.status_code}'
            }), 500
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()
        
        return jsonify({
            'success': False,
            'error': f'Error interno: {str(e)}'
        }), 500

@app.route('/estado', methods=['GET'])
def estado():
    """Endpoint para verificar estado del servicio y DB"""
    try:
        cur = mysql.connection.cursor()
        cur.execute("SELECT COUNT(*) as total FROM placas WHERE deleted_at IS NULL")
        total_placas = cur.fetchone()['total']
        cur.close()
        
        return jsonify({
            'success': True,
            'estado': 'online',
            'servicio': 'SCPPP Consulta API',
            'base_datos': 'conectada',
            'total_placas': total_placas,
            'easyocr': 'listo',
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })
    except Exception as e:
        return jsonify({
            'success': True,
            'estado': 'online',
            'servicio': 'SCPPP Consulta API',
            'base_datos': f'error: {str(e)}',
            'easyocr': 'listo',
            'timestamp': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        })

@app.route('/placas', methods=['GET'])
def listar_placas():
    """Lista todas las placas registradas"""
    try:
        cur = mysql.connection.cursor()
        
        page = request.args.get('page', 1, type=int)
        per_page = request.args.get('per_page', 20, type=int)
        offset = (page - 1) * per_page
        
        cur.execute("SELECT COUNT(*) as total FROM placas WHERE deleted_at IS NULL")
        total = cur.fetchone()['total']
        
        cur.execute("""
            SELECT id, placa, estado_licencia, nombre_completo, dni, 
                   licencia, clase_categoria, vigencia, papeletas_estado,
                   papeletas_cantidad, consultas_realizadas,
                   created_at, updated_at
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
        cur = mysql.connection.cursor()
        cur.execute("""
            SELECT id, placa, estado_licencia, nombre_completo, dni, 
                   licencia, clase_categoria, vigencia, papeletas_estado,
                   papeletas_cantidad, consultas_realizadas,
                   created_at, updated_at
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
        cur = mysql.connection.cursor()
        
        # Total de placas
        cur.execute("SELECT COUNT(*) as total FROM placas WHERE deleted_at IS NULL")
        total = cur.fetchone()['total']
        
        # Por estado de licencia
        cur.execute("""
            SELECT estado_licencia, COUNT(*) as cantidad 
            FROM placas 
            WHERE deleted_at IS NULL 
            GROUP BY estado_licencia
        """)
        por_estado = cur.fetchall()
        
        # Por estado de papeletas
        cur.execute("""
            SELECT papeletas_estado, COUNT(*) as cantidad 
            FROM placas 
            WHERE deleted_at IS NULL 
            GROUP BY papeletas_estado
        """)
        por_papeletas = cur.fetchall()
        
        # Últimas consultas
        cur.execute("""
            SELECT placa, estado_licencia, updated_at 
            FROM placas 
            WHERE deleted_at IS NULL 
            ORDER BY updated_at DESC 
            LIMIT 10
        """)
        ultimas = cur.fetchall()
        
        cur.close()
        
        return jsonify({
            'success': True,
            'estadisticas': {
                'total_placas': total,
                'por_estado_licencia': por_estado,
                'por_estado_papeletas': por_papeletas,
                'ultimas_consultas': ultimas
            }
        })
    except Exception as e:
        return jsonify({
            'success': False,
            'error': f'Error obteniendo estadísticas: {str(e)}'
        }), 500

if __name__ == "__main__":
    # Crear tabla al iniciar (con app context)
    with app.app_context():
        crear_tabla_placas()
    
    print("🚀 Iniciando servidor Flask API con MySQL...")
    print("📌 Endpoints disponibles:")
    print("   POST /consultar    - Consultar y guardar en DB")
    print("   GET  /estado       - Estado del servicio y DB")
    print("   GET  /placas       - Listar todas las placas")
    print("   GET  /placas/<placa> - Obtener placa específica")
    print("   DELETE /placas/<placa> - Eliminar placa (soft delete)")
    print("   GET  /estadisticas - Estadísticas de la base de datos")
    print(f"🔗 Servidor en: http://localhost:5000")
    
    app.run(debug=True, host='0.0.0.0', port=5000)