import os
import shutil

from astronverse.software.core import ISoftwareCore


class SoftwareCore(ISoftwareCore):
    @staticmethod
    def get_app_path(app_name: str = "") -> str:
        if not app_name:
            return ""
        if os.path.isabs(app_name) and os.path.exists(app_name):
            return app_name
        found = shutil.which(app_name)
        if found:
            return found
        base = os.path.basename(app_name)
        if base != app_name:
            found = shutil.which(base)
            if found:
                return found
        return ""
