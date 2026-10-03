import sys
from pathlib import Path

import pytest
from astronverse.pdf.pdf import PDF, PDFCore
from pypdf import PdfReader, PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject


def _create_sample_two_page_pdf(file_path: Path) -> None:
    """使用 pypdf 创建包含文本的 2 页 PDF 文件"""
    writer = PdfWriter()

    # 准备字体字典资源
    resources = DictionaryObject()
    font = DictionaryObject()
    f1 = DictionaryObject()
    f1[NameObject("/Type")] = NameObject("/Font")
    f1[NameObject("/Subtype")] = NameObject("/Type1")
    f1[NameObject("/BaseFont")] = NameObject("/Helvetica")
    font[NameObject("/F1")] = f1
    resources[NameObject("/Font")] = font

    # 第一页
    page1 = writer.add_blank_page(width=300, height=300)
    stream1 = DecodedStreamObject()
    stream1.set_data(b"BT /F1 12 Tf 50 250 Td (Page 1 Test Content) Tj ET")
    page1[NameObject("/Contents")] = stream1
    page1[NameObject("/Resources")] = resources

    # 第二页
    page2 = writer.add_blank_page(width=300, height=300)
    stream2 = DecodedStreamObject()
    stream2.set_data(b"BT /F1 12 Tf 50 250 Td (Page 2 Test Content) Tj ET")
    page2[NameObject("/Contents")] = stream2
    page2[NameObject("/Resources")] = resources

    with open(file_path, "wb") as f:
        writer.write(f)


@pytest.mark.skipif(sys.platform != "darwin", reason="macOS specific tests")
class TestMacOSPDF:
    def test_import_pdf_darwin(self):
        """测试在 macOS 环境下正确导入 PDF 模块及 Core 实例"""
        assert PDF is not None
        assert PDFCore is not None
        assert hasattr(PDFCore, "get_pages_num")
        assert hasattr(PDFCore, "get_page_text")

    def test_page_count_and_text_public_api(self, tmp_path):
        """测试通过公共 API 获取页数与页面文本内容"""
        pdf_file = tmp_path / "two_page_sample.pdf"
        _create_sample_two_page_pdf(pdf_file)

        assert pdf_file.exists()

        # 验证底层生成成功
        reader = PdfReader(str(pdf_file))
        assert len(reader.pages) == 2

        # 1. 调用公共 API: get_pages_num
        pages_count = PDF.get_pages_num(file_path=str(pdf_file))
        assert pages_count == 2

        # 2. 调用公共 API: get_pdf_text
        pages_text = PDF.get_pdf_text(file_path=str(pdf_file))
        assert isinstance(pages_text, list)
        assert len(pages_text) == 2
        assert "Page 1 Test Content" in pages_text[0]
        assert "Page 2 Test Content" in pages_text[1]
