from __future__ import annotations

import hashlib
import re
from collections.abc import Sequence
from enum import StrEnum

from pydantic import Field, field_validator, model_validator

from source_understanding.schemas.context import (
    Confidence,
    FiniteFloat,
    Identifier,
    JsonObject,
    Label,
    SchemaModel,
    StructureSource,
)
from source_understanding.schemas.element import Element, ElementType
from source_understanding.source_attributes import (
    HEADING_LEVEL_ATTRIBUTE,
    SourceAttributeError,
    source_heading_level,
)


STRUCTURE_SIGNAL_VERSION = "2"
STRUCTURE_SIGNAL_POLICY_VERSION = "1"

_DEFAULT_SECTION_MARKERS = (
    "chapter",
    "section",
    "part",
    "điều",
    "khoản",
    "mục",
    "summary",
    "todo",
)

_NUMBERING_RE = re.compile(
    r"^\s*(?P<marker>(?:\d+\.\d+(?:\.\d+)*|\d+[.)]|[A-Za-z][.)]|[IVXLCDMivxlcdm]+[.)]))\s+"
)
_QUESTION_RE = re.compile(r"^\s*(?P<marker>q(?:uestion)?\s*[:\-])\s*", re.IGNORECASE)
_ANSWER_RE = re.compile(r"^\s*(?P<marker>a(?:nswer)?\s*[:\-])\s*", re.IGNORECASE)
_TIMESTAMP_RE = re.compile(
    r"^\s*(?P<marker>"
    r"\[(?:\d{4}-\d{2}-\d{2}[ T])?\d{1,2}:\d{2}(?::\d{2})?\]"
    r"|(?:\d{4}-\d{2}-\d{2}[ T])\d{1,2}:\d{2}(?::\d{2})?"
    r"|\d{1,2}:\d{2}(?::\d{2})?"
    r")(?=\s|$)"
)
_SPEAKER_RE = re.compile(r"^\s*(?P<marker>[^\s:][^:\n]{0,39})\s*:\s+(?=\S)")
_LEXICAL_TYPES = frozenset(
    {
        ElementType.TITLE,
        ElementType.HEADING,
        ElementType.PARAGRAPH,
        ElementType.SENTENCE,
        ElementType.LINE,
        ElementType.QUESTION,
        ElementType.ANSWER,
        ElementType.DIALOGUE_TURN,
        ElementType.UNKNOWN,
    }
)


class StructureSignalError(ValueError):
    """Input cannot be converted into trustworthy structural evidence."""


class StructureSignalKind(StrEnum):
    """Observed/inferred evidence only; no kind represents a final boundary."""

    ELEMENT_TYPE = "ELEMENT_TYPE"
    STYLE_BOLD = "STYLE_BOLD"
    STYLE_FONT_SIZE = "STYLE_FONT_SIZE"
    STYLE_INDENTATION = "STYLE_INDENTATION"
    HEADING_LEVEL = "HEADING_LEVEL"
    NUMBERING_MARKER = "NUMBERING_MARKER"
    SECTION_MARKER = "SECTION_MARKER"
    QUESTION_MARKER = "QUESTION_MARKER"
    ANSWER_MARKER = "ANSWER_MARKER"
    TIMESTAMP_PATTERN = "TIMESTAMP_PATTERN"
    SPEAKER_LABEL_CANDIDATE = "SPEAKER_LABEL_CANDIDATE"
    ELEMENT_TYPE_TRANSITION = "ELEMENT_TYPE_TRANSITION"


class StructureSignalPolicy(SchemaModel):
    """Configuration that materially affects deterministic signal extraction."""

    version: str = STRUCTURE_SIGNAL_POLICY_VERSION
    section_markers: tuple[str, ...] = _DEFAULT_SECTION_MARKERS

    @field_validator("section_markers", mode="before")
    @classmethod
    def normalize_markers(cls, value: object) -> object:
        if isinstance(value, str) or value is None:
            raise ValueError("section_markers must be a sequence of marker strings")
        try:
            markers = tuple(value)
        except TypeError as exc:
            raise ValueError("section_markers must be an iterable of strings") from exc
        if any(not isinstance(marker, str) for marker in markers):
            raise ValueError("section_markers must contain only strings")
        return tuple(marker.strip() for marker in markers)

    @model_validator(mode="after")
    def validate_markers(self) -> "StructureSignalPolicy":
        if not self.section_markers or any(not marker for marker in self.section_markers):
            raise ValueError("section_markers must contain non-blank markers")
        if any(len(marker) > 128 for marker in self.section_markers):
            raise ValueError("section markers must be <= 128 characters")
        folded = [marker.casefold() for marker in self.section_markers]
        if len(folded) != len(set(folded)):
            raise ValueError("section_markers must be unique case-insensitively")
        return self


class StructureSignal(SchemaModel):
    """One auditable piece of structural evidence attached to one/two elements."""

    id: Identifier
    kind: StructureSignalKind
    element_ids: tuple[Identifier, ...] = Field(min_length=1, max_length=2)
    source: StructureSource
    confidence: Confidence | None = None
    text_value: Label | None = None
    numeric_value: FiniteFloat | None = None
    metadata: JsonObject = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_element_refs(self) -> "StructureSignal":
        if len(self.element_ids) != len(set(self.element_ids)):
            raise ValueError("structure signal element_ids must be unique")
        return self


class StructureSignalSet(SchemaModel):
    version: str = STRUCTURE_SIGNAL_VERSION
    element_count: int = Field(ge=1)
    policy: StructureSignalPolicy = Field(default_factory=StructureSignalPolicy)
    signals: tuple[StructureSignal, ...] = Field(default_factory=tuple)


class StructureSignalExtractor:
    """Extract local structural evidence without deciding boundaries or groups."""

    version: str = STRUCTURE_SIGNAL_VERSION

    def __init__(
        self,
        *,
        section_markers: Sequence[str] | None = None,
        policy: StructureSignalPolicy | None = None,
    ) -> None:
        if section_markers is not None and policy is not None:
            raise ValueError("provide either section_markers or policy, not both")
        if policy is None:
            policy = StructureSignalPolicy(
                section_markers=(
                    _DEFAULT_SECTION_MARKERS
                    if section_markers is None
                    else tuple(section_markers)
                )
            )
        self._policy = policy
        self._section_markers = policy.section_markers
        escaped = "|".join(
            re.escape(marker)
            for marker in sorted(self._section_markers, key=len, reverse=True)
        )
        self._section_marker_re = re.compile(
            rf"^\s*(?P<marker>{escaped})(?=\s|[:.\-]|$)",
            re.IGNORECASE,
        )

    def extract(self, elements: Sequence[Element]) -> StructureSignalSet:
        snapshot = tuple(elements)
        self._validate_elements(snapshot)

        signals: list[StructureSignal] = []
        for index, element in enumerate(snapshot):
            signals.extend(self._element_signals(element))
            if index:
                previous = snapshot[index - 1]
                if previous.type != element.type:
                    signals.append(
                        self._signal(
                            StructureSignalKind.ELEMENT_TYPE_TRANSITION,
                            (previous.id, element.id),
                            source=StructureSource.DERIVED,
                            metadata={
                                "from_type": previous.type.value,
                                "to_type": element.type.value,
                            },
                        )
                    )

        return StructureSignalSet(
            element_count=len(snapshot),
            policy=self._policy,
            signals=tuple(signals),
        )

    def _element_signals(self, element: Element) -> list[StructureSignal]:
        signals = [
            self._signal(
                StructureSignalKind.ELEMENT_TYPE,
                (element.id,),
                source=element.provenance.source,
                confidence=element.confidence.type,
                text_value=element.type.value,
            )
        ]

        if element.type == ElementType.HEADING and HEADING_LEVEL_ATTRIBUTE in element.attributes:
            try:
                heading_level = source_heading_level(element)
            except SourceAttributeError as exc:
                raise StructureSignalError(str(exc)) from exc
            if heading_level is not None:
                signals.append(
                    self._signal(
                        StructureSignalKind.HEADING_LEVEL,
                        (element.id,),
                        source=element.provenance.source,
                        confidence=element.confidence.type,
                        numeric_value=float(heading_level),
                        metadata={"attribute_key": HEADING_LEVEL_ATTRIBUTE},
                    )
                )

        if element.style is not None:
            if element.style.bold is True:
                signals.append(
                    self._signal(
                        StructureSignalKind.STYLE_BOLD,
                        (element.id,),
                        source=element.provenance.source,
                    )
                )
            if element.style.font_size is not None:
                signals.append(
                    self._signal(
                        StructureSignalKind.STYLE_FONT_SIZE,
                        (element.id,),
                        source=element.provenance.source,
                        numeric_value=element.style.font_size,
                    )
                )
            if element.style.indentation is not None:
                signals.append(
                    self._signal(
                        StructureSignalKind.STYLE_INDENTATION,
                        (element.id,),
                        source=element.provenance.source,
                        numeric_value=element.style.indentation,
                    )
                )

        text = element.text
        if text is None or element.type not in _LEXICAL_TYPES:
            return signals

        question_match = _QUESTION_RE.match(text)
        answer_match = _ANSWER_RE.match(text)
        timestamp_match = _TIMESTAMP_RE.match(text)

        for kind, match in (
            (StructureSignalKind.NUMBERING_MARKER, _NUMBERING_RE.match(text)),
            (StructureSignalKind.SECTION_MARKER, self._section_marker_re.match(text)),
            (StructureSignalKind.QUESTION_MARKER, question_match),
            (StructureSignalKind.ANSWER_MARKER, answer_match),
            (StructureSignalKind.TIMESTAMP_PATTERN, timestamp_match),
        ):
            if match is not None:
                signals.append(
                    self._signal(
                        kind,
                        (element.id,),
                        source=StructureSource.INFERRED,
                        text_value=match.group("marker").strip(),
                    )
                )

        speaker_match = _SPEAKER_RE.match(text)
        if (
            speaker_match is not None
            and question_match is None
            and answer_match is None
            and timestamp_match is None
            and self._section_marker_re.match(text) is None
        ):
            signals.append(
                self._signal(
                    StructureSignalKind.SPEAKER_LABEL_CANDIDATE,
                    (element.id,),
                    source=StructureSource.INFERRED,
                    text_value=speaker_match.group("marker").strip(),
                )
            )

        return signals

    @staticmethod
    def _signal(
        kind: StructureSignalKind,
        element_ids: tuple[str, ...],
        *,
        source: StructureSource,
        confidence: float | None = None,
        text_value: str | None = None,
        numeric_value: float | None = None,
        metadata: dict[str, object] | None = None,
    ) -> StructureSignal:
        identity = "|".join((kind.value, *element_ids))
        digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
        return StructureSignal(
            id=f"sig_{digest}",
            kind=kind,
            element_ids=element_ids,
            source=source,
            confidence=confidence,
            text_value=text_value,
            numeric_value=numeric_value,
            metadata={} if metadata is None else metadata,
        )

    @staticmethod
    def _validate_elements(elements: tuple[Element, ...]) -> None:
        if not elements:
            raise StructureSignalError("cannot extract structure signals from empty elements")

        ids = [element.id for element in elements]
        if len(ids) != len(set(ids)):
            raise StructureSignalError("structure signals require unique element ids")

        orders = [element.order for element in elements]
        if len(orders) != len(set(orders)):
            raise StructureSignalError("structure signals require unique element order values")
        if orders != sorted(orders):
            raise StructureSignalError(
                "structure signals require elements in ascending canonical source order"
            )
