"""Local work coordinator. SQLite supports many readers but only one writer.

Keep analysis and metadata rebuilds serialized so their write phases cannot
compete. The desktop app runs one Flask server process; don't deploy this
thread-based scheduler behind multiple independent WSGI workers.
"""
import threading

PROCESS_LOCK = threading.Lock()
