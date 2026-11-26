"""Contract tests for Omega's shared execution decision boundary."""

import pytest

from execution_decision import (
    ExecutionDecisionError,
    ExecutionPlanSelector,
    ExecutionRequest,
    ModelRoute,
    ModelRoutingRequest,
)


def test_coordinator_plan_can_include_an_independent_model_route():
    seen = []

    def choose_model(request):
        seen.append(request)
        return ModelRoute("OpenRouter", "balanced-model", "complexity-policy")

    request = ExecutionRequest(
        task="Answer a short question",
        model_request=ModelRoutingRequest(
            requirements={"complexity": "low", "latency": "interactive"}
        ),
    )
    plan = ExecutionPlanSelector(model_selector=choose_model).select(request)

    assert plan.mode == "coordinator"
    assert plan.worker_id is None
    assert plan.model_route.provider_id == "OpenRouter"
    assert seen == [request.model_request]


def test_subagent_and_model_policies_are_composed_in_one_plan():
    def choose_worker(request):
        assert request.capability == "coding"
        return "coding-agent"

    def choose_model(request):
        assert request.requirements == {"complexity": "high"}
        return ModelRoute("Provider-A", "code-model")

    selector = ExecutionPlanSelector(choose_worker, choose_model)
    plan = selector.select(ExecutionRequest(
        task="Implement the bounded change",
        capability="coding",
        model_request=ModelRoutingRequest(requirements={"complexity": "high"}),
    ))

    assert plan.mode == "subagent"
    assert plan.worker_id == "coding-agent"
    assert plan.requested_capability == "coding"
    assert plan.model_route.model_id == "code-model"


def test_explicit_worker_override_remains_a_policy_input():
    selector = ExecutionPlanSelector(
        worker_selector=lambda request: request.explicit_worker_id
    )

    plan = selector.select(ExecutionRequest(
        task="Review this artifact",
        capability="research",
        explicit_worker_id="reviewer-agent",
    ))

    assert plan.worker_id == "reviewer-agent"
    assert plan.reason == "explicit_worker"


def test_subagent_request_requires_a_worker_policy():
    with pytest.raises(ExecutionDecisionError, match="worker-selection policy"):
        ExecutionPlanSelector().select(ExecutionRequest(
            task="Investigate",
            capability="research",
        ))


def test_model_requirements_are_provider_neutral_and_json_safe():
    request = ModelRoutingRequest.from_input({
        "requirements": {"complexity": "high", "privacy": "local"},
        "preferred_provider": "Provider-A",
        "preferred_model": "model-1",
    })

    assert request.to_dict() == {
        "requirements": {"complexity": "high", "privacy": "local"},
        "preferred_provider": "Provider-A",
        "preferred_model": "model-1",
    }


def test_invalid_model_requirements_are_rejected():
    with pytest.raises(ExecutionDecisionError, match="must be an object"):
        ModelRoutingRequest.from_input({"requirements": ["high"]})


def test_invalid_model_policy_result_is_rejected():
    selector = ExecutionPlanSelector(model_selector=lambda request: "model-1")

    with pytest.raises(ExecutionDecisionError, match="invalid model route"):
        selector.select(ExecutionRequest(task="Answer directly"))
