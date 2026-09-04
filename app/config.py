from pydantic import Field
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    groq_api_key: str = Field(..., alias="GROQ_API_KEY")
    llm_model: str = Field("openai/gpt-oss-120b", alias="LLM_MODEL")
    llm_model_fallbacks: list[str] = Field(
        default_factory=lambda: ["openai/gpt-oss-120b", "openai/gpt-oss-20b"]
    )
    db_path: str = Field("./commitment_tracker.db", alias="DB_PATH")
    confidence_threshold: float = Field(0.75, alias="CONFIDENCE_THRESHOLD")
    max_llm_retries: int = Field(2, alias="MAX_LLM_RETRIES")
    default_timezone: str = Field("Asia/Kolkata", alias="DEFAULT_TIMEZONE")

    # --- NEW LIVE EMAIL SETTINGS ---
    email_mode: str = Field("stored", alias="EMAIL_MODE")
    imap_host: str = Field("imap.gmail.com", alias="IMAP_HOST")
    imap_user: str = Field("", alias="IMAP_USER")
    imap_app_password: str = Field("", alias="IMAP_APP_PASSWORD")
    imap_folder: str = Field("INBOX", alias="IMAP_FOLDER")
    poll_interval_seconds: int = Field(30, alias="POLL_INTERVAL_SECONDS")
    
    smtp_host: str = Field("", alias="SMTP_HOST")
    smtp_port: int = Field(587, alias="SMTP_PORT")
    smtp_user: str = Field("", alias="SMTP_USER")
    smtp_password: str = Field("", alias="SMTP_PASSWORD")
    smtp_from_name: str = Field("Collections Team", alias="SMTP_FROM_NAME")

    class Config:
        env_file = ".env"
        populate_by_name = True

settings = Settings()