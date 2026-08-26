#!/usr/bin/env bash
set -Eeuo pipefail

sudo -n /usr/bin/systemctl restart \
  caseclosed-backend.service \
  caseclosed-frontend.service
