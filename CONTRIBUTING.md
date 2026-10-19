# Contributing

Small fixes and clear bug reports are welcome.

- Run the commands in the README from `rotpunkt-shorts/`.
- Do not commit `work/`, rendered video, audio, `node_modules/`, virtualenvs, model weights, or `config.toml`.
- Do not commit API keys. `prepare_company.py` reads `OPENAI_API_KEY` or `ANTHROPIC_API_KEY` from the environment when you want a draft filled in, and it works without them.
- Figures in `rotpunkt-shorts/companies/*.yaml` are examples. Do not present them as measured results for those companies.
- The proof-card wording lives in `rotpunkt-shorts/template/copy.py`. Keep it a description of the system. Do not add an internal project name.
