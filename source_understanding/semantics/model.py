from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from typing import Protocol, runtime_checkable

from pydantic import Field, model_validator

from source_understanding.schemas.context import JsonObject, SchemaModel

from .provider import (
    SemanticCandidate,
    SemanticProviderCapabilities,
    SemanticRequest,
)


MODEL_SEMANTIC_PROVIDER_VERSION = "1"
MODEL_SEMANTIC_PROVIDER_POLICY_VERSION = "1"


class ModelSemanticProviderError(ValueError):
    """A model backend violated the structured semantic-provider boundary."""


class ModelSemanticProviderPolicy(SchemaModel):
    version: str = MODEL_SEMANTIC_PROVIDER_POLICY_VERSION
    batch_size: int = Field(default=16, ge=1, le=256)
    max_candidates_per_target: int = Field(default=32, ge=1, le=256)


class _ModelSemanticConfiguration(SchemaModel):
    value: JsonObject


class SemanticModelBatch(SchemaModel):
    provider_name: str = Field(min_length=1, max_length=128)
    provider_version: str = Field(min_length=1, max_length=128)
    batch_index: int = Field(ge=0)
    requests: tuple[SemanticRequest, ...] = Field(min_length=1)
    capabilities: SemanticProviderCapabilities

    @model_validator(mode="after")
    def validate_targets(self) -> "SemanticModelBatch":
        target_ids = [request.target_id for request in self.requests]
        if len(target_ids) != len(set(target_ids)):
            raise ValueError("semantic model batch request target_ids must be unique")
        return self


@runtime_checkable
class SemanticModelBackend(Protocol):
    """Transport-neutral structured inference backend.

    Implementations may call a local model, hosted API, or deterministic fixture.
    They return candidate-shaped objects; the provider and annotator validate every
    target, capability, provenance class, and schema field before attachment.
    """

    name: str
    version: str

    def infer(self, batch: SemanticModelBatch) -> Iterable[object]: ...


class ModelSemanticProvider:
    """Adapt structured model inference to the current SemanticProvider protocol."""

    implementation_version = MODEL_SEMANTIC_PROVIDER_VERSION

    def __init__(
        self,
        *,
        name: str,
        version: str,
        backend: SemanticModelBackend,
        capabilities: SemanticProviderCapabilities,
        policy: ModelSemanticProviderPolicy | None = None,
        configuration: dict[str, object] | None = None,
    ) -> None:
        if not isinstance(name, str) or not name.strip() or len(name.strip()) > 128:
            raise TypeError("model semantic provider name must be non-blank and <= 128 chars")
        if not isinstance(version, str) or not version.strip() or len(version.strip()) > 128:
            raise TypeError(
                "model semantic provider version must be non-blank and <= 128 chars"
            )
        infer = getattr(backend, "infer", None)
        backend_name = getattr(backend, "name", None)
        backend_version = getattr(backend, "version", None)
        if not callable(infer):
            raise TypeError("semantic model backend must define callable infer(batch)")
        if (
            not isinstance(backend_name, str)
            or not backend_name.strip()
            or len(backend_name.strip()) > 128
        ):
            raise TypeError("semantic model backend name must be non-blank and <= 128 chars")
        if (
            not isinstance(backend_version, str)
            or not backend_version.strip()
            or len(backend_version.strip()) > 128
        ):
            raise TypeError(
                "semantic model backend version must be non-blank and <= 128 chars"
            )

        self.name = name.strip()
        self.version = version.strip()
        self.capabilities = SemanticProviderCapabilities.model_validate(capabilities)
        self._backend = backend
        self._policy = policy if policy is not None else ModelSemanticProviderPolicy()
        self.configuration = _ModelSemanticConfiguration(
            value={
                "implementation_version": self.implementation_version,
                "policy": self._policy.model_dump(mode="json"),
                "backend": {
                    "name": backend_name.strip(),
                    "version": backend_version.strip(),
                },
                "model": {} if configuration is None else configuration,
            }
        ).value

    def annotate(
        self,
        requests: tuple[SemanticRequest, ...],
    ) -> Iterable[SemanticCandidate]:
        snapshot = tuple(requests)
        target_ids = [request.target_id for request in snapshot]
        if len(target_ids) != len(set(target_ids)):
            raise ModelSemanticProviderError(
                "model semantic provider requires unique request target_ids"
            )
        if not snapshot:
            return ()

        output: list[SemanticCandidate] = []
        counts: Counter[str] = Counter()
        batch_size = self._policy.batch_size
        for batch_index, start in enumerate(range(0, len(snapshot), batch_size)):
            requests_batch = snapshot[start : start + batch_size]
            batch = SemanticModelBatch(
                provider_name=self.name,
                provider_version=self.version,
                batch_index=batch_index,
                requests=requests_batch,
                capabilities=self.capabilities,
            )
            try:
                raw_candidates = tuple(self._backend.infer(batch))
            except Exception as exc:
                raise ModelSemanticProviderError(
                    f"semantic model backend {self._backend.name!r} failed for "
                    f"batch {batch_index}: {exc}"
                ) from exc

            allowed_targets = {
                request.target_id: request.target_kind for request in requests_batch
            }
            for raw_candidate in raw_candidates:
                try:
                    candidate = SemanticCandidate.model_validate(raw_candidate)
                except Exception as exc:
                    raise ModelSemanticProviderError(
                        f"semantic model backend returned invalid candidate: "
                        f"{raw_candidate!r}: {exc}"
                    ) from exc
                target_kind = allowed_targets.get(candidate.target_id)
                if target_kind is None:
                    raise ModelSemanticProviderError(
                        "semantic model backend returned candidate for target outside "
                        f"batch {batch_index}: {candidate.target_id!r}"
                    )
                if not self.capabilities.supports_candidate(
                    target_kind,
                    candidate.type,
                    candidate.ontology,
                ):
                    raise ModelSemanticProviderError(
                        "semantic model backend returned output outside declared capability: "
                        f"target={candidate.target_id!r}, type={candidate.type.value!r}"
                    )
                counts[candidate.target_id] += 1
                if counts[candidate.target_id] > self._policy.max_candidates_per_target:
                    raise ModelSemanticProviderError(
                        f"semantic model backend exceeded max_candidates_per_target for "
                        f"{candidate.target_id!r}"
                    )
                output.append(candidate)
        return tuple(output)
