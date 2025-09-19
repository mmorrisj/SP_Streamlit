# filename: backend/scripts/embed_weekly_summaries_monitor.py

import logging
import sys
import time
from backend.tasks.embedding_tasks import embed_weekly_summaries_parallel
from backend.celery import celery

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)

def monitor_task_progress(task_ids, check_interval=30):
    """Monitor the progress of embedding tasks."""
    logging.info(f"📊 Monitoring {len(task_ids)} batch tasks...")
    
    completed = 0
    failed = 0
    
    while completed + failed < len(task_ids):
        time.sleep(check_interval)
        
        current_completed = 0
        current_failed = 0
        
        for task_id in task_ids:
            try:
                result = celery.AsyncResult(task_id)
                
                if result.ready():
                    if result.successful():
                        current_completed += 1
                        if result.result and isinstance(result.result, dict):
                            processed = result.result.get('processed', 0)
                            total = result.result.get('total', 0)
                            logging.info(f"✅ Batch {task_id[:8]} completed: {processed}/{total}")
                    else:
                        current_failed += 1
                        logging.error(f"❌ Batch {task_id[:8]} failed: {result.result}")
                elif result.state == 'PROGRESS':
                    meta = result.info or {}
                    current = meta.get('current', 0)
                    total = meta.get('total', 0)
                    status = meta.get('status', 'Processing...')
                    elapsed = meta.get('elapsed', 0)
                    logging.info(f"🔄 Batch {task_id[:8]}: {current}/{total} - {status} (elapsed: {elapsed:.1f}s)")
                    
            except Exception as e:
                logging.warning(f"Error checking task {task_id}: {e}")
        
        if current_completed > completed:
            logging.info(f"📈 Progress: {current_completed}/{len(task_ids)} batches completed")
            completed = current_completed
            
        if current_failed > failed:
            logging.warning(f"⚠️ Failed batches: {current_failed}")
            failed = current_failed
    
    return completed, failed

def main():
    """Script to trigger and monitor the parallel weekly embedding pipeline."""
    try:
        logging.info("🚀 Triggering parallel weekly embedding pipeline...")
        
        # Option 1: Fast dispatch (skip embedding checks, let workers handle duplicates)
        logging.info("Using fast dispatch mode (skipping pre-checks)...")
        result = embed_weekly_summaries_parallel.apply_async(
            args=[15, True],  # batch_size=15, skip_check=True
            queue="default"
        )
        
        # Give it more time for dispatch but not too much
        try:
            dispatch_result = result.get(timeout=180)  # 3 minutes max for dispatch
        except Exception as e:
            logging.error(f"Dispatch failed or timed out: {e}")
            logging.info("Trying alternative approach...")
            
            # Option 2: Direct batch creation without orchestrator
            from backend.app import create_app
            from backend.scripts.models import WeeklyEvent, WeeklyEventSummary
            from backend.tasks.embedding_tasks import embed_weekly_batch
            
            app = create_app()
            with app.app_context():
                summaries = (
                    db.session.query(WeeklyEventSummary.id)
                    .join(WeeklyEvent, WeeklyEventSummary.event_id == WeeklyEvent.id)
                    .filter(WeeklyEventSummary.summary_text.isnot(None))
                    .filter(WeeklyEventSummary.summary_text != "")
                    .limit(100)  # Process first 100 as test
                    .all()
                )
                
                summary_ids = [s.id for s in summaries]
                
                if not summary_ids:
                    logging.info("✅ No summaries found to process")
                    return
                
                logging.info(f"📋 Direct dispatch: {len(summary_ids)} summaries")
                
                # Create batches and dispatch directly
                batch_size = 10
                batches = [summary_ids[i:i + batch_size] for i in range(0, len(summary_ids), batch_size)]
                task_ids = []
                
                for i, batch in enumerate(batches):
                    task = embed_weekly_batch.apply_async(args=[batch], queue="embeddings")
                    task_ids.append(task.id)
                    logging.info(f"   Dispatched batch {i+1}/{len(batches)}: {task.id[:8]}")
                
                dispatch_result = {
                    "status": "dispatched",
                    "total": len(summary_ids),
                    "batches": len(batches),
                    "task_ids": task_ids
                }
        
        if dispatch_result.get('status') == 'completed':
            logging.info("✅ No summaries needed embedding")
            return
        
        total = dispatch_result.get('total', 0)
        batches = dispatch_result.get('batches', 0)
        task_ids = dispatch_result.get('task_ids', [])
        
        logging.info(f"📋 Dispatched {total} summaries across {batches} batches")
        
        if not task_ids:
            logging.warning("⚠️ No tasks were dispatched")
            return
        
        # Show first few task IDs
        sample_ids = task_ids[:3] + (['...'] if len(task_ids) > 3 else [])
        logging.info(f"🔗 Sample task IDs: {sample_ids}")
        
        # Monitor progress with shorter intervals for responsiveness
        completed, failed = monitor_task_progress(task_ids, check_interval=15)
        
        # Final summary
        logging.info("📊 Final Results:")
        logging.info(f"   • Total summaries: {total}")
        logging.info(f"   • Completed batches: {completed}/{batches}")
        logging.info(f"   • Failed batches: {failed}")
        
        if failed > 0:
            logging.warning("⚠️ Some batches failed. Check Celery logs for details.")
            sys.exit(1)
        else:
            logging.info("✅ All batches completed successfully!")
            
    except KeyboardInterrupt:
        logging.info("⏹️ Interrupted by user")
        sys.exit(0)
    except Exception as e:
        logging.error(f"❌ Error running embedding pipeline: {str(e)}")
        import traceback
        logging.error(f"Full traceback: {traceback.format_exc()}")
        sys.exit(1)

if __name__ == "__main__":
    main()