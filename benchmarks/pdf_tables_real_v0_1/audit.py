from __future__ import annotations

from collections import Counter
from collections.abc import Iterable


MissedCaseKey = tuple[str, int]


def audit_missed_table_failures(
    missed_cases: Iterable[MissedCaseKey],
    source_reports: Iterable[dict[str, object]],
) -> dict[str, object]:
    """Summarize production failure reasons for independently known table misses.

    This is an audit view, not a gold evaluator. Gold determines which source/page
    cases are misses; production diagnostics only explain those misses. One case
    may expose multiple candidate-level reasons, so case coverage and raw reason
    occurrences are reported separately.
    """

    missed = tuple(sorted(set(missed_cases)))
    reports_by_source = {
        str(report.get("source_id")): report
        for report in source_reports
        if isinstance(report.get("source_id"), str)
    }

    case_counts: Counter[str] = Counter()
    occurrence_counts: Counter[str] = Counter()
    by_case: dict[str, object] = {}
    unclassified: list[str] = []

    for source_id, page in missed:
        reason_counts = _reason_counts_for_page(
            reports_by_source.get(source_id),
            page=page,
        )
        case_key = f"{source_id}#page:{page}"
        failure_classes = tuple(sorted(reason_counts))
        if failure_classes:
            case_counts.update(failure_classes)
            occurrence_counts.update(reason_counts)
        else:
            unclassified.append(case_key)
        by_case[case_key] = {
            "failure_classes": list(failure_classes),
            "candidate_reason_counts": dict(sorted(reason_counts.items())),
        }

    return {
        "missed_case_count": len(missed),
        "classified_missed_case_count": len(missed) - len(unclassified),
        "unclassified_missed_cases": unclassified,
        "failure_class_case_counts": dict(sorted(case_counts.items())),
        "candidate_reason_occurrences": dict(sorted(occurrence_counts.items())),
        "by_case": dict(sorted(by_case.items())),
    }


def _reason_counts_for_page(
    report: dict[str, object] | None,
    *,
    page: int,
) -> Counter[str]:
    counts: Counter[str] = Counter()
    if report is None:
        return counts
    diagnostics = report.get("table_diagnostics")
    if not isinstance(diagnostics, list):
        return counts
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            continue
        metadata = diagnostic.get("metadata")
        if not isinstance(metadata, dict) or metadata.get("page") != page:
            continue
        reason_counts = metadata.get("reason_counts")
        if not isinstance(reason_counts, dict):
            continue
        for reason, count in reason_counts.items():
            if (
                isinstance(reason, str)
                and reason.strip()
                and isinstance(count, int)
                and not isinstance(count, bool)
                and count > 0
            ):
                counts[reason] += count
    return counts
