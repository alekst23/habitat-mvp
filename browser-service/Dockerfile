# Browser service stays separate from the Alpine AICL image and its secrets.
FROM mcr.microsoft.com/playwright/python:v1.63.0-noble@sha256:72bd171a9ffc2b4b59532aaa6210e21014d07093120dc25528870c0b840da1f0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app/backend
WORKDIR /app
COPY requirements-browser.txt /app/requirements-browser.txt
RUN python -m pip install --no-cache-dir -r /app/requirements-browser.txt
COPY --chown=pwuser:pwuser backend/browser_service /app/backend/browser_service
# Chromium must launch with its sandbox. Startup fails if the host does not allow
# the required user namespace/sandbox support; never replace this with root or
# --no-sandbox to make a deployment appear healthy.
USER pwuser
EXPOSE 8090
CMD ["python", "-m", "uvicorn", "browser_service.app:create_app", "--factory", "--host", "0.0.0.0", "--port", "8090", "--workers", "1", "--no-proxy-headers", "--no-access-log"]
