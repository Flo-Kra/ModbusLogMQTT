#!/bin/sh
BASEDIR=$(dirname $(realpath "$0"))
TMPFILE=modbuslog.service
SERVICEFILE=/etc/systemd/system/modbuslog.service

echo [Unit]>$TMPFILE
echo Description=ModbusLogger>>$TMPFILE
echo StartLimitInterval=0>>$TMPFILE
echo >>$TMPFILE
echo [Service]>>$TMPFILE
echo Type=simple>>$TMPFILE
echo Restart=always>>$TMPFILE
echo RestartSec=1>>$TMPFILE
echo ExecStart=$BASEDIR/modbuslog.py>>$TMPFILE
echo User=pi>>$TMPFILE
echo >>$TMPFILE
echo [Install]>>$TMPFILE
echo WantedBy=multi-user.target>>$TMPFILE

sudo cp $TMPFILE $SERVICEFILE

sudo systemctl daemon-reload
sudo systemctl enable modbuslog.service
sudo systemctl start modbuslog.service
