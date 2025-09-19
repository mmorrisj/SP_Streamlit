# filename: backend/scripts/embed_weekly_dispatch.py

import logging
import sys
from backend.app import create_app
from backend.extensions import db
from backend.scripts.models import WeeklyEvent, WeeklyEventSummary
from backend.tasks.embedding_tasks import embed_weekly_batch

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def main():
    """Simple script that dispatches embedding tasks without waiting."""
    try:
        logging.info("🚀 Dispatching weekly embedding tasks...")
        
        app = create_app()
        with app.app_context():
            # Get all summaries with text (no embedding check)
            summaries = (
                db.session.query(WeeklyEventSummary.id)
                .join(WeeklyEvent, WeeklyEventSummary.event_id == WeeklyEvent.id)
                .filter(WeeklyEventSummary.summary_text.isnot(None))
                .filter(WeeklyEventSummary.summary_text != "")
                .all()
            )
            
            summary_ids = [s.id for s in summaries]
            
            if not summary_ids:
                logging.info("✅ No summaries found to process")
                return
            
            logging.info(f"📋 Found {len(summary_ids)} summaries to process")
            
            # Create small batches and dispatch
            batch_size = 10
            batches = [summary_ids[i:i + batch_size] for i in range(0, len(summary_ids), batch_size)]
            
            logging.info(f"📦 Dispatching {len(batches)} batches of {batch_size} summaries each")
            
            dispatched = 0
            for i, batch in enumerate(batches):
                try:
                    task = embed_weekly_batch.apply_async(args=[batch], queue="embeddings")
                    dispatched += 1
                    
                    # Log progress for first few and every 10th batch
                    if i < 5 or (i + 1) % 10 == 0:
                        logging.info(f"   Batch {i+1}/{len(batches)}: {len(batch)} items -> {task.id[:8]}")
                        
                except Exception as e:
                    logging.error(f"Failed to dispatch batch {i+1}: {e}")
            
            logging.info(f"✅ Successfully dispatched {dispatched}/{len(batches)} batches")
            logging.info("🔍 Monitor progress with: celery -A backend.celery flower")
            logging.info("📊 Or check worker logs: docker-compose logs -f celery_worker")
            
    except Exception as e:
        logging.error(f"❌ Error dispatching tasks: {str(e)}")
        import traceback
        logging.error(f"Full traceback: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    main()