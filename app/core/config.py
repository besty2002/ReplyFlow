from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    PROJECT_NAME: str = "ReplyFlow"
    API_V1_STR: str = "/api/v1"
    
    # Supabase 설정 (env에서 가져옴)
    SUPABASE_URL: str
    SUPABASE_KEY: str
    JWT_SECRET: str
    GEMINI_API_KEY: str | None = None
    
    # Yamato API 설정
    YAMATO_SITE_ID: str | None = None
    YAMATO_SITE_PASSWORD: str | None = None
    YAMATO_API_VERSION: str = "1.0"
    YAMATO_ENV: str = "prod" # test or prod
    
    model_config = SettingsConfigDict(env_file=".env", case_sensitive=True, extra="ignore")

settings = Settings()
