#!/usr/bin/env python3
"""
Job App Tool -- Tailor your resume and generate cover letters for specific job postings.

Usage:
    python job_app_tool.py --url <job_posting_url> [options]
    python job_app_tool.py --job-text "<job_description>" [options]

Examples:
    python job_app_tool.py --url "https://linkedin.com/jobs/view/12345"
    python job_app_tool.py --url "https://example.com/job" --resume "My_Resume.docx"
    python job_app_tool.py --url "https://example.com/job" --model "qwen3-coder:latest"
    python job_app_tool.py --url "https://example.com/job" --output-dir "./my_applications"
    python job_app_tool.py --url "https://example.com/job" --instructions "Highlight my AI experience more"
    python job_app_tool.py --job-text "$(cat job.txt)"  # read from file
"""

import argparse
import logging
import sys
import io
from pathlib import Path
from datetime import datetime

# Force UTF-8 encoding for stdout (handles •, ●, — etc. on Windows)
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
elif hasattr(sys.stdout, "buffer"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from scraper import scrape_job_posting, summarize_job_posting
from resume_handler import (
    load_resume,
    write_tailored_resume,
    write_cover_letter,
)
from ai_handler import AIHandler, DEFAULT_MODEL

# --- Setup logging ---
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger("job_app_tool")


# --- Default resume path ---
DEFAULT_RESUME = Path.home() / "Downloads" / "Jean-Jacques_Boileau_Resume-2026 (1).docx"


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Tailor your resume and generate a cover letter for a specific job posting.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --url "https://linkedin.com/jobs/view/12345"
  %(prog)s --url "https://example.com/job" --resume "My_Resume.docx"
  %(prog)s --url "https://example.com/job" --model "qwen3-coder:latest"
  %(prog)s --url "https://example.com/job" --skip-cover
  %(prog)s --url "https://example.com/job" --instructions "Emphasize leadership experience"
  %(prog)s --job-text \"Job Title: Engineer...\"  # paste description directly
        """,
    )

    parser.add_argument(
        "--url",
        default=None,
        help="URL of the job posting to target",
    )
    parser.add_argument(
        "--job-text",
        default=None,
        help="Job description text directly (use instead of --url if scraping fails)",
    )
    parser.add_argument(
        "--resume",
        default=str(DEFAULT_RESUME),
        help=f"Path to your resume .docx file (default: {DEFAULT_RESUME})",
    )
    parser.add_argument(
        "--output-dir",
        default="./output",
        help="Directory to save output files (default: ./output)",
    )
    parser.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Ollama model to use (default: {DEFAULT_MODEL})",
    )
    parser.add_argument(
        "--ollama-host",
        default="http://localhost:11434",
        help="Ollama server host (default: http://localhost:11434)",
    )
    parser.add_argument(
        "--temperature",
        type=float,
        default=0.3,
        help="Temperature for AI generation, lower = more conservative (default: 0.3)",
    )
    parser.add_argument(
        "--instructions",
        default=None,
        help='Optional extra instructions, e.g. "Emphasize my AI experience"',
    )
    parser.add_argument(
        "--skip-cover",
        action="store_true",
        help="Skip cover letter generation",
    )
    parser.add_argument(
        "--skip-resume",
        action="store_true",
        help="Skip resume tailoring (cover letter only)",
    )
    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable debug logging",
    )
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()

    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    print("=" * 65)
    print("  JOB APP TOOL - Resume Tailoring & Cover Letter Generator")
    print("=" * 65)

    # --- Validate inputs ---
    if not args.url and not args.job_text:
        print("  [FAIL] You must provide either --url (job posting URL) or --job-text (job description text)")
        sys.exit(1)

    resume_path = Path(args.resume)
    if not resume_path.exists():
        # Try to find any resume in Downloads
        downloads = Path.home() / "Downloads"
        found = list(downloads.glob("*Resume*.docx"))
        if found:
            resume_path = found[0]
            print(f"  [OK] Using found resume: {resume_path.name}")
        else:
            print(f"  [FAIL] Resume not found at: {resume_path}")
            print("    Please specify a valid path with --resume")
            sys.exit(1)
    else:
        print(f"  [OK] Resume: {resume_path.name}")

    if args.url:
        print(f"  [OK] Job URL: {args.url}")
    else:
        print(f"  [OK] Job description: {len(args.job_text)} chars (provided directly)")
    print(f"  [OK] Model: {args.model}")
    print(f"  [OK] Output: {args.output_dir}")
    if args.instructions:
        print(f"  [OK] Extra instructions: {args.instructions}")
    print()

    # --- Ensure output directory ---
    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    # --- Step 1: Load resume ---
    print("[1/4] Loading resume...")
    try:
        original_doc, resume_data = load_resume(resume_path)
        print(f"       [OK] Resume loaded ({len(resume_data.raw_text)} chars)")
    except Exception as e:
        print(f"       [FAIL] Error loading resume: {e}")
        sys.exit(1)

    # --- Step 2: Get job description ---
    if args.url:
        print("[2/4] Scraping job posting...")
        try:
            job_raw = scrape_job_posting(args.url)
            job_description = summarize_job_posting(job_raw)
            print(f"       [OK] Job description extracted ({len(job_description)} chars)")
        except Exception as e:
            print(f"       [FAIL] Error scraping job posting: {e}")
            print("       The URL may require authentication or be blocked.")
            print("       Provide the text directly with --job-text as a fallback.")
            sys.exit(1)
    else:
        print("[2/4] Using provided job description text...")
        job_description = summarize_job_posting(args.job_text)
        print(f"       [OK] Job description loaded ({len(job_description)} chars)")

    # --- Step 3: Tailor resume (unless skipped) ---
    if not args.skip_resume:
        print("[3/4] Tailoring resume with AI...")
        try:
            ai = AIHandler(
                model=args.model,
                host=args.ollama_host,
                temperature=args.temperature,
            )
            tailored = ai.tailor_resume(
                resume_text=resume_data.raw_text,
                job_description=job_description,
                instructions=args.instructions,
            )
            print(f"       [OK] Resume tailored ({len(tailored)} chars)")

            # Write tailored resume
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            resume_filename = f"Tailored_Resume_{timestamp}.docx"
            resume_output = output_dir / resume_filename
            write_tailored_resume(resume_path, tailored, resume_output)
            print(f"       [OK] Saved: {resume_output}")
        except Exception as e:
            print(f"       [FAIL] Error tailoring resume: {e}")
            print("       Make sure Ollama is running with your chosen model.")
            print(f"       Try: ollama pull {args.model}")
    else:
        print("[3/4] Skipping resume tailoring (--skip-resume)")

    # --- Step 4: Generate cover letter (unless skipped) ---
    if not args.skip_cover:
        print("[4/4] Generating cover letter...")
        try:
            if args.skip_resume:
                ai = AIHandler(
                    model=args.model,
                    host=args.ollama_host,
                    temperature=args.temperature,
                )
            # ai should already be initialized unless both skip-resume and skip-cover
            if 'ai' not in locals():
                ai = AIHandler(
                    model=args.model,
                    host=args.ollama_host,
                    temperature=args.temperature,
                )

            cover = ai.generate_cover_letter(
                resume_text=resume_data.raw_text,
                job_description=job_description,
                candidate_name="Jean-Jacques Boileau",
                instructions=args.instructions,
            )
            print(f"       [OK] Cover letter generated ({len(cover)} chars)")

            # Write cover letter
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            cover_filename = f"Cover_Letter_{timestamp}.docx"
            cover_output = output_dir / cover_filename
            write_cover_letter(cover, cover_output, resume_path)
            print(f"       [OK] Saved: {cover_output}")
        except Exception as e:
            print(f"       [FAIL] Error generating cover letter: {e}")
    else:
        print("[4/4] Skipping cover letter (--skip-cover)")

    print()
    print("=" * 65)
    print("  [OK] DONE! Your application materials are ready.")
    print(f"  [OK] Output folder: {output_dir.resolve()}")
    print("=" * 65)


if __name__ == "__main__":
    main()
