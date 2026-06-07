# Tsubaki Project Context

## Project Overview
Tsubaki is a Discord auto-moderation bot built using **discord.py**. It features AI-powered interactions via the **Groq API** and is designed with a "cute weeb anime-girl vibe". The project is optimized for deployment on Render, including a built-in health check server.

- **Primary Language:** Python 3.12+
- **Key Libraries:** `discord.py`, `groq`, `python-dotenv`
- **Infrastructure:** Built-in HTTP health check server for Render compatibility.

## Getting Started

### Prerequisites
- Python 3.12+
- `uv` (recommended for dependency management and running)
- Discord Bot Token (with **Server Members Intent** enabled)
- Groq API Key

### Installation
```bash
# Clone the repository
git clone https://github.com/GaseousIce/Tsubaki.git
cd Tsubaki

# Setup environment
cp .env.example .env
# Edit .env with your DISCORD_TOKEN and GROQ_API_KEY
```

### Running the Bot
```bash
# Using uv (recommended)
uv run python src/main.py

# Without uv
python -m pip install -r pyproject.toml # Or use a venv
python src/main.py
```

## Project Structure
- `src/`: Core source code.
  - `main.py`: Entry point, Discord bot initialization, and command registration.
  - `groq_service.py`: Wrapper for Groq AI completions.
- `logs/`: (Auto-generated) Contains `logs.log` (standard bot logs).
- `pyproject.toml`: Dependency and project metadata.
- `render.yaml`: Deployment configuration for Render.
- `ruff.toml`: Linting and formatting configuration.

## Development Conventions

### Coding Style
- Follows standard Python conventions.
- Linting and formatting are managed by **Ruff**.
- Asynchronous programming is used extensively via `asyncio` (required by `discord.py` and `groq`).

### AI Personality (The "Tsubaki" Vibe)
The `/ask` command uses a system prompt to maintain a "cute weeb anime-girl personality":
- Natural conversation in **Japanglish** (mixing English with weeb slang).
- Focuses on English-based phrasing rather than Japanese script.
- Extensive use of diverse and expressive kaomojis.
- Clear organization with frequent line breaks.

### Error Handling
- Missing `GROQ_API_KEY` will disable the `/ask` command rather than crashing the bot.
- API errors during `/ask` are logged and reported to the user gracefully.

## Deployment Notes
- When `PORT` environment variable is present, the bot starts a health check server on that port (default 10000).
- Render Blueprint (`render.yaml`) is pre-configured for easy deployment.
