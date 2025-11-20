from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "HiddenCatch API"
    app_version: str = "0.1.0"
    environment: str = "development"
    debug: bool = False
    allowed_origins: list[str] = ["http://localhost:3000"]
    database_url: str = ""
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


settings = Settings()
