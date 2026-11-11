#!/usr/bin/env bash
# Rebuild every dashboard data file (see resume_build.sh).
exec bash "$(dirname "$0")/resume_build.sh" --all
