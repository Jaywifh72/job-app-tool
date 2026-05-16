#!/usr/bin/env python3
"""
Job App Tool - Web Application
Flask web interface for resume tailoring and cover letter generation.
"""

import logging
import os
import sys
import threading
import uuid
import json
from pathlib import Path
from datetime import datetime

from flask import (
    Flask,
    render_template,
    request,
    jsonify,
    send_file,
    abort,
    url_for,
)

# Ensure the project root is on the path
_project_root = Path(__file__).parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

from scraper import scrape_job_posting, summarize_job_posting
from resume_handler import load_resume, write_tailored_resume, write_cover_letter
from ai_handler import AIHandler, DEFAULT_MODEL
from diff_utils import generate_diff_html
from pdf_utils import convert_docx_to_pdf

# --- Setup ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("webapp")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16 MB max upload

# --- Paths ---
BASE_DIR = _project_root
UPLOAD_DIR = BASE_DIR / "uploads"
GENERATED_DIR = BASE_DIR / "generated"
DEFAULT_RESUME = (
    Path.home() / "Downloads" / "Jean-Jacques_Boileau_Resume-2026 (1).docx"
)
UPLOAD_DIR.mkdir(exist_ok=True)
GENERATED_DIR.mkdir(exist_ok=True)

# --- In-memory job store ---
# Structure: { job_id: {
#     "status": str, "current_step": str, "steps": list,
#     "error": str, "files": dict, "summary": str
# }}
_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def _update_job(job_id: str, **kwargs):
    """Thread-safe update of job status."""
    with _lock:
        if job_id in _jobs:
            _jobs[job_id].update(kwargs)


def _get_job(job_id: str) -> dict | None:
    """Thread-safe read of job status."""
    with _lock:
        return _jobs.get(job_id)


# =========================================================================
# Background Processing
# =========================================================================

def _run_processing(
    job_id: str,
    resume_path: Path,
    job_description: str,
    model: str,
    instructions: str | None,
):
    """
    Run the full AI pipeline in a background thread.
    Updates _jobs dict with granular progress steps and results.
    """
    try:
        _update_job(job_id, status="processing", current_step="Loading resume...",
                     steps=[
                         {"text": "Loading resume document...", "status": "done"},
                         {"text": "Reading job posting...", "status": "pending"},
                         {"text": "Analyzing requirements and matching to resume...", "status": "pending"},
                         {"text": "Tailoring resume content...", "status": "pending"},
                         {"text": "Writing tailored resume document...", "status": "pending"},
                         {"text": "Generating cover letter...", "status": "pending"},
                         {"text": "Finalizing and generating report...", "status": "pending"},
                     ])

        # --- Load resume ---
        _update_job(job_id, current_step="Reading resume document...")
        original_doc, resume_data = load_resume(resume_path)

        # --- Helper to advance steps ---
        def advance_step(step_text: str):
            with _lock:
                if job_id in _jobs:
                    steps = list(_jobs[job_id].get("steps", []))
                    # Mark the first pending step done, set new current
                    found = False
                    for s in steps:
                        if s["status"] == "pending" and not found:
                            s["status"] = "done"
                            found = True
                    # Add a new pending step if needed
                    steps.append({"text": step_text, "status": "active"})
                    _jobs[job_id]["steps"] = steps
                    _jobs[job_id]["current_step"] = step_text

        advance_step("Reading job posting...")

        # --- Init AI handler with progress callback ---
        def ai_progress(step_text: str):
            _update_job(job_id, current_step=step_text)

        ai = AIHandler(model=model, temperature=0.3, progress_callback=ai_progress)

        # --- Extract company name for filenames ---
        advance_step("Identifying target company...")
        company_raw = ai.extract_company_name(job_description)
        company = company_raw if company_raw.lower() != "hiring manager" else ""
        safe_company = "".join(c for c in company if c.isalnum() or c in " -._").strip() or ""

        def make_filename(doc_type: str, ext: str = ".docx") -> str:
            name = "Jean-Jacques (Jay) Boileau"
            if safe_company:
                return f"{name} - {doc_type} - {safe_company}{ext}"
            return f"{name} - {doc_type}{ext}"

        job_gen_dir = GENERATED_DIR / job_id
        job_gen_dir.mkdir(parents=True, exist_ok=True)

        # --- Step 1: Tailor resume ---
        advance_step("Analyzing requirements and matching to resume...")
        tailored_text, resume_analysis, resume_changes = ai.tailor_resume(
            resume_text=resume_data.raw_text,
            job_description=job_description,
            instructions=instructions,
        )

        # Write tailored resume
        advance_step("Writing tailored resume document...")
        resume_filename = make_filename("Resume")
        resume_out = job_gen_dir / resume_filename
        write_tailored_resume(resume_path, tailored_text, resume_out)

        # Generate PDF of tailored resume
        resume_pdf = job_gen_dir / make_filename("Resume", ".pdf")
        try:
            convert_docx_to_pdf(resume_out, resume_pdf)
        except Exception as e:
            logger.warning(f"Resume PDF conversion failed: {e}")
            resume_pdf = None

        # Save resume preview text
        (job_gen_dir / "resume_preview.txt").write_text(tailored_text, encoding="utf-8")

        # Save original resume text for diff
        (job_gen_dir / "original_resume.txt").write_text(resume_data.raw_text, encoding="utf-8")

        # Generate diff HTML
        diff_html = generate_diff_html(resume_data.raw_text, tailored_text)
        (job_gen_dir / "diff.html").write_text(diff_html, encoding="utf-8")

        # --- Step 2: Generate cover letter ---
        advance_step("Crafting cover letter...")
        cover_text, cover_analysis = ai.generate_cover_letter(
            resume_text=resume_data.raw_text,
            job_description=job_description,
            candidate_name="Jean-Jacques Boileau",
            instructions=instructions,
        )

        cover_filename = make_filename("Cover Letter")
        cover_out = job_gen_dir / cover_filename
        write_cover_letter(cover_text, cover_out, resume_path)

        # Generate PDF of cover letter
        cover_pdf = job_gen_dir / make_filename("Cover Letter", ".pdf")
        try:
            convert_docx_to_pdf(cover_out, cover_pdf)
        except Exception as e:
            logger.warning(f"Cover PDF conversion failed: {e}")
            cover_pdf = None

        (job_gen_dir / "cover_preview.txt").write_text(cover_text, encoding="utf-8")

        # --- Step 3: Generate summary ---
        advance_step("Generating processing report...")
        summary = ai.generate_summary(
            job_description=job_description,
            resume_analysis=resume_analysis,
            resume_changes=resume_changes,
            cover_analysis=cover_analysis,
        )

        (job_gen_dir / "summary.txt").write_text(summary, encoding="utf-8")

        # Mark all steps done
        with _lock:
            if job_id in _jobs:
                final_steps = list(_jobs[job_id].get("steps", []))
                for s in final_steps:
                    if s["status"] in ("pending", "active"):
                        s["status"] = "done"
                _jobs[job_id]["steps"] = final_steps

        _update_job(
            job_id,
            status="done",
            current_step="Complete!",
            files={
                "resume": str(resume_out),
                "cover": str(cover_out),
                "resume_preview": tailored_text,
                "cover_preview": cover_text,
                "resume_filename": resume_filename,
                "cover_filename": cover_filename,
                "resume_pdf": str(resume_pdf) if resume_pdf else None,
                "cover_pdf": str(cover_pdf) if cover_pdf else None,
                "resume_pdf_filename": make_filename("Resume", ".pdf"),
                "cover_pdf_filename": make_filename("Cover Letter", ".pdf"),
                "diff_html": diff_html,
            },
            summary=summary,
        )

    except Exception as e:
        logger.exception(f"Job {job_id} failed")
        _update_job(job_id, status="error", current_step="Failed", error=str(e))


# =========================================================================
# Routes
# =========================================================================

@app.route("/")
def index():
    """Main page with the input form."""
    return render_template(
        "index.html",
        default_model=DEFAULT_MODEL,
        default_resume_exists=DEFAULT_RESUME.exists(),
    )


@app.route("/generate", methods=["POST"])
def generate():
    """Start a new generation job."""
    url = request.form.get("url", "").strip()
    job_text = request.form.get("job_text", "").strip()
    instructions = request.form.get("instructions", "").strip() or None
    model = request.form.get("model", DEFAULT_MODEL).strip()
    uploaded_file = request.files.get("resume")

    if not url and not job_text:
        return jsonify({"error": "Provide a job posting URL or paste the description."}), 400

    job_id = uuid.uuid4().hex[:12]

    if uploaded_file and uploaded_file.filename:
        upload_dir = UPLOAD_DIR / job_id
        upload_dir.mkdir(parents=True, exist_ok=True)
        resume_path = upload_dir / "resume.docx"
        uploaded_file.save(str(resume_path))
    elif DEFAULT_RESUME.exists():
        resume_path = DEFAULT_RESUME
    else:
        return jsonify({"error": "No resume provided and no default resume found."}), 400

    if url:
        try:
            job_raw = scrape_job_posting(url)
            job_description = summarize_job_posting(job_raw)
        except Exception as e:
            return jsonify({"error": f"Failed to scrape job posting: {e}"}), 400
    else:
        job_description = summarize_job_posting(job_text)

    _jobs[job_id] = {
        "status": "queued",
        "current_step": "Queued...",
        "steps": [
            {"text": "Loading resume document...", "status": "pending"},
            {"text": "Reading job posting...", "status": "pending"},
            {"text": "Analyzing requirements and matching to resume...", "status": "pending"},
            {"text": "Tailoring resume content...", "status": "pending"},
            {"text": "Writing tailored resume document...", "status": "pending"},
            {"text": "Generating cover letter...", "status": "pending"},
            {"text": "Finalizing and generating report...", "status": "pending"},
        ],
        "error": None,
        "files": None,
        "summary": None,
    }

    thread = threading.Thread(
        target=_run_processing,
        args=(job_id, resume_path, job_description, model, instructions),
        daemon=True,
    )
    thread.start()

    return jsonify({"job_id": job_id})


@app.route("/status/<job_id>")
def status(job_id: str):
    """Poll job status. Returns JSON with steps and summary."""
    job = _get_job(job_id)
    if not job:
        return jsonify({"error": "Job not found"}), 404
    return jsonify(job)


@app.route("/results/<job_id>")
def results(job_id: str):
    """Show results page for a completed job."""
    job = _get_job(job_id)
    if not job:
        abort(404)

    if job["status"] == "error":
        return render_template("results.html", job_id=job_id, status="error", error=job.get("error"))

    if job["status"] != "done":
        return render_template("results.html", job_id=job_id, status=job["status"])

    files = job.get("files", {})
    summary = job.get("summary", "")
    steps = job.get("steps", [])
    return render_template(
        "results.html",
        job_id=job_id,
        status="done",
        resume_preview=files.get("resume_preview", ""),
        cover_preview=files.get("cover_preview", ""),
        resume_filename=files.get("resume_filename", "Tailored_Resume.docx"),
        cover_filename=files.get("cover_filename", "Cover_Letter.docx"),
        resume_pdf_filename=files.get("resume_pdf_filename", ""),
        cover_pdf_filename=files.get("cover_pdf_filename", ""),
        diff_html=files.get("diff_html", ""),
        summary=summary,
        steps=steps,
    )


@app.route("/download/<job_id>/<filename>")
def download(job_id: str, filename: str):
    """Download generated files."""
    job_dir = GENERATED_DIR / job_id
    file_path = job_dir / filename
    if not file_path.exists():
        abort(404)
    return send_file(str(file_path), as_attachment=True)


@app.route("/preview/<job_id>/<doc_type>")
def preview_text(job_id: str, doc_type: str):
    """Get the text preview of a generated document."""
    job_dir = GENERATED_DIR / job_id
    if doc_type == "resume":
        txt_file = job_dir / "resume_preview.txt"
    elif doc_type == "cover":
        txt_file = job_dir / "cover_preview.txt"
    elif doc_type == "summary":
        txt_file = job_dir / "summary.txt"
    else:
        abort(404)

    if not txt_file.exists():
        abort(404)
    return txt_file.read_text(encoding="utf-8")


# =========================================================================
# Main
# =========================================================================

if __name__ == "__main__":
    import webbrowser

    port = 5000
    print(f"  Starting Job App Tool web interface...")
    print(f"  Open http://127.0.0.1:{port} in your browser")
    print(f"  Press Ctrl+C to stop")
    print()
    webbrowser.open(f"http://127.0.0.1:{port}")
    app.run(debug=True, use_reloader=False, host="127.0.0.1", port=port, threaded=True)
