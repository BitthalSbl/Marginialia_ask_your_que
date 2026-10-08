from functools import lru_cache
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Reads backend/.env or the repo-root .env; real environment variables win.
    model_config = SettingsConfigDict(env_file=(".env", "../.env"), extra="ignore")

    # --- Providers -----------------------------------------------------------
    # "auto": Gemini if GEMINI_API_KEY is set, else OpenAI if OPENAI_API_KEY is set, else offline "local" mode.
    llm_provider: Literal["auto", "local", "gemini", "openai"] = "auto"
    gemini_api_key: str = ""
    openai_api_key: str = ""
    gemini_embed_model: str = "gemini-embedding-001"
    gemini_embed_dim: int = 768
    gemini_chat_model: str = "gemini-2.5-flash"
    openai_embed_model: str = "text-embedding-3-small"
    openai_chat_model: str = "gpt-4o-mini"

    # --- Storage -------------------------------------------------------------
    data_dir: str = "./data"
    chroma_dir: str = "./data/chroma"

    # --- Ingestion / retrieval ----------------------------------------------
    chunk_size: int = 1000
    chunk_overlap: int = 200
    max_upload_mb: int = 15
    max_chunks_per_doc: int = 800
    top_k_default: int = 5
    top_k_max: int = 12

    # --- CORS ----------------------------------------------------------------
    # Comma-separated list of exact origins, e.g. "https://app.onrender.com,http://localhost:5173"
    allowed_origins: str = "http://localhost:5173"  # only needed if the frontend is hosted elsewhere
    # Optional regex, handy for preview deploys: ^https://.*\.vercel\.app$
    allowed_origin_regex: str = ""

    @property
    def provider(self) -> Literal["local", "gemini", "openai"]:
        """The provider actually used. A missing key never breaks the app: it falls back to offline mode."""
        p = self.llm_provider
        if p == "auto":
            p = "gemini" if self.gemini_api_key.strip() else "openai" if self.openai_api_key.strip() else "local"
        if p == "gemini" and not self.gemini_api_key.strip():
            return "local"
        if p == "openai" and not self.openai_api_key.strip():
            return "local"
        return p

    @property
    def embed_tag(self) -> str:
        if self.provider == "gemini":
            return f"gemini:{self.gemini_embed_model}:{self.gemini_embed_dim}"
        if self.provider == "openai":
            return f"openai:{self.openai_embed_model}"
        return ""

    @property
    def origins(self) -> list[str]:
        return [o.strip().rstrip("/") for o in self.allowed_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
