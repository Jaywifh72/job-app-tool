"""
PDF utility functions using Word COM automation.
"""

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)


def convert_docx_to_pdf(docx_path: os.PathLike, pdf_path: os.PathLike) -> Path:
    """Convert a .docx file to PDF using Microsoft Word automation."""
    docx_path = Path(docx_path)
    pdf_path = Path(pdf_path)

    import comtypes.client
    import pythoncom

    pythoncom.CoInitialize()
    word = None
    doc = None
    try:
        word = comtypes.client.CreateObject("Word.Application")
        word.Visible = False
        word.DisplayAlerts = False

        doc = word.Documents.Open(str(docx_path.resolve()))
        doc.SaveAs(str(pdf_path.resolve()), FileFormat=17)  # 17 = wdFormatPDF
        logger.info(f"PDF saved: {pdf_path}")
        return pdf_path
    except Exception as e:
        logger.error(f"PDF conversion failed: {e}")
        raise
    finally:
        if doc is not None:
            doc.Close(SaveChanges=False)
        if word is not None:
            word.Quit()
        pythoncom.CoUninitialize()
