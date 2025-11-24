from flask import Flask, render_template, request, jsonify, send_from_directory
import os
import sqlite3
import uuid
from datetime import datetime
from werkzeug.utils import secure_filename
import json
from dotenv import load_dotenv
import requests
from sentence_transformers import SentenceTransformer
import PyPDF2
import logging

# Cargar variables de entorno
load_dotenv()

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

# Inicializar modelos
print("Cargando modelo de embeddings...")
embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
print("¡Modelo de embeddings cargado!")

# Configuración de OpenRouter
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
MODEL_NAME = "openai/gpt-3.5-turbo"
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
        
        return jsonify({
            'exito': True,
            'pdfId': pdf_id,
            'nombreArchivo': nombre_archivo
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
    
    historial = [{'role': fila['role'], 'content': fila['content']} for fila in c.fetchall()]
    
    # Llamar a la API de OpenRouter
    try:
        headers = {
            "Authorization": f"Bearer {OPENROUTER_API_KEY}",
            "Content-Type": "application/json",
            "HTTP-Referer": os.getenv('OPENROUTER_HTTP_REFERER', 'http://localhost:5000'),
            "X-Title": "Asistente de PDF",
        }
        
        data = {
            "model": MODEL_NAME,
            "messages": historial,
            "temperature": 0.7,
            "max_tokens": 1000
        }
        
        respuesta = requests.post(API_URL, headers=headers, json=data, timeout=30)
        respuesta.raise_for_status()
        
        try:
            datos_respuesta = respuesta.json()
            if 'choices' in datos_respuesta and len(datos_respuesta['choices']) > 0:
                respuesta_asistente = datos_respuesta['choices'][0]['message']['content']
            else:
                respuesta_asistente = "No se pudo obtener una respuesta del asistente."
        except ValueError:
            respuesta_asistente = "Error al procesar la respuesta del asistente."
        
        # Guardar respuesta del asistente
        id_respuesta = str(uuid.uuid4())
        c.execute('''
            INSERT INTO messages (id, session_id, role, content, created_at)
            VALUES (?, ?, ?, ?, ?)
        ''', (id_respuesta, id_sesion, 'asistente', respuesta_asistente, datetime.now().isoformat()))
        
        c.execute('''
            UPDATE chat_sessions
            SET updated_at = ?
            WHERE id = ?
        ''', (datetime.now().isoformat(), id_sesion))
        
        conn.commit()
        conn.close()
        
        return jsonify({
            'respuesta': respuesta_asistente,
            'idSesion': id_sesion
        })
    except Exception as e:
        if 'conn' in locals():
            conn.close()
        return jsonify({'error': str(e)}), 500

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

if __name__ == '__main__':
    app.run(debug=True)