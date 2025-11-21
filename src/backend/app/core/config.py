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
    aws_region: str = "ap-northeast-2"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    s3_bucket_name: str = ""
    s3_upload_prefix: str = "uploads"
    s3_presign_ttl_seconds: int = 900
    rds_url: str

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


settings = Settings()
