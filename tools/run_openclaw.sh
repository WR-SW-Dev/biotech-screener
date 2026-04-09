#!/bin/bash
# Wrapper to ensure openclaw runs with Node v22+ (cron's env resolves to system node v20)
export PATH="/home/arrenchulz/.nvm/versions/node/v22.22.1/bin:$PATH"
exec openclaw "$@"
