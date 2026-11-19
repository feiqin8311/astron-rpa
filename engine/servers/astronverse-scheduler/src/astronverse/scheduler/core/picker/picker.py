import os
import platform
import sys

from astronverse.scheduler import ComponentType
from astronverse.scheduler.utils.subprocess import SubPopen


class Picker:
    def __init__(self, svc):
        self.svc = svc
        self.highlighter = None  # 画框
        self.vision_picker = None  # cv 识别
        self.app_picker = None  # 拾取
        # self.app_picker_core = None  # 拾取
        self.start = False

    def set_start(self, start):
        self.start = start

    def init(self):
        python_executable = self.svc.config.python_core

        # 1. 平台特定 highlighter
        base_dir = os.path.dirname(os.path.abspath(__file__))
        if sys.platform == "win32" and platform.release() != "7":
            highlighter_path = os.path.join(
                base_dir,
                "win",
                "RPAHighlighter",
                "ConsoleApp1.exe",
            )
            self.highlighter = SubPopen(name="highlighter", cmd=[highlighter_path])
        elif sys.platform == "win32" and platform.release() == "7":
            highlighter_path = os.path.join(
                base_dir,
                "win",
                "RPAHighlighter",
                "cv_match_application_4.0.py",
            )
            self.highlighter = SubPopen(
                name="rpa_highlighter",
                cmd=[
                    python_executable,
                    highlighter_path,
                    "{}".format(self.svc.rpa_hl_port),
                ],
            )
        elif sys.platform == "darwin":
            highlighter_path = os.path.join(
                base_dir,
                "mac",
                "highlighter.py",
            )
            self.highlighter = SubPopen(
                name="rpa_highlighter",
                cmd=[
                    python_executable,
                    highlighter_path,
                    "{}".format(self.svc.rpa_hl_port),
                ],
            )
        else:
            highlighter_path = os.path.join(
                base_dir,
                "linux",
                "RPAHighlighter",
                "cv_match_application_4.0.py",
            )
            self.highlighter = SubPopen(
                name="rpa_highlighter",
                cmd=[
                    python_executable,
                    highlighter_path,
                    "{}".format(self.svc.rpa_hl_port),
                ],
            )

        # 2. 定位服务进程
        self.vision_picker = SubPopen(name="vision_picker", cmd=[python_executable, "-m", "astronverse.vision_picker"])
        self.app_picker = SubPopen(name="picker", cmd=[python_executable, "-m", "astronverse.picker"])

        # 3. 服务配置
        self.app_picker.set_param("port", self.svc.get_validate_port(ComponentType.PICKER))
        self.app_picker.set_param("route_port", self.svc.rpa_route_port)
        self.app_picker.set_param("highlight_socket_port", self.svc.rpa_hl_port)

        self.vision_picker.set_param("schema", "vision_picker")
        self.vision_picker.set_param("vision_picker_port", self.svc.get_validate_port(ComponentType.CV_PICKER))
        self.vision_picker.set_param("remote_addr", self.svc.config.remote_addr)
        self.vision_picker.set_param("highlight_socket_port", self.svc.rpa_hl_port)
