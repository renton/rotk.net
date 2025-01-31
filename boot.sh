#!/bin/bash

while true; do
    flask deploy
    if [[ "$?" == "0" ]]; then
        break
    fi
    echo Deploy command failed, retrying in 5 secs...
    sleep 5
done

# exec gunicorn rotk:app \
#     -b :5000 \
#     # --certfile=/etc/letsencrypt/live/rotk.net/fullchain.pem \
#     # --keyfile=/etc/letsencrypt/live/rotk.net/privkey.pem \
#     --access-logfile - \
#     --error-logfile - \
#     --timeout 240 \
#     --workers 3 \
#     --reload

flask run