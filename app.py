from flask import Flask, jsonify
from flask_cors import CORS
import psycopg2
from psycopg2.extras import RealDictCursor

app = Flask(__name__)
CORS(app)  # Разрешаем запросы с фронтенда (порт 3000)

# Конфигурация базы данных
DB_CONFIG = {
    'dbname': 'weather',
    'user': 'postgres',
    'password': '123',
    'host': 'localhost',
    'port': '5432'
}


def get_db_connection():
    """Подключение к базе данных"""
    try:
        conn = psycopg2.connect(**DB_CONFIG)
        return conn
    except Exception as e:
        print(f"Ошибка подключения к БД: {e}")
        return None


@app.route('/api/hello', methods=['GET'])
def hello():
    """Тестовый эндпоинт для проверки связи с БД"""
    conn = get_db_connection()

    if conn is None:
        return jsonify({"message": "Hello world, but DB connection failed"}), 500

    try:
        cursor = conn.cursor()
        cursor.execute('SELECT version();')
        db_version = cursor.fetchone()
        cursor.close()
        conn.close()

        return jsonify({
            "message": f"Hello world from DB: PostgreSQL {db_version[0][:50]}..."
        }), 200

    except Exception as e:
        return jsonify({"message": f"Hello world, but DB error: {str(e)}"}), 500


@app.route('/api/health', methods=['GET'])
def health():
    """Простая проверка что сервер работает"""
    return jsonify({"status": "ok", "message": "Backend is running"}), 200


if __name__ == '__main__':
    print("🚀 Сервер запускается на порту 5000...")
    print("📍 Проверь: http://localhost:5000/api/hello")
    app.run(host='0.0.0.0', port=5000, debug=True)