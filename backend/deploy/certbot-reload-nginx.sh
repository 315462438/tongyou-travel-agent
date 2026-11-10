#!/bin/sh
# Certbot deploy hook: activate renewed certificates only with valid nginx config.
set -eu
nginx -t
systemctl reload nginx
