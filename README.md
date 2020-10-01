# Modbus Energy Meter Logger and MQTT gateway
Log Modbus Energy Meter data to InfluxDB on a Raspberry Pi and publish values via MQTT 

Based on original project on [Github](https://github.com/samuelphy/energy-meter-logger)

#### Added features

* base configuration using ini file
* MQTT publishing to use the readings in other systems
* split data aquiring completely in momentary (power) and energy readings with different intervals
* calculate daily total energy usage and log to file system as a backup
* higher sample rate for momentary power reading, write to database on power changes and/or interval
* separate interval for aquiring/writing energy readings
* split InfluxDB logging in momentary (power) and energy readings (seperate databases if desired to enable usage of different retention policies and continuous queries)
* enhanced meters configuration to support that changes, using yaml file as in original project
* many more improvements

Verified to work on a Raspberry Pi 4 with Digitus USB-RS485 Interface, reading values from 3 Eastron SDM120 instruments. By changing the meters.yml file and making a corresponding metertype_[model].yml file it should be possible to use other modbus enabled models.

### Requirements

#### Hardware

* Raspberry Pi 2/3/4
* RS485 USB interface or RS485 Shield for RPi
* Modbus based Energy Meter(s), e.g WEBIQ 131D / Eastron SDM120 or WEBIQ 343L / Eastron SMD630

#### Software

* Rasbian
* Python 3.7 and PIP
* [Minimalmodbus](https://minimalmodbus.readthedocs.io/en/master/)
* [InfluxDB](https://docs.influxdata.com/influxdb/v1.8/)
* [Grafana](http://docs.grafana.org/)

### Prerequisite

The original project has been documented at [Hackster](https://www.hackster.io/samuelphy/energy-meter-logger-6a3468). Please follow the instructions there for more detailed information. 
Also check original project on [Github](https://github.com/samuelphy/energy-meter-logger).
