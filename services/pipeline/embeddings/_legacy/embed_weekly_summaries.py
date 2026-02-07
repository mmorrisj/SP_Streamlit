# filename: backend/scripts/embed_weekly_summaries_celery.py

import logging
import sys
from backend.tasks.embedding_tasks import embed_weekly_summaries_parallel

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def main():
    """Script to trigger the parallel weekly embedding pipeline."""
    try:
        logging.info("🚀 Triggering parallel weekly embedding pipeline...")
        
        # Direct call (blocks until complete)
        result = embed_weekly_summaries_parallel.delay()
        final_result = result.get()  # This will block until completion
        
        logging.info("📊 Final Results:")
        logging.info(f"   • Total summaries: {final_result.get('total', 0)}")
        logging.info(f"   • Successfully processed: {final_result.get('processed', 0)}")
        
        if final_result.get('processed', 0) == final_result.get('total', 0):
            logging.info("✅ All embeddings completed successfully!")
        else:
            logging.warning("⚠️ Some embeddings may have been skipped. Check logs for details.")
            
    except KeyboardInterrupt:
        logging.info("⏹️ Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"❌ Error running embedding pipeline: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()