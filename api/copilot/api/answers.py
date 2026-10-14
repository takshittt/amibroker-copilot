"""Pipeline results as plain JSON, for the stream and for the messages table.

What the user sees is decided here once, so the live answer and the one
shown again from history are the same.
"""

from copilot.pipeline.orchestrator import WriteResult
from copilot.pipeline.review import ReviewFinding, ReviewResult
from copilot.pipeline.rewrite import FixResult

# Statuses that give the user an answer, and so use a unit of quota.
ANSWERED = frozenset(["checked", "not_fully_checked", "not_checked", "reviewed"])


def _checks(checks) -> list[dict]:
    return [{"name": line.name, "outcome": line.outcome} for line in checks]


def _problems(problems) -> list[dict]:
    return [
        {
            "rule": p.rule,
            "source": p.source,
            "severity": p.severity,
            "line": p.line,
            "message": p.message,
            "fix": p.fix_hint,
        }
        for p in problems
    ]


def finding_dict(finding: ReviewFinding) -> dict:
    return {
        "label": finding.label,
        "severity": finding.severity,
        "line": finding.line,
        "message": finding.message,
        "fix": finding.fix,
        "rule": finding.rule,
    }


def finding_from_dict(data: dict) -> ReviewFinding:
    return ReviewFinding(
        data["label"], data["severity"], data["line"], data["message"], data["fix"], data["rule"]
    )


def write_answer(result: WriteResult) -> dict:
    return {
        "status": result.status,
        "questions": list(result.questions),
        "code": result.code,
        "explanation": [block.model_dump() for block in result.explanation_blocks],
        "checks": _checks(result.checks),
        "problems": _problems(result.problems),
        "doc_links": [{"name": name, "url": url} for name, url in result.doc_links],
        "notes": list(result.notes),
        "message": result.message,
    }


def review_answer(result: ReviewResult, code: str) -> dict:
    return {
        "status": result.status,
        "findings": [finding_dict(f) for f in result.findings],
        "checks": _checks(result.checks),
        "checker_status": result.checker_status,
        "ai_review": result.ai_review,
        "summary": result.summary,
        "notes": list(result.notes),
        "message": result.message,
        # Kept so "apply all fixes" works on exactly the code that was reviewed.
        "reviewed_code": code,
    }


def fix_answer(result: FixResult) -> dict:
    return {
        "status": result.status,
        "code": result.code,
        "changes": [{"line": c.line, "text": c.text} for c in result.changes],
        "checks": _checks(result.checks),
        "problems": _problems(result.problems),
        "doc_links": [{"name": name, "url": url} for name, url in result.doc_links],
        "notes": list(result.notes),
        "message": result.message,
    }
