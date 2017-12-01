import requests
import logging

import astropy.units as u
from astropy.units import cds
from astropy.table import Table
from astropy.time import Time, TimeISO, TimeDelta

from pocs.utils.messaging import PanMessaging

from . import load_config

def get_mongodb():
    from pocs.utils.database import PanMongo
    return PanMongo()


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
class WeatherData(object):

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
        self.config = load_config()
        self.logger = logging.getLogger('aat-weatherdata')
        self.logger.setLevel(logging.INFO)

        # Read configuration
        self.cfg = self.config['weather']['aag_cloud']
        self.max_age = TimeDelta(self.lcl_cfg.get('max_age', 60.), format='sec')

        self.lcl_cfg = self.local_config['weather']['data']
        self.safety_delay = self.cfg.get('safety_delay', 15.)

        self.db = None
        if use_mongo:
            self.db = get_mongodb()

        self.messaging = None
        self.safe_dict = None
        self.table_data = None
        self.weather_entries = list()

    # sends message to dome controller
    def send_message(self, msg, channel='weather'):
        if self.messaging is None:
            self.messaging = PanMessaging.create_publisher(6510)

        self.messaging.send_message(channel, msg)

    # stores current weather conditions in a dictionary
    def capture(self, use_mongo=False, send_message=False, **kwargs):
        self.logger.debug("Updating weather data")

        data = {}
        data['Weather data'] = self.lcl_cfg.get('name')

        self.table_data = self.fetch_met_data()
        col_names = self.lcl_cfg.get('column_names')
        for i in range(0, len('col_names')):
            data[col_names[i]] = self.table_data[col_names[i]][0]

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

    # decide whether the weather conditions are safe or unsafe
    def make_safety_decision(self, current_values):
        self.logger.debug('Making safety decision with {}'.format(self.lcl_cfg.get('name')))
        self.logger.debug('Found {} weather data entries in last {:.0f} minutes'.format(
            len(self.weather_entries), self.safety_delay))

        safe = False

        # Tuple with condition,safety
        cloud = self._get_cloud_safety(current_values)

        try:
            wind, gust = self._get_wind_safety(current_values)
        except Exception as e:
            self.logger.warning('Problem getting wind safety: {}'.format(e))
            wind = ['N/A']
            gust = ['N/A']

        rain = self._get_rain_safety(current_values)

        safe = cloud[1] and wind[1] and gust[1] and rain[1]

        self.logger.debug('Weather Safe: {}'.format(safe))

        return {'Safe': safe,
                'Sky': cloud[0],
                'Wind': wind[0],
                'Gust': gust[0],
                'Rain': rain[0]}

    # get metdata from the website and turn into a readable and usable table
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

    # check cloud condition
    def _get_cloud_safety(self, current_values):
            safety_delay = self.safety_delay

            entries = self.weather_entries
            threshold_cloudy = self.cfg.get('threshold_cloudy', -22.5)
            threshold_very_cloudy = self.cfg.get('threshold_very_cloudy', -15.)

            sky_amb = entries[self.lcl_cfg.get('sky_ambient')]
            sky_amb_u = entries[self.lcl_cfg.get('sky_ambient_uncertainty', 0)]

            if len(sky_amb) == 0:
                print(' UNSAFE: no sky temperatures found')
                sky_safe = False
                cloud_condition = 'Unknown'
            else:
                if (sky_amb + sky_amb_u) > threshold_cloudy:
                    self.logger.debug(' UNSAFE: Cloudy in last {:.0f} min. Max sky amb {:.1f} C'.format(
                                      safety_delay, sky_amb + sky_amb_u))
                    sky_safe = False
                else:
                    sky_safe = True

                    if sky_amb > threshold_very_cloudy:
                        cloud_condition = 'Very Cloudy'
                    elif sky_amb > threshold_cloudy:
                        cloud_condition = 'Cloudy'
                    else:
                        cloud_condition = 'Clear'
                        self.logger.debug(' Cloud Condition: {} (Sky-Amb={:.1f} C)'.format(
                                          cloud_condition, sky_amb))

            return cloud_condition, sky_safe

    # check wind and gust conditions
    def _get_wind_safety(self, current_values):
            safety_delay = self.safety_delay
            entries = self.weather_entries

            threshold_windy = self.cfg.get('threshold_windy', 20)
            threshold_very_windy = self.cfg.get('threshold_very_windy', 30)

            threshold_gusty = self.cfg.get('threshold_gusty', 40)
            threshold_very_gusty = self.cfg.get('threshold_very_gusty', 50)

            # Wind (average and gusts)
            wind_speed = entries[self.lcl_cfg.get('average_wind_speed')]
            wind_gust = entries[self.lcl_cfg.get('maximum_wind_gust')]

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

    # check rain condition
    def _get_rain_alarm_safety(self, current_values):
        safety_delay = self.safety_delay
        entries = self.weather_entries

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
            # If safe now, check last 15 minutes
            if rain_safe:
                if rain_sensor > threshold_rain and rain_flag > threshold_rain:
                    self.logger.debug(' UNSAFE:  Rain in last {:.0f} min.'.format(safety_delay))
                    rain_safe = False
                elif wet_flag > threshold_wet:
                    self.logger.debug(' UNSAFE:  Wet in last {:.0f} min.'.format(safety_delay))
                    rain_safe = False
                else:
                    rain_safe = True

            self.logger.debug('Rain Condition: {}'.format(rain_condition))

        return rain_condition, rain_safe
