# Paperless AI Manager

CLI tool for AI-powered document management in [Paperless-NGX](https://github.com/paperless-ngx/paperless-ngx). Uses LLMs to analyze documents and suggest metadata — tags, correspondents, document types, and titles.

## Features

- **Interactive review** — step through documents one by one, accept or reject AI suggestions
- **Batch analysis** — analyze multiple documents at once with progress tracking
- **Validation** — check existing metadata for potential issues
- **Natural language search** — find documents by meaning, not just keywords
- **Change history** — track all applied changes
- **Multiple AI providers** — OpenAI, Anthropic, Ollama, Azure, Google Gemini, or any OpenAI-compatible API

## Quickstart

```bash
# Install dependencies
pip install -e .

# Create config from example
cp config.yaml.example config.yaml

# Edit config with your Paperless URL, API token, and AI provider
# Then run:
paperless-ai init
```

## Usage

```bash
# Interactive review of untagged documents
paperless-ai review

# Review a specific document
paperless-ai review --id 123

# Batch analyze (dry run — shows suggestions)
paperless-ai analyze --limit 20

# Batch analyze with auto-apply (confidence >= 70%)
paperless-ai analyze --auto --limit 20

# Validate existing metadata
paperless-ai validate --limit 50

# Search documents
paperless-ai search "tax documents from 2024"

# View change history
paperless-ai history --limit 30
```

All commands support `--verbose` and `--debug` flags.

## Configuration

Copy `config.yaml.example` to `config.yaml` and adjust:

```yaml
paperless:
  url: "http://your-paperless-instance:8000"
  token: "your-api-token"

ai:
  model: "ollama/llama3.2"   # or openai/gpt-4, anthropic/claude-3-sonnet, etc.
  # api_key: "sk-..."        # required for cloud providers
  # api_base: "..."          # for Ollama, Azure, or custom APIs

analysis:
  language: "de"             # "de" or "en"
  auto_apply: false
  max_documents: 100
```

### Supported AI Providers

| Provider | Model format | Notes |
|----------|-------------|-------|
| Ollama | `ollama/llama3.2` | Local, free |
| OpenAI | `openai/gpt-4` | Requires API key |
| Anthropic | `anthropic/claude-3-sonnet-20240229` | Requires API key |
| Azure | `azure/gpt-4` | Requires API key + base URL |
| Google | `gemini/gemini-pro` | Requires API key |
| Custom | `openai/your-model` | Any OpenAI-compatible API |

### Environment Variables

All config values can be overridden via environment variables:

`PAPERLESS_URL`, `PAPERLESS_TOKEN`, `AI_MODEL`, `AI_API_KEY`, `AI_API_BASE`

## License

MIT
