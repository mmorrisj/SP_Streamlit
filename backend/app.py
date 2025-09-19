import os
from flask import Flask
from flask_migrate import Migrate
from dotenv import load_dotenv
from backend.extensions import db

# Load environment variables
load_dotenv()

def create_app():
    app = Flask(__name__, static_folder="static", template_folder="templates")

    # Database config
    POSTGRES_USER = os.getenv("POSTGRES_USER", "matthew50")
    POSTGRES_PASSWORD = os.getenv("POSTGRES_PASSWORD", "softpower")
    POSTGRES_DB = os.getenv("POSTGRES_DB", "softpower-db")
    DB_HOST = os.getenv("DB_HOST", "localhost")   # "postgres_db" inside Docker
    DB_PORT = os.getenv("DB_PORT", 5432)

    app.config["SQLALCHEMY_DATABASE_URI"] = (
        f"postgresql://{POSTGRES_USER}:{POSTGRES_PASSWORD}@{DB_HOST}:{DB_PORT}/{POSTGRES_DB}"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    # Initialize extensions
    db.init_app(app)
    Migrate(app, db)

    # Register routes and CLI commands
    from backend.routes import register_routes
    from backend.commands import register_commands
    register_commands(app)
    register_routes(app)

    return app


# For `flask run` or direct execution
app = create_app()

if __name__ == "__main__":
    app.run(debug=True, host="0.0.0.0", port=5500)
