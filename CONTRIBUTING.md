# Contributing to Agent-Surgeon

First off — thanks for considering contributing! 🎉

Agent-Surgeon is intentionally small, focused, and opinionated. We love contributions that keep it that way.

## Ways to Contribute

### 🐛 Bug Reports

Found something broken? [Open an issue](https://github.com/anthropic-agents/agent-surgeon/issues/new?template=bug_report.md) with:

- What you expected to happen
- What actually happened
- Steps to reproduce
- Your Python version and OS

### 💡 Feature Requests

Have an idea? [Open an issue](https://github.com/anthropic-agents/agent-surgeon/issues/new?template=feature_request.md) and describe:

- The problem you're solving
- Your proposed solution
- Any alternatives you considered

### 🔧 Pull Requests

1. Fork the repo
2. Create a feature branch: `git checkout -b feat/your-feature`
3. Make your changes
4. Run the demo to verify: `python example.py && surgeon-view`
5. Commit with a clear message: `git commit -m "feat: add X"`
6. Push and open a PR

### 🔌 New Framework Adapters

We especially welcome adapters for:

- CrewAI
- LlamaIndex
- DSPy
- Haystack
- Custom agent frameworks

Look at `src/surgeon/hooks.py` for the pattern. Each adapter should:

1. Inherit from `_CallbackRegistry` or implement `start_span`/`finish` directly
2. Map framework events to trace spans
3. Include a demo in `example.py` (or a separate example file)

## Development Setup

```bash
git clone https://github.com/anthropic-agents/agent-surgeon.git
cd agent-surgeon
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
python example.py  # Verify everything works
```

## Code Style

- We keep it simple: standard Python, type hints where helpful
- No linter wars — just keep it readable
- Docstrings on public APIs

## Commit Convention

We loosely follow [Conventional Commits](https://www.conventionalcommits.org/):

- `feat:` new feature
- `fix:` bug fix
- `docs:` documentation
- `refactor:` code refactoring
- `test:` tests

## Questions?

Open an issue or start a discussion. We're friendly! 🤝
