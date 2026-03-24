import psycopg2

# Конфигурация БД
DB_CONFIG = {
    'dbname': 'weather',
    'user': 'postgres',
    'password': 'твой_пароль',
    'host': 'localhost',
    'port': '5432'
}

# Читаем SQL файл
with open('weather_schema.sql', 'r', encoding='utf-8') as f:
    sql_script = f.read()

# Подключаемся и выполняем
conn = psycopg2.connect(**DB_CONFIG)
cursor = conn.cursor()
cursor.execute(sql_script)
conn.commit()
cursor.close()
conn.close()

print("✅ База данных инициализирована!")