import os
import subprocess
import sys

from astronverse.scheduler.logger import logger
from astronverse.scheduler.utils.utils import EmitType, emit_to_front


def win_env_check(svc):
    if sys.platform != "win32":
        return

    try:
        pass
    except Exception as e:
        emit_to_front(EmitType.ALERT, msg={"msg": "系统依赖缺失，执行修复中...", "type": "normal"})
        resource_dir = os.path.dirname(svc.config.conf_file)
        try:
            vc_redist_exe = os.path.join(resource_dir, "VC_redist.x64.exe")
            if os.path.exists(vc_redist_exe):
                subprocess.run([vc_redist_exe, "-quiet"], check=True)
        except Exception as e:
            pass


def linux_env_check():
    """linux环境检测"""
    if not sys.platform.startswith("linux"):
        return

    try:
        result = subprocess.run(
            [
                "gsettings",
                "get",
                "org.gnome.desktop.interface",
                "toolkit-accessibility",
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.stdout.strip() != "true":
            emit_to_front(EmitType.ALERT, msg={"msg": "首次安装，请手动重启电脑后重启打开", "type": "normal"})

            # 环境写入
            subprocess.run(
                [
                    "gsettings",
                    "set",
                    "org.gnome.desktop.interface",
                    "toolkit-accessibility",
                    "true",
                ],
                check=True,
                encoding="utf-8",
                errors="replace",
            )
            # qt写入
            result = subprocess.run(
                ["grep", "^export QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1", "/etc/profile"],
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
            )
            if not result.stdout:
                subprocess.run(
                    [
                        "sudo",
                        "sh",
                        "-c",
                        'echo "export QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1" >> /etc/profile',
                    ],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.PIPE,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                )
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        logger.warning("linux_env_check error: %s", e)


def mac_env_check():
    """macOS环境检测"""
    if sys.platform != "darwin":
        return

    try:
        import Quartz
        from ApplicationServices import AXIsProcessTrustedWithOptions, kAXTrustedCheckOptionPrompt

        ax_trusted = AXIsProcessTrustedWithOptions({kAXTrustedCheckOptionPrompt: True})
        screen_trusted = Quartz.CGPreflightScreenCaptureAccess()
        if not screen_trusted:
            Quartz.CGRequestScreenCaptureAccess()
        listen_trusted = True
        try:
            listen_trusted = bool(Quartz.CGPreflightListenEventAccess())
            if not listen_trusted:
                Quartz.CGRequestListenEventAccess()
        except Exception:
            listen_trusted = True

        if not ax_trusted or not screen_trusted or not listen_trusted:
            emit_to_front(
                EmitType.ALERT,
                msg={
                    "msg": (
                        "请在“系统设置 > 隐私与安全性”中为星辰RPA授予"
                        "辅助功能(Accessibility)、屏幕录制(Screen Recording)"
                        "和输入监控(Input Monitoring)权限，然后重启应用"
                    ),
                    "type": "normal",
                },
            )
    except Exception as e:
        logger.warning("mac_env_check error: %s", e)
