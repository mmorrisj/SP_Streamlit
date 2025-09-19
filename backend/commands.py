import click
from flask.cli import with_appcontext
from backend.scripts.flatten import normalize_data
from backend.scripts.dsr import process_dsr
# from backend.scripts.embedding_dispatcher import run_dispatcher
def register_commands(app):

    @app.cli.command("normalize")
    @with_appcontext
    def normalize():
        try:
            normalize_data() 
            return {"message": "Data normalized successfully."}, 200
        except Exception as e:
            return {"error": str(e)}, 500
        
    @app.cli.command("dsr")
    @with_appcontext
    def dsr():
        try:
            process_dsr(relocate=False) 
            return {"message": "DSR data loaded successfully."}, 200
        except Exception as e:
            return {"error": str(e)}, 500    

    @app.cli.command("embed")
    def embed():
        """Dispatch embedding tasks for unprocessed documents."""
        click.echo("📦 Dispatching embedding tasks...")
        run_dispatcher()
        click.echo("✅ All tasks dispatched.")
