# zhibo-trend-source

Public trend JSON source for the zhibo short-video topic pipeline.

Raw source URL:

```text
https://raw.githubusercontent.com/servagent-ai/zhibo-trend-source/main/public/trendradar_source.json
```

The JSON is refreshed by GitHub Actions and is compatible with zhibo's
`videos/_assets/trendradar_bridge.py`.

## Config hygiene

Do not commit personal config, local paths, tokens, cookies, or private endpoint
URLs. Keep personal overrides in GitHub Actions secrets/variables or ignored
files such as `config/local.json`.
