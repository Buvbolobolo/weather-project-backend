from pathlib import Path

from app import BASE_DIR, Base, engine, seed_database


def recreate_database() -> None:
    db_file = BASE_DIR / "weather.db"

    if db_file.exists():
        db_file.unlink()

    Base.metadata.create_all(bind=engine)
    seed_database()


if __name__ == "__main__":
    recreate_database()
    print(f"База данных инициализирована: {Path(BASE_DIR / 'weather.db')}")
