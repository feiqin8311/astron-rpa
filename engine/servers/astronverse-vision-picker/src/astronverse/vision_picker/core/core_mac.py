import pyautogui
from astronverse.vision_picker.core.core import IPickCore, IRectHandler


class RectHandler(IRectHandler):
    @staticmethod
    def _frontmost_window():
        import Quartz
        from AppKit import NSWorkspace

        options = Quartz.kCGWindowListOptionOnScreenOnly | Quartz.kCGWindowListExcludeDesktopElements
        windows = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID) or []
        app = NSWorkspace.sharedWorkspace().frontmostApplication()
        if app is None:
            return None, None, None
        pid = app.processIdentifier()
        for win in windows:
            owner_pid = win.get("kCGWindowOwnerPID")
            layer = win.get("kCGWindowLayer", 0) or 0
            if owner_pid != pid or int(layer) != 0:
                continue
            bounds = win.get("kCGWindowBounds") or {}
            w = int(bounds.get("Width", 0))
            h = int(bounds.get("Height", 0))
            if w <= 0 or h <= 0:
                continue
            window_id = win.get("kCGWindowNumber")
            title = win.get("kCGWindowName") or win.get("kCGWindowOwnerName") or ""
            x = int(bounds.get("X", 0))
            y = int(bounds.get("Y", 0))
            return window_id, title, (x, y, w, h)
        return None, None, None

    @staticmethod
    def get_foreground_window_rect():
        # picker.take_screenshot crops with LTRB: (left, top, right, bottom)
        window_id, title, rect = RectHandler._frontmost_window()
        if window_id is None or rect is None:
            width, height = pyautogui.size()
            return None, "", (0, 0, width, height)
        x, y, w, h = rect
        return window_id, title or "", (x, y, x + w, y + h)


class PickCore(IPickCore):
    @staticmethod
    def get_mouse_position():
        current_position = pyautogui.position()
        return current_position.x, current_position.y
