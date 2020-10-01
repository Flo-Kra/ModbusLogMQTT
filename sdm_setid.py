#!/usr/bin/python3 -u
# -*- coding: utf-8 -*-
#
import minimalmodbus
import sys

serialdevice = '/dev/serial/by-id/usb-FTDI_FT232R_USB_UART_AK05DZIG-if00-port0'

if len(sys.argv) == 2:
    id = int(sys.argv[1])
    idnew = int(sys.argv[2])
    if id > 0 and id <= 247: 
        if idnew > 0 and idnew <= 247: 
            print("New ID out of range")
            exit()
        else:
            meter_id = tmpid
            meter_id_new = tmpidnew
    else:
        print("ID out of range")
        exit()
elif len(sys.argv) == 1:
    id = 1
    idnew = int(sys.argv[1])
    if idnew <= 0 and idnew > 247:
        print("New ID out of range")
        exit()
else:
    print("Usage: sdm_setid.py [oldID] [newID]")
    exit()

exit()

rs485 = minimalmodbus.Instrument(serialdevice, meter_id)
rs485.serial.baudrate = 2400
rs485.serial.bytesize = 8
rs485.serial.parity = minimalmodbus.serial.PARITY_NONE
rs485.serial.stopbits = 1
rs485.serial.timeout = 1
rs485.debug = False
rs485.mode = minimalmodbus.MODE_RTU
print(rs485)

# Modbus Parity
# Addr 0x0012
# 4 byte float
# 0 = 1 stop bit, no parity (default)
# 1 = 1 stop bit, even parity
# 2 = 1 stop bit, odd parity
# 3 = 2 stop bits, no parity
#rs485.write_float(0x0012, meter_id_new, number_of_registers=2)

# Meter ID
# Addr 0x0014
# 4 byte float
# 1-247, default 1
rs485.write_float(0x0014, meter_id_new, number_of_registers=2)

# Baud rate
# Addr 0x00C1
# 4 byte float
# 0 = 2400 (default)
# 1 = 4800
# 2 = 9600
# 5 = 1200
#rs485.write_float(0x00C1, meter_id_new, number_of_registers=2)

# Pulse 1 output mode
# Addr 0x0056
# 4 byte float
# 1 = Import Active Energy
# 2 = Import + Export Active Energy
# 4 = Export Active Energy (default)
# 5 = Import Reactive Energy
# 8 = Export Reactive Energy
#rs485.write_float(0x0056, meter_id_new, number_of_registers=2)

# Time of scroll display
# Addr 0xF900
# 2 byte HEX
# Range 0-30s
# 0 = does not display in turns
#rs485.write_register(0xF900, meter_id_new, number_of_registers=1)

# Pulse 1 output
# Addr 0xF910
# 2 byte HEX
# 0000 = 0.001 kWh/imp (default)
# 0001 = 0.01  kWh/imp
# 0002 = 0.1   kWh/imp
# 0003 = 1     kWh/imp
#rs485.write_register(0xF910, meter_id_new, number_of_registers=1)

# Measurement mode
# Addr 0xF920
# 2 byte HEX
# 0001 = mode 1 (total = import)
# 0002 = mode 2 (total = import + export) (default)
# 0003 = mode 3 (total = import - export)
#rs485.write_register(0xF920, meter_id_new, number_of_registers=1)
