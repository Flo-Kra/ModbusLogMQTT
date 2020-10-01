#!/usr/bin/env python3

from influxdb import InfluxDBClient
from os import path
import configparser
import sys
import os
import minimalmodbus
import time
import datetime
import yaml
import logging
import json
import paho.mqtt.client as mqtt

# Change working dir to the same dir as this script
os.chdir(sys.path[0])

config = configparser.ConfigParser()
config.read('modbuslog.ini')
#print(config.sections())

# additional conffile names
conffile_meter_types = 'meter_types.yml'
conffile_readings_names = 'readings_names.yml'


# config vars used more than once or updateable via commandline argument are stored as global vars
conf_modbus_read_retries = config['rs485'].getint('read_retries', 4)
conf_modbus_raise_error_on_reading_failure = config['rs485'].getboolean('raise_error_on_reading_failure', False)
conf_modbus_sleep_between_readings = config['rs485'].getfloat('sleep_between_readings', 0.1)
conf_modbus_sleep_between_instruments = config['rs485'].getfloat('sleep_between_instruments', 0.7)

conf_publish_on_mqtt = config['main'].getboolean('publish_on_mqtt', False)
conf_store_in_influxdb = config['main'].getboolean('store_in_influxdb', False)

conf_mqtt_enabled = config['mqtt'].getboolean('enable', False)

conf_mqtt_topic_prefix = config['mqtt'].get('topic_prefix') #must NOT end with / !!
if conf_mqtt_topic_prefix[-1:] == '/':
    conf_mqtt_topic_prefix = conf_mqtt_topic_prefix[0:-1]
    
conf_mqtt_topic_error = config['mqtt'].get('topic_error') #must NOT end with / !!

conf_storage_path = config['filelog'].get('storage_path')
if conf_storage_path[-1:] != '/':
    conf_storage_path += '/'
    
meters_interval_momentary = config['meters'].getint('interval_momentary', 1) # s - base interval for reading instruments 
meters_interval_report_momentary = config['meters'].getint('interval_report_momentary', 60)    # interval for reporting momentary readings, 0 to report immediately, overruled by powerdelta settings
meters_interval_energy = config['meters'].getint('interval_energy', 60)    # s - interval for reporting kWh-readings
                            # for now this is not a seperate function but based on "meters_interval_momentary" 
                            # easuring elapsed time since last reading, so actual interval can vary, especially when
                            # high "meters_interval_momentary" is set. To avoid that set 
                            # "meters_interval_momentary" (= command parameter --interval) to desired value 
                            # and configure "meters_use_only_one_interval" to True
meters_use_only_one_interval = config['meters'].getboolean('use_only_one_interval', False)   # use only interval 1 "meters_interval_momentary"
meters_report_on_powerdelta_low  = config['meters'].getfloat('report_on_powerdelta_low', 0.95)  # % in decimal notation - immediately report if power value changes by more then this %
meters_report_on_powerdelta_high = config['meters'].getfloat('report_on_powerdelta_high', 1.05)      # % in decimal notation - immediately report if power value changes by more then this %
meters_report_on_lowpower_treshold = config['meters'].getint('report_on_lowpower_treshold', 10) # treshold under which measured power is considered "low" and different powerdeltas are used
meters_report_on_lowpower_powerdelta_low  = config['meters'].getfloat('report_on_lowpower_powerdelta_low', 0.70)   # % in decimal notation - immediately report if power value changes by more then this %
meters_report_on_lowpower_powerdelta_high = config['meters'].getfloat('report_on_lowpower_powerdelta_high', 1.30)   # % in decimal notation - immediately report if power value changes by more then this %
##report_instrument_read_retries = config['rs485'].getboolean('report_instrument_read_retries', False)

conf_send_meters_readTime = config['meters'].getboolean('send_readtime', True)
conf_default_decimals = config['readings'].getint('default_decimals', 3)


conf_readingerror_publish_after = config['rs485'].getint('readingerror_publish_after', 60)         # time in s after that repeated instrument reading errors are published via MQTT
conf_readingerror_publish_interval = config['rs485'].getint('readingerror_publish_interval', 300)     # interval in s to publish repeated instrument reading errors via MQTT


# -------------------------------------------------------------

# global variables - not for configuration
args_output_verbose1 = False
args_output_verbose2 = False


influxdb_write_energy_today_total = True
influxdb_write_energy_yesterday_total = True






class DataCollector:
    def __init__(self, influx_client_momentary, influx_client_energy, meter_yaml):
        self.influx_client_momentary = influx_client_momentary
        self.influx_client_energy = influx_client_energy
        self.meter_yaml = meter_yaml
        self.max_iterations = None  # run indefinitely by default
        #self.meter_types = None
        self.meter_types = dict()
        self.meter_types_last_change = dict()
        #self.meter_types_last_change = -1
        self.meter_map = None
        self.meter_map_last_change = -1
        self.meter_configuration_lastchecktime = None
        self.meter_typesconfiguration_lastchecktime = None
        self.lastMomentaryReportTime = dict()
        self.lastEnergyUpdate = dict()
        self.lastReadingErrorTime = dict()
        self.lastReadingErrorPublishtime = dict()
        #self.totalEnergy = dict()
        self.saved_energy_today_min = dict()
        self.data_momentary_last = dict()
        self.saved_energy_yesterday_total = dict()     # remember total energy for each meter 
        self.saved_todays_date = dict()      # remember today´s date for each meter, needed to check for date rollover in order to calculate energy yesterday/today
        log.info('Meters:')
        #for meter in sorted(self.get_meters()):   # does not work in Python 3, so dont sort for now
        
        # reading conffile_readings_names
        self.readingsNames = yaml.load(open(conffile_readings_names), Loader=yaml.FullLoader)
        
        for meter in self.get_meters():
            log.info('\t {} <--> {}'.format( meter['id'], meter['name']))
    
    def load_meter_type(self, metertype):
        log.info("Loading meter type: " + metertype)
        conffile_meter_type = "metertype_" + metertype + ".yml"
        assert path.exists(conffile_meter_type), 'Meters configuration not found: %s' % conffile_meter_type
        lastchange = self.meter_types_last_change.get(metertype, None)
        lastchange_file = path.getmtime(conffile_meter_type)
        if lastchange == None or (lastchange and lastchange_file != lastchange):
            try:
                log.info('Reloading meter type configuration for ' + metertype + 'as file changed')
                self.meter_types[metertype] = yaml.load(open(conffile_meter_type), Loader=yaml.FullLoader)
                self.meter_types_last_change[metertype] = lastchange_file
                log.debug('Reloaded meters configuration')
            except Exception as e:
                log.warning('Failed to re-load meter type configuration, going on with the old one.')
                log.warning(e)
    
    def check_load_reload_meter_types(self):
        log.debug("")
        log.debug("checking loaded meter types...")
        for metertype in self.meter_types: 
            log.debug(metertype)
            self.load_meter_type(metertype)
        log.debug("")
        
    def get_meters(self):
        reloadconf = False
        ts = int(time.time())
        if self.meter_configuration_lastchecktime == None or (ts - self.meter_configuration_lastchecktime) > 60:
            self.meter_configuration_lastchecktime = ts
            assert path.exists(self.meter_yaml), 'Meter map not found: %s' % self.meter_yaml
            if path.getmtime(self.meter_yaml) != self.meter_map_last_change:
                reloadconf = True
        if reloadconf:
            try:
                log.info('Reloading meter map as file changed')
                new_map = yaml.load(open(self.meter_yaml), Loader=yaml.FullLoader)
                self.meter_map = new_map['meters']
                self.meter_map_last_change = path.getmtime(self.meter_yaml)                
                log.debug('Reloaded meter map')
                for entry in self.meter_map:
                    log.debug(entry['type'])
                    self.load_meter_type(entry['type'])

            except Exception as e:
                log.warning('Failed to re-load meter map, going on with the old one.')
                log.warning(e)
                
        if self.meter_typesconfiguration_lastchecktime == None or (ts - self.meter_typesconfiguration_lastchecktime) > 60:
            self.meter_typesconfiguration_lastchecktime = ts
            self.check_load_reload_meter_types()
            
        return self.meter_map

    def collect_and_store(self):
        #instrument.debug = True
        meters = self.get_meters()
        
        instrument = minimalmodbus.Instrument(config['rs485'].get('serialdevice','/dev/ttyUSB0'), config['rs485'].getfloat('serialtimeout', 1.0))
        instrument.mode = minimalmodbus.MODE_RTU   # rtu or ascii mode
        
        data_momentary = dict()
        data_energy = dict()
        meter_id_name = dict() # mapping id to name

        for meter in meters:
            meterReadingError_momentary = False
            meterReadingError_energy = False
            if conf_modbus_sleep_between_instruments  > 0:
                time.sleep(conf_modbus_sleep_between_instruments)
            meter_id_name[meter['id']] = meter['name']
            instrument.serial.baudrate = meter['baudrate']
            instrument.serial.bytesize = meter['bytesize']
            if meter['parity'] == 'none':
                instrument.serial.parity = minimalmodbus.serial.PARITY_NONE
            elif meter['parity'] == 'odd':
                instrument.serial.parity = minimalmodbus.serial.PARITY_ODD
            elif meter['parity'] == 'even':
                instrument.serial.parity = minimalmodbus.serial.PARITY_EVEN
            else:
                log.error('No parity specified')
                raise
            instrument.serial.stopbits = meter['stopbits']
            instrument.serial.timeout  = meter['timeout']    # seconds
            instrument.address = meter['id']    # this is the slave address number

            log.debug('\nReading meter %s \'%s\'' % (meter['id'], meter_id_name[meter['id']]))
            start_time = time.time()
            
            #if not self.meter_types.get(meter['type'], False):
            #    self.load_meter_type(meter['type'])
                
            readings = self.meter_types[meter['type']]
            if args_output_verbose2:
                log.debug("")
                log.debug("Meter Type " + meter['type'] + " - defined readings:")
                log.debug(json.dumps(readings, indent = 4))
                log.debug("")
            
            data_momentary[meter['id']] = dict()
            data_energy[meter['id']] = dict()

            reading_success_momentary = 0
            for reading in readings['momentary']:
                # to prevent random readout errors, e.g. CRC check fail, sleep for a short time between the readings
                if conf_modbus_sleep_between_readings > 0:
                    time.sleep(conf_modbus_sleep_between_readings) # Sleep between readings to avoid read errors
                retries = conf_modbus_read_retries
                
                # get decimals needed from meter_types config
                decimals = readings['momentary'][reading].get('decimals', conf_default_decimals)
                
                while retries > 0:
                    try:
                        retries -= 1
                        data_momentary[meter['id']][reading] = round(instrument.read_float(readings['momentary'][reading]['address'], 4, 2), decimals)
                        log.debug('OK read meter {}, {} retries => \'{}\' = \'{}\''.format(meter['id'], conf_modbus_read_retries - retries, reading, data_momentary[meter['id']][reading]))
                        retries = 0
                        reading_success_momentary += 1
                        pass
                    except ValueError as ve:
                        log.warning('Value Error while reading register {} from meter {}. Retries left {}.'
                               .format(readings['momentary'][reading]['address'], meter['id'], retries))
                        log.error(ve)
                        if retries == 0 and conf_modbus_raise_error_on_reading_failure:
                            raise RuntimeError
                    except TypeError as te:
                        log.warning('Type Error while reading register {} from meter {}. Retries left {}.'
                               .format(readings['momentary'][reading]['address'], meter['id'], retries))
                        log.error(te)
                        if retries == 0 and conf_modbus_raise_error_on_reading_failure:
                            raise RuntimeError
                    except IOError as ie:
                        log.warning('IO Error while reading register {} from meter {}. Retries left {}.'
                               .format(readings['momentary'][reading]['address'], meter['id'], retries))
                        log.error(ie)
                        if retries == 0 and conf_modbus_raise_error_on_reading_failure:
                            raise RuntimeError
                    except:
                        log.error("Unexpected error:", sys.exc_info()[0])
                        raise
            if reading_success_momentary < len(readings['momentary']):
                log.debug("THERE WERE READING ERRORS")
                meterReadingError_momentary = True
            
            # report momentary interval
            reportMomentary = False
            if meters_interval_report_momentary > 0:
                ts = int(time.time())
                lastMomentaryReportTime = self.lastMomentaryReportTime.get(meter['id'], False)
                if lastMomentaryReportTime:
                    tdiff = ts - lastMomentaryReportTime
                    if (tdiff > meters_interval_report_momentary):
                        log.debug('Reporting momentary readings for meter %s' % meter['id'])
                        reportMomentary = True
                        self.lastMomentaryReportTime[meter['id']] = ts
                else:
                    log.debug('No lastMomentaryReportTime has yet been saved for meter %s' % meter['id'])
                    reportMomentary = True
                    self.lastMomentaryReportTime[meter['id']] = ts
            else:
                reportMomentary = True
            
             
            # override meters_interval_report_momentary if power has changed for more than configured powerdelta and no interval reporting is due in this iteration
            if config['meters'].getboolean('report_on_powerdelta_enable', False) and not reportMomentary:
                lastValues = self.data_momentary_last.get(meter['id'], None)
                                
                for usedReading in data_momentary[meter['id']].keys():
                    currentValue = data_momentary[meter['id']][usedReading]
                    for powerreadingname in self.readingsNames['power']:
                        if usedReading == powerreadingname:
                            lastValue = None
                            if lastValues != None:
                                lastValue = lastValues.get(powerreadingname, None)
                            if lastValue != None:
                                if (currentValue >= meters_report_on_lowpower_treshold):
                                    powerdelta_high = meters_report_on_powerdelta_high
                                    powerdelta_low = meters_report_on_powerdelta_low
                                else:
                                    powerdelta_high = meters_report_on_lowpower_powerdelta_high
                                    powerdelta_low = meters_report_on_lowpower_powerdelta_low
                                    
                                if (currentValue > (lastValue * powerdelta_high)):
                                    log.debug(powerreadingname + " INCREASED by more than factor " + str(powerdelta_high) + "     currentValue=" + str(currentValue) + "  lastValue=" + str(lastValue))
                                    reportMomentary = True
                                if (currentValue < (lastValue * powerdelta_low)):
                                    log.debug(powerreadingname + " DECREASED by more than factor " + str(powerdelta_low) + "     currentValue=" + str(currentValue) + "  lastValue=" + str(lastValue))
                                    reportMomentary = True
                            if lastValues == None:
                                self.data_momentary_last[meter['id']] = dict()
                            self.data_momentary_last[meter['id']][powerreadingname] = data_momentary[meter['id']][powerreadingname]
                    
            
            # influxdb
            t_utc = datetime.datetime.utcnow()
            t_str = t_utc.isoformat() + 'Z'
            
            if conf_store_in_influxdb and not meterReadingError_momentary and reportMomentary:
                jsondata_momentary = [
                    {
                        'measurement': 'energy',
                        'tags': {
                            'meter': meter_id_name[meter['id']],
                        },
                        'time': t_str,
                        'fields': data_momentary[meter['id']]
                    }
                ]
                if args_output_verbose1:
                    print(json.dumps(jsondata_momentary, indent = 4))
                try:
                    self.influx_client_momentary.write_points(jsondata_momentary)
                except Exception as e:
                    log.error('Data not written!')
                    log.error(e)
                
            if conf_send_meters_readTime:
                readtime = round(time.time() - start_time, 3)
                log.debug("Read time: " + str(readtime))
                data_momentary[meter['id']]['Read time'] = readtime
                if conf_mqtt_enabled and conf_publish_on_mqtt:
                        mqttc.publish(conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/ReadTime", str(readtime))
            
            if conf_mqtt_enabled and conf_publish_on_mqtt and reportMomentary:
                for reading in readings['momentary']:
                    tmpreading = data_momentary[meter['id']].get(reading, None)
                    if tmpreading != None:
                        if tmpreading.is_integer():
                            tmpreading = int(tmpreading)
                        #mqttc.publish(conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/" + reading, str('{0:.3f}'.format(tmpreading)))
                        log.debug("MQTT pub: '"+conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/" + reading + "' = '" + str(tmpreading) + "'")
                        mqttc.publish(conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/" + reading, str(tmpreading))
            
            
            
            if meters_use_only_one_interval:
                readEnergyData = True
            else:
                readEnergyData = False
                ts = int(time.time())
                lastUpdate = self.lastEnergyUpdate.get(meter['id'], False)
                if lastUpdate:
                    tdiff = ts - lastUpdate
                    if (tdiff > meters_interval_energy):
                        readEnergyData = True
                        self.lastEnergyUpdate[meter['id']] = ts
                else:
                    log.debug('No lastEnergyUpdate has yet been saved for meter %s' % meter['id'])
                    readEnergyData = True
                    self.lastEnergyUpdate[meter['id']] = ts
            
            
            
            # save and restore yesterday´s total energy to calculate today´s energy
            # check if total energy from yesterday is stored in memory, if not try to get it from saved file
            today = datetime.date.today()
            today_str = today.strftime('%Y%m%d')
            yesterday = today - datetime.timedelta(days = 1)
            yesterday_str = yesterday.strftime('%Y%m%d')
            
            # check for date rollover
            dateRollover = False
            savedtoday = self.saved_todays_date.get(meter['id'], False)
            if not savedtoday or savedtoday != today:
                log.debug("date rollover happened or no date has been saved yet for meter " + str(meter['id']))
                if savedtoday and savedtoday == yesterday:
                    # a date rollover just happened, so change todays date to current and proceed with what has to be done
                    dateRollover = True
                    readEnergyData = True
                    #log.debug(savedtoday)
                self.saved_todays_date[meter['id']] = today
                
                
            if readEnergyData:
                reading_success_energy = 0
                for reading in readings['energy']:
                    # to prevent random readout errors, e.g. CRC check fail, sleep for a short time between the readings
                    if conf_modbus_sleep_between_readings > 0:
                        time.sleep(conf_modbus_sleep_between_readings) # Sleep between readings to avoid read errors
                    retries = conf_modbus_read_retries
                    
                    # get decimals needed from meter_types config
                    decimals = readings['energy'][reading].get('decimals', conf_default_decimals)
                
                    while retries > 0:
                        try:
                            retries -= 1
                            data_energy[meter['id']][reading] = round(instrument.read_float(readings['energy'][reading]['address'], 4, 2), decimals)
                            log.debug('OK read meter {}, {} retries => \'{}\' = \'{}\''
                                .format(meter['id'], conf_modbus_read_retries - retries, reading, data_energy[meter['id']][reading]))
                            reading_success_energy += 1
                            retries = 0
                            pass
                        except ValueError as ve:
                            log.warning('Value Error while reading register {} from meter {}. Retries left {}.'
                                .format(readings['energy'][reading]['address'], meter['id'], retries))
                            log.error(ve)
                            if retries == 0 and conf_modbus_raise_error_on_reading_failure:
                                raise RuntimeError
                        except TypeError as te:
                            log.warning('Type Error while reading register {} from meter {}. Retries left {}.'
                                .format(readings['energy'][reading]['address'], meter['id'], retries))
                            log.error(te)
                            if retries == 0 and conf_modbus_raise_error_on_reading_failure:
                                raise RuntimeError
                        except IOError as ie:
                            log.warning('IO Error while reading register {} from meter {}. Retries left {}.'
                                .format(readings['energy'][reading]['address'], meter['id'], retries))
                            log.error(ie)
                            if retries == 0 and conf_modbus_raise_error_on_reading_failure:
                                raise RuntimeError
                        except:
                            log.error("Unexpected error:", sys.exc_info()[0])
                            if conf_modbus_raise_error_on_reading_failure:
                                raise
                if reading_success_energy < len(readings['energy']):
                    log.debug("THERE WERE READING ERRORS")
                    meterReadingError_energy = True
                    
                
                file_path_meter = conf_storage_path + meter_id_name[meter['id']] + "/"
                file_today_min = file_path_meter + today_str + "_min.txt"
                file_yesterday_total = file_path_meter + yesterday_str + "_total.txt"
                
                energy_today_total = 0
                energy_yesterday_min = 0
                energy_today_min = self.saved_energy_today_min.get(meter['id'], None)
                
                if dateRollover:
                    energy_today_min = None
                if energy_today_min == None:
                    exists = os.path.isfile(file_today_min)
                    if exists:
                        # load energy_today_min from file if exists
                        f = open(file_today_min, "r")
                        if f.mode == 'r':
                            contents = f.read()
                            f.close()
                        energy_today_min = float(contents)
                        self.saved_energy_today_min[meter['id']] = energy_today_min
                        log.debug(meter_id_name[meter['id']] + " - Energy Today min read from file -> = " + str(energy_today_min) + " kWh")
                    else:
                        # save current Energy_total to min-file
                        if not os.path.exists(file_path_meter):
                            os.mkdir(file_path_meter)
                        f = open(file_today_min, "w+")
                        energy_today_min = data_energy[meter['id']][self.readingsNames['energy_total']]
                        self.saved_energy_today_min[meter['id']] = energy_today_min
                        f.write(str('{0:.3f}'.format(energy_today_min)))
                        f.close()
                log.debug(meter_id_name[meter['id']] + " - Energy Today Min: " + str(energy_today_min) + " kWh")
                
                try:
                    energy_today_total = data_energy[meter['id']][self.readingsNames['energy_total']] - energy_today_min
                    log.debug(meter_id_name[meter['id']] + " - Energy Today total: " + str('{0:.3f}'.format(energy_today_total)) + " kWh")
                except:
                    pass
                
                
                
                energy_yesterday_total = self.saved_energy_yesterday_total.get(meter['id'], None)
                if dateRollover:
                    energy_yesterday_total = None
                if energy_yesterday_total == None:
                    exists = os.path.isfile(file_yesterday_total)
                    if exists:
                        # load energy_yesterday_total from file if exists
                        f = open(file_yesterday_total, "r")
                        if f.mode == 'r':
                            contents = f.read()
                            f.close()
                        energy_yesterday_total = float(contents)
                        self.saved_energy_yesterday_total[meter['id']] = energy_yesterday_total
                        log.debug(meter_id_name[meter['id']] + " - Energy Yesterday total read from file -> = " + str(energy_yesterday_total) + " kWh")
                    else:
                        file_yesterday_min = file_path_meter + yesterday_str + "_min.txt"
                        exists = os.path.isfile(file_yesterday_min)
                        if exists:
                            # load yesterday_min from file
                            #if args_output_verbose1:
                            #    print("file file_yesterday_min exists")
                            f = open(file_yesterday_min, "r")
                            if f.mode == 'r':
                                contents =f.read()
                                f.close()
                            energy_yesterday_min = float(contents)
                            log.debug(meter_id_name[meter['id']] + " - Energy yesterday min: " + str(energy_yesterday_min) + " kWh")
                            
                            energy_yesterday_total = round(energy_today_min - energy_yesterday_min, 3)
                            ###log.debug(meter_id_name[meter['id']] + " - Energy yesterday total: " + str(energy_yesterday_total))
                            
                            if not os.path.exists(file_path_meter):
                                os.mkdir(file_path_meter)
                            f = open(file_yesterday_total, "w+")
                            f.write(str('{0:.3f}'.format(energy_yesterday_total)))
                            f.close()
                        #else:
                        #    # file yesterday_min does not exist
                log.debug(meter_id_name[meter['id']] + " - Energy Yesterday Total: " + str(energy_yesterday_total) + " kWh")
                
                if influxdb_write_energy_today_total:
                    data_energy[meter['id']][self.readingsNames['energy_today']] = energy_today_total
                if influxdb_write_energy_yesterday_total:
                    data_energy[meter['id']][self.readingsNames['energy_yesterday']] = energy_yesterday_total
                
                t_utc = datetime.datetime.utcnow()
                t_str = t_utc.isoformat() + 'Z'
                
                if conf_store_in_influxdb and not meterReadingError_energy:
                    jsondata_energy = [
                        {
                            'measurement': 'energy',
                            'tags': {
                                'meter': meter_id_name[meter['id']],
                            },
                            'time': t_str,
                            'fields': data_energy[meter['id']]
                        }
                    ]
                    if args_output_verbose1:
                        print(json.dumps(jsondata_energy, indent = 4))
                    try:
                        self.influx_client_energy.write_points(jsondata_energy)
                    except Exception as e:
                        log.error('Data not written!')
                        log.error(e)
                
                if conf_send_meters_readTime:
                    readtime = round(time.time() - start_time, 3)
                    log.debug("Read time: " + str(readtime))
                    data_energy[meter['id']]['Read time'] = readtime
                    if conf_mqtt_enabled and conf_publish_on_mqtt:
                        mqttc.publish(conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/ReadTime", str(readtime))
                
                if conf_mqtt_enabled and conf_publish_on_mqtt:
                    for reading in readings['energy']:
                        tmpreading = data_energy[meter['id']].get(reading, None)
                        if tmpreading != None:
                            if tmpreading.is_integer():
                                tmpreading = int(tmpreading)
                            #mqttc.publish(conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/" + reading, str('{0:.3f}'.format(tmpreading)))
                            log.debug("MQTT pub: '"+conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/" + reading + "' = '" + str(tmpreading) + "'")
                            mqttc.publish(conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/" + reading, str(tmpreading))
                    mqttc.publish(conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/" + self.readingsNames['energy_today'], str('{0:.3f}'.format(energy_today_total)))
                    mqttc.publish(conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/" + self.readingsNames['energy_yesterday'], str('{0:.3f}'.format(energy_yesterday_total)))
            
            if meterReadingError_momentary or meterReadingError_energy:
                ts = int(time.time())
                lasterrortime = self.lastReadingErrorTime.get(meter['id'], 0)
                if lasterrortime == 0:
                    self.lastReadingErrorTime[meter['id']] = ts
                elif (ts - lasterrortime) > conf_readingerror_publish_after:
                    lasterrorpubtime = self.lastReadingErrorPublishtime.get(meter['id'], 0)
                    if lasterrorpubtime == 0 or (lasterrorpubtime > 0 and (ts - lasterrorpubtime) > conf_readingerror_publish_interval):
                        self.lastReadingErrorPublishtime[meter['id']] = ts
                        if conf_mqtt_enabled and conf_publish_on_mqtt:
                            lasterrortime_str = datetime.datetime.fromtimestamp(lasterrortime).strftime("%Y-%m-%d %H:%M:%S")
                            mqttc.publish(conf_mqtt_topic_prefix + "/" + meter_id_name[meter['id']] + "/STATE", "ERROR: could not read MODBUS meter " + meter_id_name[meter['id']] + " with ID=" + str(meter['id']) + " since " + str(lasterrortime_str))
                            mqttc.publish(conf_mqtt_topic_error, "ERROR: could not read MODBUS meter " + meter_id_name[meter['id']] + " with ID=" + str(meter['id']) + " since " + str(lasterrortime_str))
            else:
                self.lastReadingErrorTime[meter['id']] = 0
                
# END class DataCollector
################################



def mqtt_on_connect(client, userdata, flags, rc):
    if args_output_verbose1:
        print("MQTT connected with result code " + str(rc))
    #client.subscribe("some/topic")


def mqtt_on_disconnect(client, userdata, rc):
    if rc != 0:
        if print_errors:
            print("Unexpected MQTT disconnection. Will auto-reconnect")


def repeat(interval_sec, max_iter, func, *args, **kwargs):
    from itertools import count
    starttime = 0
    for i in count():
        if i > 0 and interval_sec > 0:  # do not wait for interval time on first run
            if ((time.time() - starttime) < interval_sec):
                sleeptime = interval_sec - (time.time() - starttime)
                print("\nsleep " + str(sleeptime) + " s")
                time.sleep(sleeptime)
        try:
            starttime = time.time()
            func(*args, **kwargs)
        except Exception as ex:
            log.error(ex)
        if max_iter and i >= max_iter:
            return


if __name__ == '__main__':
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument('--interval', default=meters_interval_momentary,
                        help='Meter readout interval for momentary values i.e. power, current... - in seconds, default 1s')
    parser.add_argument('--energyinterval', default=meters_interval_energy,
                        help='Meter readout interval for energy values, i.e. total kWh - in seconds, default 60s')
    parser.add_argument('--use-only-one-interval', default=False,
                        help='Meter readout interval for energy values, i.e. total kWh - in seconds, default 60s', action='store_true')
    parser.add_argument('--meters', default='meters.yml',
                        help='YAML file containing Meter ID, name, type etc. Default "meters.yml"')
    #parser.add_argument('--verbose', '-v', default=0, help='print read data from the instruments to console', action='store_true')
    parser.add_argument('--verbose', '-v', type=int, default=0, choices=[1, 2], help='print read data from the instruments to console')
    parser.add_argument('--log', default='CRITICAL',
                        help='Log levels, DEBUG, INFO, WARNING, ERROR or CRITICAL')
    parser.add_argument('--logfile', default='',
                        help='Specify log file, if not specified the log is streamed to console')
    
    
    args = parser.parse_args()
    
    loglevel = args.log.upper()
    logfile = args.logfile
    
    # Setup logging
    log = logging.getLogger('energy-logger')
    log.setLevel(getattr(logging, loglevel))

    if logfile:
        loghandle = logging.FileHandler(logfile, 'w')
        formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
        loghandle.setFormatter(formatter)
    else:
        loghandle = logging.StreamHandler()

    log.addHandler(loghandle)
    
    log.info('Started app')
    
    #if args.verbose:
    if int(args.verbose) == 1 or int(args.verbose) == None:
        args_output_verbose1 = True
        args_output_verbose2 = False
        log.info("Verbose Level 1 ON - printing read data to console.")
    elif int(args.verbose) == 2:
        args_output_verbose1 = True
        args_output_verbose2 = True
        log.info("Verbose Level 2 ON - printing read data and more to console.")
        
    interval = int(args.interval)
    log.info("Interval 1 (for MOMENTARY readings): " + str(interval) + " s")
    
    if args.use_only_one_interval:
        meters_use_only_one_interval = True
        log.info("Using only Interval 1")
    else:
        meters_interval_energy = int(args.energyinterval)
        log.info("Interval 2 (for ENERGY readings):    " + str(meters_interval_energy) + " s")
    
    # create MQTT client object
    if conf_mqtt_enabled:
        mqttc = mqtt.Client()
        mqttc.on_connect = mqtt_on_connect
        mqttc.on_disconnect = mqtt_on_disconnect
        ##mqttc.on_message = on_message  # callback for incoming msg (unused)
        if len(config['mqtt'].get('password')) > 0 or len(config['mqtt'].get('server')) > 0:
            mqttc.username_pw_set(config['mqtt'].get('user'), config['mqtt'].get('password'))
        mqttc.connect(config['mqtt'].get('server'), config['mqtt'].getint('port', 1883), 60)
        mqttc.loop_start()
        #mqttc.loop_forever()


    # Create the InfluxDB object
    if config['influxdb'].getboolean('separate_momentary_database', False):
        influxclient_energy = InfluxDBClient(config['influxdb'].get('host'),
                            config['influxdb'].getint('port', 8086),
                            config['influxdb'].get('user'),
                            config['influxdb'].get('password'),
                            config['influxdb'].get('database'))
        influxclient_momentary = InfluxDBClient(config['influxdb_momentary'].get('host'),
                            config['influxdb_momentary'].getint('port', 8086),
                            config['influxdb_momentary'].get('user'),
                            config['influxdb_momentary'].get('password'),
                            config['influxdb_momentary'].get('database'))
    else:
        influxclient_energy = InfluxDBClient(config['influxdb'].get('host'),
                            config['influxdb'].getint('port', 8086),
                            config['influxdb'].get('user'),
                            config['influxdb'].get('password'),
                            config['influxdb'].get('database'))
        influxclient_momentary = InfluxDBClient(config['influxdb'].get('host'),
                            config['influxdb'].getint('port', 8086),
                            config['influxdb'].get('user'),
                            config['influxdb'].get('password'),
                            config['influxdb'].get('database'))
        

    collector = DataCollector(influx_client_momentary=influxclient_momentary,
                              influx_client_energy=influxclient_energy,
                              meter_yaml=args.meters)
                              
    repeat(interval,
        max_iter=collector.max_iterations,
        func=lambda: collector.collect_and_store())
