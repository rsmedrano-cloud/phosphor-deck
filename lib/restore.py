"""`phosphor restore FILE`: lib/backup.py's other half."""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from backup import restore_main as main

if __name__ == "__main__":
    sys.exit(main() or 0)
