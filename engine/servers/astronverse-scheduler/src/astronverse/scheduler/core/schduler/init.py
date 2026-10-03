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


def _write_linux_environment_d() -> bool:
    """User-level environment.d; no sudo, no /etc/profile."""
    from pathlib import Path

    conf_path = Path.home() / ".config" / "environment.d" / "90-astron.conf"
    conf_path.parent.mkdir(parents=True, exist_ok=True)
    wanted = "QT_LINUX_ACCESSIBILITY_ALWAYS_ON=1"
    existing = conf_path.read_text(encoding="utf-8") if conf_path.exists() else ""
    if wanted in existing:
        return False
    prefix = "" if not existing or existing.endswith("\n") else "\n"
    conf_path.write_text(existing + prefix + wanted + "\n", encoding="utf-8")
    return True


def linux_env_check():
    """linux环境检测：GNOME toolkit-accessibility + user environment.d。"""
    if not sys.platform.startswith("linux"):
        return

    need_relogin = False
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
            need_relogin = True
    except (subprocess.CalledProcessError, FileNotFoundError, OSError) as e:
        logger.warning("linux_env_check gsettings: %s", e)

    try:
        if _write_linux_environment_d():
            need_relogin = True
    except OSError as e:
        logger.warning("linux_env_check environment.d: %s", e)

    if need_relogin:
        emit_to_front(
            EmitType.ALERT,
            msg={"msg": "已开启无障碍支持，请注销或重启后再打开星辰RPA", "type": "normal"},
        )


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
