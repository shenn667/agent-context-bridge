# acb-mcp on Smithery / standalone Docker.
# Zero-dependency Python (>=3.10): installs the PyPI release sources from this repo.
FROM python:3.12-slim

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/

RUN pip install --no-cache-dir .

ENTRYPOINT ["acb-mcp"]
