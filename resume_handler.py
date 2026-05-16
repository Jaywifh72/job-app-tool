"""
Resume handler module.
Reads .docx resume files, extracts structured data, and writes modified resumes.
Replaces text in-place to preserve ALL original formatting, tables, and layout.
"""

import logging
import shutil
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from copy import deepcopy

from docx import Document
from docx.shared import Pt, Inches, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn

logger = logging.getLogger(__name__)

# Section headers that identify section boundaries in the document
_SECTION_HEADERS = {
    "EXECUTIVE SUMMARY", "SUMMARY",
    "CORE COMPETENCIES", "SKILLS", "TECHNICAL SKILLS",
    "PROFESSIONAL EXPERIENCE", "WORK EXPERIENCE", "EXPERIENCE",
    "EDUCATION", "CERTIFICATIONS",
    "LANGUAGES",
}


@dataclass
class ResumeData:
    """Structured representation of a parsed resume."""
    raw_text: str
    paragraphs: list = field(default_factory=list)
    header: str = ""
    summary: str = ""
    competencies: str = ""
    experience: str = ""
    education: str = ""
    languages: str = ""


def _add_bottom_border(paragraph):
    """Add a thin gray bottom border to a paragraph."""
    pPr = paragraph._element.get_or_add_pPr()
    pBdr = OxmlElement('w:pBdr')
    bottom = OxmlElement('w:bottom')
    bottom.set(qn('w:val'), 'single')
    bottom.set(qn('w:sz'), '6')
    bottom.set(qn('w:space'), '1')
    bottom.set(qn('w:color'), '999999')
    pBdr.append(bottom)
    pPr.append(pBdr)


def _replace_run_text(paragraph, new_text):
    """Replace paragraph text in-place, preserving the first run's formatting.
    Clears all existing runs and sets the new text on the first run.
    """
    if not paragraph.runs:
        paragraph.add_run(new_text)
        return
    for run in paragraph.runs:
        run.text = ''
    paragraph.runs[0].text = new_text


def _clear_paragraph(paragraph):
    """Clear all text from a paragraph while preserving its formatting."""
    for run in paragraph.runs:
        run.text = ''


def _find_doc_sections(doc):
    """Map section names to their paragraph-index ranges in the document body.
    Returns list of (name, start_idx, end_idx) sorted by document order.
    Also returns the table index for CORE COMPETENCIES if present.
    """
    body = doc.paragraphs

    # Find all section headers
    header_indices = {}  # section_name -> paragraph index
    for i, p in enumerate(body):
        text = p.text.strip().upper()
        if text in _SECTION_HEADERS:
            header_indices[text] = i

    # Build section ranges
    sorted_items = sorted(header_indices.items(), key=lambda x: x[1])
    sections = []
    prev_end = 0

    # Header section (before first section header)
    if sorted_items:
        first_name, first_idx = sorted_items[0]
        sections.append(("HEADER", 0, first_idx))

    for idx, (name, start) in enumerate(sorted_items):
        if idx + 1 < len(sorted_items):
            end = sorted_items[idx + 1][1]
        else:
            end = len(body)
        sections.append((name, start, end))

    return sections


def _find_ai_section_segments(segments):
    """Find section boundaries in AI segments.
    Returns dict: section_name -> list of segment strings
    """
    section_segments = {}
    current_section = "HEADER"
    section_content = []

    for seg in segments:
        upper = seg.strip().upper()
        if upper in _SECTION_HEADERS:
            if section_content:
                section_segments[current_section] = section_content
            current_section = upper
            section_content = [seg]
        else:
            section_content.append(seg)

    if section_content:
        section_segments[current_section] = section_content

    return section_segments


def _extract_competency_bullets(section_segments):
    """Extract competency bullet segments for table handling."""
    comp_segments = section_segments.get("CORE COMPETENCIES", [])
    if comp_segments:
        # First segment is the section header itself; rest are bullet points
        return comp_segments[1:]
    return []


def _distribute_competencies(table, comp_bullets):
    """Distribute competency bullet text across a single-row, multi-column table.
    Each column gets a roughly equal share of bullets.
    """
    if not table.rows or not table.rows[0].cells:
        return

    cells = table.rows[0].cells
    n_cells = len(cells)
    n_bullets = len(comp_bullets)

    # Clear all cell content first
    for cell in cells:
        for p in cell.paragraphs:
            _clear_paragraph(p)

    if n_bullets == 0:
        return

    # Distribute across columns
    base = n_bullets // n_cells
    extra = n_bullets % n_cells
    idx = 0

    for ci, cell in enumerate(cells):
        cell_paras = cell.paragraphs
        n_here = base + (1 if ci < extra else 0)

        for pi in range(len(cell_paras)):
            if pi < n_here and idx < n_bullets:
                _replace_run_text(cell_paras[pi], comp_bullets[idx])
                idx += 1
            else:
                _clear_paragraph(cell_paras[pi])

        # If we need more paragraphs in this cell
        while idx < n_here and idx < n_bullets:
            p = cell.add_paragraph(comp_bullets[idx])
            idx += 1


def load_resume(filepath: str | Path) -> tuple[Document, ResumeData]:
    """Load a .docx resume file and return Document + ResumeData."""
    filepath = Path(filepath)
    if not filepath.exists():
        raise FileNotFoundError(f"Resume file not found: {filepath}")

    logger.info(f"Loading resume: {filepath}")
    doc = Document(str(filepath))

    raw_text_parts = []
    for p in doc.paragraphs:
        raw_text_parts.append(p.text)
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                raw_text_parts.append(cell.text)

    raw_text = "\n".join(raw_text_parts)
    resume_data = ResumeData(raw_text=raw_text, paragraphs=[p.text for p in doc.paragraphs])

    current_section = None
    section_buf = []
    section_keywords = {
        "EXECUTIVE SUMMARY": "summary",
        "SUMMARY": "summary",
        "PROFESSIONAL EXPERIENCE": "experience",
        "WORK EXPERIENCE": "experience",
        "EXPERIENCE": "experience",
        "CORE COMPETENCIES": "competencies",
        "SKILLS": "competencies",
        "EDUCATION": "education",
        "LANGUAGES": "languages",
        "CERTIFICATIONS": "education",
    }
    for p in doc.paragraphs:
        text = p.text.strip()
        if not text:
            continue
        upper = text.upper()
        matched_section = None
        for keyword, section_name in section_keywords.items():
            if keyword in upper:
                matched_section = section_name
                break
        if matched_section:
            if current_section and section_buf:
                setattr(resume_data, current_section, "\n".join(section_buf))
            current_section = matched_section
            section_buf = [text]
        elif current_section:
            section_buf.append(text)
    if current_section and section_buf:
        setattr(resume_data, current_section, "\n".join(section_buf))
    if doc.paragraphs:
        resume_data.header = doc.paragraphs[0].text

    logger.info(f"Resume loaded: {len(raw_text_parts)} paragraphs, {len(raw_text)} chars")
    return doc, resume_data


def write_tailored_resume(
    original_path: str | Path,
    tailored_text: str,
    output_path: str | Path,
) -> Path:
    """
    Write a tailored resume by copying the original .docx and replacing text
    in-place. Preserves ALL original formatting: margins, page size, fonts,
    styles, headers/footers, colors, tables, multi-run formatting, etc.

    Uses section-anchored mapping: AI content is partitioned by section headers
    (EXECUTIVE SUMMARY, CORE COMPETENCIES, etc.) and each section's content is
    mapped to the corresponding paragraph range in the document. This correctly
    handles variable-length sections (e.g. different numbers of bullet points).
    """
    output_path = Path(output_path)
    original_path = Path(original_path)
    logger.info(f"Writing tailored resume to: {output_path}")

    # Copy original to preserve ALL formatting
    shutil.copy(str(original_path), str(output_path))
    doc = Document(str(output_path))

    # Parse AI output into non-empty segments
    segments = [line.strip() for line in tailored_text.strip().split('\n') if line.strip()]
    if not segments:
        logger.warning("AI produced empty tailored text")
        return output_path

    # --- Find section boundaries ---
    doc_sections = _find_doc_sections(doc)
    ai_sections = _find_ai_section_segments(segments)
    comp_bullets = _extract_competency_bullets(ai_sections)

    # --- Replace competency table content ---
    for table in doc.tables:
        _distribute_competencies(table, comp_bullets)

    # --- Map each document section to AI content ---
    for name, doc_start, doc_end in doc_sections:
        if name == "CORE COMPETENCIES":
            # Header paragraph only; table handled above
            ai_segs = ai_sections.get(name, [])
            # Only use the header text, not the bullet content
            if ai_segs:
                _replace_run_text(doc.paragraphs[doc_start], ai_segs[0])
            else:
                _clear_paragraph(doc.paragraphs[doc_start])
            continue

        ai_segs = ai_sections.get(name, [])
        para_indices = list(range(doc_start, doc_end))

        for i, seg in enumerate(ai_segs):
            if i < len(para_indices):
                _replace_run_text(doc.paragraphs[para_indices[i]], seg)

        # Clear remaining paragraphs in this section
        for i in range(len(ai_segs), len(para_indices)):
            _clear_paragraph(doc.paragraphs[para_indices[i]])

    doc.save(str(output_path))
    logger.info(f"Tailored resume saved to: {output_path}")
    return output_path


def write_cover_letter(
    cover_text: str,
    output_path: str | Path,
    style_reference_path: str | Path | None = None,
) -> Path:
    """Write a professional cover letter as a .docx file.

    Uses the resume as a style template when style_reference_path is provided,
    giving the cover letter consistent fonts, margins, and branding.
    """
    output_path = Path(output_path)
    logger.info(f"Writing cover letter to: {output_path}")

    if style_reference_path and Path(style_reference_path).exists():
        shutil.copy(str(style_reference_path), str(output_path))
        doc = Document(str(output_path))
        # Clear body while preserving sections/headers/footers
        body = doc.element.body
        children = list(body)
        sect_prs = [child for child in children if child.tag == qn('w:sectPr')]
        for child in children:
            body.remove(child)
        for sp in sect_prs:
            body.append(deepcopy(sp))
    else:
        doc = Document()
        style = doc.styles["Normal"]
        style.font.name = "Calibri"
        style.font.size = Pt(11)
        style.paragraph_format.line_spacing = 1.15
        for section in doc.sections:
            section.top_margin = Inches(1)
            section.bottom_margin = Inches(1)
            section.left_margin = Inches(1)
            section.right_margin = Inches(1)

    # --- Parse AI output into structured parts ---
    body_paragraphs = []
    salutation = ""
    closing_lines = []
    in_closing = False

    for line in cover_text.strip().split("\n"):
        stripped = line.strip()
        if not stripped:
            continue
        lower = stripped.lower()
        if lower.startswith("dear "):
            salutation = stripped
        elif lower.startswith(("sincerely", "best regards", "yours truly", "yours", "cordially")):
            in_closing = True
            closing_lines.append(stripped)
        elif in_closing:
            closing_lines.append(stripped)
        else:
            body_paragraphs.append(stripped)

    # --- Build the document ---

    # Sender name (centered, bold, 14pt)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("Jean-Jacques Boileau")
    run.bold = True
    run.font.size = Pt(14)

    # Contact info (centered, smaller, gray)
    p = doc.add_paragraph()
    p.alignment = WD_ALIGN_PARAGRAPH.CENTER
    run = p.add_run("jeanjacquesboileau@gmail.com  |  (514) 704-8917")
    run.font.size = Pt(10)
    try:
        run.font.color.rgb = RGBColor(0x55, 0x55, 0x55)
    except Exception:
        pass

    # Separator line
    p = doc.add_paragraph()
    p.paragraph_format.space_before = Pt(2)
    p.paragraph_format.space_after = Pt(8)
    p.add_run("")
    _add_bottom_border(p)

    # Date
    p = doc.add_paragraph()
    run = p.add_run(date.today().strftime("%B %d, %Y"))
    run.font.size = Pt(11)
    p.paragraph_format.space_after = Pt(12)

    # Salutation
    if salutation:
        p = doc.add_paragraph()
        run = p.add_run(salutation)
        run.font.size = Pt(11)
        p.paragraph_format.space_after = Pt(6)

    # Body paragraphs
    for para_text in body_paragraphs:
        p = doc.add_paragraph()
        run = p.add_run(para_text)
        run.font.size = Pt(11)
        p.paragraph_format.space_after = Pt(6)
        p.paragraph_format.line_spacing = 1.15

    # Closing
    if closing_lines:
        p = doc.add_paragraph()
        p.paragraph_format.space_before = Pt(12)
        for i, line in enumerate(closing_lines):
            if i > 0:
                p.add_run("\n")
            run = p.add_run(line)
            run.font.size = Pt(11)

    doc.save(str(output_path))
    logger.info(f"Cover letter saved to: {output_path}")
    return output_path
