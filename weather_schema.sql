CREATE TABLE IF NOT EXISTS cities (
    id INTEGER PRIMARY KEY,
    name VARCHAR(120) NOT NULL UNIQUE,
    country VARCHAR(120) NOT NULL,
    condition VARCHAR(120) NOT NULL,
    temperature_c REAL NOT NULL,
    feels_like_c REAL NOT NULL,
    humidity INTEGER NOT NULL,
    wind_speed REAL NOT NULL,
    pressure_hpa INTEGER NOT NULL,
    visibility_km REAL NOT NULL,
    updated_at VARCHAR(40) NOT NULL
);

CREATE TABLE IF NOT EXISTS forecasts (
    id INTEGER PRIMARY KEY,
    city_id INTEGER NOT NULL,
    day_index INTEGER NOT NULL,
    day_name VARCHAR(30) NOT NULL,
    condition VARCHAR(120) NOT NULL,
    min_temp_c REAL NOT NULL,
    max_temp_c REAL NOT NULL,
    precipitation_chance INTEGER NOT NULL,
    FOREIGN KEY (city_id) REFERENCES cities(id)
);
