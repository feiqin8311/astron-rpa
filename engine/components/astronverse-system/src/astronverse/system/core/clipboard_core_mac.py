import os
import subprocess

from astronverse.system.core.clipboard_core import IClipBoardCore
from astronverse.system.error import CONTENT_TYPE_ERROR_FORMAT, BaseException

_PB_ENV = {**os.environ, "LANG": "en_US.UTF-8"}


class ClipBoardCore(IClipBoardCore):
    @staticmethod
    def copy_str_clip(data: str = ""):
        proc = subprocess.Popen(["pbcopy"], stdin=subprocess.PIPE, env=_PB_ENV)
        proc.communicate((data or "").encode("utf-8"))
        if proc.returncode:
            raise RuntimeError("pbcopy 失败")

    @staticmethod
    def paste_str_clip() -> str:
        result = subprocess.run(
            ["pbpaste"],
            capture_output=True,
            env=_PB_ENV,
        )
        if result.returncode:
            raise RuntimeError("pbpaste 失败")
        return (result.stdout or b"").decode("utf-8")

    @staticmethod
    def clear_clip():
        ClipBoardCore.copy_str_clip("")

    @staticmethod
    def _pasteboard():
        from AppKit import NSPasteboard

        return NSPasteboard.generalPasteboard()

    @staticmethod
    def copy_file_clip(file_path: str = ""):
        from AppKit import NSURL

        abs_path = os.path.abspath(file_path)
        pasteboard = ClipBoardCore._pasteboard()
        pasteboard.clearContents()
        url = NSURL.fileURLWithPath_(abs_path)
        pasteboard.writeObjects_([url])

    @staticmethod
    def paste_file_clip() -> str:
        from AppKit import NSURL

        pasteboard = ClipBoardCore._pasteboard()
        urls = pasteboard.readObjectsForClasses_options_([NSURL], None)
        if not urls:
            raise BaseException(
                CONTENT_TYPE_ERROR_FORMAT,
                "剪切板中内容为文本内容，请检查剪切板内容及获取类型设置是否正确",
            )
        url = urls[0]
        if url is None or not url.isFileURL():
            raise BaseException(
                CONTENT_TYPE_ERROR_FORMAT,
                "剪切板中内容为文本内容，请检查剪切板内容及获取类型设置是否正确",
            )
        return url.path()

    @staticmethod
    def paste_html_clip() -> str:
        from AppKit import NSPasteboardTypeHTML

        pasteboard = ClipBoardCore._pasteboard()
        html = pasteboard.stringForType_(NSPasteboardTypeHTML)
        if html:
            return html
        return ClipBoardCore.paste_str_clip()
