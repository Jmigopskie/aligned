import os
from urllib.parse import quote_plus

from dotenv import load_dotenv

load_dotenv()

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

def _default_database_uri():
    """DATABASE_URL wins outright when set (any SQLAlchemy-compatible URI,
    e.g. a full mysql+pymysql://... string). Otherwise, if MYSQL_HOST is
    set, build a MySQL URI from the discrete MYSQL_* vars — lets the .env
    file spell out host/user/password/database separately instead of
    hand-assembling one URL. Falls back to the local sqlite file only when
    neither is configured, so a fresh checkout still runs with zero setup."""
    explicit = os.getenv("DATABASE_URL")
    if explicit:
        return explicit

    mysql_host = os.getenv("MYSQL_HOST")
    if mysql_host:
        user = quote_plus(os.getenv("MYSQL_USER", "root"))
        password = quote_plus(os.getenv("MYSQL_PASSWORD", ""))
        port = os.getenv("MYSQL_PORT", "3306")
        database = os.getenv("MYSQL_DATABASE", "aligned")
        return f"mysql+pymysql://{user}:{password}@{mysql_host}:{port}/{database}?charset=utf8mb4"

    return f"sqlite:///{os.path.join(BASE_DIR, 'aligned.db')}"

class Config:
    SECRET_KEY = os.getenv("SECRET_KEY", "dev-secret-change-me")

    SQLALCHEMY_DATABASE_URI = _default_database_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # AI provider: OpenRouter is used whenever its key is set; otherwise
    # Google Gemini directly (see services/ai_service.py).
    OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
    OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "qwen/qwen3.7-plus")
    # Tried in order when the main model is unavailable (Qwen3.7 Plus is served
    # by a single upstream provider on OpenRouter and gets rate-limited at busy
    # times). A different provider keeps generation and chat working.
    OPENROUTER_FALLBACK_MODELS = [m.strip() for m in os.getenv(
        "OPENROUTER_FALLBACK_MODELS", "google/gemini-3.1-flash-lite").split(",") if m.strip()]
    # Off by default: lesson content and owl chat replies don't need a
    # separate thinking pass, which only adds time and output tokens.
    OPENROUTER_REASONING = os.getenv("OPENROUTER_REASONING", "").lower() in ("1", "true", "on", "yes")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")

    UPLOAD_FOLDER = os.path.join(BASE_DIR, "uploads")
    GENERATED_FOLDER = os.path.join(BASE_DIR, "generated")
    MAX_CONTENT_LENGTH = 10 * 1024 * 1024

    FRONTEND_ORIGIN = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5500")

    # Password-reset codes are emailed through Resend; the sender's domain
    # must be verified there.
    RESEND_API_KEY = os.getenv("RESEND_API_KEY", "")
    MAIL_FROM = os.getenv("MAIL_FROM", "AlignED <noreply@align-ed.online>")

    # Bootstrap admin account, created automatically on first run if no
    # admin user exists yet. Change the password after first login.
    DEFAULT_ADMIN_NAME = os.getenv("DEFAULT_ADMIN_NAME", "System Administrator")
    DEFAULT_ADMIN_EMAIL = os.getenv("DEFAULT_ADMIN_EMAIL", "admin@aligned.local")
    DEFAULT_ADMIN_PASSWORD = os.getenv("DEFAULT_ADMIN_PASSWORD", "ChangeMe123!")
