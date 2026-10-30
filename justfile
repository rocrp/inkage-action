# Inkage development recipes

default:
    @just --list

# Install deps and the Chromium used for rendering
setup:
    uv sync --all-extras
    uv run playwright install chromium

fmt:
    uvx ruff format src tests
    uvx ruff check --fix src tests

lint:
    uvx ruff format --check src tests
    uvx ruff check src tests
    uv run pyright

test *args:
    uv run pytest -q {{args}}

check: lint test

# Validate a config and print the resolved plan
validate config="inkage.toml":
    uv run inkage validate {{config}}

# Build the Site locally into dist/
run config="inkage.toml" site_url="":
    uv run inkage run --config {{config}} --site-url "{{site_url}}" --out dist
