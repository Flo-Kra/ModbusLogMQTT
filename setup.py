import sys
from setuptools import setup

try:
    import pypandoc
    readme = pypandoc.convert('README.md', 'rst')
    readme = readme.replace("\r", "")
except ImportError:
    import io
    with io.open('README.md', encoding="utf-8") as f:
        readme = f.read()

setup(name='ModbusLog',
      version=0.1,
      description='Read Energy Meter data using RS485 Modbus, '+
      'store in local InfluxDB database and publish via MQTT.',
      long_description=readme,
      url='https://github.com/Flo-Kra/ModbusLogMQTT',
      download_url='',
      author='Florian Krauter',
      author_email='florian@krauter.at',
      platforms='Raspberry Pi',
      classifiers=[
        'Development Status :: 4 - Beta',
        'Intended Audience :: Developers',
        'License :: MIT License',
        'Operating System :: Raspbian',
        'Programming Language :: Python :: 3'
      ],
      keywords='Energy Meter RS485 Modbus SD120 SDM630 InfluxDB',
      install_requires=[]+(['pyserial','minimalmodbus', 'influxdb', 'pyyaml', 'paho-mqtt', ] if "linux" in sys.platform else []),
      license='MIT',
      packages=[],
      include_package_data=True,
      tests_require=[],
      test_suite='',
      zip_safe=True)
