from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import sqlite3
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
import json
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    print("python-dotenv no está disponible, usando variables de entorno del sistema")

try:
    import requests
except ImportError:
    print("requests no está disponible, instalando...")
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests==2.31.0"])
    import requests

try:
    import PyPDF2
except ImportError:
    print("PyPDF2 no está disponible, instalando...")
    import subprocess
    import sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "PyPDF2==3.0.1"])
    import PyPDF2

import logging

# Cargar variables de entorno

app = Flask(__name__, static_folder='static')
app.config['UPLOAD_FOLDER'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'data/uploads')
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB máximo
app.secret_key = os.urandom(24)

# Configurar logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Crear directorios necesarios
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs('data', exist_ok=True)

# Configuración básica completada
print("Aplicación inicializada correctamente")

# Configuración de OpenRouter (adaptado del ejemplo PyQt5)
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODEL_NAME = "x-ai/grok-4.1-fast:free"
API_URL = "https://openrouter.ai/api/v1/chat/completions"

# Configuración de la base de datos
def init_db():
    conn = sqlite3.connect('data/database.sqlite')
    c = conn.cursor()
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS pdf_files (
            id TEXT PRIMARY KEY,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS pdf_content (
            id TEXT PRIMARY KEY,
            pdf_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            text_content TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pdf_id) REFERENCES pdf_files(id) ON DELETE CASCADE
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS pdf_images (
            id TEXT PRIMARY KEY,
            pdf_id TEXT NOT NULL,
            page_number INTEGER NOT NULL,
            image_name TEXT NOT NULL,
            image_path TEXT NOT NULL,
            image_description TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (pdf_id) REFERENCES pdf_files(id) ON DELETE CASCADE
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS chat_sessions (
            id TEXT PRIMARY KEY,
            title TEXT,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    c.execute('''
        CREATE TABLE IF NOT EXISTS messages (
            id TEXT PRIMARY KEY,
            session_id TEXT NOT NULL,
            role TEXT NOT NULL,
            content TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (session_id) REFERENCES chat_sessions(id) ON DELETE CASCADE
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def get_db():
    conn = sqlite3.connect('data/database.sqlite')
    conn.row_factory = sqlite3.Row
    return conn

def procesar_respuesta_con_imagenes(respuesta_grok, imagenes_pdfs):
    """
    Post-procesa la respuesta de Grok para insertar automáticamente 
    las imágenes cuando menciona páginas específicas del PDF
    """
    import re
    
    if not imagenes_pdfs:
        return respuesta_grok
    
    respuesta_final = respuesta_grok
    
    # Detectar menciones de páginas en la respuesta de Grok
    patrones_pagina = [
        r'[Pp]ágina\s*(\d+)',
        r'[Pp]ág\.\s*(\d+)', 
        r'[Pp]age\s*(\d+)',
        r'[Pp]ortada',  # Para página 1
        r'primera\s+página',  # Para página 1
    ]
    
    # Crear un mapa de imágenes por página
    imagenes_por_pagina = {}
    for img in imagenes_pdfs:
        if img['image_name'] and img['page_number']:
            pagina = img['page_number']
            imagen_url = f"https://prueba-7-tr52.onrender.com/api/imagen/{img['pdf_id']}/{img['image_name']}"
            imagenes_por_pagina[pagina] = imagen_url
    
    # Buscar menciones de páginas y agregar imágenes
    for patron in patrones_pagina:
        matches = re.finditer(patron, respuesta_final, re.IGNORECASE)
        
        for match in matches:
            if 'portada' in match.group().lower() or 'primera' in match.group().lower():
                pagina_num = 1
            else:
                try:
                    pagina_num = int(match.group(1))
                except (IndexError, ValueError):
                    continue
            
            # Si tenemos imagen para esta página, insertarla después de la mención
            if pagina_num in imagenes_por_pagina:
                imagen_url = imagenes_por_pagina[pagina_num]
                imagen_markdown = f"\n\n![Página {pagina_num} del PDF]({imagen_url})\n\n"
                
                # Insertar la imagen después de la mención de la página
                pos_final = match.end()
                respuesta_final = (respuesta_final[:pos_final] + 
                                 imagen_markdown + 
                                 respuesta_final[pos_final:])
                break  # Solo insertar una vez por página
    
    # Si la respuesta menciona "imágenes" o "mostrar" y no se insertó ninguna, agregar todas
    if (('imagen' in respuesta_final.lower() or 'mostrar' in respuesta_final.lower() or 
         'ver' in respuesta_final.lower()) and 
        '![Página' not in respuesta_final):
        
        respuesta_final += "\n\n### 📄 **Páginas del PDF:**\n"
        for pagina, imagen_url in sorted(imagenes_por_pagina.items()):
            respuesta_final += f"\n![Página {pagina} del PDF]({imagen_url})\n"
    
    return respuesta_final

def procesar_pdf_completo(pdf_id, ruta_archivo):
    """Procesa un PDF extrayendo texto e imágenes usando PyPDF2 y pdf2image"""
    try:
        conn = get_db()
        c = conn.cursor()
        
        # Crear directorio para imágenes del PDF
        images_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'images', pdf_id)
        os.makedirs(images_dir, exist_ok=True)
        
        # Extraer texto con PyPDF2
        with open(ruta_archivo, 'rb') as file:
            pdf_reader = PyPDF2.PdfReader(file)
            
            for page_num in range(min(5, len(pdf_reader.pages))):  # Primeras 5 páginas
                page = pdf_reader.pages[page_num]
                
                # Extraer texto de la página
                texto_pagina = page.extract_text()
                if texto_pagina.strip():
                    content_id = str(uuid.uuid4())
                    c.execute('''
                        INSERT INTO pdf_content (id, pdf_id, page_number, text_content)
                        VALUES (?, ?, ?, ?)
                    ''', (content_id, pdf_id, page_num + 1, texto_pagina))
                    
                    print(f"Página {page_num + 1}: {len(texto_pagina)} caracteres extraídos")
        
        # Las imágenes ya están en la base de datos (creadas localmente)
        # Solo usamos las que ya existen
        
        conn.commit()
        conn.close()
        
        return True
        
    except Exception as e:
        print(f"Error procesando PDF: {e}")
        return False

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/subir-pdf', methods=['POST'])
def subir_pdf():
    if 'archivo' not in request.files:
        return jsonify({'error': 'No se proporcionó ningún archivo'}), 400
    
    archivo = request.files['archivo']
    if archivo.filename == '':
        return jsonify({'error': 'No se seleccionó ningún archivo'}), 400
    
    if not archivo.filename.endswith('.pdf'):
        return jsonify({'error': 'El archivo debe ser un PDF'}), 400
    
    pdf_id = str(uuid.uuid4())
    nombre_archivo = secure_filename(archivo.filename)
    ruta_archivo = os.path.join(app.config['UPLOAD_FOLDER'], f'{pdf_id}_{nombre_archivo}')
    archivo.save(ruta_archivo)
    
    try:
        conn = get_db()
        c = conn.cursor()
        
        c.execute('''
            INSERT INTO pdf_files (id, filename, file_path)
            VALUES (?, ?, ?)
        ''', (pdf_id, nombre_archivo, ruta_archivo))
        
        conn.commit()
        conn.close()
        
        # Procesar PDF para extraer texto e imágenes
        procesado_exitoso = procesar_pdf_completo(pdf_id, ruta_archivo)
        
        return jsonify({
            'exito': True,
            'pdfId': pdf_id,
            'nombreArchivo': nombre_archivo,
            'procesado': procesado_exitoso
        })
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/api/chat', methods=['POST'])
def chat():
    datos = request.json
    mensaje = datos.get('mensaje')
    id_sesion = datos.get('idSesion')
    
    if not mensaje:
        return jsonify({'error': 'Se requiere un mensaje'}), 400
    
    conn = get_db()
    c = conn.cursor()
    
    # Crear sesión si no existe
    if not id_sesion:
        id_sesion = str(uuid.uuid4())
        c.execute('''
            INSERT INTO chat_sessions (id, title, created_at, updated_at)
            VALUES (?, ?, ?, ?)
        ''', (id_sesion, mensaje[:50], datetime.now().isoformat(), datetime.now().isoformat()))
    
    # Guardar mensaje del usuario
    id_mensaje = str(uuid.uuid4())
    c.execute('''
        INSERT INTO messages (id, session_id, role, content, created_at)
        VALUES (?, ?, ?, ?, ?)
    ''', (id_mensaje, id_sesion, 'usuario', mensaje, datetime.now().isoformat()))
    
    # Obtener historial de la conversación
    c.execute('''
        SELECT role, content
        FROM messages
        WHERE session_id = ?
        ORDER BY created_at ASC
    ''', (id_sesion,))
    
    # Mapear roles para compatibilidad con Grok
    historial = []
    for fila in c.fetchall():
        role = fila['role']
        # Convertir roles a formato compatible con Grok
        if role == 'usuario':
            role = 'user'
        elif role == 'asistente':
            role = 'assistant'
        historial.append({'role': role, 'content': fila['content']})
    
    # Obtener contenido de PDFs disponibles desde la base de datos
    c.execute('''
        SELECT pf.id as pdf_id, pf.filename, pc.page_number, pc.text_content 
        FROM pdf_files pf 
        LEFT JOIN pdf_content pc ON pf.id = pc.pdf_id 
        ORDER BY pf.uploaded_at DESC, pc.page_number ASC 
        LIMIT 20
    ''')
    contenido_pdfs = c.fetchall()
    
    # Obtener imágenes de PDFs disponibles
    c.execute('''
        SELECT pf.id as pdf_id, pf.filename, pi.page_number, pi.image_name, pi.image_description
        FROM pdf_files pf 
        LEFT JOIN pdf_images pi ON pf.id = pi.pdf_id 
        ORDER BY pf.uploaded_at DESC, pi.page_number ASC 
        LIMIT 10
    ''')
    imagenes_pdfs = c.fetchall()
    
    contexto_pdf = ""
    if contenido_pdfs:
        contexto_pdf = "\n\nContenido de PDFs procesados:\n"
        pdf_actual = None
        
        for fila in contenido_pdfs:
            if fila['filename'] != pdf_actual:
                pdf_actual = fila['filename']
                contexto_pdf += f"\n--- {pdf_actual} ---\n"
            
            if fila['text_content']:
                contexto_pdf += f"Página {fila['page_number']}: {fila['text_content'][:500]}...\n"
        
        # Agregar imágenes disponibles
        if imagenes_pdfs:
            contexto_pdf += "\n\nImágenes extraídas del PDF:\n"
            for img in imagenes_pdfs:
                if img['image_name']:
                    # Crear URL para la imagen
                    imagen_url = f"https://prueba-7-tr52.onrender.com/api/imagen/{img['pdf_id']}/{img['image_name']}"
                    descripcion = img['image_description'] or f"Página {img['page_number']}"
                    contexto_pdf += f"![{descripcion}]({imagen_url})\n"
        
        # Limitar el contexto total
        if len(contexto_pdf) > 4000:
            contexto_pdf = contexto_pdf[:4000] + "...\n"
    
    # Agregar contexto del PDF al primer mensaje si hay PDFs
    if contexto_pdf and historial:
        # Modificar el último mensaje del usuario para incluir contexto
        ultimo_mensaje = historial[-1]
        if ultimo_mensaje['role'] == 'user':
            ultimo_mensaje['content'] += contexto_pdf
    
    # Llamar a la API de OpenRouter
    try:
        print(f"API Key disponible: {bool(OPENROUTER_API_KEY)}")
        print(f"Modelo: {MODEL_NAME}")
        print(f"Historial: {historial}")
        
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json"
        }
        
        data = {
            "model": MODEL_NAME,
            "messages": historial,
            "temperature": 0.7,
            "max_tokens": 2000
        }
        
        print(f"Enviando petición a OpenRouter...")
        respuesta = requests.post(API_URL, headers=headers, json=data, timeout=30)
        print(f"Código de respuesta: {respuesta.status_code}")
        
        if respuesta.status_code != 200:
            print(f"Error en API: {respuesta.text}")
            respuesta_asistente = f"Error en la API: {respuesta.status_code} - {respuesta.text[:200]}"
        else:
            try:
                datos_respuesta = respuesta.json()
                print(f"Respuesta de API: {datos_respuesta}")
                if 'choices' in datos_respuesta and len(datos_respuesta['choices']) > 0:
                    respuesta_asistente = datos_respuesta['choices'][0]['message']['content']
                else:
                    respuesta_asistente = "No se pudo obtener una respuesta del asistente."
            except ValueError as ve:
                print(f"Error al parsear JSON: {ve}")
                respuesta_asistente = "Error al procesar la respuesta del asistente."
        
        # Post-procesar respuesta para insertar imágenes automáticamente
        respuesta_final = procesar_respuesta_con_imagenes(respuesta_asistente, imagenes_pdfs)
        
        # Guardar respuesta del asistente
        id_respuesta = str(uuid.uuid4())
        c.execute('''
            INSERT INTO messages (id, session_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (id_respuesta, id_sesion, 'asistente', respuesta_final, datetime.now().isoformat()))
        
        c.execute('''
            UPDATE chat_sessions
            SET updated_at = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), id_sesion))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'respuesta': respuesta_final,
            'idSesion': id_sesion
        })
    except Exception as e:
        print(f"Error en chat: {str(e)}")
        if 'conn' in locals():
            conn.close()
        return jsonify({'error': f'Error interno: {str(e)}'}), 500

@app.route('/api/historial', methods=['GET'])
def historial():
    id_sesion = request.args.get('idSesion')
    conn = get_db()
    c = conn.cursor()
    
    if id_sesion:
        c.execute('''
            SELECT id, role, content, created_at
            FROM messages
            WHERE session_id = ?
            ORDER BY created_at ASC
        ''', (id_sesion,))
        
        mensajes = [dict(fila) for fila in c.fetchall()]
        conn.close()
        return jsonify({'mensajes': mensajes})
    else:
        c.execute('SELECT id, title, created_at, updated_at FROM chat_sessions ORDER BY updated_at DESC')
        sesiones = [dict(fila) for fila in c.fetchall()]
        conn.close()
        return jsonify({'sesiones': sesiones})

@app.route('/api/debug-pdfs', methods=['GET'])
def debug_pdfs():
    """Ruta de debug para verificar PDFs procesados"""
    conn = get_db()
    c = conn.cursor()
    
    # Verificar PDFs subidos
    c.execute('SELECT * FROM pdf_files ORDER BY uploaded_at DESC')
    pdfs = [dict(fila) for fila in c.fetchall()]
    
    # Verificar contenido procesado
    c.execute('''
        SELECT pf.filename, pc.page_number, LENGTH(pc.text_content) as text_length
        FROM pdf_files pf 
        LEFT JOIN pdf_content pc ON pf.id = pc.pdf_id 
        ORDER BY pf.uploaded_at DESC, pc.page_number ASC
    ''')
    contenido = [dict(fila) for fila in c.fetchall()]
    
    # Verificar imágenes (si las hay)
    c.execute('SELECT * FROM pdf_images ORDER BY created_at DESC')
    imagenes = [dict(fila) for fila in c.fetchall()]
    
    conn.close()
    
    return jsonify({
        'pdfs_subidos': len(pdfs),
        'pdfs': pdfs,
        'contenido_procesado': len(contenido),
        'contenido': contenido,
        'imagenes': len(imagenes),
        'imagenes_detalle': imagenes
    })

@app.route('/api/imagen/<pdf_id>/<image_name>')
def servir_imagen(pdf_id, image_name):
    """Servir imágenes extraídas de PDFs"""
    try:
        images_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'images', pdf_id)
        return send_from_directory(images_dir, image_name)
    except Exception as e:
        return jsonify({'error': f'Imagen no encontrada: {str(e)}'}), 404

@app.route('/api/imagenes-disponibles', methods=['GET'])
def imagenes_disponibles():
    """Devolver lista de imágenes disponibles en la base de datos"""
    conn = get_db()
    c = conn.cursor()
    
    c.execute('''
        SELECT pf.id as pdf_id, pf.filename, pi.page_number, pi.image_name, pi.image_description
        FROM pdf_files pf 
        INNER JOIN pdf_images pi ON pf.id = pi.pdf_id 
        ORDER BY pf.uploaded_at DESC, pi.page_number ASC
    ''')
    imagenes = c.fetchall()
    
    conn.close()
    
    # Convertir a formato JSON amigable
    resultado = []
    for img in imagenes:
        resultado.append({
            'pdf_id': img['pdf_id'],
            'filename': img['filename'],
            'page_number': img['page_number'],
            'image_name': img['image_name'],
            'description': img['image_description'],
            'url': f"/api/imagen/{img['pdf_id']}/{img['image_name']}"
        })
    
    return jsonify(resultado)

if __name__ == '__main__':
    app.run(debug=True)