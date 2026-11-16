import subprocess
import sys

import config

steps = ["fetch_recent.py", "clean.py"]
if "--skip-fetch" in sys.argv:
    steps = steps[1:]

for script in steps:
    print(f"running {script}", flush=True)
    result = subprocess.run([sys.executable, script], cwd=config.ROOT)
    if result.returncode != 0:
        sys.exit(f"{script} failed, stopping")
