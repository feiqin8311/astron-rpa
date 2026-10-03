"""macOS 拾取高亮 overlay：UDP 协议对齐 Linux PyQt 实现，绘制走 AppKit。

作为独立脚本启动：python highlighter.py <port>
纯逻辑（解析 / 状态 / 坐标换算）可在不启动 NSApplication 的情况下被测试导入。
"""

from __future__ import annotations

import json
import os
import queue
import socket
import sys
import threading
import time
from dataclasses import dataclass, field

CV_MODES = ("CV", "CV_ALT", "CV_CTRL")
HINT_TEXT_CV = "ALT  智能拾取\nCTRL  截图拾取"
HINT_TEXT_DEFAULT = "CTRL + 点击  拾取\nESC  退出"

# picking 多框：与 Linux 一样 3 次亮灭（500ms）；validate：任务要求 ~300ms
BLINK_PICKING_MS = 500
BLINK_VALIDATE_MS = 300
BLINK_CYCLES = 3


@dataclass(frozen=True)
class Box:
    left: float
    top: float
    right: float
    bottom: float
    msg: str = ""


@dataclass(frozen=True)
class ScreenFrame:
    """Cocoa 屏幕 frame：origin 为该屏左下角的全局 Cocoa 坐标。"""

    x: float
    y: float
    width: float
    height: float


@dataclass
class Blink:
    cycles_left: int
    interval_ms: int
    showing: bool
    clear_after: bool


@dataclass
class HLState:
    mode: str = "normal"
    boxes: list[Box] = field(default_factory=list)
    visible: bool = False
    blink: Blink | None = None
    hint_visible: bool = False
    hint_mode: str = ""
    should_exit: bool = False


def parse_datagram(data: bytes | str) -> dict | None:
    if isinstance(data, bytes):
        try:
            data = data.decode("utf-8")
        except UnicodeDecodeError:
            return None
    try:
        obj = json.loads(data)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(obj, dict):
        return None
    return obj


def _num(value, default: float = 0.0) -> float:
    if value is None or value == "":
        return default
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def parse_boxes(raw) -> list[Box]:
    boxes: list[Box] = []
    if not raw:
        return boxes
    for item in raw:
        if not isinstance(item, dict):
            continue
        left = _num(item.get("Left"))
        right = _num(item.get("Right"))
        top = _num(item.get("Top"))
        bottom = _num(item.get("Bottom"))
        if right < left:
            left, right = right, left
        if bottom < top:
            top, bottom = bottom, top
        boxes.append(
            Box(
                left=left,
                top=top,
                right=right,
                bottom=bottom,
                msg=str(item.get("Msg") or ""),
            )
        )
    return boxes


def hint_text_for(mode: str) -> str:
    if mode == "CV":
        return HINT_TEXT_CV
    return HINT_TEXT_DEFAULT


def top_left_to_cocoa_point(x: float, y: float, primary: ScreenFrame) -> tuple[float, float]:
    """顶左原点全局点 -> Cocoa 全局点（主屏左下为 Cocoa 原点）。"""
    return (primary.x + x, primary.y + primary.height - y)


def screen_top_left_global(screen: ScreenFrame, primary: ScreenFrame) -> tuple[float, float]:
    """该屏左上角，用顶左原点、主屏左上为 (0,0) 的全局坐标表示。"""
    left = screen.x - primary.x
    top = (primary.y + primary.height) - (screen.y + screen.height)
    return left, top


def box_to_flipped_local(
    box: Box, screen: ScreenFrame, primary: ScreenFrame
) -> tuple[float, float, float, float] | None:
    """盒子裁剪到该屏后，返回 flipped view 下的 (x, y, w, h)；无交集则 None。"""
    s_left, s_top = screen_top_left_global(screen, primary)
    s_right = s_left + screen.width
    s_bottom = s_top + screen.height
    left = max(box.left, s_left)
    top = max(box.top, s_top)
    right = min(box.right, s_right)
    bottom = min(box.bottom, s_bottom)
    if right <= left or bottom <= top:
        return None
    return (left - s_left, top - s_top, right - left, bottom - top)


def apply_message(state: HLState, message: dict) -> HLState:
    """按 Linux 协议更新内部状态。就地修改并返回同一对象。"""
    op = message.get("Operation")
    typ = message.get("Type")

    if op == "start":
        state.mode = typ or "normal"
        if typ in CV_MODES:
            state.hint_mode = typ
            state.hint_visible = True
        elif typ == "hide":
            state.hint_visible = False
        return state

    if op == "picking":
        boxes = parse_boxes(message.get("Boxes"))
        state.blink = None
        if typ == "invalid":
            state.boxes = boxes
            state.visible = bool(boxes)
            return state
        if len(boxes) == 0:
            state.boxes = []
            state.visible = False
            return state
        if len(boxes) == 1:
            state.boxes = boxes
            state.visible = True
            return state
        state.boxes = boxes
        state.visible = True
        state.blink = Blink(
            cycles_left=BLINK_CYCLES,
            interval_ms=BLINK_PICKING_MS,
            showing=True,
            clear_after=False,
        )
        return state

    if op == "validate":
        boxes = parse_boxes(message.get("Boxes"))
        state.mode = "validate"
        state.boxes = boxes
        state.visible = bool(boxes)
        state.blink = None
        if boxes:
            state.blink = Blink(
                cycles_left=BLINK_CYCLES,
                interval_ms=BLINK_VALIDATE_MS,
                showing=True,
                clear_after=True,
            )
        return state

    if op == "initialize":
        state.boxes = []
        state.visible = False
        state.blink = None
        state.mode = "normal"
        if typ == "Exit":
            state.should_exit = True
            state.hint_visible = False
        elif typ == "ESC":
            state.hint_visible = False
        elif typ == "SHIFT":
            if state.hint_mode in CV_MODES:
                state.hint_visible = True
        return state

    return state


def tick_blink(state: HLState) -> HLState:
    """推进一次亮/灭。3 次闪烁 = 3 个 on-off 周期。"""
    blink = state.blink
    if blink is None:
        return state
    if blink.showing:
        blink.showing = False
        state.visible = False
        return state
    blink.cycles_left -= 1
    if blink.cycles_left <= 0:
        state.blink = None
        if blink.clear_after:
            state.visible = False
            state.boxes = []
        else:
            state.visible = True
        return state
    blink.showing = True
    state.visible = True
    return state


def run(port: int) -> None:
    """绑定 UDP 并进入 AppKit 事件循环。仅由 __main__ 调用。"""
    from AppKit import (
        NSApplication,
        NSApplicationActivationPolicyAccessory,
        NSBackingStoreBuffered,
        NSBezierPath,
        NSColor,
        NSFont,
        NSFontAttributeName,
        NSForegroundColorAttributeName,
        NSMakePoint,
        NSMakeRect,
        NSScreen,
        NSScreenSaverWindowLevel,
        NSTextField,
        NSView,
        NSWindow,
        NSWindowCollectionBehaviorCanJoinAllSpaces,
        NSWindowCollectionBehaviorFullScreenAuxiliary,
        NSWindowCollectionBehaviorStationary,
        NSWindowStyleMaskBorderless,
    )
    from Foundation import NSObject, NSString, NSTimer
    from objc import python_method
    from objc import super as objc_super

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    try:
        sock.bind(("127.0.0.1", int(port)))
    except OSError as exc:
        sys.stderr.write("Failed to bind UDP socket to 127.0.0.1:{}: {}\n".format(port, exc))
        sys.exit(1)

    class HLView(NSView):
        def initWithFrame_(self, frame):  # noqa: N802
            self = objc_super(HLView, self).initWithFrame_(frame)
            if self is None:
                return None
            self.hl_rects = []
            self.hl_mode = "normal"
            return self

        def isFlipped(self):  # noqa: N802
            return True

        def isOpaque(self):  # noqa: N802
            return False

        def drawRect_(self, rect):  # noqa: N802
            rects = getattr(self, "hl_rects", None) or []
            mode = getattr(self, "hl_mode", "normal")
            if not rects:
                return
            validate = mode == "validate"
            fill = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 192.0 / 255.0, 203.0 / 255.0, 155.0 / 255.0)
            border = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 105.0 / 255.0, 180.0 / 255.0, 1.0)
            red = NSColor.colorWithCalibratedRed_green_blue_alpha_(1.0, 0.0, 0.0, 1.0)
            for item in rects:
                x, y, w, h, msg = item
                box_rect = NSMakeRect(x, y, w, h)
                if validate:
                    red.set()
                    path = NSBezierPath.bezierPathWithRect_(box_rect)
                    path.setLineWidth_(5.0)
                    path.stroke()
                else:
                    fill.set()
                    NSBezierPath.fillRect_(box_rect)
                    border.set()
                    path = NSBezierPath.bezierPathWithRect_(box_rect)
                    path.setLineWidth_(2.0)
                    path.stroke()
                if msg:
                    self._drawMsg_atX_y_(msg, x, y)

        def _drawMsg_atX_y_(self, msg, box_x, box_y):  # noqa: N802
            ns_text = NSString.stringWithString_(str(msg))
            attrs = {
                NSFontAttributeName: NSFont.systemFontOfSize_(11.0),
                NSForegroundColorAttributeName: NSColor.whiteColor(),
            }
            size = ns_text.sizeWithAttributes_(attrs)
            pad_x, pad_y = 6.0, 3.0
            tag_w = size.width + pad_x * 2
            tag_h = size.height + pad_y * 2
            tag_x = box_x
            tag_y = box_y - tag_h - 2.0
            if tag_y < 0:
                tag_y = box_y + 2.0
            NSColor.colorWithCalibratedWhite_alpha_(0.12, 0.88).set()
            NSBezierPath.fillRect_(NSMakeRect(tag_x, tag_y, tag_w, tag_h))
            ns_text.drawAtPoint_withAttributes_(NSMakePoint(tag_x + pad_x, tag_y + pad_y), attrs)

    class HLApp(NSObject):
        def init(self):
            self = objc_super(HLApp, self).init()
            if self is None:
                return None
            self.sock = None
            self.q = queue.SimpleQueue()
            self.stop = threading.Event()
            self.state = HLState()
            self.sender = None
            self.ppid = os.getppid()
            self.last_ppid_check = time.monotonic()
            self.blink_deadline = None
            self.windows = []
            self.hint_window = None
            self.hint_label = None
            self.app = None
            self.shutting_down = False
            return self

        @python_method
        def boot(self, udp_sock, app) -> None:
            self.sock = udp_sock
            self.app = app
            self._build_overlays()
            self._build_hint()
            t = threading.Thread(target=self._udp_loop, name="hl-udp", daemon=True)
            t.start()
            NSTimer.scheduledTimerWithTimeInterval_target_selector_userInfo_repeats_(0.03, self, "poll:", None, True)

        @python_method
        def _build_overlays(self) -> None:
            screens = list(NSScreen.screens() or [])
            if not screens:
                return
            primary_ns = NSScreen.mainScreen() or screens[0]
            pf = primary_ns.frame()
            primary = ScreenFrame(pf.origin.x, pf.origin.y, pf.size.width, pf.size.height)
            behavior = (
                NSWindowCollectionBehaviorCanJoinAllSpaces
                | NSWindowCollectionBehaviorFullScreenAuxiliary
                | NSWindowCollectionBehaviorStationary
            )
            for ns_screen in screens:
                fr = ns_screen.frame()
                screen = ScreenFrame(fr.origin.x, fr.origin.y, fr.size.width, fr.size.height)
                win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                    fr,
                    NSWindowStyleMaskBorderless,
                    NSBackingStoreBuffered,
                    False,
                )
                win.setOpaque_(False)
                win.setBackgroundColor_(NSColor.clearColor())
                win.setIgnoresMouseEvents_(True)
                win.setLevel_(NSScreenSaverWindowLevel)
                win.setCollectionBehavior_(behavior)
                win.setHasShadow_(False)
                win.setReleasedWhenClosed_(False)
                win.setHidesOnDeactivate_(False)
                view = HLView.alloc().initWithFrame_(win.contentView().bounds())
                win.setContentView_(view)
                win.setFrame_display_(fr, True)
                win.orderFront_(None)
                self.windows.append((win, view, screen, primary))

        @python_method
        def _build_hint(self) -> None:
            screens = list(NSScreen.screens() or [])
            if not screens:
                return
            primary_ns = NSScreen.mainScreen() or screens[0]
            pf = primary_ns.frame()
            hint_w, hint_h = 280.0, 52.0
            hx = pf.origin.x + (pf.size.width - hint_w) / 2.0
            hy = pf.origin.y + pf.size.height - hint_h - 16.0
            win = NSWindow.alloc().initWithContentRect_styleMask_backing_defer_(
                NSMakeRect(hx, hy, hint_w, hint_h),
                NSWindowStyleMaskBorderless,
                NSBackingStoreBuffered,
                False,
            )
            win.setOpaque_(False)
            win.setBackgroundColor_(NSColor.colorWithCalibratedWhite_alpha_(1.0, 0.82))
            win.setIgnoresMouseEvents_(True)
            win.setLevel_(NSScreenSaverWindowLevel)
            win.setHasShadow_(True)
            win.setReleasedWhenClosed_(False)
            win.setCollectionBehavior_(
                NSWindowCollectionBehaviorCanJoinAllSpaces | NSWindowCollectionBehaviorFullScreenAuxiliary
            )
            label = NSTextField.alloc().initWithFrame_(NSMakeRect(12, 6, hint_w - 24, hint_h - 12))
            label.setBezeled_(False)
            label.setDrawsBackground_(False)
            label.setEditable_(False)
            label.setSelectable_(False)
            label.setFont_(NSFont.systemFontOfSize_(13.0))
            label.setStringValue_(HINT_TEXT_CV)
            win.setContentView_(label)
            self.hint_window = win
            self.hint_label = label

        @python_method
        def _udp_loop(self) -> None:
            self.sock.settimeout(0.3)
            while not self.stop.is_set():
                try:
                    data, addr = self.sock.recvfrom(65535)
                except socket.timeout:
                    continue
                except OSError:
                    break
                self.q.put((data, addr))

        def poll_(self, _timer):
            drained = False
            while True:
                try:
                    data, addr = self.q.get_nowait()
                except queue.Empty:
                    break
                self.sender = addr
                msg = parse_datagram(data)
                if msg is None:
                    continue
                apply_message(self.state, msg)
                if self.state.blink and self.state.blink.showing:
                    self.blink_deadline = time.monotonic() + self.state.blink.interval_ms / 1000.0
                else:
                    self.blink_deadline = None
                drained = True

            now = time.monotonic()
            if self.state.blink and self.blink_deadline is not None and now >= self.blink_deadline:
                tick_blink(self.state)
                if self.state.blink:
                    self.blink_deadline = now + self.state.blink.interval_ms / 1000.0
                else:
                    self.blink_deadline = None
                drained = True

            if drained:
                self._refresh()

            if self.state.should_exit:
                self._shutdown()
                return

            if now - self.last_ppid_check >= 1.0:
                self.last_ppid_check = now
                if os.getppid() != self.ppid:
                    self._shutdown()

        @python_method
        def _refresh(self) -> None:
            state = self.state
            for _win, view, screen, primary in self.windows:
                local = []
                if state.visible:
                    for box in state.boxes:
                        rect = box_to_flipped_local(box, screen, primary)
                        if rect is None:
                            continue
                        x, y, w, h = rect
                        local.append((x, y, w, h, box.msg))
                view.hl_rects = local
                view.hl_mode = state.mode
                view.setNeedsDisplay_(True)

            if self.hint_window is None:
                return
            if state.hint_visible:
                if self.hint_label is not None:
                    self.hint_label.setStringValue_(hint_text_for(state.hint_mode or "CV"))
                self.hint_window.orderFront_(None)
            else:
                self.hint_window.orderOut_(None)

        @python_method
        def _reply(self, payload: dict) -> None:
            if not self.sender:
                return
            try:
                self.sock.sendto(json.dumps(payload).encode("utf-8"), self.sender)
            except OSError:
                pass

        @python_method
        def _shutdown(self) -> None:
            if self.shutting_down:
                return
            self.shutting_down = True
            self.stop.set()
            if self.sock is not None:
                try:
                    self.sock.close()
                except OSError:
                    pass
            if self.hint_window is not None:
                self.hint_window.orderOut_(None)
            for win, _view, _screen, _primary in self.windows:
                win.orderOut_(None)
            app = self.app
            if app is not None:
                try:
                    app.terminate_(None)
                except Exception:
                    pass
            os._exit(0)

    app = NSApplication.sharedApplication()
    app.setActivationPolicy_(NSApplicationActivationPolicyAccessory)
    controller = HLApp.alloc().init()
    controller.boot(sock, app)
    app.run()


if __name__ == "__main__":
    _port = 11001
    if len(sys.argv) > 1:
        try:
            _port = int(sys.argv[1])
        except ValueError:
            sys.stderr.write("usage: highlighter.py <port>\n")
            sys.exit(2)
    run(_port)
