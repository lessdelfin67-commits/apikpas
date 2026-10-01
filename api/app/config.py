from pathlib import Path
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "Authorized Media Conversion API"
    ffmpeg_bin: str = "ffmpeg"
    ffprobe_bin: str = "ffprobe"
    media_root: Path = Path("./media")
    max_upload_bytes: int = 2 * 1024 * 1024 * 1024
    max_url_bytes: int = 2 * 1024 * 1024 * 1024
    max_url_seconds: int = 300
    max_concurrent_jobs: int = 2
    cleanup_hours: int = 24
    request_timeout_seconds: int = 30
    api_key: str = Field("9e8ZyWghoMoWUtt0oK1crfqBbGpspArVJ217pOr98vs", validation_alias="API_KEY")
    model_config = SettingsConfigDict(env_file=".env", env_prefix="MEDIA_API_", extra="ignore")

    @property
    def upload_dir(self) -> Path:
        return self.media_root / "uploads"

    @property
    def output_dir(self) -> Path:
        return self.media_root / "outputs"

    @property
    def temp_dir(self) -> Path:
        return self.media_root / "temp"


settings = Settings()
for directory in (settings.upload_dir, settings.output_dir, settings.temp_dir):
    directory.mkdir(parents=True, exist_ok=True)
