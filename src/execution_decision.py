"""Backend-neutral execution planning shared by Omega capabilities.

The selector joins two decisions made at the same orchestration point without
coupling their implementations: whether/where to delegate work, and which
model route should execute it.  Subagent and model-router plugins provide the
respective policies.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any, Mapping, Protocol


class ExecutionDecisionError(ValueError):
    """Raised when an execution request or policy decision is invalid."""


@dataclass(frozen=True)
class ModelRoutingRequest:
    """Provider-neutral requirements for a later model-routing policy."""

    requirements: Mapping[str, str] = field(default_factory=dict)
    preferred_provider: str | None = None
    preferred_model: str | None = None

    @classmethod
    def from_input(cls, value: Any = None) -> "ModelRoutingRequest":
        if value is None:
            return cls()
        if isinstance(value, cls):
            return value
        if not isinstance(value, Mapping):
            raise ExecutionDecisionError("model requirements must be a JSON object")
        raw_requirements = value.get("requirements", {})
        if not isinstance(raw_requirements, Mapping):
            raise ExecutionDecisionError("model requirements.requirements must be an object")
        requirements = {
            str(key).strip(): str(item).strip()
            for key, item in raw_requirements.items()
            if str(key).strip() and str(item).strip()
        }
        return cls(
            requirements=requirements,
            preferred_provider=_optional_text(value.get("preferred_provider")),
            preferred_model=_optional_text(value.get("preferred_model")),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "requirements": dict(self.requirements),
            "preferred_provider": self.preferred_provider,
            "preferred_model": self.preferred_model,
        }


@dataclass(frozen=True)
class ModelRoute:
    """Concrete provider/model choice returned by a model-routing policy."""

    provider_id: str
    model_id: str
    reason: str = "policy"

    def __post_init__(self) -> None:
        if not self.provider_id.strip() or not self.model_id.strip():
            raise ExecutionDecisionError("model route requires provider_id and model_id")


@dataclass(frozen=True)
class WorkerSelectionRequest:
    task: str
    capability: str | None = None
    explicit_worker_id: str | None = None


class WorkerSelector(Protocol):
    def __call__(self, request: WorkerSelectionRequest) -> str:
        """Return one registered worker identifier."""


class ModelSelector(Protocol):
    def __call__(self, request: ModelRoutingRequest) -> ModelRoute:
        """Return one provider/model route."""


@dataclass(frozen=True)
class ExecutionRequest:
    task: str
    capability: str | None = None
    explicit_worker_id: str | None = None
    model_request: ModelRoutingRequest = field(default_factory=ModelRoutingRequest)

    def __post_init__(self) -> None:
        if not self.task.strip():
            raise ExecutionDecisionError("execution task is empty")


@dataclass(frozen=True)
class ExecutionPlan:
    """Omega-owned decision consumed independently by execution plugins."""

    mode: str
    task: str
    worker_id: str | None
    requested_capability: str | None
    model_request: ModelRoutingRequest
    model_route: ModelRoute | None
    reason: str

    def __post_init__(self) -> None:
        if self.mode not in {"coordinator", "subagent"}:
            raise ExecutionDecisionError(f"unsupported execution mode: {self.mode}")
        if self.mode == "subagent" and not self.worker_id:
            raise ExecutionDecisionError("subagent execution requires worker_id")
        if self.mode == "coordinator" and self.worker_id:
            raise ExecutionDecisionError("coordinator execution cannot select a worker")

    def to_dict(self) -> dict[str, Any]:
        value = asdict(self)
        value["model_request"] = self.model_request.to_dict()
        value["model_route"] = asdict(self.model_route) if self.model_route else None
        return value


class ExecutionPlanSelector:
    """Compose worker and model policies at one Omega decision boundary."""

    def __init__(
        self,
        worker_selector: WorkerSelector | None = None,
        model_selector: ModelSelector | None = None,
    ):
        self.worker_selector = worker_selector
        self.model_selector = model_selector

    def select(self, request: ExecutionRequest) -> ExecutionPlan:
        model_route = (
            self.model_selector(request.model_request)
            if self.model_selector is not None
            else None
        )
        if model_route is not None and not isinstance(model_route, ModelRoute):
            raise ExecutionDecisionError(
                "model-selection policy returned an invalid model route"
            )
        wants_worker = bool(request.capability or request.explicit_worker_id)
        if not wants_worker:
            return ExecutionPlan(
                mode="coordinator",
                task=request.task.strip(),
                worker_id=None,
                requested_capability=None,
                model_request=request.model_request,
                model_route=model_route,
                reason="coordinator_default",
            )
        if self.worker_selector is None:
            raise ExecutionDecisionError(
                "subagent execution requested without a worker-selection policy"
            )
        worker_id = self.worker_selector(WorkerSelectionRequest(
            task=request.task.strip(),
            capability=_optional_text(request.capability),
            explicit_worker_id=_optional_text(request.explicit_worker_id),
        ))
        if not str(worker_id).strip():
            raise ExecutionDecisionError("worker-selection policy returned no worker")
        return ExecutionPlan(
            mode="subagent",
            task=request.task.strip(),
            worker_id=str(worker_id).strip(),
            requested_capability=_optional_text(request.capability),
            model_request=request.model_request,
            model_route=model_route,
            reason=(
                "explicit_worker" if request.explicit_worker_id
                else "capability"
            ),
        )


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
