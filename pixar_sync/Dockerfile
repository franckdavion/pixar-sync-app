FROM ghcr.io/home-assistant/base:3.24
LABEL io.hass.type="app" io.hass.version="0.4.1" io.hass.arch="aarch64|amd64"
RUN apk add --no-cache python3 py3-yaml nodejs ca-certificates
COPY run.sh /run.sh
COPY updater.py /updater.py
COPY resource_version.js /resource_version.js
COPY automation_sync.py /automation_sync.py
COPY dashboard_sync.js /dashboard_sync.js
RUN chmod 0755 /run.sh && chmod 0644 /updater.py /resource_version.js /automation_sync.py /dashboard_sync.js
CMD ["/run.sh"]
