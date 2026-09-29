"""Studio configuration: paths and the vision-LLM settings.

Everything is resolved relative to the repo so the studio can be moved with it.
Secrets come from `studio/backend/.env` (gitignored) or the ambient environment.
"""
from __future__ import annotations

import os
from pathlib import Path

# studio/backend/app/config.py -> app -> backend -> studio -> <repo root>
APP_DIR = Path(__file__).resolve().parent
BACKEND_DIR = APP_DIR.parent
STUDIO_DIR = BACKEND_DIR.parent
REPO_ROOT = STUDIO_DIR.parent
PIPELINE_DIR = REPO_ROOT / "pipeline"
SITES_DIR = REPO_ROOT / "sites"

# The venv created by the repo's bootstrap.sh (numpy/pillow/scipy/skimage).
REPO_VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"

DATA_DIR = STUDIO_DIR / "data"
JOBS_DIR = DATA_DIR / "jobs"

# The pipeline's art tracer and shipped pages are hardwired to a 1024x768 stage.
STAGE_W, STAGE_H = 1024, 768

# Per-stage subprocess timeouts (seconds).
TIMEOUT_TRACE = int(os.environ.get("STUDIO_TIMEOUT_TRACE", "1800"))
TIMEOUT_BUILD = int(os.environ.get("STUDIO_TIMEOUT_BUILD", "900"))
TIMEOUT_DEFAULT = int(os.environ.get("STUDIO_TIMEOUT_DEFAULT", "300"))


def _load_dotenv() -> None:
    """Minimal .env loader (no dependency).  Does not override real env vars."""
    env_file = BACKEND_DIR / ".env"
    if not env_file.is_file():
        return
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key, val = key.strip(), val.strip().strip('"').strip("'")
        os.environ.setdefault(key, val)


_load_dotenv()


class Vision:
    """Vision-LLM settings.  Provider-agnostic OpenAI-compatible interface."""

    def __init__(self) -> None:
        self.provider = os.environ.get("VISION_PROVIDER", "openai")
        self.model = os.environ.get("VISION_MODEL", "")
        # Comma-separated fallbacks tried in order when a model/peer fails.
        self.fallback_models = [m.strip() for m in
                                os.environ.get("VISION_FALLBACK_MODELS", "").split(",")
                                if m.strip()]
        self.api_key = os.environ.get("VISION_API_KEY", "")
        self.base_url = os.environ.get("VISION_BASE_URL", "https://api.openai.com/v1")

    @property
    def models(self) -> list[str]:
        """The configured model followed by its fallbacks, de-duplicated."""
        seen: list[str] = []
        for m in [self.model, *self.fallback_models]:
            if m and m not in seen:
                seen.append(m)
        return seen

    @property
    def configured(self) -> bool:
        return bool(self.api_key and self.model)

    def describe(self) -> dict:
        return {
            "provider": self.provider,
            "model": self.model or "(unset)",
            "fallbacks": self.fallback_models,
            "configured": self.configured,
            "base_url": self.base_url,
        }


vision = Vision()
