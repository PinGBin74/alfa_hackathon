from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    database_url: str = "postgresql+psycopg://alfa:alfa@localhost:5432/alfa_news"
    cors_origins: str = "http://localhost:3000"

    jwt_secret: str = "change-me"
    jwt_ttl_minutes: int = 480

    llm_base_url: str = ""
    llm_api_key: str = ""
    # ID моделей в прокси организаторов (GET {llm_base_url}/models); только модели из Приложения 3
    llm_model_light: str = "google/gemma-4-26b-a4b-it"          # Gemma 4 26B A4B
    llm_model_reasoning: str = "z-ai/glm-5.3-flash"             # GLM-5.3-Flash
    llm_model_general: str = "qwen/qwen3.6-35b-a3b"             # Qwen3.6 35B A3B
    llm_model_research: str = "deepseek/deepseek-v4.1-flash"    # DeepSeek-V4.1-Flash
    llm_model_text: str = "moonshotai/kimi-k2.6"                # Kimi-K2.6
    llm_model_vision: str = "qwen/qwen3-vl-30b-a3b-instruct"    # Qwen3-VL-30B-A3B-Instruct

    daily_budget_rub: float = 450.0
    price_per_1k_input_rub: float = 0.05
    price_per_1k_output_rub: float = 0.15

    embedding_dim: int = 1024
    embedding_model: str = ""

    ingest_interval_minutes: int = 30
    news_max_age_days: int = 14

    data_dir: str = "data"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
