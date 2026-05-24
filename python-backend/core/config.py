# python_backend/config.py
import yaml
import os
from pathlib import Path
from typing import Optional, List
from pydantic import BaseModel
from pydantic_settings import BaseSettings


class DBConnector(BaseModel):
    id: str
    display_name: str
    engine: str
    server: str
    port: int
    username: str
    password_env_var: str
    database: str
    # Optional list of SQL schemas to include (e.g. ["Sales","Person","Production"]).
    # If omitted, all non-system schemas are included automatically.
    schemas: Optional[List[str]] = None


class AIIntegration(BaseModel):
    # Model name passed to whichever SDK is active.
    model_to_use: str = 'gemini-2.0-flash-lite'
    # Optional base URL for any OpenAI-compatible endpoint.
    # When set, the OpenAI SDK is used instead of the native Gemini SDK,
    # allowing Ollama, Azure OpenAI, vLLM, etc. as drop-in replacements.
    # Omit (or leave blank) to use the default Google Gemini endpoint.
    base_url: Optional[str] = None


class AppConfig(BaseSettings):
    # Rust engine base URL.
    # Local dev: default below is used.
    # Docker: override with RUST_ENGINE_URL=http://<service-name>:<port>
    #         pydantic_settings reads this env var automatically — no code change needed.
    rust_engine_url: str = "http://127.0.0.1:3000"
    # We look for an environment variable first (great for Docker),
    # then fall back to the local file name.
    yaml_config_path: str = os.getenv("LICHEN_CONFIG_PATH", "connectors.yaml")

    connectors: list[DBConnector] = []
    ai_integration: AIIntegration = AIIntegration()

    def load_connectors(self):
        # Resolve the absolute path so Docker doesn't get confused
        base_dir = Path(__file__).resolve().parent.parent
        full_path = base_dir / self.yaml_config_path

        if full_path.exists():
            with open(full_path, 'r') as f:
                data = yaml.safe_load(f)
                self.connectors = [DBConnector(**c) for c in data.get('connectors', [])]
                # Parse the ai_integration block if present; keep defaults if absent
                if 'ai_integration' in data:
                    self.ai_integration = AIIntegration(**data['ai_integration'])
                    print(f"✅ AI model loaded from config: {self.ai_integration.model_to_use}")
        else:
            print(f"⚠️ Warning: Configuration file not found at {full_path}")


# Single shared instance — imported everywhere else
config = AppConfig()
config.load_connectors()