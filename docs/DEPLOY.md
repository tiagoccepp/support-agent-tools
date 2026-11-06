# Deploy

Primary target: **Hugging Face Spaces (Docker mode)** — free, no card, persistent URL.

```bash
HF_TOKEN=hf_xxx python scripts/hf_deploy.py   # creates/updates the Space, prints the URL
```

Then open `https://<you>-support-agent.hf.space/ui`.

## How it works

- `Dockerfile` serves the API with uvicorn on `${PORT:-7860}`.
- The deploy script uploads only `Dockerfile`, `requirements.txt`, `src/`, `data/`
  plus a generated Space `README.md` (SDK header).
- No env vars required: mock LLM backend by default. Optional live LLM:
  `OPENAI_API_KEY` (+ `OPENAI_BASE_URL`, `MODEL`) as Space secrets.

## Alternatives

- **Render/Railway**: connect the GitHub repo, Docker runtime, free tier.
- **Local**: `./demo.sh` — identical UI.
