# Contributing

Small fixes and clear bug reports are welcome.

- Run the commands in the README from `company-shorts/`.
- Do not commit `work/`, rendered video, audio, `node_modules/`, virtualenvs, model weights, or `config.toml`.
- Do not commit API keys. `prepare_company.py` reads `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` from the environment when you want a draft filled in, and it works without them.
- The only company config in the repository is the fictional `companies/_example.yaml`. Do not commit a real company's name, logo, photos, or an internal project name.
- The proof-card wording lives in `company-shorts/template/copy.py`. Keep it a description of the system. Do not name an employer there.
