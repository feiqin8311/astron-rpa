from __future__ import annotations

import os
import re
import shutil
import subprocess
import tempfile
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from astronverse.actionlib.logger import logger
from astronverse.actionlib.types import PATH
from astronverse.word import (
    ApplicationType,
    CloseRangeType,
    CommentType,
    ConvertPageType,
    CursorPointerType,
    CursorPositionType,
    DeleteMode,
    EncodingType,
    FileExistenceType,
    InsertImgType,
    InsertionType,
    MoveDirectionType,
    MoveLeftRightType,
    MoveUpDownType,
    ReplaceMethodType,
    ReplaceType,
    RowAlignment,
    SaveFileType,
    SaveType,
    SearchTableType,
    SelectRangeType,
    SelectTextType,
    TableBehavior,
    UnderLineStyle,
    VerticalAlignment,
)
from astronverse.word.core import IDocumentCore
from astronverse.word.error import (
    CLIPBOARD_PASTE_ERROR,
    CONTENT_FORMAT_ERROR_FORMAT,
    DOCUMENT_PATH_ERROR_FORMAT,
    DOCUMENT_READ_ERROR_FORMAT,
    FILENAME_ALREADY_EXISTS_ERROR,
    TABLE_NOT_EXIST_ERROR,
    BaseException,
)
from docx import Document
from docx.opc.constants import RELATIONSHIP_TYPE as RT
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Pt, RGBColor
from docx.text.run import Run
from PIL import Image, ImageGrab

"""
python-docx 基于文件的 macOS Word 后端。

光标与选区模型说明 (Cursor & Selection Model):
- DocxDocument: 包装 python-docx Document 实例，包含 path、visible 以及 cursor (CursorModel)。
- CursorModel:
    - p_idx: 0-indexed 段落索引 (doc.paragraphs[p_idx])。
    - offset: 0-indexed 字符偏移量 (doc.paragraphs[p_idx].text 中的位置)。
    - selection_start / selection_end: 可选的选区起始与终止位置 (CursorPos)。
- 字符级插入与运行分段 (Run Splitting):
    - 当在段落内部指定字符偏移处插入文本时，若该位置位于某个 Run 内部，则执行 split_run_at 切分 Run，
      继承切分点处原 Run 的格式（粗体、斜体、字体等），并将新文本或格式化文本无损插入。
- 选区删除与替换:
    - 若当前存在非折叠选区，插入操作会先删除选区范围内的文本，然后在折叠后的光标处插入内容。

枚举支持状态 (Enum Support Status):
1. SelectRangeType: ALL (支持), SELECTED (支持)
2. SaveType: SAVE (支持), SAVE_AS (支持), ABORT (支持)
3. ApplicationType: DEFAULT/WORD/WPS (macOS 无 COM/WPS RPC，作为无操作兼容)
4. FileExistenceType: OVERWRITE (支持), RENAME (支持), CANCEL (支持)
5. CloseRangeType: ONE (支持), ALL (支持，无独立进程无操作兼容)
6. ReplaceType: STR (支持), IMG (支持)
7. ReplaceMethodType: FIRST (支持), ALL (支持)
8. SelectTextType:
    - ALL (支持)
    - PARAGRAPH (支持)
    - ROW (不支持：python-docx 无视觉排版渲染引擎，无法获取行，抛出 CONTENT_FORMAT_ERROR_FORMAT)
9. CursorPointerType:
    - ALL (支持)
    - PARAGRAPH (支持)
    - CONTENT (支持)
    - ROW (不支持：抛出 CONTENT_FORMAT_ERROR_FORMAT)
10. CursorPositionType: HEAD (支持), TAIL (支持)
11. MoveDirectionType:
    - LEFT (支持，按字符/单词移动，支持跨段)
    - RIGHT (支持，按字符/单词移动，支持跨段)
    - UP (支持按段落)
    - DOWN (支持按段落)
12. MoveUpDownType:
    - PARAGRAPH (支持)
    - ROW (不支持：抛出 CONTENT_FORMAT_ERROR_FORMAT)
13. MoveLeftRightType: CHARACTER (支持), WORD (支持)
14. InsertionType: PAGE (支持，插入分页符), PARAGRAPH (支持，插入新段落)
15. InsertImgType: FILE (支持), CLIPBOARD (支持，通过 PIL.ImageGrab 获取图片)
16. SearchTableType: IDX (支持), TEXT (支持)
17. TableBehavior: DEFAULT (支持), AUTO (支持)
18. RowAlignment: LEFT, CENTER, RIGHT (支持)
19. VerticalAlignment: TOP, CENTER, BOTTOM (支持)
20. DeleteMode: ALL (支持), CONTENT (支持), RANGE (支持)
21. CommentType: POSITION (支持), CONTENT (支持)
22. FileType: PDF (支持，依赖 LibreOffice), TXT (支持)
23. ConvertPageType: ALL (支持), CURRENT/RANGE/SELECTION (由于 LibreOffice CLI 限制，全篇转换导出)
24. SaveFileType: WARN (支持), GENERATE (支持), OVERWRITE (支持)
25. UnderLineStyle: DEFAULT (支持), LINE (支持)
"""


@dataclass
class CursorPos:
    p_idx: int = 0
    offset: int = 0


class CursorModel:
    def __init__(self, p_idx: int = 0, offset: int = 0):
        self.p_idx = p_idx
        self.offset = offset
        self.selection_start: CursorPos | None = None
        self.selection_end: CursorPos | None = None

    @property
    def has_selection(self) -> bool:
        if self.selection_start is None or self.selection_end is None:
            return False
        return (self.selection_start.p_idx, self.selection_start.offset) != (
            self.selection_end.p_idx,
            self.selection_end.offset,
        )

    def clear_selection(self):
        self.selection_start = None
        self.selection_end = None

    def set_selection(self, start: CursorPos, end: CursorPos):
        if (start.p_idx, start.offset) <= (end.p_idx, end.offset):
            self.selection_start = CursorPos(start.p_idx, start.offset)
            self.selection_end = CursorPos(end.p_idx, end.offset)
        else:
            self.selection_start = CursorPos(end.p_idx, end.offset)
            self.selection_end = CursorPos(start.p_idx, start.offset)


class DocxDocument:
    def __init__(self, doc: Document, path: str = "", visible: bool = True):
        self.doc = doc
        self.path = path
        self.visible = visible
        self.cursor = CursorModel(0, 0)
        if not self.doc.paragraphs:
            self.doc.add_paragraph()

    @property
    def Name(self) -> str:  # noqa: N802
        return os.path.basename(self.path) if self.path else "新建Word文档.docx"

    @property
    def FullName(self) -> str:  # noqa: N802
        return self.path

    @property
    def paragraphs(self):
        return self.doc.paragraphs

    @property
    def tables(self):
        return self.doc.tables

    @property
    def comments(self):
        return self.doc.comments

    def __getattr__(self, name: str) -> Any:
        return getattr(self.doc, name)


def find_libreoffice() -> str | None:
    for candidate in [
        shutil.which("soffice"),
        shutil.which("libreoffice"),
        "/Applications/LibreOffice.app/Contents/MacOS/soffice",
    ]:
        if candidate and os.path.exists(candidate):
            return candidate
    return None


class WordDocumentCore(IDocumentCore):
    @classmethod
    def _unwrap(cls, doc: object) -> DocxDocument:
        if hasattr(doc, "document_object"):
            return doc.document_object
        return doc  # type: ignore[return-value]

    @classmethod
    def initialize_word_application(cls, default_application: ApplicationType = ApplicationType.DEFAULT) -> None:
        """macOS 下为基于 python-docx 的文件后端，无常驻后台 Word 进程，此处为空操作。"""
        return None

    @classmethod
    def open(
        cls,
        document_path: PATH = "",
        preferred_application: ApplicationType = ApplicationType.WORD,
        is_visible: bool = True,
        text_encoding: Any = EncodingType.UTF8,
        open_password: str = "",
        write_password: str = "",
        **kwargs,
    ) -> DocxDocument:
        path = document_path or kwargs.get("file_path", "")
        if not path:
            raise LookupError("没有输入路径，请检查输入的word路径是否正确!")

        if not os.path.exists(path):
            raise BaseException(
                DOCUMENT_PATH_ERROR_FORMAT.format(path),
                "填写的路径有误，请输入正确的路径！",
            )

        # 二进制 .doc 文件尝试通过 LibreOffice 转为 .docx
        working_path = path
        if path.endswith(".doc"):
            soffice = find_libreoffice()
            if not soffice:
                msg = (
                    "打开 .doc 二进制文件需要 LibreOffice，"
                    "但未找到 soffice 命令或 /Applications/LibreOffice.app，"
                    "请安装 LibreOffice 或转换为 .docx 后打开！"
                )
                raise BaseException(
                    DOCUMENT_READ_ERROR_FORMAT.format(f"{path} (需要 LibreOffice)"),
                    msg,
                )
            tmp_dir = tempfile.mkdtemp(prefix="astron_doc_")
            try:
                cmd = [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "docx",
                    "--outdir",
                    tmp_dir,
                    path,
                ]
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                )
                base = os.path.splitext(os.path.basename(path))[0]
                converted_docx = os.path.join(tmp_dir, base + ".docx")
                if not os.path.exists(converted_docx):
                    raise FileNotFoundError(f"未能生成转换后的 docx 文件: {converted_docx}")
                working_path = converted_docx
            except Exception as e:
                raise BaseException(
                    DOCUMENT_READ_ERROR_FORMAT.format(path),
                    f"LibreOffice 转换 .doc 文件失败: {e}",
                ) from e

        try:
            doc = Document(working_path)
            return DocxDocument(doc, path=path, visible=is_visible)
        except Exception as e:
            raise BaseException(
                DOCUMENT_READ_ERROR_FORMAT.format(path),
                "打开文档失败，请检查文件是否损坏！",
            ) from e

    @classmethod
    def read(
        cls,
        document: object,
        content_selection_range=SelectRangeType.ALL,
        **kwargs,
    ) -> str:
        doc = cls._unwrap(document)
        select_range = kwargs.get("select_range", content_selection_range)
        if select_range == SelectRangeType.SELECTED:
            if not doc.cursor.has_selection:
                return ""
            s = doc.cursor.selection_start
            e = doc.cursor.selection_end
            if s.p_idx == e.p_idx:
                return doc.doc.paragraphs[s.p_idx].text[s.offset : e.offset]
            parts = [doc.doc.paragraphs[s.p_idx].text[s.offset :]]
            for p_i in range(s.p_idx + 1, e.p_idx):
                parts.append(doc.doc.paragraphs[p_i].text)
            parts.append(doc.doc.paragraphs[e.p_idx].text[: e.offset])
            return "\n".join(parts)
        else:
            document_content = ""
            for paragraph in doc.doc.paragraphs:
                document_content += paragraph.text + "\n"
            return document_content

    @classmethod
    def create(
        cls,
        file_path: str = "",
        file_name: str = "",
        visible_flag: bool = True,
        default_application: ApplicationType = ApplicationType.WORD,
        exist_handle_type: FileExistenceType = FileExistenceType.RENAME,
    ) -> tuple[DocxDocument, str]:
        doc = Document()
        new_file_path = ""
        if file_path and file_name:
            tentative_path = os.path.join(file_path, file_name)
            new_file_path = IDocumentCore.handle_existence(tentative_path, exist_handle_type)
            if new_file_path:
                try:
                    doc.save(new_file_path)
                except Exception as e:
                    raise RuntimeError(f"文档保存失败: {e}") from e
        docx_doc = DocxDocument(doc, path=new_file_path, visible=visible_flag)
        return docx_doc, new_file_path

    @classmethod
    def save(
        cls,
        doc: object,
        file_path: str = "",
        file_name: str = "",
        save_type=SaveType.SAVE,
        exist_handle_type: FileExistenceType = FileExistenceType.RENAME,
        close_flag: bool = False,
    ) -> PATH:
        docx_doc = cls._unwrap(doc)
        save_file_path = None
        if save_type == SaveType.SAVE_AS and file_path:
            ext = os.path.splitext(docx_doc.Name)[1] or ".docx"
            name = file_name or os.path.splitext(docx_doc.Name)[0]
            target_path = os.path.join(file_path, name + ext)
            new_path = IDocumentCore.handle_existence(target_path, exist_handle_type)
            if new_path:
                docx_doc.doc.save(new_path)
                docx_doc.path = new_path
                save_file_path = new_path
        elif save_type == SaveType.SAVE:
            if not docx_doc.path:
                raise BaseException(DOCUMENT_PATH_ERROR_FORMAT.format(""), "文件路径未指定，无法保存！")
            docx_doc.doc.save(docx_doc.path)
            save_file_path = docx_doc.path

        if close_flag:
            cls.close(docx_doc)

        return save_file_path or ""

    @classmethod
    def close(
        cls,
        doc: object,
        file_path: str = "",
        file_name: str = "",
        save_type=SaveType.SAVE,
        exist_handle_type: FileExistenceType = FileExistenceType.RENAME,
        close_range_flag: CloseRangeType = CloseRangeType.ONE,
        pkill_flag: bool = False,
    ):
        docx_doc = cls._unwrap(doc)
        if close_range_flag == CloseRangeType.ALL:
            # macOS 下无常驻进程，空操作
            return
        else:
            if save_type in (SaveType.SAVE, SaveType.SAVE_AS):
                cls.save(
                    docx_doc,
                    file_path=file_path,
                    file_name=file_name,
                    save_type=save_type,
                    exist_handle_type=exist_handle_type,
                )

    # ----------------- 光标与文本切分辅助方法 -----------------

    @staticmethod
    def _split_run_at(p, offset: int):
        """将段落 p 中位于字符偏移 offset 处的 Run 切分成两个独立的 Run，保持各自格式。"""
        curr = 0
        for r in list(p.runs):
            r_len = len(r.text)
            if curr < offset < curr + r_len:
                local = offset - curr
                new_r_elem = deepcopy(r._r)
                new_run = Run(new_r_elem, p)
                new_run.text = r.text[local:]
                r.text = r.text[:local]
                r._r.addnext(new_r_elem)
                return
            curr += r_len

    @classmethod
    def _insert_element_at(cls, p, offset: int, element):
        """在段落 p 的 offset 字符边界处插入一个 XML 元素 (Run / Hyperlink / Drawing 等)。"""
        cls._split_run_at(p, offset)
        curr = 0
        prev_r = None
        next_r = None
        for r in p.runs:
            if curr == offset:
                next_r = r
                break
            prev_r = r
            curr += len(r.text)
        if prev_r is not None:
            prev_r._r.addnext(element)
        elif next_r is not None:
            next_r._r.addprevious(element)
        else:
            p._element.append(element)

    @classmethod
    def _delete_in_paragraph(cls, p, start: int, end: int):
        """删除段落 p 内 [start, end] 范围内的文本，保留其余部分及其 Run 格式。"""
        if start >= end:
            return
        cls._split_run_at(p, end)
        cls._split_run_at(p, start)
        curr = 0
        for r in list(p.runs):
            r_len = len(r.text)
            if curr >= start and curr + r_len <= end:
                p._element.remove(r._r)
            curr += r_len

    @classmethod
    def _delete_selection(cls, docx_doc: DocxDocument):
        """删除当前激活的选区。"""
        if not docx_doc.cursor.has_selection:
            return
        s = docx_doc.cursor.selection_start
        e = docx_doc.cursor.selection_end
        if s.p_idx == e.p_idx:
            cls._delete_in_paragraph(docx_doc.doc.paragraphs[s.p_idx], s.offset, e.offset)
        else:
            p_start = docx_doc.doc.paragraphs[s.p_idx]
            cls._delete_in_paragraph(p_start, s.offset, len(p_start.text))
            for _ in range(s.p_idx + 1, e.p_idx):
                p_mid = docx_doc.doc.paragraphs[s.p_idx + 1]
                p_mid._element.getparent().remove(p_mid._element)
            p_end = docx_doc.doc.paragraphs[s.p_idx + 1]
            cls._delete_in_paragraph(p_end, 0, e.offset)
            for r in list(p_end.runs):
                p_start._element.append(r._r)
            p_end._element.getparent().remove(p_end._element)

        docx_doc.cursor.p_idx = s.p_idx
        docx_doc.cursor.offset = s.offset
        docx_doc.cursor.clear_selection()

    @classmethod
    def _normalize_cursor(cls, docx_doc: DocxDocument):
        """规范化光标位置，防止段落和字符越界。"""
        if not docx_doc.doc.paragraphs:
            docx_doc.doc.add_paragraph()
        if docx_doc.cursor.p_idx >= len(docx_doc.doc.paragraphs):
            docx_doc.cursor.p_idx = len(docx_doc.doc.paragraphs) - 1
        if docx_doc.cursor.p_idx < 0:
            docx_doc.cursor.p_idx = 0
        p_len = len(docx_doc.doc.paragraphs[docx_doc.cursor.p_idx].text)
        if docx_doc.cursor.offset > p_len:
            docx_doc.cursor.offset = p_len
        if docx_doc.cursor.offset < 0:
            docx_doc.cursor.offset = 0

    # ----------------- 公开操作实现 -----------------

    @classmethod
    def insert(
        cls,
        doc: object,
        text: str = "",
        enter_flag: bool = False,
        text_format: dict | None = None,
    ):
        docx_doc = cls._unwrap(doc)
        cls._normalize_cursor(docx_doc)

        if docx_doc.cursor.has_selection:
            cls._delete_selection(docx_doc)

        p = docx_doc.doc.paragraphs[docx_doc.cursor.p_idx]
        offset = docx_doc.cursor.offset

        if enter_flag:
            cls._split_run_at(p, offset)
            p_new = docx_doc.doc.add_paragraph()
            p._element.addnext(p_new._element)
            curr = 0
            for r in list(p.runs):
                r_len = len(r.text)
                if curr >= offset:
                    p_new._element.append(r._r)
                curr += r_len
            docx_doc.cursor.p_idx += 1
            docx_doc.cursor.offset = 0
            p = p_new
            offset = 0

        # 执行分段并插入新文本
        cls._split_run_at(p, offset)
        curr = 0
        prev_r = None
        next_r = None
        for r in p.runs:
            if curr == offset:
                next_r = r
                break
            prev_r = r
            curr += len(r.text)

        if prev_r is not None:
            ins_elem = deepcopy(prev_r._r)
            ins_run = Run(ins_elem, p)
            ins_run.text = text
            prev_r._r.addnext(ins_elem)
        elif next_r is not None:
            ins_elem = deepcopy(next_r._r)
            ins_run = Run(ins_elem, p)
            ins_run.text = text
            next_r._r.addprevious(ins_elem)
        else:
            ins_run = p.add_run(text)

        # 应用格式配置
        if text_format:
            if text_format.get("bold") is not None:
                ins_run.bold = text_format["bold"]
            if text_format.get("italic") is not None:
                ins_run.italic = text_format["italic"]
            if text_format.get("underline") is not None:
                ins_run.underline = bool(text_format["underline"])
            if text_format.get("font_name"):
                name = text_format["font_name"]
                ins_run.font.name = name
                ins_run._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), name)
            if text_format.get("font_size"):
                ins_run.font.size = Pt(int(text_format["font_size"]))
            if text_format.get("font_color"):
                try:
                    rgb = [int(c.strip()) for c in text_format["font_color"].split(",")]
                    ins_run.font.color.rgb = RGBColor(rgb[0], rgb[1], rgb[2])
                except Exception as e:
                    logger.warning("解析字体颜色失败: %s", e)

        docx_doc.cursor.offset += len(text)
        docx_doc.cursor.clear_selection()

    @classmethod
    def replace(
        cls,
        doc: object,
        replace_type: ReplaceType = ReplaceType.STR,
        origin_word: str = "",
        new_word: str = "",
        img_path: str = "",
        replace_method: ReplaceMethodType = ReplaceMethodType.ALL,
        ignore_case: bool = True,
    ) -> int:
        docx_doc = cls._unwrap(doc)
        if not origin_word:
            return 0

        if replace_type == ReplaceType.IMG:
            if not img_path or not os.path.isfile(img_path):
                raise BaseException(DOCUMENT_PATH_ERROR_FORMAT.format(img_path), "图片路径错误")

        flags = re.IGNORECASE if ignore_case else 0
        pattern = re.compile(re.escape(origin_word), flags)

        # 收集所有段落（含普通段落和表格内段落）
        all_paragraphs = list(docx_doc.doc.paragraphs)
        for tbl in docx_doc.doc.tables:
            for row in tbl.rows:
                for cell in row.cells:
                    all_paragraphs.extend(cell.paragraphs)

        replace_count = 0
        for p in all_paragraphs:
            while True:
                match = pattern.search(p.text)
                if not match:
                    break

                start, end = match.start(), match.end()
                cls._split_run_at(p, end)
                cls._split_run_at(p, start)

                # 定位并替换范围内的 Run
                curr = 0
                first_r = None
                prev_r = None
                for r in list(p.runs):
                    r_len = len(r.text)
                    if curr >= start and curr + r_len <= end:
                        if first_r is None:
                            first_r = r
                        else:
                            p._element.remove(r._r)
                    elif curr + r_len <= start:
                        prev_r = r
                    curr += r_len

                if replace_type == ReplaceType.STR:
                    if first_r is not None:
                        first_r.text = new_word
                    elif prev_r is not None:
                        ins = Run(deepcopy(prev_r._r), p)
                        ins.text = new_word
                        prev_r._r.addnext(ins._r)
                    else:
                        p.add_run(new_word)
                else:
                    # 替换为图片
                    pic_run = p.add_run()
                    pic_run.add_picture(img_path)
                    if first_r is not None:
                        first_r._r.addnext(pic_run._r)
                        p._element.remove(first_r._r)
                    elif prev_r is not None:
                        prev_r._r.addnext(pic_run._r)

                replace_count += 1
                if replace_method == ReplaceMethodType.FIRST:
                    return replace_count

        return replace_count

    @classmethod
    def select(
        cls,
        doc: object,
        select_type: SelectTextType = SelectTextType.ALL,
        p_start: int = 1,
        p_end: int = 1,
        r_start: int = 1,
        r_end: int = 1,
    ):
        docx_doc = cls._unwrap(doc)
        if select_type == SelectTextType.ALL:
            last_p = max(0, len(docx_doc.doc.paragraphs) - 1)
            start = CursorPos(0, 0)
            end = CursorPos(last_p, len(docx_doc.doc.paragraphs[last_p].text))
            docx_doc.cursor.set_selection(start, end)
            docx_doc.cursor.p_idx = end.p_idx
            docx_doc.cursor.offset = end.offset
        elif select_type == SelectTextType.PARAGRAPH:
            p_count = len(docx_doc.doc.paragraphs)
            if p_start < 1 or p_end < 1 or p_start > p_count or p_end > p_count or p_start > p_end:
                raise BaseException(
                    CONTENT_FORMAT_ERROR_FORMAT,
                    f"段落号超出范围 (1-{p_count})！",
                )
            start = CursorPos(p_start - 1, 0)
            end = CursorPos(p_end - 1, len(docx_doc.doc.paragraphs[p_end - 1].text))
            docx_doc.cursor.set_selection(start, end)
            docx_doc.cursor.p_idx = end.p_idx
            docx_doc.cursor.offset = end.offset
        elif select_type == SelectTextType.ROW:
            msg = "python-docx 后端不支持按行(row)选中文本，请使用全选或按段落选择！"
            raise BaseException(CONTENT_FORMAT_ERROR_FORMAT.format(msg), msg)
        else:
            msg = f"不支持的选择模式: {select_type}"
            raise BaseException(CONTENT_FORMAT_ERROR_FORMAT.format(msg), msg)

    @classmethod
    def cursor_position(
        cls,
        doc,
        by: CursorPointerType = CursorPointerType.ALL,
        pos: CursorPositionType = CursorPositionType.HEAD,
        content: str = "",
        c_idx: int = 1,
        p_idx: int = 1,
        r_idx: int = 1,
    ):
        docx_doc = cls._unwrap(doc)
        if by == CursorPointerType.CONTENT:
            if not content:
                raise BaseException(
                    CONTENT_FORMAT_ERROR_FORMAT,
                    "请填写要定位光标的文本内容,目前不支持空内容的定位!!!",
                )
            count = 0
            found = False
            for p_i, p in enumerate(docx_doc.doc.paragraphs):
                idx = 0
                while True:
                    match_pos = p.text.find(content, idx)
                    if match_pos == -1:
                        break
                    count += 1
                    if count == c_idx:
                        docx_doc.cursor.p_idx = p_i
                        docx_doc.cursor.offset = (
                            match_pos if pos == CursorPositionType.HEAD else match_pos + len(content)
                        )
                        docx_doc.cursor.clear_selection()
                        found = True
                        break
                    idx = match_pos + len(content)
                if found:
                    break
            if not found:
                raise BaseException(CONTENT_FORMAT_ERROR_FORMAT, "内容不存在！")

        elif by == CursorPointerType.ALL:
            if pos == CursorPositionType.HEAD:
                docx_doc.cursor.p_idx = 0
                docx_doc.cursor.offset = 0
            else:
                last_p = max(0, len(docx_doc.doc.paragraphs) - 1)
                docx_doc.cursor.p_idx = last_p
                docx_doc.cursor.offset = len(docx_doc.doc.paragraphs[last_p].text)
            docx_doc.cursor.clear_selection()

        elif by == CursorPointerType.PARAGRAPH:
            p_count = len(docx_doc.doc.paragraphs)
            if p_idx < 1 or p_idx > p_count:
                raise BaseException(CONTENT_FORMAT_ERROR_FORMAT, f"段落号超出范围 (共 {p_count} 段)！")
            target_p = p_idx - 1
            docx_doc.cursor.p_idx = target_p
            if pos == CursorPositionType.HEAD:
                docx_doc.cursor.offset = 0
            elif pos == CursorPositionType.TAIL:
                docx_doc.cursor.offset = len(docx_doc.doc.paragraphs[target_p].text)
            else:
                raise BaseException(CONTENT_FORMAT_ERROR_FORMAT, "不支持的参考位置，请检查pos参数！")
            docx_doc.cursor.clear_selection()

        elif by == CursorPointerType.ROW:
            msg = "python-docx 后端不支持按行(row)定位光标，请使用按段落或全文定位！"
            raise BaseException(CONTENT_FORMAT_ERROR_FORMAT.format(msg), msg)
        else:
            msg = f"不支持的定位方式: {by}"
            raise BaseException(CONTENT_FORMAT_ERROR_FORMAT.format(msg), msg)

    @classmethod
    def move_cursor(
        cls,
        doc: object = None,
        direction: MoveDirectionType = MoveDirectionType.UP,
        unitupdown: MoveUpDownType = MoveUpDownType.ROW,
        unitleftright: MoveLeftRightType = MoveLeftRightType.CHARACTER,
        distance: int = 0,
        with_shift: bool = False,
    ):
        docx_doc = cls._unwrap(doc)
        cls._normalize_cursor(docx_doc)
        old_pos = CursorPos(docx_doc.cursor.p_idx, docx_doc.cursor.offset)

        if direction in (MoveDirectionType.UP, MoveDirectionType.DOWN):
            if unitupdown == MoveUpDownType.ROW:
                msg = "python-docx 后端不支持按行(row)移动光标，请使用段落(paragraph)移动！"
                raise BaseException(CONTENT_FORMAT_ERROR_FORMAT.format(msg), msg)
            elif unitupdown == MoveUpDownType.PARAGRAPH:
                if direction == MoveDirectionType.UP:
                    new_p = max(0, docx_doc.cursor.p_idx - distance)
                else:
                    new_p = min(
                        len(docx_doc.doc.paragraphs) - 1,
                        docx_doc.cursor.p_idx + distance,
                    )
                new_off = min(
                    docx_doc.cursor.offset,
                    len(docx_doc.doc.paragraphs[new_p].text),
                )
                new_pos = CursorPos(new_p, new_off)
            else:
                raise BaseException(CONTENT_FORMAT_ERROR_FORMAT, f"不支持的移动单位: {unitupdown}")

        elif direction in (MoveDirectionType.LEFT, MoveDirectionType.RIGHT):
            cur_p = docx_doc.cursor.p_idx
            cur_off = docx_doc.cursor.offset
            if unitleftright == MoveLeftRightType.CHARACTER:
                rem = distance
                if direction == MoveDirectionType.LEFT:
                    while rem > 0:
                        if cur_off >= rem:
                            cur_off -= rem
                            rem = 0
                        else:
                            rem -= cur_off + 1
                            if cur_p > 0:
                                cur_p -= 1
                                cur_off = len(docx_doc.doc.paragraphs[cur_p].text)
                            else:
                                cur_off = 0
                                rem = 0
                else:
                    while rem > 0:
                        p_len = len(docx_doc.doc.paragraphs[cur_p].text)
                        avail = p_len - cur_off
                        if avail >= rem:
                            cur_off += rem
                            rem = 0
                        else:
                            rem -= avail + 1
                            if cur_p < len(docx_doc.doc.paragraphs) - 1:
                                cur_p += 1
                                cur_off = 0
                            else:
                                cur_off = p_len
                                rem = 0
                new_pos = CursorPos(cur_p, cur_off)
            elif unitleftright == MoveLeftRightType.WORD:
                p_text = docx_doc.doc.paragraphs[cur_p].text
                words = list(re.finditer(r"\b\w+\b", p_text))
                if direction == MoveDirectionType.LEFT:
                    target_off = 0
                    for w in reversed(words):
                        if w.start() < cur_off:
                            target_off = w.start()
                            break
                    new_pos = CursorPos(cur_p, target_off)
                else:
                    target_off = len(p_text)
                    for w in words:
                        if w.end() > cur_off:
                            target_off = w.end()
                            break
                    new_pos = CursorPos(cur_p, target_off)
            else:
                raise BaseException(CONTENT_FORMAT_ERROR_FORMAT, f"不支持的左右移动单位: {unitleftright}")
        else:
            raise BaseException(CONTENT_FORMAT_ERROR_FORMAT, f"不支持的移动方向: {direction}")

        if with_shift:
            if not docx_doc.cursor.has_selection:
                docx_doc.cursor.set_selection(old_pos, new_pos)
            else:
                anchor = (
                    docx_doc.cursor.selection_start
                    if (old_pos.p_idx, old_pos.offset)
                    == (
                        docx_doc.cursor.selection_end.p_idx,
                        docx_doc.cursor.selection_end.offset,
                    )
                    else docx_doc.cursor.selection_end
                )
                docx_doc.cursor.set_selection(anchor, new_pos)
        else:
            docx_doc.cursor.clear_selection()

        docx_doc.cursor.p_idx = new_pos.p_idx
        docx_doc.cursor.offset = new_pos.offset

    @classmethod
    def insert_sep(
        cls,
        doc: object = None,
        sep_type: InsertionType = InsertionType.PARAGRAPH,
    ):
        docx_doc = cls._unwrap(doc)
        cls._normalize_cursor(docx_doc)

        if docx_doc.cursor.has_selection:
            cls._delete_selection(docx_doc)

        p = docx_doc.doc.paragraphs[docx_doc.cursor.p_idx]
        offset = docx_doc.cursor.offset

        if sep_type == InsertionType.PARAGRAPH:
            cls._split_run_at(p, offset)
            p_new = docx_doc.doc.add_paragraph()
            p._element.addnext(p_new._element)
            curr = 0
            for r in list(p.runs):
                r_len = len(r.text)
                if curr >= offset:
                    p_new._element.append(r._r)
                curr += r_len
            docx_doc.cursor.p_idx += 1
            docx_doc.cursor.offset = 0

        elif sep_type == InsertionType.PAGE:
            br_run = OxmlElement("w:r")
            br = OxmlElement("w:br")
            br.set(qn("w:type"), "page")
            br_run.append(br)
            cls._insert_element_at(p, offset, br_run)
        else:
            raise BaseException(
                CONTENT_FORMAT_ERROR_FORMAT,
                "不支持的分隔符类型，请检查传入的sep_type参数！",
            )

    @classmethod
    def insert_hyperlink(cls, doc: object = None, url: str = "", display: str = ""):
        docx_doc = cls._unwrap(doc)
        cls._normalize_cursor(docx_doc)

        if docx_doc.cursor.has_selection:
            cls._delete_selection(docx_doc)

        p = docx_doc.doc.paragraphs[docx_doc.cursor.p_idx]
        offset = docx_doc.cursor.offset
        cls._split_run_at(p, offset)

        display_text = display or url
        part = p.part
        r_id = part.relate_to(url, RT.HYPERLINK, is_external=True)

        hyperlink = OxmlElement("w:hyperlink")
        hyperlink.set(qn("r:id"), r_id)

        new_run = OxmlElement("w:r")
        rPr = OxmlElement("w:rPr")
        c = OxmlElement("w:color")
        c.set(qn("w:val"), "0000FF")
        rPr.append(c)
        u = OxmlElement("w:u")
        u.set(qn("w:val"), "single")
        rPr.append(u)
        new_run.append(rPr)

        text_elem = OxmlElement("w:t")
        text_elem.text = display_text
        new_run.append(text_elem)
        hyperlink.append(new_run)

        cls._insert_element_at(p, offset, hyperlink)
        docx_doc.cursor.offset += len(display_text)

    @classmethod
    def insert_img(
        cls,
        doc,
        img_from: InsertImgType = InsertImgType.FILE,
        img_path: str = "",
        scale: int = 100,
        newline: bool = False,
    ):
        docx_doc = cls._unwrap(doc)
        cls._normalize_cursor(docx_doc)

        if docx_doc.cursor.has_selection:
            cls._delete_selection(docx_doc)

        temp_img_file = None
        target_path = img_path
        if img_from == InsertImgType.CLIPBOARD:
            try:
                clip = ImageGrab.grabclipboard()
            except Exception as e:
                raise BaseException(CLIPBOARD_PASTE_ERROR.format("无法获取剪贴板数据"), "") from e

            if isinstance(clip, Image.Image):
                with tempfile.NamedTemporaryFile(delete=False, suffix=".png") as temp_file:
                    temp_img_file = temp_file.name
                clip.save(temp_img_file, format="PNG")
                target_path = temp_img_file
            elif isinstance(clip, list):
                for p in clip:
                    if p.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".gif")):
                        target_path = p
                        break
                else:
                    raise BaseException(CLIPBOARD_PASTE_ERROR.format("剪贴板中没有图片文件"), "")
            else:
                raise BaseException(CLIPBOARD_PASTE_ERROR.format("剪贴板没有图片数据"), "")

        if not target_path or not os.path.isfile(target_path):
            if temp_img_file and os.path.exists(temp_img_file):
                os.remove(temp_img_file)
            raise BaseException(DOCUMENT_PATH_ERROR_FORMAT.format(target_path), "图片路径错误")

        try:
            if newline:
                p = docx_doc.doc.add_paragraph()
                docx_doc.cursor.p_idx = len(docx_doc.doc.paragraphs) - 1
                docx_doc.cursor.offset = 0
            else:
                p = docx_doc.doc.paragraphs[docx_doc.cursor.p_idx]

            offset = docx_doc.cursor.offset
            cls._split_run_at(p, offset)

            pic_run = p.add_run()
            picture = pic_run.add_picture(target_path)
            if scale != 100:
                picture.width = int(picture.width * (scale / 100.0))
                picture.height = int(picture.height * (scale / 100.0))

            if not newline:
                curr = 0
                prev_r = None
                for r in p.runs:
                    if r is pic_run:
                        continue
                    if curr == offset:
                        break
                    prev_r = r
                    curr += len(r.text)
                if prev_r is not None:
                    prev_r._r.addnext(pic_run._r)
        finally:
            if temp_img_file and os.path.exists(temp_img_file):
                os.remove(temp_img_file)

    @classmethod
    def read_table(
        cls,
        doc: object,
        search_type: SearchTableType = SearchTableType.IDX,
        idx: int = 1,
        text: str = "",
    ) -> list[list[str]]:
        docx_doc = cls._unwrap(doc)
        table_content: list[list[str]] = []
        if search_type == SearchTableType.IDX:
            try:
                table = docx_doc.doc.tables[idx - 1]
                table_content = cls._extract_table_content(table)
            except Exception as e:
                raise BaseException(TABLE_NOT_EXIST_ERROR.format("序号" + str(idx))) from e
        elif search_type == SearchTableType.TEXT:
            count = 0
            for table in docx_doc.doc.tables:
                if any(text in cell.text for row in table.rows for cell in row.cells):
                    count += 1
                    if count == idx:
                        table_content = cls._extract_table_content(table)
                        return table_content
            if not table_content:
                raise BaseException(TABLE_NOT_EXIST_ERROR.format("内容" + str(text)))
        return table_content

    @staticmethod
    def _extract_table_content(table) -> list[list[str]]:
        content = []
        for row in table.rows:
            row_content = []
            for cell in row.cells:
                cell_text = re.sub(r"[\x00-\x1F\x7F]", "", cell.text).strip()
                row_content.append(cell_text)
            content.append(row_content)
        return content

    @classmethod
    def insert_table(
        cls,
        doc: object,
        table_content: list = "",
        table_behavior: TableBehavior = TableBehavior.DEFAULT,
        alignment: RowAlignment = RowAlignment.LEFT,
        v_alignment: VerticalAlignment = VerticalAlignment.TOP,
        border: bool = True,
        if_change_font: bool = False,
        font_size=None,
        font_color=None,
        font_set=None,
        font_bold: bool = False,
        font_italic: bool = False,
        underline: UnderLineStyle = UnderLineStyle.DEFAULT,
        newline: bool = True,
    ):
        docx_doc = cls._unwrap(doc)
        rows = len(table_content)
        cols = len(table_content[0]) if rows > 0 else 0

        table = docx_doc.doc.add_table(rows=rows, cols=cols)
        if border:
            table.style = "Table Grid"
        table.autofit = table_behavior == TableBehavior.AUTO

        if docx_doc.doc.paragraphs:
            p = docx_doc.doc.paragraphs[docx_doc.cursor.p_idx]
            p._element.addnext(table._tbl)

        for row_idx, row_data in enumerate(table_content):
            row = table.rows[row_idx]
            for col_idx, cell_data in enumerate(row_data):
                cell = row.cells[col_idx]
                cell.text = str(cell_data) + ("\n" if newline else "")
                cell.vertical_alignment = v_alignment.value
                for p in cell.paragraphs:
                    p.alignment = alignment.value
                    if if_change_font:
                        for r in p.runs:
                            r.font.name = font_set or "宋体"
                            r._r.get_or_add_rPr().get_or_add_rFonts().set(qn("w:eastAsia"), font_set or "宋体")
                            r.font.size = Pt(font_size or 12)
                            r.bold = font_bold
                            r.italic = font_italic
                            r.underline = underline.value if underline else UnderLineStyle.DEFAULT.value
                            if font_color:
                                if isinstance(font_color, (list, tuple)):
                                    r.font.color.rgb = RGBColor(*font_color)
                                elif isinstance(font_color, str):
                                    rgb = [int(c.strip()) for c in font_color.split(",")]
                                    r.font.color.rgb = RGBColor(*rgb)

    @classmethod
    def delete(
        cls,
        doc: object,
        delete_mode: DeleteMode = DeleteMode.ALL,
        delete_str: str = "",
        delete_idx: int = 0,
        str_delete_all: bool = False,
        p_start: int = 0,
        c_start: int = 0,
        p_end: int = 0,
        c_end: int = 0,
    ):
        docx_doc = cls._unwrap(doc)
        if delete_mode == DeleteMode.ALL:
            for p in list(docx_doc.doc.paragraphs):
                p._element.getparent().remove(p._element)
            for tbl in list(docx_doc.doc.tables):
                tbl._element.getparent().remove(tbl._element)
            docx_doc.doc.add_paragraph()
            docx_doc.cursor.p_idx = 0
            docx_doc.cursor.offset = 0
            docx_doc.cursor.clear_selection()

        elif delete_mode == DeleteMode.CONTENT:
            if not delete_str:
                return
            if str_delete_all:
                for p in docx_doc.doc.paragraphs:
                    while delete_str in p.text:
                        pos = p.text.find(delete_str)
                        cls._delete_in_paragraph(p, pos, pos + len(delete_str))
            else:
                count = 0
                for p in docx_doc.doc.paragraphs:
                    idx = 0
                    while True:
                        pos = p.text.find(delete_str, idx)
                        if pos == -1:
                            break
                        count += 1
                        if count == delete_idx:
                            cls._delete_in_paragraph(p, pos, pos + len(delete_str))
                            return
                        idx = pos + len(delete_str)

        elif delete_mode == DeleteMode.RANGE:
            p_count = len(docx_doc.doc.paragraphs)
            ps = max(0, (p_start - 1) if p_start > 0 else 0)
            pe = max(0, (p_end - 1) if p_end > 0 else 0)
            if ps >= p_count or pe >= p_count:
                return
            cs = max(0, c_start)
            ce = max(0, c_end)

            if ps == pe:
                cls._delete_in_paragraph(docx_doc.doc.paragraphs[ps], cs, ce)
            else:
                p_s = docx_doc.doc.paragraphs[ps]
                cls._delete_in_paragraph(p_s, cs, len(p_s.text))
                for _ in range(ps + 1, pe):
                    p_mid = docx_doc.doc.paragraphs[ps + 1]
                    p_mid._element.getparent().remove(p_mid._element)
                p_e = docx_doc.doc.paragraphs[ps + 1]
                cls._delete_in_paragraph(p_e, 0, ce)
                for r in list(p_e.runs):
                    p_s._element.append(r._r)
                p_e._element.getparent().remove(p_e._element)

    @classmethod
    def create_comment(
        cls,
        doc: object = None,
        paragraph_idx: int = 1,
        start: int = 1,
        end: int = 1,
        comment: str = "",
        comment_type: CommentType = CommentType.POSITION,
        target_str: str = "",
        comment_all: bool = True,
        comment_index: int = 1,
    ):
        docx_doc = cls._unwrap(doc)
        if not hasattr(docx_doc.doc, "add_comment"):
            raise BaseException(
                DOCUMENT_READ_ERROR_FORMAT.format("python-docx"),
                "当前 python-docx 版本不支持批注，需 >= 1.2！",
            )

        def _slice_runs(p, s_off, e_off):
            if not p.runs:
                p.add_run()
                return [p.runs[0]]
            cls._split_run_at(p, e_off)
            cls._split_run_at(p, s_off)
            selected = []
            curr = 0
            for r in p.runs:
                r_len = len(r.text)
                if curr >= s_off and curr + r_len <= e_off:
                    selected.append(r)
                curr += r_len
            if not selected:
                selected = [p.runs[0]]
            return selected

        if comment_type == CommentType.POSITION:
            p_count = len(docx_doc.doc.paragraphs)
            if paragraph_idx < 1 or paragraph_idx > p_count:
                raise BaseException(CONTENT_FORMAT_ERROR_FORMAT, f"段落号超出范围 (共 {p_count} 段)！")
            p = docx_doc.doc.paragraphs[paragraph_idx - 1]
            s_off = max(0, min(start, len(p.text)))
            e_off = max(s_off, min(end, len(p.text)))
            runs = _slice_runs(p, s_off, e_off)
            docx_doc.doc.add_comment(runs, comment)

        elif comment_type == CommentType.CONTENT:
            if not target_str:
                return
            count = 0
            for p in docx_doc.doc.paragraphs:
                idx = 0
                while True:
                    pos = p.text.find(target_str, idx)
                    if pos == -1:
                        break
                    count += 1
                    if comment_all or count == comment_index:
                        runs = _slice_runs(p, pos, pos + len(target_str))
                        docx_doc.doc.add_comment(runs, comment)
                        if not comment_all:
                            return
                    idx = pos + len(target_str)

    @classmethod
    def delete_comment(cls, doc: object = None, comment_index: int = 1, delete_all: bool = False):
        docx_doc = cls._unwrap(doc)
        if not hasattr(docx_doc.doc, "comments") or docx_doc.doc.comments is None:
            return

        comments = list(docx_doc.doc.comments)
        to_delete = (
            comments if delete_all else ([comments[comment_index - 1]] if 1 <= comment_index <= len(comments) else [])
        )

        for c in to_delete:
            cid = str(c.comment_id)
            for el in docx_doc.doc._element.xpath(f'//*[@w:id="{cid}"]'):
                parent = el.getparent()
                if parent is not None:
                    parent.remove(el)
            if hasattr(docx_doc.doc.comments, "_comments_elm"):
                for el in docx_doc.doc.comments._comments_elm.xpath(f'//*[@w:id="{cid}"]'):
                    parent = el.getparent()
                    if parent is not None:
                        parent.remove(el)

    @classmethod
    def convert_to_txt(
        cls,
        doc: object = None,
        output_path: str = "",
        output_name: str = "",
        save_type: SaveFileType = SaveFileType.WARN,
    ):
        filename = f"{output_name}.txt"
        if IDocumentCore.check_file_in_path(output_path, filename):
            if save_type == SaveFileType.WARN:
                raise BaseException(FILENAME_ALREADY_EXISTS_ERROR.format(filename), "")
            if save_type == SaveFileType.GENERATE:
                counter = 1
                oldfilename, _ = os.path.splitext(filename)
                while IDocumentCore.check_file_in_path(output_path, filename):
                    filename = f"{oldfilename}_{counter}.txt"
                    counter += 1
            elif save_type == SaveFileType.OVERWRITE:
                fullpath = os.path.join(output_path, filename)
                if os.path.exists(fullpath):
                    os.remove(fullpath)

        docx_doc = cls._unwrap(doc)
        new_path = os.path.join(output_path, filename)
        with open(new_path, "w", encoding="utf-8") as txt_file:
            txt_file.writelines(para.text + "\n" for para in docx_doc.doc.paragraphs)
            for table in docx_doc.doc.tables:
                for row in table.rows:
                    row_texts = [cell.text.replace("\n", " ").strip() for cell in row.cells]
                    txt_file.write("\t".join(row_texts) + "\n")

    @classmethod
    def convert_to_pdf(
        cls,
        doc: object = None,
        output_path: str = "",
        output_name: str = "新建PDF",
        page_type: ConvertPageType = ConvertPageType.ALL,
        page_start: int = 1,
        page_end: int = 1,
        save_type: SaveFileType = SaveFileType.WARN,
    ):
        soffice = find_libreoffice()
        if not soffice:
            raise BaseException(
                DOCUMENT_READ_ERROR_FORMAT.format("LibreOffice"),
                "未找到 LibreOffice，转换 PDF 需要安装 LibreOffice"
                "（请确保在 PATH 中配置 soffice 或安装在 /Applications/LibreOffice.app）！",
            )

        filename = f"{output_name}.pdf"
        if IDocumentCore.check_file_in_path(output_path, filename):
            if save_type == SaveFileType.WARN:
                raise BaseException(FILENAME_ALREADY_EXISTS_ERROR.format(filename), "")
            if save_type == SaveFileType.GENERATE:
                counter = 1
                oldfilename, _ = os.path.splitext(filename)
                while IDocumentCore.check_file_in_path(output_path, filename):
                    filename = f"{oldfilename}_{counter}.pdf"
                    counter += 1
            elif save_type == SaveFileType.OVERWRITE:
                fullpath = os.path.join(output_path, filename)
                if os.path.exists(fullpath):
                    os.remove(fullpath)

        docx_doc = cls._unwrap(doc)
        temp_docx = None
        if not docx_doc.path or not os.path.exists(docx_doc.path):
            with tempfile.NamedTemporaryFile(suffix=".docx", delete=False) as f:
                temp_docx = f.name
            docx_doc.doc.save(temp_docx)
            input_docx = temp_docx
        else:
            docx_doc.doc.save(docx_doc.path)
            input_docx = docx_doc.path

        try:
            with tempfile.TemporaryDirectory() as tmp_out:
                cmd = [
                    soffice,
                    "--headless",
                    "--convert-to",
                    "pdf",
                    "--outdir",
                    tmp_out,
                    input_docx,
                ]
                subprocess.run(
                    cmd,
                    check=True,
                    capture_output=True,
                )
                base = os.path.splitext(os.path.basename(input_docx))[0]
                generated_pdf = os.path.join(tmp_out, base + ".pdf")
                dest_pdf = os.path.join(output_path, filename)
                shutil.move(generated_pdf, dest_pdf)
        finally:
            if temp_docx and os.path.exists(temp_docx):
                os.remove(temp_docx)
