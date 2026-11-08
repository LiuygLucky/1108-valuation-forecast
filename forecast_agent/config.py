from pathlib import Path

import yaml
from pydantic import Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from forecast_agent.schemas import MarketRules, Model

ROOT = Path(__file__).resolve().parents[1]


class Settings(Model):
    model_version: str
    max_iterations: int = Field(ge=1, le=3)
    queries_per_round: int = Field(ge=1, le=8)
    max_search_calls: int = Field(ge=1, le=30)
    max_llm_calls: int = Field(ge=1, le=30)
    max_tokens: int = Field(ge=1000, le=500000)
    max_output_tokens: int = Field(ge=100, le=16000)
    llm_timeout_seconds: int = Field(default=120, ge=10, le=600)
    qwen_enable_thinking: bool = False
    qwen_thinking_budget: int = Field(default=1024, ge=0, le=16000)
    max_cost_usd: float = Field(gt=0)
    search_cost_usd: float = Field(ge=0)
    search_retries: int = Field(ge=0, le=3)
    results_per_query: int = Field(ge=1, le=10)
    max_evidence: int = Field(ge=1, le=100)
    stale_days: int = Field(ge=1)
    seed: int
    samples: int = Field(ge=1000, le=1000000)
    annual_log_drift: float = Field(ge=-1, le=1)
    annual_volatility: float = Field(gt=0, le=2)
    anchor_log_uncertainty: float = Field(gt=0, le=1)
    max_anchor_age_days: int = Field(ge=1)
    max_event_log_shift: float = Field(ge=0, le=0.2)
    max_total_log_shift: float = Field(ge=0, le=0.5)
    scenario_down_log_shift: float = Field(ge=-1, le=0)
    scenario_up_log_shift: float = Field(ge=0, le=1)
    scenario_weights: tuple[float, float, float]
    embedding_backend: str
    embedding_model: str
    embedding_dimensions: int = Field(ge=64)
    preferred_domains: list[str]

    @field_validator("scenario_weights")
    @classmethod
    def weights(cls, value):
        if any(x < 0 for x in value) or abs(sum(value) - 1) > 1e-9:
            raise ValueError("Scenario weights must be nonnegative and sum to 1")
        return value

    @field_validator("embedding_backend")
    @classmethod
    def backend(cls, value):
        if value not in {"hashing", "sentence-transformers"}:
            raise ValueError("Unsupported embedding backend")
        return value


class Secrets(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / ".env", extra="ignore", env_ignore_empty=True)
    llm_api_key: SecretStr = SecretStr("")
    llm_base_url: str = ""
    llm_model: str = "qwen3.8-max"
    tavily_api_key: SecretStr = SecretStr("")
    llm_input_usd_per_million: float | None = Field(default=None, ge=0)
    llm_output_usd_per_million: float | None = Field(default=None, ge=0)


def load_settings(path: Path | None = None) -> Settings:
    return Settings.model_validate(yaml.safe_load((path or ROOT / "config/settings.yaml").read_text("utf-8")))


def load_rules(path: Path | None = None) -> MarketRules:
    return MarketRules.model_validate(
        yaml.safe_load((path or ROOT / "config/market_rules.yaml").read_text("utf-8"))
    )
