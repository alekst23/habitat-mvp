# Official Python 3.12.15 / Alpine 3.24 linux/amd64 manifest, verified 2026-10-18.
FROM python:3.12-alpine3.24@sha256:2055081c860db8c842b663415b795b026e7e5cc63b59c5193fcc9997713ea5b8
ARG SOURCE_SHA
LABEL org.opencontainers.image.revision=${SOURCE_SHA}
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
COPY backend/requirements.lock /app/backend/requirements.lock
RUN apk add --no-cache zlib=1.3.2-r1 \
    && python -m pip install --no-cache-dir --only-binary=:all: --require-hashes -r backend/requirements.lock \
    && python -m pip uninstall --yes pip \
    && rm -rf /usr/local/lib/python3.12/ensurepip \
    && addgroup -S -g 10001 habitat \
    && adduser -S -D -H -u 10001 -G habitat -s /sbin/nologin habitat \
    && mkdir /data && chown 10001:10001 /data
COPY --chown=10001:10001 backend/aicl /app/backend/aicl
USER 10001:10001
EXPOSE 8000
CMD ["python", "-m", "uvicorn", "aicl.runtime:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--no-proxy-headers"]
