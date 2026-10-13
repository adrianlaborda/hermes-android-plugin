# Contributing

Thanks for helping. Bug reports, ideas and pull requests are all welcome. For anything larger than a small fix, open
an issue first.

## Development

The tests import Hermes Agent from source, so check it out next to the plugin:

```sh
git clone https://github.com/NousResearch/hermes-agent ../hermes-agent
python -m venv .venv && . .venv/bin/activate
pip install -e '.[test]' pyyaml ruamel.yaml python-dotenv rich croniter platformdirs pydantic requests
HERMES_AGENT_SRC=../hermes-agent python -m pytest tests -q
```

CI runs the tests on Python 3.11 and 3.13, against the tested Hermes Agent release and against `main`.

## Conventions

- Use only Hermes' public plugin extension points. Never patch Hermes core.
- Secrets never reach the model, the chat or FCM. Tests use synthetic credentials only.
- The wire protocol is documented in [docs/protocol-v1.md](docs/protocol-v1.md). Changes must stay compatible with
  released versions of Hermes Mobile.
- Add an entry under `## [Unreleased]` in [CHANGELOG.md](CHANGELOG.md) for every user-visible change.

## Releases

Maintainers release by:
1. Moving the `Unreleased` entries under a new version heading.
2. Bumping `version` in both `plugin.yaml` and `pyproject.toml`.
3. Pushing a tag `vX.Y.Z`.

The release workflow then tests and publishes the GitHub release.

By contributing you agree that your work is licensed under the [MIT License](LICENSE).
