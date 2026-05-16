"""
AI handler module.
Interfaces with OpenAI API to tailor resumes and generate cover letters.
"""

import logging
import json
import os
from typing import Optional, Callable

from openai import OpenAI

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "gpt-5.5"


class AIHandler:
    """Handles communication with OpenAI for resume/cover letter generation."""

    def __init__(
        self,
        model: str = DEFAULT_MODEL,
        temperature: float = 0.3,
        progress_callback: Optional[Callable] = None,
    ):
        api_key = os.environ.get("OPENAI_API_KEY")
        if not api_key:
            raise ValueError(
                "OPENAI_API_KEY environment variable not set. "
                "Run: setx OPENAI_API_KEY \"your-key-here\" and restart your terminal."
            )
        self.client = OpenAI(api_key=api_key, timeout=120)
        self.model = model
        self.temperature = temperature
        self.progress_callback = progress_callback
        logger.info(f"AIHandler initialized with model={model}")

    def _progress(self, step: str):
        if self.progress_callback:
            self.progress_callback(step)

    @staticmethod
    def _strip_markdown_json(text: str) -> str:
        """Extract outermost JSON object from text, stripping markdown fences."""
        text = text.strip()
        # Find outermost { ... } using brace counting
        start = text.find("{")
        if start == -1:
            return text
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i+1]
        return text

    def _call_ai(self, system_prompt: str, user_prompt: str, max_tokens: int = 4096) -> str:
        """Make a request to OpenAI and return the response text."""
        logger.debug(f"Calling OpenAI model={self.model}")

        kwargs = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
        }
        # o-series / gpt-5 reasoning models use max_completion_tokens and no temperature
        if self.model.startswith("gpt-5") or self.model.startswith("o"):
            kwargs["max_completion_tokens"] = max_tokens
        else:
            kwargs["max_tokens"] = max_tokens
            kwargs["temperature"] = self.temperature
        response = self.client.chat.completions.create(**kwargs)

        msg = response.choices[0].message
        msg_dict = msg.to_dict() if hasattr(msg, 'to_dict') else {}
        result = (msg.content or msg_dict.get("reasoning_content", "") or "").strip()
        logger.debug(f"OpenAI response received ({len(result)} chars)")
        return result

    def tailor_resume(
        self,
        resume_text: str,
        job_description: str,
        instructions: Optional[str] = None,
    ) -> tuple[str, str, list[str]]:
        """
        Tailor the resume to match the job posting.

        Returns:
            (tailored_resume_text, analysis_narrative, list_of_changes)
        """
        self._progress("Reading job posting and extracting key requirements...")

        system_prompt = """You are an expert executive resume writer and career coach. 
Your task is to analyze a job posting against a candidate's resume, then produce a tailored version.

You MUST output valid JSON only, with this structure:
{
  "analysis": "A 2-3 sentence narrative of what you observed about the match",
  "changes": ["Change 1", "Change 2", ...],
  "tailored_resume": "The complete tailored resume text"
}

TAILORING RULES:
- Preserve ALL factual experience - never fabricate skills, titles, or achievements
- Reword bullet points using keywords from the job description where authentic
- Reorder bullet points so the most relevant appear first
- Adjust the executive summary to align with the target role
- Highlight competencies that match the job requirements
- Keep the SAME format: Name, Tagline, Contact, EXECUTIVE SUMMARY, CORE COMPETENCIES (as bullet list), PROFESSIONAL EXPERIENCE (job | company | dates, location, \u2022 bullets per role), LANGUAGES

FORMAT RULES FOR THE TAILORED RESUME:
- Section headers MUST be ALL CAPS on their own line
- Job/role lines MUST use: Job Title | Company Name | Dates
- Bullet points MUST start with \u2022 (bullet character), one per line
- Never use markdown like **bold** or ## headers"""

        user_prompt = f"""=== CANDIDATE'S CURRENT RESUME ===

{resume_text}

=== TARGET JOB POSTING ===

{job_description}

{instructions or ""}

Output the complete tailored resume as valid JSON."""

        self._progress("Analyzing requirements and comparing to existing resume...")
        raw = self._call_ai(system_prompt, user_prompt, max_tokens=8192)

        self._progress("Identifying gaps and tailoring content sections...")
        try:
            clean = self._strip_markdown_json(raw)
            data = json.loads(clean)
            tailored = data.get("tailored_resume", clean)
            analysis = data.get("analysis", "Resume tailored to match the job requirements.")
            changes = data.get("changes", [])
        except (json.JSONDecodeError, KeyError):
            tailored = raw
            analysis = "Resume tailored and optimized for the target position."
            changes = ["Content adjusted to emphasize relevant experience"]

        self._progress("Finalizing tailored resume...")
        return tailored, analysis, changes

    def generate_cover_letter(
        self,
        resume_text: str,
        job_description: str,
        candidate_name: str = "Jean-Jacques Boileau",
        instructions: Optional[str] = None,
    ) -> tuple[str, str]:
        """
        Generate a tailored cover letter.

        Returns:
            (cover_letter_text, analysis_narrative)
        """
        self._progress("Analyzing job requirements for cover letter...")

        system_prompt = """You are an expert cover letter writer. Your task is to write a compelling, professional cover letter.

You MUST output valid JSON only, with this structure:
{
  "analysis": "A 2-3 sentence narrative of your approach to this cover letter",
  "cover_letter": "The complete cover letter text"
}

RULES:
- Address it to "Dear Hiring Manager," unless a specific name is given
- Candidate name: Jean-Jacques Boileau
- Open with a strong hook mentioning the role and company
- 2-3 body paragraphs connecting specific achievements to job requirements
- Close professionally with a call to action
- Be specific - reference actual metrics and achievements
- Do NOT fabricate experience

FORMAT FOR COVER LETTER:
- Start with "Dear Hiring Manager," on its own line
- Separate each paragraph with a blank line
- End with "Sincerely," then "Jean-Jacques Boileau" on the next line"""

        user_prompt = f"""=== CANDIDATE'S RESUME ===

{resume_text}

=== TARGET JOB POSTING ===

{job_description}

{instructions or ""}

Output the complete cover letter as valid JSON."""

        self._progress("Drafting compelling opening paragraph...")
        raw = self._call_ai(system_prompt, user_prompt, max_tokens=4096)

        self._progress("Crafting body paragraphs and closing statement...")
        try:
            clean = self._strip_markdown_json(raw)
            data = json.loads(clean)
            cover = data.get("cover_letter", clean)
            analysis = data.get("analysis", "Cover letter crafted to highlight relevant experience.")
        except (json.JSONDecodeError, KeyError):
            cover = raw
            analysis = "Cover letter written to match the target position."

        return cover, analysis

    def generate_summary(
        self,
        job_description: str,
        resume_analysis: str,
        resume_changes: list[str],
        cover_analysis: str,
    ) -> str:
        """
        Generate a post-processing summary explaining what was done and why.
        """
        self._progress("Generating processing report...")

        system_prompt = """You are a professional resume writing consultant. 
Write a brief, insightful summary of what was done to tailor this candidate's application materials.
The summary should be 3-5 paragraphs and explain:

1. What the job required
2. How the resume was adjusted to meet those requirements
3. What specific changes were made and why
4. How the cover letter supports the application

Write in a professional, consultative tone. Be specific about the changes made."""

        changes_text = "\n".join(f"- {c}" for c in resume_changes) if resume_changes else "- Content optimized for target role"

        user_prompt = f"""=== JOB DESCRIPTION ===
{job_description[:2000]}

=== RESUME ANALYSIS ===
{resume_analysis}

=== CHANGES MADE TO RESUME ===
{changes_text}

=== COVER LETTER ANALYSIS ===
{cover_analysis}

Please write a comprehensive summary of what was done and why."""

        result = self._call_ai(system_prompt, user_prompt, max_tokens=2048)
        return result

    def extract_company_name(self, job_description: str) -> str:
        """Try to extract the company name from the job posting."""
        system_prompt = "Extract the company name from this job posting. Return ONLY the company name, nothing else."
        try:
            result = self._call_ai(system_prompt, job_description[:2000], max_tokens=100)
            result = result.strip().strip('"').strip("'")
            if len(result) < 100 and result:
                return result
        except Exception as e:
            logger.warning(f"Could not extract company name: {e}")
        return "Hiring Manager"

    def extract_job_title(self, job_description: str) -> str:
        """Try to extract the job title from the posting."""
        system_prompt = "Extract the job title from this job posting. Return ONLY the job title, nothing else."
        try:
            result = self._call_ai(system_prompt, job_description[:2000], max_tokens=100)
            result = result.strip().strip('"').strip("'")
            if len(result) < 100 and result:
                return result
        except Exception as e:
            logger.warning(f"Could not extract job title: {e}")
        return "the position"
