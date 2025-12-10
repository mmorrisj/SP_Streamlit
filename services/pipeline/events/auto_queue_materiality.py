#!/usr/bin/env python3
"""
Auto-queue materiality scoring - monitors China completion and starts Iran automatically.

Usage:
    python services/pipeline/events/auto_queue_materiality.py
"""

import time
import subprocess
import sys
import os
from pathlib import Path

def is_process_running(log_file):
    """Check if a process is still running by monitoring its log file"""
    if not os.path.exists(log_file):
        return False

    # Check if log file is being written to (modified in last 60 seconds)
    mtime = os.path.getmtime(log_file)
    age_seconds = time.time() - mtime
    return age_seconds < 60

def check_completion(log_file):
    """Check if the process completed successfully"""
    if not os.path.exists(log_file):
        return False

    with open(log_file, 'r', encoding='utf-8') as f:
        content = f.read()
        # Look for completion indicators
        if 'Materiality scoring completed' in content or 'FINAL SUMMARY' in content:
            return True
    return False

def start_iran_materiality():
    """Start Iran materiality scoring"""
    print("\n" + "="*70)
    print("STARTING IRAN MATERIALITY SCORING")
    print("="*70)

    cmd = [
        sys.executable,
        "services/pipeline/events/score_canonical_event_materiality.py",
        "--country", "Iran"
    ]

    # Set environment
    env = os.environ.copy()
    env['PYTHONPATH'] = '/c/Users/mmorr/Desktop/Apps/SP_Streamlit'
    env['PYTHONUNBUFFERED'] = '1'

    # Start process
    with open('logs/materiality_scoring_iran.log', 'w') as logfile:
        process = subprocess.Popen(
            cmd,
            stdout=logfile,
            stderr=subprocess.STDOUT,
            env=env,
            cwd='/c/Users/mmorr/Desktop/Apps/SP_Streamlit'
        )

    print(f"[OK] Iran materiality scoring started (PID: {process.pid})")
    print(f"[LOG] Log file: logs/materiality_scoring_iran.log")
    return process.pid

def main():
    china_log = 'logs/materiality_scoring_china.log'

    print("="*70)
    print("AUTO-QUEUE MATERIALITY SCORING")
    print("="*70)
    print(f"Monitoring: {china_log}")
    print("Will start Iran materiality scoring when China completes")
    print("Press Ctrl+C to stop monitoring")
    print("="*70)

    check_interval = 30  # Check every 30 seconds

    try:
        while True:
            # Check if China is still running
            is_running = is_process_running(china_log)
            is_complete = check_completion(china_log)

            if is_complete:
                print("\n[OK] China materiality scoring completed!")
                iran_pid = start_iran_materiality()
                print(f"\n[OK] Iran materiality scoring launched (PID: {iran_pid})")
                print("Monitor progress: tail -f logs/materiality_scoring_iran.log")
                break
            elif not is_running:
                # Process stopped but didn't complete - might be an error
                print("\n[WARN] China process stopped but didn't show completion")
                print("Check logs/materiality_scoring_china.log for errors")
                response = input("Start Iran anyway? (y/n): ")
                if response.lower() == 'y':
                    iran_pid = start_iran_materiality()
                    print(f"\n[OK] Iran materiality scoring launched (PID: {iran_pid})")
                break
            else:
                # Still running - show status
                if os.path.exists(china_log):
                    # Count completed events from log
                    with open(china_log, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        # Look for pattern like "[123/6515]"
                        for line in reversed(lines[-50:]):
                            if '[' in line and '/' in line and ']' in line:
                                import re
                                match = re.search(r'\[(\d+)/(\d+)\]', line)
                                if match:
                                    current = int(match.group(1))
                                    total = int(match.group(2))
                                    pct = (current / total) * 100
                                    print(f"[CHINA] Progress: {current:,}/{total:,} ({pct:.1f}%) - Still running...", end='\r')
                                    break

                time.sleep(check_interval)

    except KeyboardInterrupt:
        print("\n\n[WARN] Monitoring stopped by user")
        print("China materiality scoring is still running")
        return 1

    return 0

if __name__ == "__main__":
    sys.exit(main())
