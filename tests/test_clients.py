import httpx
import pytest

from forecast_agent.clients import Budget, BudgetExceeded, CompatibleLLM, ProviderError, TavilySearch
from forecast_agent.config import Secrets, load_settings
from forecast_agent.schemas import ResearchPlan, Usage


def setup_client(handler, retries=0):
    settings = load_settings().model_copy(update={"search_retries": retries})
    secrets = Secrets(
        _env_file=None,
        tavily_api_key="test-only",
        llm_api_key="test-only",
        llm_base_url="https://test.invalid/v1",
    )
    budget = Budget(settings, secrets, Usage())
    return settings, secrets, budget, httpx.MockTransport(handler)


def test_search_failure_is_explicit():
    settings, secrets, budget, transport = setup_client(lambda r: httpx.Response(401))
    with pytest.raises(ProviderError, match="401"):
        TavilySearch(secrets, settings, budget, transport).search("test")
    assert budget.usage.search_calls == 1


def test_search_preserves_provenance():
    settings, secrets, budget, transport = setup_client(
        lambda r: httpx.Response(
            200,
            json={
                "results": [
                    {
                        "url": "https://reuters.com/test",
                        "title": "test",
                        "content": "complete source text",
                        "published_date": "2026-11-01T12:00:00Z",
                    }
                ]
            },
        )
    )
    source = TavilySearch(secrets, settings, budget, transport).search("original query")[0]
    assert source.content == "complete source text"
    assert source.query == "original query" and source.source == "reuters.com"
    assert source.published_at.tzinfo is not None and source.retrieved_at.tzinfo is not None


def test_llm_rejects_bad_schema():
    settings, secrets, budget, transport = setup_client(
        lambda r: httpx.Response(200, json={"choices": [{"message": {"content": '{"made_up": true}'}}]})
    )
    with pytest.raises(ProviderError, match="validation"):
        CompatibleLLM(secrets, settings, budget, transport).generate("plan", {}, ResearchPlan)


def test_token_budget_before_network():
    settings, secrets, budget, _ = setup_client(lambda r: httpx.Response(200))
    with pytest.raises(BudgetExceeded):
        budget.llm(settings.max_tokens)
    assert budget.usage.llm_calls == 0


@pytest.mark.parametrize("model", ["qwen3.8-max", "deepseek-chat"])
def test_qwen_thinking_is_explicit_without_breaking_deepseek(model):
    import json

    from forecast_agent.demo import DemoLLM

    requests = []
    plan = DemoLLM().generate("plan", {}, ResearchPlan)

    def handler(request):
        requests.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"message": {"content": plan.model_dump_json()}}]})

    settings, secrets, budget, transport = setup_client(handler)
    secrets.llm_model = model
    CompatibleLLM(secrets, settings, budget, transport).generate("plan", {}, ResearchPlan)
    if model.startswith("qwen"):
        assert requests[0]["enable_thinking"] is False
    else:
        assert "enable_thinking" not in requests[0]


def test_optional_thinking_tokens_are_reserved():
    settings = load_settings().model_copy(update={"qwen_enable_thinking": True, "qwen_thinking_budget": 1000})
    budget = Budget(settings, Secrets(_env_file=None, llm_model="qwen3.8-max"), Usage())
    budget.llm(100)
    assert budget.usage.reserved_tokens == 100 + settings.max_output_tokens + 1000
