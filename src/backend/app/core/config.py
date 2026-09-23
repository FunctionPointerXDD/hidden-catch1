from pydantic import AliasChoices, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "HiddenCatch API"
    app_version: str = "0.2.0"
    environment: str = "development"
    debug: bool = False
    allowed_origins: list[str] = ["*"]
    database_url: str | None = (
        Field(
            "",
            validation_alias=AliasChoices("AWS_RDS_URL_TUNNEL", "DATABASE_URL"),
        )
        or None
    )
    database_echo: bool = False
    database_pool_size: int = 5
    database_max_overflow: int = 10
    aws_region: str = "ap-northeast-2"
    aws_access_key_id: str | None = None
    aws_secret_access_key: str | None = None
    aws_s3_bucket_name: str = ""
    aws_s3_upload_prefix: str = "uploads"
    aws_s3_presign_ttl_seconds: int = 900
    allowed_upload_content_types: list[str] = ["image/png", "image/jpeg"]

    # Celery
    celery_broker_url: str = "redis://localhost:6379/0"
    celery_result_backend: str = "redis://localhost:6379/0"

    # GCP / Google AI
    gcp_project_id: str = ""
    # Gemini image models are served from the "global" endpoint on Vertex AI.
    gcp_location: str = "global"
    google_application_credentials: str | None = None
    # Optional: use the Gemini Developer API (API key) instead of Vertex AI.
    google_api_key: str | None = None

    # ---- Puzzle generation pipeline -------------------------------------
    # Long edge (px) of the normalized puzzle image. Everything downstream
    # (object detection, image editing, what the browser downloads) works on
    # this size, so it bounds latency, bandwidth and API payloads.
    puzzle_max_edge: int = 1024
    # Center-crop to the nearest aspect ratio the image model supports so the
    # generated image lines up 1:1 with the original after resizing.
    puzzle_fit_aspect_ratio: bool = True
    puzzle_jpeg_quality: int = 90
    puzzle_max_differences: int = 5
    # Objects smaller than this fraction of the image area are skipped
    # (too small to click on a phone and too small to edit reliably).
    puzzle_min_area_ratio: float = 0.003
    # Mean absolute pixel difference (0-255) a region must show after editing
    # to count as a real difference. Regions below this are restored to the
    # original pixels and dropped from the answer list.
    puzzle_min_change_score: float = 10.0
    # Content-addressed puzzle cache in S3 (same picture -> same puzzle, no
    # AI calls). Disable if every upload must be generated fresh.
    puzzle_cache_enabled: bool = True
    puzzle_cache_prefix: str = "puzzle-cache"

    # Image editing model. imagen-3.0-capability-001 (mask inpainting) was
    # discontinued on 2026-06-30 and gemini-2.5-flash-image shuts down on
    # 2026-10-02, so the pipeline targets the Gemini 3.1 image models and
    # composites the result with its own mask.
    image_edit_model: str = "gemini-3.1-flash-lite-image"
    image_edit_fallback_models: list[str] = ["gemini-3.1-flash-image"]
    # "512px" | "1K" | "2K" | "4K" (uppercase K). Lite supports 1K only.
    image_edit_image_size: str | None = "1K"
    # Send a second image with numbered red boxes so the model knows exactly
    # which regions to change (text-only "semantic masks" are imprecise).
    image_edit_send_region_hint: bool = True
    # If no region shows a visible change, retry once with a bolder prompt.
    image_edit_max_attempts: int = 2

    model_config = SettingsConfigDict(
        env_file=".env", env_file_encoding="utf-8", case_sensitive=False, extra="ignore"
    )


settings = Settings()
