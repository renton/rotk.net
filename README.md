# rotk.net
rotk.net

# let's encrypt setup
apt install certbot
sudo certbot certonly --standalone -d rotk.net
renewal
0 3 * * * docker stop <container_name> && certbot renew --quiet && docker start <container_name>


docker run --rm -it \
  -v /etc/letsencrypt:/etc/letsencrypt \
  certbot/certbot certonly --webroot -w /usr/share/nginx/html -d your_domain