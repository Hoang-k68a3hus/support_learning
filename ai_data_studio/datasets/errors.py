from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from ai_data_studio.validation import ValidationReport


class GoldCompilationError(ValueError):
    """Working annotations cannot be compiled into authoritative gold."""


class GoldValidationError(GoldCompilationError):
    """Working inputs failed mandatory cross-object validation."""

    def __init__(self, report: "ValidationReport") -> None:
        self.report = report
        details = "; ".join(
            f"{issue.code.value}: {issue.message}" for issue in report.errors
        )
        super().__init__(f"working inputs are not valid for gold compilation: {details}")


class GoldEligibilityError(GoldCompilationError):
    """One or more requested records do not satisfy the gold policy."""

    def __init__(
        self,
        record_reasons: tuple[tuple[str, tuple[str, ...]], ...],
    ) -> None:
        self.record_reasons = record_reasons
        details = "; ".join(
            f"{record_id!r} [{', '.join(reasons)}]"
            for record_id, reasons in record_reasons
        )
        super().__init__(f"working records are not eligible for gold: {details}")


class GoldSourceResolutionError(GoldCompilationError):
    """Compiler inputs do not resolve to one exact canonical source revision."""


class GoldSplitResolutionError(GoldCompilationError):
    """Compiler inputs do not resolve through the supplied split manifest."""


class GoldDuplicateTargetError(GoldCompilationError):
    """More than one working record claims the same physical gold target."""


class GoldUnsupportedDecisionError(GoldCompilationError):
    """A working decision state cannot be represented as semantic gold."""


class DatasetFreezeError(RuntimeError):
    """A compiled gold dataset could not be published as a frozen release."""


class DatasetVersionAlreadyFrozenError(DatasetFreezeError):
    """The requested dataset name/version path is already immutable."""


class DatasetFreezeWriteError(DatasetFreezeError):
    """A frozen artifact could not be written or atomically published."""


class DatasetFreezeVerificationError(DatasetFreezeError):
    """Written artifacts failed mandatory round-trip verification."""


class DatasetFreezeInvariantError(DatasetFreezeError):
    """Freeze inputs violate release identity or provenance invariants."""
