from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from backend.extensions import db
from dotenv import load_dotenv
import os
load_dotenv()
DB_HOST = os.getenv("DB_HOST", "localhost")
POSTGRES_PORT = os.getenv("POSTGRES_PORT",5432)
DATABASE_URL = f"postgresql://matthew50:softpower@{DB_HOST}:{POSTGRES_PORT}/softpower-db"  # adjust if needed
engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(bind=engine)

def get_session():
    return SessionLocal()