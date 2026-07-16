.PHONY: help install build wheel sdist clean test

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

install: ## Install in editable mode
	pip install -e .

build: wheel sdist ## Build wheel and sdist

wheel: ## Build wheel package
	pip install build --quiet
	python -m build --wheel
	@echo "Wheel: $$(ls -t dist/*.whl | head -1)"

sdist: ## Build source distribution
	pip install build --quiet
	python -m build --sdist
	@echo "Sdist: $$(ls -t dist/*.tar.gz | head -1)"

clean: ## Remove build artifacts
	rm -rf dist/ build/ *.egg-info

test: ## Run test suite
	python -m pytest tests/ -q

typecheck: ## Run frontend typecheck
	cd opc/plugins/office_ui/frontend_src && npx tsc -b --noEmit

frontend: ## Build frontend
	cd opc/plugins/office_ui/frontend_src && npm run build

ui: ## Launch UI (dev mode)
	opc ui --rebuild

setup: ## Run environment setup
	opc setup
