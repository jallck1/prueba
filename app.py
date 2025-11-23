from flask import Flask, render_template_string

app = Flask(__name__)

# HTML simple para la página principal
HTML_TEMPLATE = """
<!DOCTYPE html>
<html>
<head>
    <title>Aplicación de Prueba</title>
    <style>
        body {
            font-family: Arial, sans-serif;
            max-width: 800px;
            margin: 0 auto;
            padding: 20px;
            background-color: #f5f5f5;
        }
        .container {
            background-color: white;
            padding: 30px;
            border-radius: 8px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            text-align: center;
        }
        h1 {
            color: #2c3e50;
        }
        .status {
            background-color: #4CAF50;
            color: white;
            padding: 10px 20px;
            border-radius: 20px;
            display: inline-block;
            margin: 20px 0;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>¡Aplicación Flask en Render!</h1>
        <div class="status">
            Estado: Funcionando correctamente ✅
        </div>
        <p>Esta es una aplicación de prueba para verificar el despliegue en Render.</p>
        <p>Hora del servidor: {{ hora_actual }}</p>
    </div>
</body>
</html>
"""

@app.route('/')
def hola():
    from datetime import datetime
    ahora = datetime.now()
    hora_formateada = ahora.strftime("%Y-%m-%d %H:%M:%S")
    return render_template_string(HTML_TEMPLATE, hora_actual=hora_formateada)

if __name__ == '__main__':
    app.run(debug=True)
