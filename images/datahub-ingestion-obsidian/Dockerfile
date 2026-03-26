FROM acryldata/datahub-ingestion-slim:v1.4.0.3
COPY services/datahub-obsidian-source/ /tmp/obsidian-source/
RUN pip install --no-cache-dir /tmp/obsidian-source/ && rm -rf /tmp/obsidian-source/
COPY datahub/recipes/obsidian.yml /recipes/obsidian.yml
