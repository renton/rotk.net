#!/bin/bash

while true; do
    flask deploy
    if [[ "$?" == "0" ]]; then
        break
    fi
    echo Deploy command failed, retrying in 5 secs...
    sleep 5
done

exec gunicorn rotk:app
    --bind 0.0.0.0:5000
    --certfile=/etc/letsencrypt/live/rotk.net/fullchain.pem
    --keyfile=/etc/letsencrypt/live/rotk.net/privkey.pem
    --access-logfile -
    --error-logfile -
    --reload

#flask run