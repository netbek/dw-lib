ifneq ($(shell which tput),)
	ifneq ($(TERM),)
		RED    := $(shell tput setaf 1)
		GREEN  := $(shell tput setaf 2)
		YELLOW := $(shell tput setaf 3)
		CYAN   := $(shell tput setaf 6)
		RESET  := $(shell tput sgr0)
	endif
endif

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

bump-version:
	@BUMP=$(word 2,$(MAKECMDGOALS)); \
	VALID_BUMP="major minor patch stable alpha beta rc post dev"; \
	if [ -z "$$BUMP" ]; then \
		echo "$(RED)Error: Bump is required.$(RESET)"; \
		echo "Usage: make bump-version [major|minor|patch|stable|alpha|beta|rc|post|dev]"; \
		exit 1; \
	fi; \
	if ! echo "$$VALID_BUMP" | grep -qw "$$BUMP"; then \
		echo "$(RED)Error: Invalid bump '$$BUMP'.$(RESET)"; \
		echo "Must be one of: $(CYAN)$$VALID_BUMP$(RESET)"; \
		exit 1; \
	fi; \
	uv version --bump $$BUMP; \
	VERSION=$$(uv version --short); \
	$(MAKE) --no-print-directory uv-sync-all; \
	git add \
		pyproject.toml \
		uv.lock \
		examples/cli/uv.lock \
		examples/cli/packages/example_cli/uv.lock; \
	git commit -m $$VERSION;

build:
	find dist -maxdepth 1 ! -name ".gitignore" -type f -exec rm -f {} +
	uv build -o dist --sdist
	uv build -o dist --wheel
	twine check dist/*

create-release:
	@VERSION=$$(uv version --short); \
	gh release create $$VERSION; \
	git fetch --tags;

publish:
	twine upload --config-file .pypirc --verbose dist/*

# Prevent make from treating arguments to bump-version as targets
ifeq (bump-version,$(firstword $(MAKECMDGOALS)))
%:
	@:
endif
