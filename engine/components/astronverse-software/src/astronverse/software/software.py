import locale
import os
import platform
import shlex
import subprocess
import sys
import time
import warnings

import psutil
from astronverse.actionlib import AtomicFormType, AtomicFormTypeMeta, AtomicLevel
from astronverse.actionlib.atomic import atomicMg
from astronverse.actionlib.logger import logger
from astronverse.software.core import ISoftwareCore
from astronverse.software.error import *
from astronverse.software.error import (
    BaseException as SoftwareBaseException,
)

if sys.platform == "win32":
    from astronverse.software.core_win import SoftwareCore
elif sys.platform == "darwin":
    from astronverse.software.core_mac import SoftwareCore
elif platform.system() == "Linux":
    from astronverse.software.core_unix import SoftwareCore
else:
    raise NotImplementedError(f"Your platform ({platform.system()}) is not supported by (software).")

SoftwareCore: ISoftwareCore = SoftwareCore()
system_encoding = locale.getpreferredencoding()


class Software:
    @staticmethod
    @atomicMg.atomic(
        "Software",
        inputList=[
            atomicMg.param(
                "app_absolute_path",
                formType=AtomicFormTypeMeta(
                    type=AtomicFormType.INPUT_VARIABLE_PYTHON_FILE.value,
                    params={"filters": []},
                ),
            ),
            atomicMg.param("app_arguments", required=False, level=AtomicLevel.ADVANCED),
        ],
        outputList=[atomicMg.param("software_open", types="Str")],
    )
    def open(app_absolute_path: str = "", app_arguments: str = "") -> str:
        """
        打开软件
        :param app_absolute_path: 地址
        :param app_arguments: 参数
        :return:
        """

        if not os.path.exists(app_absolute_path):
            raise SoftwareBaseException(
                INVALID_APP_PATH_ERROR_CODE.format(app_absolute_path),
                "填写的应用程序路径有误，请输入正确的路径！",
            )

        warnings.filterwarnings("ignore", category=ResourceWarning)
        if sys.platform == "darwin" and (app_absolute_path.endswith(".app") or os.path.isdir(app_absolute_path)):
            cmd = ["open", "-a", app_absolute_path]
            if app_arguments:
                cmd.extend(["--args", *shlex.split(app_arguments)])
            process = subprocess.Popen(
                cmd,
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                close_fds=True,
            )
            while not process.pid:
                time.sleep(0.3)
            return app_absolute_path

        process = subprocess.Popen(
            [app_absolute_path] + shlex.split(app_arguments),
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
        )
        while not process.pid:
            time.sleep(0.3)
        return app_absolute_path

    @staticmethod
    @atomicMg.atomic(
        "Software",
        inputList=[
            atomicMg.param(
                "app_absolute_path",
                formType=AtomicFormTypeMeta(
                    type=AtomicFormType.INPUT_VARIABLE_PYTHON_FILE.value,
                    params={"filters": []},
                ),
            )
        ],
    )
    def close(app_absolute_path: str):
        """
        关闭软件
        :param app_absolute_path: 地址
        :return:
        """

        if not os.path.exists(app_absolute_path):
            raise SoftwareBaseException(
                INVALID_APP_PATH_ERROR_CODE.format(app_absolute_path),
                "填写的应用程序路径有误，请输入正确的路径！",
            )

        exe_name = os.path.split(app_absolute_path)[1]
        try:
            if sys.platform == "win32":
                # 特殊处理
                if exe_name == "ThunderStart.exe":
                    subprocess.run(
                        ["taskkill", "/F", "/IM", "Thunder.exe"],
                        check=False,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                    )
                    return
                subprocess.run(
                    ["taskkill", "/F", "/IM", exe_name],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
            elif sys.platform == "darwin":
                import plistlib

                # 获取 app_name 和 bundle executable 名字
                bundle_path = app_absolute_path
                if not bundle_path.endswith(".app") and ".app/" in bundle_path:
                    bundle_path = bundle_path.split(".app/")[0] + ".app"

                bundle_exec = exe_name
                app_name = (
                    os.path.splitext(os.path.basename(bundle_path))[0] if bundle_path.endswith(".app") else exe_name
                )

                if bundle_path.endswith(".app"):
                    plist_path = os.path.join(bundle_path, "Contents", "Info.plist")
                    if os.path.exists(plist_path):
                        try:
                            with open(plist_path, "rb") as fp:
                                plist_data = plistlib.load(fp)
                            bundle_exec = plist_data.get("CFBundleExecutable", bundle_exec)
                            bundle_name = plist_data.get("CFBundleName")
                            if bundle_name:
                                app_name = bundle_name
                        except Exception as e:
                            logger.warning(f"Failed to read Info.plist for {bundle_path}: {e}")

                # 1. 尝试使用 osascript 优雅退出
                clean_app_name = app_name.replace('"', '\\"')
                try:
                    subprocess.run(
                        ["osascript", "-e", f'quit app "{clean_app_name}"'],
                        check=False,
                        stdin=subprocess.DEVNULL,
                        stdout=subprocess.DEVNULL,
                        stderr=subprocess.DEVNULL,
                        timeout=3,
                    )
                except Exception as e:
                    logger.warning(f"osascript quit failed: {e}")

                # 2. 检查是否有匹配的进程仍在运行，如仍存活则使用 psutil 强制杀死
                target_names = {bundle_exec, app_name, exe_name}
                if exe_name.endswith(".app"):
                    target_names.add(exe_name[:-4])

                # 给优雅退出短暂等待时间（最多1秒）
                matching_procs = []
                for _ in range(5):
                    matching_procs = []
                    for proc in psutil.process_iter(["name"]):
                        try:
                            if proc.name() in target_names:
                                matching_procs.append(proc)
                        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                            pass
                    if not matching_procs:
                        break
                    time.sleep(0.2)

                # 强制杀死仍未退出的进程
                for proc in matching_procs:
                    try:
                        proc.kill()
                    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                        pass
            else:
                subprocess.run(
                    ["pkill", exe_name],
                    check=False,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
        except (subprocess.SubprocessError, OSError) as error:
            logger.error(f"error: Software close {error}")
            return

    @staticmethod
    def exists(app_name: str = "", parent_name: str = "") -> bool:
        """
        exists 软件是否存在
        :param app_name: 软件名称
        :param parent_name: 软件的父级名称
        :return:
        """

        return Software.pid(app_name, parent_name) >= 0

    @staticmethod
    def pid(app_name: str = "", parent_name: str = "") -> int:
        """
        pid 获取正在执行的软件pid
        :param app_name: 软件名称
        :param parent_name: 软件的父级名称
        :return:
        """
        is_mac = sys.platform == "darwin"
        target_names = {app_name}
        if is_mac:
            if app_name.endswith(".exe"):
                target_names.add(app_name[:-4])
            if app_name.endswith(".app"):
                target_names.add(os.path.splitext(os.path.basename(app_name))[0])
            if "/" in app_name:
                base = os.path.basename(app_name.rstrip("/"))
                target_names.add(base)
                if base.endswith(".app"):
                    target_names.add(base[:-4])

        target_parents = {parent_name} if parent_name else set()
        if is_mac and parent_name:
            if parent_name.endswith(".exe"):
                target_parents.add(parent_name[:-4])
            if parent_name.endswith(".app"):
                target_parents.add(os.path.splitext(os.path.basename(parent_name))[0])
            if "/" in parent_name:
                base = os.path.basename(parent_name.rstrip("/"))
                target_parents.add(base)
                if base.endswith(".app"):
                    target_parents.add(base[:-4])

        for process in psutil.process_iter():
            try:
                proc_name = process.name()
                if is_mac:
                    if proc_name not in target_names:
                        continue
                else:
                    if proc_name != app_name:
                        continue

                if not parent_name:
                    return process.pid

                for parent in process.parents():
                    parent_proc_name = parent.name()
                    if is_mac:
                        if parent_proc_name in target_parents:
                            return process.pid
                    else:
                        if parent_proc_name == parent_name:
                            return process.pid
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pass
        return -1

    @staticmethod
    def get_app_path(app_name: str = "") -> str:
        """
        获取软件地址
        """
        return SoftwareCore.get_app_path(app_name)

    @staticmethod
    @atomicMg.atomic("Software", outputList=[atomicMg.param("exec_cmd", types="Dict")])
    def cmd(cmd: str) -> dict:
        with subprocess.Popen(
            cmd,
            shell=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding=system_encoding,
            errors="replace",
        ) as process:
            stdout, stderr = process.communicate()
            return {
                "status": process.returncode,
                "stdout": stdout,
                "stderr": stderr,
            }
