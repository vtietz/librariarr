FROM node:24-alpine AS ui-builder

WORKDIR /ui

COPY ui/package.json ./
RUN npm install

COPY ui ./
RUN npm run build

FROM python:3.12-slim

WORKDIR /app

COPY requirements.txt ./
RUN apt-get update \
	&& apt-get install -y --no-install-recommends gosu \
	&& rm -rf /var/lib/apt/lists/*
RUN pip install --no-cache-dir -r requirements.txt

COPY librariarr ./librariarr
COPY --from=ui-builder /ui/dist ./ui/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

ENTRYPOINT ["/usr/local/bin/docker-entrypoint.sh"]
CMD ["--config", "/config/config.yaml"]
