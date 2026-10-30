# ---- Build stage: install dependencies ----
FROM python:3.12-slim AS builder

WORKDIR /app

COPY requirements.txt .
# --user installs into /root/.local instead of system site-packages,
# so the whole folder can be copied into the runtime stage in one shot.
RUN pip install --no-cache-dir --user -r requirements.txt


# ---- Runtime stage: only what's needed to run the app ----
FROM python:3.12-slim

# Create a dedicated, unprivileged user/group — the base image only has
# root by default, so this has to be created before we can switch to it.
RUN groupadd --system appuser \
    && useradd --system --gid appuser --home /home/appuser --create-home appuser

WORKDIR /app

# Copy installed packages from builder stage, into the NEW user's home
# (not /root/.local — that directory is only readable by root, so a
# non-root user could never reach the packages if left there).
# --chown sets ownership at copy time so appuser can actually read/execute it.
COPY --from=builder --chown=appuser:appuser /root/.local /home/appuser/.local
COPY --chown=appuser:appuser . .

ENV PATH=/home/appuser/.local/bin:$PATH
ENV HOME=/home/appuser

# Everything above this line still runs as root (needed to create the user
# and set ownership). From here on, the process runs unprivileged.
USER appuser

EXPOSE 8000

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]