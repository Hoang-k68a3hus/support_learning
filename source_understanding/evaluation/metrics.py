from __future__ import annotations

from collections.abc import Iterable

from pydantic import Field

from source_understanding.schemas.context import SchemaModel


class PRFScore(SchemaModel):
    true_positive: int = Field(ge=0)
    false_positive: int = Field(ge=0)
    false_negative: int = Field(ge=0)
    precision: float | None = Field(default=None, ge=0.0, le=1.0)
    recall: float | None = Field(default=None, ge=0.0, le=1.0)
    f1: float | None = Field(default=None, ge=0.0, le=1.0)
    support: int = Field(ge=0)


class AccuracyScore(SchemaModel):
    correct: int = Field(ge=0)
    total: int = Field(ge=0)
    accuracy: float | None = Field(default=None, ge=0.0, le=1.0)


class LabelPRF(SchemaModel):
    label: str
    score: PRFScore


def prf_counts(tp: int, fp: int, fn: int) -> PRFScore:
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    if precision is None or recall is None:
        f1 = None
    elif precision + recall == 0:
        f1 = 0.0
    else:
        f1 = 2 * precision * recall / (precision + recall)
    return PRFScore(
        true_positive=tp,
        false_positive=fp,
        false_negative=fn,
        precision=precision,
        recall=recall,
        f1=f1,
        support=tp + fn,
    )


def prf_from_sets(gold: set[object], predicted: set[object]) -> PRFScore:
    return prf_counts(
        len(gold & predicted),
        len(predicted - gold),
        len(gold - predicted),
    )


def accuracy_score(correct: int, total: int) -> AccuracyScore:
    return AccuracyScore(
        correct=correct,
        total=total,
        accuracy=correct / total if total else None,
    )


def macro_f1(scores: Iterable[PRFScore]) -> float | None:
    values = [score.f1 for score in scores if score.support > 0 and score.f1 is not None]
    return sum(values) / len(values) if values else None
