## Change Log


## v0.2 - 2020-10-01
* rename to ModbusLogMQTT
* Python 3 compatibility
* added app-configuration using ini file - instruments configuration keeps in yml files
* added MQTT client, publishing all read data on configured topics
* added simple file logging
  * writes 2 files per meter and day on each date rollover: 
    * today min - kWh total from meter at that time
    * yesterday total - calculated from current kWh reading and yesterdays saved value
    * both values are also published on every energy reading interval to MQTT and written into InfluxDB if desired
    * this is meant either as a backup of the most important data (I lost many data in the past due to InfluxDB misconfiguration and bad backup), and in order to calculate and publish daily energy usage directly and without complicated database transactions (I used to display "energy today" and "energy yesterday" on a simple display that just subscribes a MQTT topic and displays what it gets)
* changed repeat method to run first iteration immediately after start
* stability improvments
  * do not exit script with error on repeated instrument read errors, instead send error msg on MQTT
* heavy rework of meters configuration and reading method:
  * split data aquiring in different intervals, where the base interval (which runs the main method) is now intended to be very short. All other intervals are based on this (just measuring elapsed time since last run within main method)
  * data aquiring run as often as possible in order to get meaningful momentary (power, current...) data
  * meter types configurations:
    * split in 2 sections: momentary and energy
    * each reading now has 2 parameters: address, decimals - so every reading can have it´s own reasonable conversion, i.e. 0 decimals for power reading, as its not that accurate anyway, or 3 decimals for a kWh reading. 0 decimals values are converted to int for MQTT to prevent trailing zeros, but not for InfluxDB as it breaks data writing when now-integer-values after config changes are already stored in InfluxDB as float
  * meters and meter types configuration is no more checked for file update on every iteration, instead in a fixed interval of 60s, meter types configuration is read on demand (if a meter with this type is configured) and stored in memory rather than reading the yml file on every iteration
  * momentary readings are aquired on every iteration of the main method with no or very short interval
    * on significant change in power reading: immediately publish on MQTT / write to InfluxDB, otherwise in a fixed additional interval
  * energy readings are only aquired and processed in an additional, longer interval, which also handles file logging and yesterday total calculation method
* InfluxDB
  * split to 2 different databases for momentary/energy data if desired, as it makes sense to store power readings and energy readings in different databases with different retention policies and continuous queries


## forked - 2020-09-30

## [0.1] - 2017-11-09
* Read registers of RS485 modbus based energy meter 
