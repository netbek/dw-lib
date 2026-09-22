ifneq ($(shell which tput),)
	ifneq ($(TERM),)
		RED    := $(shell tput setaf 1)
		GREEN  := $(shell tput setaf 2)
		YELLOW := $(shell tput setaf 3)
		CYAN   := $(shell tput setaf 6)
		RESET  := $(shell tput sgr0)
	endif
endif

# ==============================================================================
# DEPENDENCY MANAGEMENT
# ==============================================================================

deps-scan:
	@echo "$(YELLOW)Scanning root lockfiles for vulnerabilities...$(RESET)"
	trivy fs uv.lock --table-mode detailed
	cd examples/cli && trivy fs uv.lock --table-mode detailed
	cd examples/cli/packages/example_cli && trivy fs uv.lock --table-mode detailed

python-outdated:
	@echo "$(YELLOW)Listing outdated Python dependencies...$(RESET)"
	@uv tree --outdated --depth 1

python-upgrade: TOMORROW := $(shell date -d "tomorrow" +%Y-%m-%d)
python-upgrade: EXCLUDE_NEWER_PACKAGE ?=
python-upgrade:
	$(eval OPTIONS := --upgrade $(if $(EXCLUDE_NEWER_PACKAGE),--exclude-newer-package $(EXCLUDE_NEWER_PACKAGE)=$(TOMORROW),))
	uv lock $(OPTIONS)
	cd examples/cli && uv lock $(OPTIONS)
	cd examples/cli/packages/example_cli && uv lock $(OPTIONS)

python-why: PACKAGE := $(word 2,$(MAKECMDGOALS))
python-why:
	@if [ -z "$(PACKAGE)" ]; then \
		echo "$(RED)Error: Package name is required.$(RESET)"; \
		echo "Usage: make python-why <package>"; \
		exit 1; \
	fi
	@echo "$(YELLOW)Listing Python dependencies of '$(PACKAGE)'...$(RESET)"
	uv tree --invert --package $(PACKAGE)
	cd examples/cli && uv tree --invert --package $(PACKAGE)
	cd examples/cli/packages/example_cli && uv tree --invert --package $(PACKAGE)

# Prevent make from treating arguments to python-why as targets
ifeq (python-why,$(firstword $(MAKECMDGOALS)))
%:
	@:
endif

uv-sync: TOMORROW := $(shell date -d "tomorrow" +%Y-%m-%d)
uv-sync: EXCLUDE_NEWER_PACKAGE ?=
uv-sync:
	$(eval OPTIONS := --all-extras --all-groups $(if $(EXCLUDE_NEWER_PACKAGE),--exclude-newer-package $(EXCLUDE_NEWER_PACKAGE)=$(TOMORROW),))
	uv sync $(OPTIONS)
	cd examples/cli && uv sync $(OPTIONS)
	cd examples/cli/packages/example_cli && uv sync $(OPTIONS)
	uv sync $(OPTIONS)

skills-install:
	@echo "$(YELLOW)Installing agent skills...$(RESET)"
	pnpm exec skills-manager install --force

skills-uninstall:
	@echo "$(YELLOW)Uninstalling agent skills...$(RESET)"
	pnpm exec skills-manager uninstall

# ==============================================================================
# FORMAT
# ==============================================================================

autoflake:
	@echo "Removing unused imports..."
	pre-commit run autoflake --hook-stage manual --files $(filter-out $@,$(MAKECMDGOALS))

format:
	@echo "Formatting code..."
	pre-commit run yamlfmt --all-files
	pre-commit run pyupgrade --all-files
	pre-commit run isort --all-files
	pre-commit run ruff-format --all-files

# ==============================================================================
# LINT
# ==============================================================================

lint:
	@echo "Linting code..."
	pre-commit run ruff-check --hook-stage manual --all-files

# ==============================================================================
# RELEASE
# ==============================================================================

bump-version:
	@./scripts/bump-version.sh $(word 2,$(MAKECMDGOALS))

# Prevent make from treating the bump type as a target (e.g. `make bump-version patch`)
ifeq (bump-version,$(firstword $(MAKECMDGOALS)))
%:
	@:
endif

build:
	find dist -maxdepth 1 ! -name ".gitignore" -type f -exec rm -f {} +
	uv build -o dist --sdist
	uv build -o dist --wheel
	twine check dist/*

create-release:
	@./scripts/create-release.sh

publish:
	@PASSWORD=$$(keyring get pypi-dw-lib __token__); \
	if [ -z "$$PASSWORD" ]; then \
		echo "$(RED)Error: PyPI token not found in keyring. Run: keyring set pypi-dw-lib __token__$(RESET)"; \
		exit 1; \
	fi; \
	TWINE_USERNAME=__token__ TWINE_PASSWORD="$$PASSWORD" twine upload --verbose dist/*
