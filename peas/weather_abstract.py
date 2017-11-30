#!/usr/bin/env python3
from abc import ABCMeta, abstractmethod

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
    __metaclass__ = ABCMeta

    def __init__(self, use_mongo=True):
        self.config = load_config()

        # Read configuration
        self.cfg = self.config['weather']['aag_cloud']
        self.safety_delay = self.cfg.get('safety_delay', 15.)

        self.logger = logging.getLogger(self.cfg.get('product', 'product-unknown'))
        self.logger.setLevel(logging.INFO)

        self.db = None
        if use_mongo:
            self.db = get_mongodb()

        self.messaging = None
        self.safe_dict = None
        self.weather_entries = list()

    @abstractmethod
    def send_message(self, msg, channel='weather'):
        if self.messaging is None:
            self.messaging = PanMessaging.create_publisher(6510)

        self.messaging.send_message(channel, msg)

    @abstractmethod
    def capture(self):
        self.logger.debug("Updating weather data")

        data = {}
        data['Product'] = self.cfg.get('product')

        return data

    # still needs to be improved
    @abstractmethod
    def make_safety_decision(self):
        self.logger.debug('Making safety decision with {}'.format(self.cfg.get('product')))

        return {'Safe': safe,
                'Sky': cloud[0],
                'Wind': wind[0],
                'Gust': gust[0],
                'Rain': rain[0]}

    # still needs to be improved
    @abstractmethod
    def _get_cloud_safety(self):
        safety_delay = self.safety_delay

        threshold_cloudy = self.cfg.get('threshold_cloudy', -22.5)
        threshold_very_cloudy = self.cfg.get('threshold_very_cloudy', -15.)

        return cloud_condition, sky_safe

    # still needs to be improved
    @abstractmethod
    def _get_wind_safety(self):
        safety_delay = self.safety_delay

        threshold_windy = self.cfg.get('threshold_windy', 20)
        threshold_very_windy = self.cfg.get('threshold_very_windy', 30)

        threshold_gusty = self.cfg.get('threshold_gusty', 40)
        threshold_very_gusty = self.cfg.get('threshold_very_gusty', 50)

        return (wind_condition, wind_safe), (gust_condition, gust_safe)

    # still needs to be improved
    @abstractmethod
    def _get_rain_safety(self):
        safety_delay = self.safety_delay

        return rain_condition, rain_safe
