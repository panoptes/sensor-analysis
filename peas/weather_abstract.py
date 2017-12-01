#!/usr/bin/env python3

import logging
import numpy as np
import re
import serial
import sys
import time
import requests

from datetime import datetime as dt
from dateutil.parser import parse as date_parser

import astropy.units as u
from astropy.units import cds
from astropy.table import Table
from astropy.time import Time, TimeISO, TimeDelta

from pocs.utils.messaging import PanMessaging

from . import load_config
from .PID import PID

def get_mongodb():
    from pocs.utils.database import PanMongo
    return PanMongo()

# -----------------------------------------------------------------------------
#   Base class to read and check weather data
# -----------------------------------------------------------------------------
class WeatherAbstract(object):

    """ Base class for checking generic weather data and sending it to the
        required location.
    """

    def __init__(self, use_mongo=True):
        self.config = load_config()

        # Read configuration
        self.cfg = self.config['weather']['aag_cloud']
        self.safety_delay = self.cfg.get('safety_delay', 15.)

        self.db = None
        if use_mongo:
            self.db = get_mongodb()

        self.messaging = None
        self.safe_dict = None
        self.weather_entries = list()

    def send_message(self, msg, channel='weather'):
        if self.messaging is None:
            self.messaging = PanMessaging.create_publisher(6510)

        self.messaging.send_message(channel, msg)

    def capture(self):
        # Make Safety Decision
        self.safe_dict = self.make_safety_decision(data)

        data['Safe'] = self.safe_dict['Safe']
        data['Sky condition'] = self.safe_dict['Sky']
        data['Wind condition'] = self.safe_dict['Wind']
        data['Gust condition'] = self.safe_dict['Gust']
        data['Rain condition'] = self.safe_dict['Rain']

        # Store current weather
        self.weather_entries.append(data)

        if send_message:
            self.send_message({'data': data}, channel='weather')

        if use_mongo:
            self.db.insert_current('weather', data)

        return data

    def make_safety_decision(self):
        self.logger.debug('Making safety decision with {}'.format(self.cfg.get('product')))

        return {'Safe': safe,
                'Sky': cloud[0],
                'Wind': wind[0],
                'Gust': gust[0],
                'Rain': rain[0]}

    def _get_cloud_safety(self):
        safety_delay = self.safety_delay

        threshold_cloudy = self.cfg.get('threshold_cloudy', -22.5)
        threshold_very_cloudy = self.cfg.get('threshold_very_cloudy', -15.)

        if len(sky_diff) == 0:
            self.logger.debug('  UNSAFE: no sky temperatures found')
            sky_safe = False
            cloud_condition = 'Unknown'
        else:
            if max_sky_diff > threshold_cloudy:
                self.logger.debug('UNSAFE: Cloudy in last {} min. Max sky diff {:.1f} C'.format(
                                  safety_delay, max_sky_diff))
                sky_safe = False
            else:
                sky_safe = True

            if last_cloud > threshold_very_cloudy:
                cloud_condition = 'Very Cloudy'
            elif last_cloud > threshold_cloudy:
                cloud_condition = 'Cloudy'
            else:
                cloud_condition = 'Clear'
            self.logger.debug('Cloud Condition: {} (Sky-Amb={:.1f} C)'.format(cloud_condition, last_cloud))

        return cloud_condition, sky_safe

    def _get_wind_safety(self):
        safety_delay = self.safety_delay

        threshold_windy = self.cfg.get('threshold_windy', 20)
        threshold_very_windy = self.cfg.get('threshold_very_windy', 30)

        threshold_gusty = self.cfg.get('threshold_gusty', 40)
        threshold_very_gusty = self.cfg.get('threshold_very_gusty', 50)

        if len(wind_gust) == 0:
            self.logger.debug(' UNSAFE: no maximum wind gust readings found')
            gust_safe = False
            gust_condition = 'Unknown'

        if len(wind_speed) == 0:
            self.logger.debug(' UNSAFE: no average wind speed readings found')
            wind_safe = False
            wind_condition = 'Unknown'
        else:
            # Windy?
            if wind_speed > threshold_very_windy:
                self.logger.debug(' UNSAFE:  Very windy in last {:.0f} min. Average wind speed {:.1f} kph'.format(
                                  safety_delay, wind_speed))
                wind_safe = False
            else:
                wind_safe = True

            if wind_speed > threshold_very_windy:
                wind_condition = 'Very Windy'
            elif wind_speed > threshold_windy:
                wind_condition = 'Windy'
            else:
                wind_condition = 'Calm'
                self.logger.debug('Wind Condition: {} ({:.1f} km/h)'.format(
                                  wind_condition, wind_speed))

            # Gusty?
            if wind_gust > threshold_very_gusty:
                self.logger.debug(' UNSAFE:  Very gusty in last {:.0f} min. Max gust speed {:.1f} kph'.format(
                                  safety_delay, wind_gust))
                gust_safe = False
            else:
                gust_safe = True

            if wind_gust > threshold_very_gusty:
                gust_condition = 'Very Gusty'
            elif wind_gust > threshold_gusty:
                gust_condition = 'Gusty'
            else:
                gust_condition = 'Calm'

            self.logger.debug('Gust Condition: {} ({:.1f} km/h)'.format(
                              gust_condition, wind_gust))

        return (wind_condition, wind_safe), (gust_condition, gust_safe)

    def _get_rain_safety(self):
        safety_delay = self.safety_delay

        return rain_condition, rain_safe
