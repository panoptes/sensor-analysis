#!/usr/bin/env python3

import requests
import logging

import astropy.units as u
from astropy.units import cds
from astropy.table import Table
from astropy.time import Time, TimeISO, TimeDelta

from pocs.utils.messaging import PanMessaging
from . import load_config
from weather_abstract import WeatherAbstract
from weather_abstract import get_mongodb


class MixedUpTime(TimeISO):

    """
    Subclass the astropy.time.TimeISO time format to handle the mixed up
    American style time format that the AAT met system uses.
    """

    name= 'mixed_up_time'
    subfmts = (('date_hms',
                '%m-%d-%Y %H:%M:%S',
                '{mon:02d}-{day:02d}-{year:d} {hour:02d}:{min:02d}:{sec:02d}'),
               ('date_hm',
                '%m-%d-%Y %H:%M',
                '{mon:02d}-{day:02d}-{year:d} {hour:02d}:{min:02d}'),
               ('date',
                '%m-%d-%Y',
                '{mon:02d}-{day:02d}-{year:d}'))

# -----------------------------------------------------------------------------
# External weather data class
# -----------------------------------------------------------------------------
class WeatherData(WeatherAbstract):

    """ Gets AAT weather data from  http://site.aao.gov.au/AATdatabase/met.html

    Turns the weather data into a useable and meaningful table whose columns are the
    entries of the data. The table only features one row (Excluding the title row)
    which has the numerical data of all the entries.

    The data is then compared with specified parameters and if the data is not within
    the parameters then the safety condition of that entry is defined as False, i.e.
    not safe.
    Data is also given the weather condition, for example if the wind value is greater
    that the one specified the weather condition will be 'windy'.

    Once all the required data has been defined and given conditions, it will then
    decide if the system is safe. If one value is False then the safety condition of
    the system is False. All entries must be True so that the safety condition can
    return True.

    The final conditions and values are then sent to the dome controller to either
    leave, open or close the dome. They are also saved in a database so that previous
    entries can be retrived.
    """

    def __init__(self, use_mongo=True):
        WeatherAbstract.__init__(self, use_mongo=True)

        self.logger = logging.getLogger(self.cfg.get('product_2', 'product-unknown'))
        self.logger.setLevel(logging.INFO)

        self.lcl_cfg = self.local_config['weather']['data']
        self.max_age = TimeDelta(self.lcl_cfg.get('max_age', 60.), format='sec')

        self.table_data = None

    def send_message(self, msg, channel='weather'):
        super().send_message()

    def capture(self, use_mongo=False, send_message=False, **kwargs):
        self.logger.debug("Updating weather data")

        data = {}

        self.table_data = self.fetch_met_data()
        col_names = self.lcl_cfg.get('column_names')

        for i in range(0, len('col_names')):
            data[col_names[i]] = self.table_data[col_names[i]][0]

        return data

    def make_safety_decision(self, ):
        super.make_safety_decision()
        self.logger.debug('Found {} weather data entries in last {:.0f} minutes'.format(
            len(self.fetch_met_data()), self.safety_delay))

        safe = False
        data['Product'] = self.cfg.get('product_2')

        # Tuple with condition,safety
        cloud = self._get_cloud_safety()
        wind, gust = self._get_wind_safety()
        rain = self._get_rain_safety()

        safe = cloud[1] & wind[1] & gust[1] & rain[1]
        self.logger.debug('Weather Safe: {}'.format(safe))

        return {'Safe': safe,
                'Sky': cloud[0],
                'Wind': wind[0],
                'Gust': gust[0],
                'Rain': rain[0]}

    def fetch_met_data(self):
        try:
            cache_age = Time.now() - self._met_data['Time (UTC)'][0] * 86400
        except AttributeError:
            cache_age = self.lcl_cfg.get('cache_age', 1.382e10) * u.year

        if cache_age > self.max_age:
            # Download met data file
            m = requests.get(self.lcl_cfg.get('link'))
            # Remove the annoying " and newline between the date and time
            met = m.text.replace('."\n',' ')
            # Remove the " before the date
            met = met.replace('" ', '')

            # Parse the tab delimited met data into a Table
            t = Table.read(met, format='ascii.no_header', delimiter='\t',
                                names=self.lcl_cfg.get('column_names'))

            # Convert time strings to Time
            t['Time (UTC)'] = Time(t['Time (UTC)'], format='mixed_up_time')
            # Change string format to ISO
            t['Time (UTC)'].format = 'iso'
            # Convert from AAT standard time to UTC
            t['Time (UTC)'] = t['Time (UTC)'] - 10 * u.hour

            col_names = self.lcl_cfg.get('column_names')
            col_units = self.lcl_cfg.get('column_units')
            # Set units for items that have them
            for i in range(1, len('col_names')):
                t[col_names[i]].unit = col_units[i]

            self._met_data = t

        return self._met_data

    def _get_cloud_safety(self):
        entries = self.fetch_met_data()

        sky_diff = entries[self.lcl_cfg.get('sky_ambient')]
        sky_diff_u = entries[self.lcl_cfg.get('sky_ambient_uncertainty', 0)]

        max_sky_diff = sky_diff + sky_diff_u
        last_cloud = sky_diff

        super._get_cloud_safety()

        return cloud_condition, sky_safe

    def _get_wind_safety(self):
        entries = self.fetch_met_data()

        # Wind (average and gusts)
        wind_speed = entries[self.lcl_cfg.get('average_wind_speed')]
        wind_gust = entries[self.lcl_cfg.get('maximum_wind_gust')]

        super._get_wind_safety()

        return (wind_condition, wind_safe), (gust_condition, gust_safe)

    def _get_rain_safety(self):
        super._get_rain_safety()
        entries = self.fetch_met_data()

        threshold_rain = self.lcl_cfg.get('threshold_rain', 0)
        threshold_wet = self.lcl_cfg.get('threshold_wet', 0)

        # Rain
        rain_sensor = entries[self.lcl_cfg('rain_sensor')]
        rain_flag = entries[self.lcl_cfg('rain_flag')]
        wet_flag = entries[self.lcl_cfg('wet_flag')]

        if len(rain_sensor) == 0 and len(rain_flag) == 0 and len(wet_flag) == 0:
            rain_safe = False
            rain_condition = 'Unknown'
        else:
            # Check current values
            if rain_sensor > threshold_rain and rain_flag > threshold_rain:
                rain_condition = 'RAIN'
                rain_safe = False
            elif wet_flag > threshold_wet:
                rain_condition = 'WET'
                rain_safe = False
            else:
                rain_condition = 'NO RAIN'
                rain_safe = True

            self.logger.debug('Rain Condition: {}'.format(rain_condition))

        return rain_condition, rain_safe
