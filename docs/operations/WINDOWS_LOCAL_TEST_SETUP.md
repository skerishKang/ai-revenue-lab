# Windows local test setup

Use an isolated worktree and Python 3.12 or newer (Engine requires 3.12+).
Run these commands in PowerShell from the repository root. If `uv` is not on
PATH but is installed as a Python module, use `python -m uv` as shown.

```powershell
python -m uv sync --project packages/padiem-ai-core --extra dev
python -m uv sync --project apps/padiem-chat --locked --extra dev
python -m uv sync --project apps/korean-ai-platform --locked
python -m uv sync --project apps/padiem-ai-engine --extra dev
python -m uv pip install --python packages/padiem-ai-core/.venv/Scripts/python.exe "pytest-asyncio>=0.24,<1"
```

The Core `dev` extra includes the pinned PDF authoring dependencies, including
`reportlab`, and the audited pypdf range. Chat's dev environment contains its
own required timezone and Worker test packages. For PADIEM Agent(kagent), run
tests from its directory with the Core dev interpreter and the source paths on
`PYTHONPATH`; do not install the Agent as editable for tests that check child
process import isolation:

```powershell
$env:PYTHONPATH = "src;../../packages/padiem-ai-core;../../packages/padiem-control-plane;../padiem-ai-engine/clients/python"
& ../../packages/padiem-ai-core/.venv/Scripts/python.exe -m pytest tests
```

Some tests need additional suite-specific dependencies; follow the existing
`validate-b54-kagent.yml` installation list and Pillow verification before
claiming equivalence to CI. Use the interpreter from the selected environment
(`.venv/Scripts/python.exe`) rather than relying on the Windows `python3`
alias. Run a suite from its own project directory so its pytest settings apply.
If the system temporary directory is unavailable, pass `--basetemp` pointing
to a new, dedicated empty directory owned by the current user; pytest deletes
that directory at startup, so never point it at a shared or valuable folder.
