import locale
import os
import subprocess
import sys
import time

import psutil
from astronverse.scheduler.logger import logger
from astronverse.scheduler.utils.utils import kill_proc_tree

system_encoding = locale.getpreferredencoding()


class Process:
    """进程管理类"""

    @staticmethod
    def kill_all_zombie():
        """杀死所有的僵尸进程"""
        zombie_processes = Process.get_python_proc_in_current_dir()
        for z_p in zombie_processes:
            kill_proc_tree(z_p)

    @staticmethod
    def get_python_proc_in_current_dir():
        """获取所有在当前目录Python进程"""

        if sys.platform != "win32":
            # 收集自己的信息（当前进程及其所有祖先进程）
            self_proc_id_set = set()
            try:
                proc = psutil.Process(os.getpid())
                while proc:
                    self_proc_id_set.add(proc.pid)
                    proc = proc.parent()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            target_prefixes = (
                sys.prefix,
                os.path.realpath(sys.prefix),
                sys.base_prefix,
                os.path.realpath(sys.base_prefix),
            )

            all_process = []
            for proc in psutil.process_iter(["pid", "name", "exe", "cmdline"]):
                try:
                    pid = proc.info.get("pid") or proc.pid
                    if pid in self_proc_id_set:
                        continue

                    exe_path = proc.info.get("exe")
                    if not exe_path:
                        try:
                            exe_path = proc.exe()
                        except Exception:
                            pass

                    cmdline = proc.info.get("cmdline")
                    if cmdline is None:
                        try:
                            cmdline = proc.cmdline()
                        except Exception:
                            cmdline = []

                    candidate_exe = exe_path or (cmdline[0] if cmdline else "")
                    if not candidate_exe:
                        continue

                    exe_real = os.path.realpath(candidate_exe)
                    # 检查其 exe/cmdline python 是否在当前 sys.executable 相同的 python 安装路径下
                    is_same_python = any(
                        p == prefix or p.startswith(prefix.rstrip(os.sep) + os.sep)
                        for prefix in target_prefixes
                        for p in (candidate_exe, exe_real)
                    )
                    if not is_same_python:
                        continue

                    # 检查 cmdline 包含 -m astronverse.* 或 exe 路径包含 astron-rpa
                    has_astron_module = False
                    if cmdline:
                        for i in range(len(cmdline) - 1):
                            if cmdline[i] == "-m" and cmdline[i + 1].startswith("astronverse."):
                                has_astron_module = True
                                break

                    has_astron_exe = "astron-rpa" in (exe_path or "") or "astron-rpa" in exe_real

                    if has_astron_module or has_astron_exe:
                        all_process.append(proc)
                except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                    continue
                except Exception:
                    continue

            return all_process

        # 收集所有需要关联的进程
        all_process_ids = []
        for process_name in ["python.exe", "route.exe", "ConsoleApp1.exe", "winvnc.exe"]:
            output = subprocess.check_output(
                ["tasklist", "/FI", f"IMAGENAME eq {process_name}", "/FO", "CSV"],
                encoding=system_encoding,
                errors="replace",
            )
            for line in output.splitlines()[1:]:
                parts = line.split(",")
                if len(parts) > 1:
                    pid = parts[1].strip('"')
                    all_process_ids.append(int(pid))

        if not all_process_ids:
            return []

        # 收集自己的信息
        self_proc_id_list = []
        try:
            proc = psutil.Process(os.getpid())
            while proc:
                self_proc_id_list.append(proc.pid)
                proc = proc.parent()
        except psutil.NoSuchProcess:
            pass

        # 判读所有的进程是否合理
        all_process = list()
        for pid in all_process_ids:
            try:
                # 忽略自己
                if pid in self_proc_id_list:
                    continue

                # 查看cwd
                proc = psutil.Process(pid)
                proc_cwd = proc.exe()
                if "astron-rpa" not in proc_cwd:
                    continue

                # 符合条件
                all_process.append(proc)
            except Exception as e:
                pass
        return all_process

    @staticmethod
    def get_root_process(proc):
        """
        获取根节点进程号(第一个不是python的进程)
        """
        if "python" in proc.name():
            p_proc = proc.parent()
            return Process.get_root_process(p_proc)
        else:
            return proc

    @staticmethod
    def pid_exist_check():
        # 一开始就启动获取root进程号，往往不是rpa进程号，这里异步3秒获取
        time.sleep(3)
        self = psutil.Process(os.getpid())
        root = Process.get_root_process(self)
        root_id = root.pid
        root_name = root.name()
        while True:
            time.sleep(1)
            try:
                if not psutil.pid_exists(root_id) or psutil.Process(root_id).name() != root_name:
                    logger.info("pid_exist_check kill process...")
                    # 首先递归杀一遍子进程
                    kill_proc_tree(psutil.Process(os.getpid()), exclude_pids=[os.getpid()])
                    # 再找到当前的启动路径的所有python进程杀一遍
                    Process.kill_all_zombie()
                    # 自行杀掉
                    kill_proc_tree(psutil.Process(os.getpid()))
            except Exception as e:
                logger.exception(e)
