# askLenny — Self-Hosted SQL AI

Ask your databases anything in plain English. askLenny translates natural language into real SQL and returns live results, entirely inside your own infrastructure. No data leaves your network.

---

## How it works

1. You connect askLenny to your databases via a YAML config file
2. It indexes your schema (tables, columns, foreign keys) into a local graph database
3. You ask a question in plain English
4. The AI generates SQL from your schema context and runs it against your database
5. Results appear in the UI

---

## Stack

| Layer | Technology |
|---|---|
| Frontend | React + Vite, served by nginx |
| App layer | Python / FastAPI |
| Graph engine | Rust (LichenEngine) — binary graph DB optimised for schema RAG |
| AI | Gemini, Claude, Ollama, Azure OpenAI, or any OpenAI-compatible endpoint |

Everything runs in three Docker containers on your own machine or server.

---

## Quick start

**Prerequisites:** Docker and Docker Compose installed.

**1. Clone the repo**
```bash
git clone https://github.com/Yousefb92/askLenny.git
cd askLenny
```

**2. Add your AI API key**
```bash
cp .env.example .env
# Edit .env and set AI_API_KEY=your-key-here
```

**3. Configure your databases**

Edit `python-backend/connectors.yaml` and add your database connections:
```yaml
connectors:
  - name: "My Database"
    type: mssql          # mssql | postgres | mysql
    host: "localhost"
    port: 1433
    database: "MyDB"
    username: "sa"
    password: "your-password"

ai_integration:
  model_to_use: "gemini-2.0-flash-lite"   # or claude-sonnet-4-5, gpt-4o, etc.
```

**4. Start**
```bash
docker compose up --build
```

Open [http://localhost](http://localhost) in your browser.

---

## AI provider options

| Provider | Config |
|---|---|
| Google Gemini (default) | Set `model_to_use: gemini-...` in connectors.yaml, `AI_API_KEY` in .env |
| Anthropic Claude | Set `model_to_use: claude-...`, `AI_API_KEY` in .env |
| OpenAI | Set `model_to_use: gpt-4o`, `AI_API_KEY` in .env |
| Ollama (local) | Set `model_to_use: llama3`, `base_url: http://host.docker.internal:11434/v1` |
| Azure OpenAI | Set `model_to_use: your-deployment`, `base_url: https://your-resource.openai.azure.com/...` |

---

## Security

- All processing happens inside your Docker network
- Databases are only reachable from inside the containers
- The Rust engine and Python backend are never exposed to the host — only the nginx frontend is on port 80
- Your API key lives in `.env` and is never committed to source control

---

## Supported databases

- Microsoft SQL Server
- PostgreSQL
- MySQL

---

## License

MIT
