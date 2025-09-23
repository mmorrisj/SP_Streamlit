import os
from dotenv import load_dotenv
from sqlalchemy import create_engine, text

load_dotenv()

# Manual URL construction
db_user = os.getenv("POSTGRES_USER", "matthew50")
db_pass = os.getenv("POSTGRES_PASSWORD", "softpower") 
db_host = "localhost"
db_port = "5432"
db_name = os.getenv("POSTGRES_DB", "softpower-db")

url = f"postgresql+psycopg2://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}"
print(f"Testing URL: {url}")

try:
    engine = create_engine(url)
    with engine.connect() as conn:
        result = conn.execute(text("SELECT version()"))
        print("✅ Connection successful!")
        print(result.fetchone())
except Exception as e:
    print(f"❌ Connection failed: {e}")