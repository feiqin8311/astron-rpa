import os
import sys
from pathlib import Path

import pytest
from astronverse.word import (
    CloseRangeType,
    CommentType,
    CursorPointerType,
    CursorPositionType,
    DeleteMode,
    FileExistenceType,
    FileType,
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
    TextInputSourceType,
    VerticalAlignment,
)
from astronverse.word.core_docx import WordDocumentCore, find_libreoffice
from astronverse.word.docx import Docx
from astronverse.word.error import BaseException
from PIL import Image

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="Task M tests are specific to macOS darwin backend")


def _create_sample_image(path: Path) -> str:
    img = Image.new("RGB", (60, 60), color="red")
    img_path = str(path / "sample.png")
    img.save(img_path)
    return img_path


def test_docx_workflow_end_to_end(tmp_path: Path):
    """从头到尾贯穿执行 docx.py 的完整操作流程:

    create -> insert -> move_cursor -> select -> replace -> insert table/img/link/sep
    -> read -> read_table -> comment -> save -> convert_to_txt -> convert_to_pdf
    """
    # 1. create_docx
    folder = str(tmp_path)
    doc_obj, created_path = Docx.create_docx(
        file_path=folder,
        file_name="test_doc",
        exist_handle_type=FileExistenceType.OVERWRITE,
    )
    assert os.path.exists(created_path)
    assert doc_obj is not None
    assert doc_obj.document_object.Name == "test_doc.docx"

    # 2. insert_docx: 插入普通文本与带格式文本
    Docx.insert_docx(
        doc=doc_obj,
        text="Hello World!",
        font_size=14,
        bold_flag=True,
        italic_flag=False,
        font_name="Arial",
        font_color="255,0,0",
    )
    read_text = Docx.read_docx(doc_obj)
    assert "Hello World!" in read_text

    # 3. insert_docx with enter_flag=True
    Docx.insert_docx(
        doc=doc_obj,
        text="Second line of document.",
        enter_flag=True,
    )
    read_text = Docx.read_docx(doc_obj)
    assert "Second line of document." in read_text

    # 4. insert_docx from file
    txt_source = tmp_path / "input.txt"
    txt_source.write_text("Text from file source.", encoding="utf-8")
    Docx.insert_docx(
        doc=doc_obj,
        text_source=TextInputSourceType.FILE,
        text_file_path=str(txt_source),
        enter_flag=True,
    )
    read_text = Docx.read_docx(doc_obj)
    assert "Text from file source." in read_text

    # 5. cursor_position & move_cursor & select_text
    # 移动到开头
    Docx.get_cursor_position(
        doc=doc_obj,
        by=CursorPointerType.ALL,
        pos=CursorPositionType.HEAD,
    )
    assert doc_obj.document_object.cursor.p_idx == 0
    assert doc_obj.document_object.cursor.offset == 0

    # 移动到指定文本
    Docx.get_cursor_position(
        doc=doc_obj,
        by=CursorPointerType.CONTENT,
        pos=CursorPositionType.HEAD,
        content="World",
        c_idx=1,
    )
    assert doc_obj.document_object.cursor.offset == 6

    # 移动光标向右 5 个字符，带 shift 选择
    Docx.move_cursor(
        doc=doc_obj,
        direction=MoveDirectionType.RIGHT,
        unitleftright=MoveLeftRightType.CHARACTER,
        distance=5,
        with_shift=True,
    )
    assert doc_obj.document_object.cursor.has_selection
    selected_text = Docx.read_docx(doc=doc_obj, select_range=SelectRangeType.SELECTED)
    assert selected_text == "World"

    # 按段落选择
    Docx.select_text(
        doc=doc_obj,
        select_type=SelectTextType.PARAGRAPH,
        p_start=1,
        p_end=2,
    )
    selected_paragraphs = Docx.read_docx(doc=doc_obj, select_range=SelectRangeType.SELECTED)
    assert "Hello World!" in selected_paragraphs
    assert "Second line" in selected_paragraphs

    # 全选
    Docx.select_text(doc=doc_obj, select_type=SelectTextType.ALL)
    assert doc_obj.document_object.cursor.has_selection
    all_selected = Docx.read_docx(doc=doc_obj, select_range=SelectRangeType.SELECTED)
    assert "Hello World!" in all_selected

    # 将光标定位到末尾（折叠全选选区，避免后续插入覆盖全文档）
    Docx.get_cursor_position(
        doc=doc_obj,
        by=CursorPointerType.ALL,
        pos=CursorPositionType.TAIL,
    )

    # 6. replace (STR)
    Docx.replace(
        doc=doc_obj,
        origin_word="World",
        new_word="Universe",
        replace_type=ReplaceType.STR,
        replace_method=ReplaceMethodType.FIRST,
        ignore_case=True,
    )
    read_text = Docx.read_docx(doc_obj)
    assert "Universe" in read_text
    assert "World" not in read_text

    # 7. replace (IMG)
    sample_img = _create_sample_image(tmp_path)
    Docx.insert_docx(doc=doc_obj, text="Replace [PIC] here", enter_flag=True)
    Docx.replace(
        doc=doc_obj,
        origin_word="[PIC]",
        img_path=sample_img,
        replace_type=ReplaceType.IMG,
        replace_method=ReplaceMethodType.FIRST,
    )
    read_text = Docx.read_docx(doc_obj)
    assert "[PIC]" not in read_text

    # 8. insert_sep (PARAGRAPH & PAGE)
    Docx.insert_sep(doc=doc_obj, sep_type=InsertionType.PARAGRAPH)
    Docx.insert_docx(doc=doc_obj, text="Paragraph after separator.")
    Docx.insert_sep(doc=doc_obj, sep_type=InsertionType.PAGE)
    Docx.insert_docx(doc=doc_obj, text="Text on new page.")
    read_text = Docx.read_docx(doc_obj)
    assert "Paragraph after separator." in read_text
    assert "Text on new page." in read_text

    # 9. insert_hyperlink
    Docx.insert_hyperlink(
        doc=doc_obj,
        url="https://example.com",
        display="Example Link",
    )
    read_text = Docx.read_docx(doc_obj)
    assert "Example Link" in read_text

    # 10. insert_img
    Docx.insert_img(
        doc=doc_obj,
        img_from=InsertImgType.FILE,
        img_path=sample_img,
        scale=50,
        newline=True,
    )

    # 11. insert_table & read_table
    table_data = [
        ["Header 1", "Header 2", "Header 3"],
        ["Row 1 Col 1", "Row 1 Col 2", "TargetCell"],
        ["Row 2 Col 1", "Row 2 Col 2", "Row 2 Col 3"],
    ]
    Docx.insert_table(
        doc=doc_obj,
        table_content=table_data,
        table_behavior=TableBehavior.DEFAULT,
        alignment=RowAlignment.CENTER,
        v_alignment=VerticalAlignment.CENTER,
        border=True,
        newline=False,
    )
    # 按索引读取表格
    read_tbl = Docx.read_table(doc=doc_obj, search_type=SearchTableType.IDX, idx=1)
    assert read_tbl[0] == ["Header 1", "Header 2", "Header 3"]
    assert read_tbl[1][2] == "TargetCell"

    # 按包含文本搜索表格
    read_tbl_text = Docx.read_table(doc=doc_obj, search_type=SearchTableType.TEXT, text="TargetCell")
    assert read_tbl_text == read_tbl

    # 12. comment (create & delete)
    # 按位置创建批注
    Docx.create_comment(
        doc=doc_obj,
        comment="This is a test comment",
        comment_type=CommentType.POSITION,
        paragraph_idx=1,
        start=0,
        end=5,
    )
    assert len(list(doc_obj.document_object.comments)) >= 1

    # 按内容创建批注
    Docx.create_comment(
        doc=doc_obj,
        comment="Comment for Universe",
        comment_type=CommentType.CONTENT,
        target_str="Universe",
        comment_all=True,
    )

    # 删除批注
    Docx.delete_comment(doc=doc_obj, delete_all=True)
    assert len(list(doc_obj.document_object.comments)) == 0

    # 13. delete (CONTENT & RANGE & ALL)
    Docx.insert_docx(doc=doc_obj, text="DeleteMeTarget string", enter_flag=True)
    Docx.delete(
        doc=doc_obj,
        delete_mode=DeleteMode.CONTENT,
        delete_str="DeleteMeTarget",
        str_delete_all=True,
    )
    assert "DeleteMeTarget" not in Docx.read_docx(doc_obj)

    # 14. save_docx (SAVE & SAVE_AS)
    saved_path = Docx.save_docx(doc=doc_obj, save_type=SaveType.SAVE)
    assert os.path.exists(saved_path)

    save_as_path = Docx.save_docx(
        doc=doc_obj,
        save_type=SaveType.SAVE_AS,
        file_path=folder,
        file_name="save_as_test",
        exist_handle_type=FileExistenceType.OVERWRITE,
    )
    assert os.path.exists(save_as_path)

    # 15. convert_format to TXT
    Docx.convert_format(
        doc=doc_obj,
        output_path=folder,
        default_name=False,
        output_name="exported_txt",
        output_file_type=FileType.TXT,
        save_type=SaveFileType.OVERWRITE,
    )
    exported_txt_file = Path(folder) / "exported_txt.txt"
    assert exported_txt_file.exists()
    content = exported_txt_file.read_text(encoding="utf-8")
    assert "Universe" in content
    assert "TargetCell" in content

    # 16. convert_format to PDF
    soffice = find_libreoffice()
    if soffice:
        Docx.convert_format(
            doc=doc_obj,
            output_path=folder,
            default_name=False,
            output_name="exported_pdf",
            output_file_type=FileType.PDF,
            save_type=SaveFileType.OVERWRITE,
        )
        assert (Path(folder) / "exported_pdf.pdf").exists()
    else:
        # 必须抛出清晰提及 LibreOffice 的错误
        with pytest.raises(BaseException) as exc_info:
            WordDocumentCore.convert_to_pdf(
                doc=doc_obj,
                output_path=folder,
                output_name="exported_pdf",
                save_type=SaveFileType.OVERWRITE,
            )
        assert "LibreOffice" in str(exc_info.value)

    # 17. close_docx
    Docx.close_docx(doc=doc_obj, close_range_flag=CloseRangeType.ONE)


def test_open_docx_and_doc(tmp_path: Path):
    """测试 open_docx 打开正常 docx 文件以及 .doc 转换行为。"""
    folder = str(tmp_path)
    doc_obj, path = Docx.create_docx(
        file_path=folder,
        file_name="open_test",
        exist_handle_type=FileExistenceType.OVERWRITE,
    )
    Docx.insert_docx(doc=doc_obj, text="Sample for open test.")
    Docx.save_docx(doc=doc_obj)

    # 打开刚才创建的 docx
    opened = Docx.open_docx(file_path=path)
    assert "Sample for open test." in Docx.read_docx(opened)

    # 测试 .doc 文件：若无 LibreOffice 则抛出明确错误
    dummy_doc = tmp_path / "legacy.doc"
    dummy_doc.write_bytes(b"\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1")  # OLE CFB header
    soffice = find_libreoffice()
    if not soffice:
        with pytest.raises(BaseException) as exc_info:
            Docx.open_docx(file_path=str(dummy_doc))
        # 验证错误信息提及 LibreOffice
        err = exc_info.value
        cause = err.__cause__
        text = f"{err} {getattr(err, 'message', '')} {cause} {getattr(cause, 'message', '')}"
        assert "LibreOffice" in text


def test_unsupported_enum_modes_raise_clear_error(tmp_path: Path):
    """测试不支持的视觉排版行(ROW)等枚举抛出明确中文错误。"""
    folder = str(tmp_path)
    doc_obj, _ = Docx.create_docx(
        file_path=folder,
        file_name="unsupported_test",
        exist_handle_type=FileExistenceType.OVERWRITE,
    )
    Docx.insert_docx(doc=doc_obj, text="Row test content")

    # 1. select_text with ROW
    with pytest.raises(BaseException) as exc_info:
        WordDocumentCore.select(
            doc=doc_obj.document_object,
            select_type=SelectTextType.ROW,
        )
    assert "不支持按行" in (str(exc_info.value) + getattr(exc_info.value, "message", ""))

    # 2. cursor_position with ROW
    with pytest.raises(BaseException) as exc_info:
        WordDocumentCore.cursor_position(
            doc=doc_obj.document_object,
            by=CursorPointerType.ROW,
        )
    assert "不支持按行" in (str(exc_info.value) + getattr(exc_info.value, "message", ""))

    # 3. move_cursor with ROW
    with pytest.raises(BaseException) as exc_info:
        WordDocumentCore.move_cursor(
            doc=doc_obj.document_object,
            direction=MoveDirectionType.UP,
            unitupdown=MoveUpDownType.ROW,
            distance=1,
        )
    assert "不支持按行" in (str(exc_info.value) + getattr(exc_info.value, "message", ""))
