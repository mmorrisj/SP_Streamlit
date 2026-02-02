"""
OpenAI Batch API processing pipeline.

Provides batch processing capabilities for LLM deconfliction tasks in the
event processing pipeline. Achieves 50% cost savings and 10x throughput
improvement over synchronous processing.

Workflow:
1. batch_prepare.py - Generate JSONL input files from database
2. batch_submit.py - Submit to OpenAI Batch API
3. batch_monitor.py - Monitor batch status until completion
4. batch_process_results.py - Process results and update database
5. batch_cleanup.py - Archive files and cleanup
"""

__version__ = '1.0.0'
