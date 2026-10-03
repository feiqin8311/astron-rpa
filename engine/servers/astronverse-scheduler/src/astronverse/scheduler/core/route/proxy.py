import os
import sys


def get_cmd():
    if sys.platform == "win32":
        return [os.path.join(os.path.dirname(__file__), "win", "route.exe")]
    return [sys.executable, "-m", "astronverse.scheduler.core.route.local_router"]
