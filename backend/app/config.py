from functools import lru_cache

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL

DEFAULT_JWT_SECRET = "change-me-to-random-64-hex-chars-openssl-rand-hex-32"
MIN_JWT_SECRET_BYTES = 32


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_env: str = "dev"
    # Адрес БД: DATABASE_URL целиком или (если пуст) собирается из POSTGRES_*. В Docker - из POSTGRES_*:
    # пароль не попадает в строку подключения в compose, спецсимволы в нём экранируются.
    database_url: str = ""
    postgres_user: str = "alfa"
    postgres_password: str = ""
    postgres_db: str = "alfa_news"
    postgres_host: str = "localhost"
    postgres_port: int = 5432
    cors_origins: str = "http://localhost:3000"

    # 32+ байт: HS256 с более коротким ключом PyJWT считает небезопасным (InsecureKeyLengthWarning)
    jwt_secret: str = DEFAULT_JWT_SECRET
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

    @model_validator(mode="after")
    def _build_database_url(self) -> "Settings":
        if not self.database_url:
            self.database_url = URL.create(
                "postgresql+psycopg", username=self.postgres_user, password=self.postgres_password or None,
                host=self.postgres_host, port=self.postgres_port, database=self.postgres_db,
            ).render_as_string(hide_password=False)
        return self

    def check_prod_secrets(self) -> None:
        """На стенде (APP_ENV=prod) токены входа нельзя подписывать общеизвестным или коротким ключом."""
        if self.app_env != "prod":
            return
        if self.jwt_secret in (DEFAULT_JWT_SECRET, "change-me-in-prod") or \
                len(self.jwt_secret.encode()) < MIN_JWT_SECRET_BYTES:
            raise RuntimeError("APP_ENV=prod requires JWT_SECRET of 32+ random bytes: openssl rand -hex 32")


@lru_cache
def get_settings() -> Settings:
    return Settings()
