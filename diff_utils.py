"""
Diff utility for comparing original vs. tailored resume text.
"""

import difflib
import html


def generate_diff_html(original: str, tailored: str) -> str:
    """
    Generate an HTML diff between original and tailored resume text.
    Returns an HTML fragment with inline highlights:
      green background for new/added lines,
      red background for removed lines.
    """
    orig_lines = original.splitlines(keepends=False)
    tail_lines = tailored.splitlines(keepends=False)

    diff = list(difflib.ndiff(orig_lines, tail_lines))

    parts = []
    parts.append('<div class="diff-container">')

    for line in diff:
        if not line:
            continue
        prefix = line[:2]
        content = line[2:]
        escaped = html.escape(content)

        if prefix == "  ":
            parts.append(f'<div class="diff-unchanged"><span>{escaped}</span></div>')
        elif prefix == "- ":
            parts.append(f'<div class="diff-removed"><span>{escaped}</span></div>')
        elif prefix == "+ ":
            parts.append(f'<div class="diff-added"><span>{escaped}</span></div>')
        elif prefix == "? ":
            continue  # skip ndiff position markers

    parts.append('</div>')
    return "\n".join(parts)
