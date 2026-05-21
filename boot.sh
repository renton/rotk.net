#!/bin/bash
set -e

if [ "$FLASK_ENV" = "development" ]; then
    echo "*** Running in development mode ***"
    exec flask run
elif [ "$FLASK_ENV" = "production" ]; then
    echo "*** Running in production mode ***"
    exec gunicorn rotk:app \
        -b :8081 \
        --access-logfile - \
        --error-logfile - \
        --timeout 240 \
        --workers 3
fi
