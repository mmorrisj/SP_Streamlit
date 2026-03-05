import os

DB_HOST = os.getenv("DB_HOST") or "0.0.0.0"
DB_PORT = os.getenv("DB_PORT") or "5432"
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
DB_NAME = os.getenv("POSTGRES_DB")
start_date = '2024-08-01'


def get_database_url():
    """Build DATABASE_URL from env vars or raise if credentials are missing."""
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    missing = [v for v, val in [("POSTGRES_USER", DB_USER), ("POSTGRES_PASSWORD", DB_PASSWORD), ("POSTGRES_DB", DB_NAME)] if not val]
    if missing:
        raise EnvironmentError(
            f"Required database environment variables not set: {', '.join(missing)}. "
            "Set them in your .env file or environment."
        )
    return f"postgresql://{DB_USER}:{DB_PASSWORD}@{DB_HOST}:{DB_PORT}/{DB_NAME}"


DATABASE_URL = get_database_url()
