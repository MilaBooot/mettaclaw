FROM python:3.11-slim-bookworm

ARG LAB_UID=10001
ARG LAB_GID=10001

RUN groupadd --gid ${LAB_GID} labagent \
    && useradd --uid ${LAB_UID} --gid ${LAB_GID} --create-home --shell /bin/sh labagent \
    && mkdir -p /opt/security-lab/bin /opt/security-lab/seed /workspace /run/security-lab \
    && chown -R labagent:labagent /opt/security-lab /workspace /run/security-lab

COPY --chown=labagent:labagent runtime/ /opt/security-lab/bin/
COPY --chown=labagent:labagent seed/ /opt/security-lab/seed/

# Deliberately vulnerable seed state. The live copy is created in the ephemeral
# /workspace tmpfs on each container start.
RUN chmod 0666 /opt/security-lab/seed/config/app.json \
    && chmod 0644 /opt/security-lab/seed/config/services.json \
    && chmod 0644 /opt/security-lab/seed/public/test-credentials.txt

USER labagent:labagent
WORKDIR /workspace

CMD ["python", "/opt/security-lab/bin/launcher.py"]
