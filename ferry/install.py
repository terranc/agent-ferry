"""Install copied code without changing Claude's user settings."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

from .core import DEFAULTS, Store, write_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("install", "uninstall"))
    parser.add_argument("--keep-state", action="store_true")
    args = parser.parse_args()
    os.umask(0o077)
    store = Store()
    destination = Path.home() / ".local/share/agent-ferry"
    entry = Path.home() / ".local/bin/ferry"
    if args.action == "uninstall":
        entry.unlink(missing_ok=True)
        for path in (destination, store.config_dir):
            if path.exists():
                shutil.rmtree(path)
        if not args.keep_state and store.root.exists():
            shutil.rmtree(store.root)
        print(json.dumps({"ok": True, "kept_state": args.keep_state}))
        return 0
    source = Path(__file__).resolve().parent.parent
    if source != destination:
        shutil.copytree(source / "ferry", destination / "ferry", dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        (destination / "bin").mkdir(parents=True, exist_ok=True)
        shutil.copy2(source / "bin/ferry", destination / "bin/ferry")
    (destination / "bin/ferry").chmod(0o700)
    entry.parent.mkdir(parents=True, exist_ok=True)
    entry.write_text("#!/usr/bin/env python3\nimport sys\nsys.path.insert(0, " + repr(str(destination)) +
                     ")\nfrom ferry.cli import main\nsys.exit(main())\n", encoding="utf-8")
    entry.chmod(0o700)
    store.config_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    config = store.config_dir / "config.json"
    if not config.exists():
        write_json(config, DEFAULTS)
    store.entry = destination / "bin/ferry"
    store.render()
    store.ensure()
    return subprocess.call([str(entry), "doctor"])


if __name__ == "__main__":
    raise SystemExit(main())
