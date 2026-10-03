import platform
import sys

from astronverse.window.core import IUITreeCore

if sys.platform == "win32":
    from astronverse.window.core_win import UITreeCore

    UITreeCore: IUITreeCore = UITreeCore()
elif sys.platform == "darwin":
    from astronverse.window.core_mac import UITreeCore

    UITreeCore: IUITreeCore = UITreeCore()
elif platform.system() == "Linux":
    pass
else:
    raise NotImplementedError(f"Your platform ({platform.system()}) is not supported by (window).")
