import os
import sys
import tempfile
from pathlib import Path

# Keep tests away from the real %APPDATA% folder.
os.environ.setdefault("AUDIOSTUDIO_BATCH_TTS_HOME", tempfile.mkdtemp(prefix="asbt_test_"))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
