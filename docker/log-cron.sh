#!/bin/sh
while true; do
    /usr/sbin/logrotate -s /tmp/logrotate.status /etc/logrotate.d/eido
    sleep 3600
done
