# rotk.net
rotk.net

# let's encrypt setup
apt install certbot
/etc/letsencrypt/live
sudo certbot certonly --standalone -d rotk.net
renewal
systemctl cat certbot.timer
/etc/letsencrypt/renewal/
sudo certbot renew --dry-run
sudo certbot renew --force-renewal
