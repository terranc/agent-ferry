#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

root = Path(os.environ["XDG_STATE_HOME"]) / "agent-ferry"
(root / "caffeinate.json").write_text(json.dumps(sys.argv[1:]))
