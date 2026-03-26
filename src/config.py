import os
from pathlib import Path
from typing import Optional
import yaml
from pydantic import BaseModel


class PaperlessConfig(BaseModel):
    url: str = "http://localhost:8000"
    token: str = ""


class OpenAIConfig(BaseModel):
    api_key: str = ""
    model: str = "gpt-4"


class OllamaConfig(BaseModel):
    url: str = "http://localhost:11434"
    model: str = "llama3.2"


class AIConfig(BaseModel):
    """
    Flexible KI-Provider-Konfiguration.
    
    Unterstützte Formate:
    - model: "ollama/llama3.2" (lokal)
    - model: "openai/gpt-4" (Cloud)
    - model: "anthropic/claude-3-sonnet-20240229" (Cloud)
    - model: "azure/gpt-4" (Cloud)
    - model: "gemini/gemini-pro" (Cloud)
    
    Legacy-Unterstützung:
    - provider: "ollama" oder "openai"
    """
    
    # Flexible Model-Konfiguration (empfohlen)
    model: str = ""
    
    # Provider-spezifische Einstellungen
    api_key: Optional[str] = None
    api_base: Optional[str] = None  # Für Ollama, Azure, Custom APIs
    api_version: Optional[str] = None  # Für Azure
    
    # Legacy-Unterstützung
    provider: str = "ollama"
    openai: OpenAIConfig = OpenAIConfig()
    ollama: OllamaConfig = OllamaConfig()


class ExtractConfig(BaseModel):
    tags: bool = True
    correspondent: bool = True
    document_type: bool = True
    title: bool = True
    date: bool = True
    custom_fields: bool = False


class AnalysisConfig(BaseModel):
    language: str = "de"
    auto_apply: bool = False
    max_documents: int = 100
    extract: ExtractConfig = ExtractConfig()


class AppConfig(BaseModel):
    paperless: PaperlessConfig = PaperlessConfig()
    ai: AIConfig = AIConfig()
    analysis: AnalysisConfig = AnalysisConfig()


def load_config(config_path: str = "config.yaml") -> AppConfig:
    """Lädt die Konfiguration aus einer YAML-Datei mit Env-Override."""
    config_file = Path(config_path)
    
    if config_file.exists():
        with open(config_file, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
    else:
        data = {}
    
    # Environment Variable Overrides
    if os.getenv("PAPERLESS_URL"):
        data.setdefault("paperless", {})["url"] = os.getenv("PAPERLESS_URL")
    if os.getenv("PAPERLESS_TOKEN"):
        data.setdefault("paperless", {})["token"] = os.getenv("PAPERLESS_TOKEN")
    
    # KI-Provider Umgebungsvariablen
    if os.getenv("AI_MODEL"):
        data.setdefault("ai", {})["model"] = os.getenv("AI_MODEL")
    if os.getenv("AI_API_KEY"):
        data.setdefault("ai", {})["api_key"] = os.getenv("AI_API_KEY")
    if os.getenv("AI_API_BASE"):
        data.setdefault("ai", {})["api_base"] = os.getenv("AI_API_BASE")
    
    # Legacy Support
    if os.getenv("OPENAI_API_KEY"):
        data.setdefault("ai", {}).setdefault("openai", {})["api_key"] = os.getenv("OPENAI_API_KEY")
    if os.getenv("AI_PROVIDER"):
        data.setdefault("ai", {})["provider"] = os.getenv("AI_PROVIDER")
    
    return AppConfig(**data)


def save_config(config: AppConfig, config_path: str = "config.yaml"):
    """Speichert die Konfiguration in eine YAML-Datei."""
    config_file = Path(config_path)
    with open(config_file, "w", encoding="utf-8") as f:
        yaml.dump(config.model_dump(), f, default_flow_style=False, allow_unicode=True)
