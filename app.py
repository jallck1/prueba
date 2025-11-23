from flask import Flask, render_template_string, request
import os
from datetime import datetime

app = Flask(__name__)

# Respuestas del bot
RESPUESTAS = {
    "hola": "¡Hola! Soy tu asistente virtual. ¿En qué puedo ayudarte hoy?",
    "cómo estás": "¡Estoy funcionando al 100%! ¿Y tú, cómo estás?",
    "qué puedes hacer": "Puedo responder preguntas básicas, contar chistes, o simplemente charlar contigo.",
    "adiós": "¡Hasta luego! Fue un placer ayudarte.",
    "gracias": "¡De nada! Estoy aquí para ayudarte cuando lo necesites."
}

# Plantilla HTML con el diseño del chat
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>ChatBot Futurista</title>
    <style>
        :root {
            --primary: #00ff9d;
            --secondary: #1a1a2e;
            --accent: #7f5af0;
            --text: #e6f1ff;
            --bg: #0f0f1a;
        }
        
        * {
            margin: 0;
            padding: 0;
            box-sizing: border-box;
            font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
        }
        
        body {
            background-color: var(--bg);
            color: var(--text);
            min-height: 100vh;
            padding: 20px;
        }
        
        .container {
            max-width: 800px;
            margin: 0 auto;
            background: rgba(26, 26, 46, 0.5);
            border-radius: 15px;
            overflow: hidden;
            border: 1px solid rgba(255, 255, 255, 0.1);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.3);
        }
        
        header {
            background: linear-gradient(45deg, var(--accent), #a78bfa);
            padding: 20px;
            text-align: center;
            border-bottom: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        h1 {
            color: white;
            font-size: 1.8em;
            margin-bottom: 5px;
            text-shadow: 0 2px 5px rgba(0, 0, 0, 0.2);
        }
        
        .subtitle {
            color: rgba(255, 255, 255, 0.8);
            font-size: 0.9em;
        }
        
        .chat-container {
            padding: 20px;
            height: 60vh;
            overflow-y: auto;
            display: flex;
            flex-direction: column;
            gap: 15px;
        }
        
        .message {
            max-width: 80%;
            padding: 12px 18px;
            border-radius: 20px;
            position: relative;
            animation: fadeIn 0.3s ease-out;
            line-height: 1.5;
            box-shadow: 0 2px 5px rgba(0, 0, 0, 0.1);
        }
        
        @keyframes fadeIn {
            from { opacity: 0; transform: translateY(10px); }
            to { opacity: 1; transform: translateY(0); }
        }
        
        .bot-message {
            align-self: flex-start;
            background: rgba(127, 90, 240, 0.2);
            border-bottom-left-radius: 5px;
            color: var(--text);
            border: 1px solid var(--accent);
        }
        
        .user-message {
            align-self: flex-end;
            background: rgba(0, 255, 157, 0.1);
            border-bottom-right-radius: 5px;
            color: var(--primary);
            border: 1px solid var(--primary);
        }
        
        .message-time {
            font-size: 0.7em;
            opacity: 0.6;
            margin-top: 5px;
            text-align: right;
        }
        
        .input-container {
            display: flex;
            padding: 15px;
            background: rgba(15, 15, 26, 0.8);
            border-top: 1px solid rgba(255, 255, 255, 0.1);
        }
        
        form {
            display: flex;
            width: 100%;
            gap: 10px;
        }
        
        input[type="text"] {
            flex: 1;
            padding: 12px 20px;
            border: none;
            border-radius: 30px;
            background: rgba(255, 255, 255, 0.05);
            color: var(--text);
            font-size: 1em;
            outline: none;
            border: 1px solid rgba(255, 255, 255, 0.1);
            transition: all 0.3s ease;
        }
        
        input[type="text"]:focus {
            border-color: var(--primary);
            box-shadow: 0 0 15px rgba(0, 255, 157, 0.2);
        }
        
        button {
            background: linear-gradient(45deg, var(--accent), #a78bfa);
            border: none;
            width: 50px;
            height: 50px;
            border-radius: 50%;
            color: white;
            font-size: 1.2em;
            cursor: pointer;
            display: flex;
            align-items: center;
            justify-content: center;
            transition: all 0.3s ease;
            box-shadow: 0 5px 15px rgba(127, 90, 240, 0.3);
        }
        
        button:hover {
            transform: translateY(-2px);
            box-shadow: 0 7px 20px rgba(127, 90, 240, 0.4);
        }
        
        .suggestions {
            display: flex;
            gap: 10px;
            flex-wrap: wrap;
            padding: 0 15px 15px;
            background: rgba(15, 15, 26, 0.8);
        }
        
        .suggestion {
            background: rgba(127, 90, 240, 0.1);
            border: 1px solid var(--accent);
            color: var(--accent);
            padding: 8px 15px;
            border-radius: 20px;
            font-size: 0.9em;
            cursor: pointer;
            transition: all 0.2s ease;
        }
        
        .suggestion:hover {
            background: var(--accent);
            color: white;
        }
    </style>
</head>
<body>
    <div class="container">
        <header>
            <h1>Asistente Virtual</h1>
            <div class="subtitle">Estoy aquí para ayudarte</div>
        </header>
        
        <div class="chat-container">
            <div class="message bot-message">
                ¡Hola! Soy tu asistente virtual. ¿En qué puedo ayudarte hoy?
                <div class="message-time">Ahora</div>
            </div>
            
            {% if user_message %}
                <div class="message user-message">
                    {{ user_message }}
                    <div class="message-time">Tú - {{ time }}</div>
                </div>
                
                <div class="message bot-message">
                    {{ bot_response }}
                    <div class="message-time">Asistente - {{ time }}</div>
                </div>
            {% endif %}
        </div>
        
        <div class="suggestions">
            <a href="/chat?q=¿Cómo estás?" class="suggestion">¿Cómo estás?</a>
            <a href="/chat?q=¿Qué puedes hacer?" class="suggestion">¿Qué puedes hacer?</a>
            <a href="/chat?q=Gracias" class="suggestion">Gracias</a>
        </div>
        
        <div class="input-container">
            <form method="POST" action="/chat">
                <input type="text" name="user_message" placeholder="Escribe tu mensaje..." required>
                <button type="submit">→</button>
            </form>
        </div>
    </div>
</body>
</html>
"""

@app.route('/')
def home():
    return chat()

@app.route('/chat', methods=['GET', 'POST'])
def chat():
    if request.method == 'POST':
        user_message = request.form.get('user_message', '').lower()
    elif request.method == 'GET' and 'q' in request.args:
        user_message = request.args.get('q', '').lower()
    else:
        return render_template_string(HTML_TEMPLATE)
    
    bot_response = RESPUESTAS.get(user_message, "Lo siento, no entiendo esa pregunta. ¿Podrías reformularla?")
    time = datetime.now().strftime("%H:%M")
    
    return render_template_string(HTML_TEMPLATE, 
                               user_message=user_message,
                               bot_response=bot_response,
                               time=time)

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 10000))
    app.run(host='0.0.0.0', port=port, debug=False)