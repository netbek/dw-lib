lint:
	@echo "Linting code..."
	pre-commit run ruff-check --hook-stage manual --all-files

format:
	@echo "Formatting code..."
	pre-commit run yamlfmt --all-files
	pre-commit run pyupgrade --all-files
	pre-commit run isort --all-files
	pre-commit run ruff-format --all-files

autoflake:
	@echo "Removing unused imports..."
	pre-commit run autoflake --hook-stage manual --files $(filter-out $@,$(MAKECMDGOALS))

uv-sync-all:
	uv sync --all-extras --all-groups
	cd examples/cli && uv sync --all-extras --all-groups
	cd examples/cli/packages/example_cli && uv sync --all-extras --all-groups
	uv sync --all-extras --all-groups

uv-lock-upgrade-all:
	uv lock --upgrade
	cd examples/cli && uv lock --upgrade
	cd examples/cli/packages/example_cli && uv lock --upgrade
