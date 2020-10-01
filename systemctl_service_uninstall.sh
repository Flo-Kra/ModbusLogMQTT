#!/bin/sh
SERVICEFILE=/etc/systemd/system/modbuslog.service

sudo systemctl stop modbuslog.service
sudo systemctl disable modbuslog.service
sudo rm $SERVICEFILE
sudo systemctl daemon-reload
