#!/bin/bash
# EC2 user data: runs once, as root, on the server's first boot. Paste it into
# "Advanced details > User data" when launching the instance (see docs/deployment.md).
# Written for Ubuntu Server; Docker's install script supports current Ubuntu releases.
set -eux
# 2 GB swap file: the 1 GB server can run out of memory while building the images.
fallocate -l 2G /swapfile
chmod 600 /swapfile
mkswap /swapfile
swapon /swapfile
echo '/swapfile none swap sw 0 0' >> /etc/fstab
# Docker Engine with the Compose and Buildx plugins, from Docker's official install script.
curl -fsSL https://get.docker.com | sh
usermod -aG docker ubuntu
