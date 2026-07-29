from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+psycopg://weam:weam_dev_local_only@localhost:5433/weam_research"
    log_level: str = "INFO"
    log_dir: str = "../logs"
    max_request_body_bytes: int = 2_000_000

    # Comma-separated Groq API keys, used in rotation so a rate-limited/exhausted key doesn't
    # stall extraction. Leave unset to run with zero LLM extraction — the graph still gets
    # populated from structured fields (graph_mapper.py) at no cost.
    groq_api_keys: str = ""
    groq_model: str = "llama-3.3-70b-versatile"

    @property
    def groq_api_keys_list(self) -> list[str]:
        return [k.strip() for k in self.groq_api_keys.split(",") if k.strip()]


settings = Settings()
