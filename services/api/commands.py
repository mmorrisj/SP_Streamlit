import click
import subprocess
import os
from flask.cli import with_appcontext
from backend.scripts.flatten import normalize_data
from backend.scripts.dsr import process_dsr
# from services.pipeline.embeddings.embedding_dispatcher import run_dispatcher
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

    @app.cli.command("docker-start")
    def docker_start():
        """Start Docker containers."""
        try:
            click.echo("🚀 Starting Docker containers...")
            result = subprocess.run(['docker-compose', 'up', '-d'],
                                  cwd=os.path.dirname(os.path.dirname(__file__)),
                                  capture_output=True, text=True)
            if result.returncode == 0:
                click.echo("✅ Containers started successfully!")
            else:
                click.echo(f"❌ Error: {result.stderr}")
        except Exception as e:
            click.echo(f"❌ Error starting containers: {str(e)}")

    @app.cli.command("docker-stop")
    def docker_stop():
        """Stop Docker containers."""
        try:
            click.echo("🛑 Stopping Docker containers...")
            result = subprocess.run(['docker-compose', 'down'],
                                  cwd=os.path.dirname(os.path.dirname(__file__)),
                                  capture_output=True, text=True)
            if result.returncode == 0:
                click.echo("✅ Containers stopped successfully!")
            else:
                click.echo(f"❌ Error: {result.stderr}")
        except Exception as e:
            click.echo(f"❌ Error stopping containers: {str(e)}")

    @app.cli.command("docker-restart")
    def docker_restart():
        """Restart Docker containers."""
        try:
            click.echo("🔄 Restarting Docker containers...")
            subprocess.run(['docker-compose', 'down'],
                          cwd=os.path.dirname(os.path.dirname(__file__)),
                          capture_output=True, text=True)
            result = subprocess.run(['docker-compose', 'up', '-d'],
                                  cwd=os.path.dirname(os.path.dirname(__file__)),
                                  capture_output=True, text=True)
            if result.returncode == 0:
                click.echo("✅ Containers restarted successfully!")
            else:
                click.echo(f"❌ Error: {result.stderr}")
        except Exception as e:
            click.echo(f"❌ Error restarting containers: {str(e)}")

    @app.cli.command("docker-status")
    def docker_status():
        """Show Docker container status."""
        try:
            click.echo("📊 Container status:")
            result = subprocess.run(['docker-compose', 'ps'],
                                  cwd=os.path.dirname(os.path.dirname(__file__)),
                                  capture_output=True, text=True)
            click.echo(result.stdout)
        except Exception as e:
            click.echo(f"❌ Error getting status: {str(e)}")

    @app.cli.command("docker-logs")
    @click.option('--service', default='', help='Show logs for specific service')
    def docker_logs(service):
        """Show Docker container logs."""
        try:
            if service:
                click.echo(f"📋 Showing logs for {service}:")
                subprocess.run(['docker-compose', 'logs', '-f', service],
                              cwd=os.path.dirname(os.path.dirname(__file__)))
            else:
                click.echo("📋 Showing logs for all containers:")
                subprocess.run(['docker-compose', 'logs', '-f'],
                              cwd=os.path.dirname(os.path.dirname(__file__)))
        except Exception as e:
            click.echo(f"❌ Error showing logs: {str(e)}")

    @app.cli.command("db-connect")
    def db_connect():
        """Connect to PostgreSQL database."""
        try:
            click.echo("🔌 Connecting to PostgreSQL database...")
            subprocess.run(['docker-compose', 'exec', 'postgres', 'psql', '-U', 'postgres', '-d', 'vectordb'],
                          cwd=os.path.dirname(os.path.dirname(__file__)))
        except Exception as e:
            click.echo(f"❌ Error connecting to database: {str(e)}")
