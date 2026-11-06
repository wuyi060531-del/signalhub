FROM python:3.12-slim
WORKDIR /app
COPY data-pipeline-python/pyproject.toml ./data-pipeline-python/pyproject.toml
COPY data-pipeline-python/src ./data-pipeline-python/src
RUN pip install --no-cache-dir --upgrade 'pip>=26.2' && pip install --no-cache-dir ./data-pipeline-python
USER 10001
ENTRYPOINT ["signalhub","worker"]
