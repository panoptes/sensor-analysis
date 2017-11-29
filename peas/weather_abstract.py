
# -----------------------------------------------------------------------------
#   Base class for weather data readers
# -----------------------------------------------------------------------------
class WeatherAbstract(object):

    """ Base class for checking generic weather data and sending it to the
        required location.
    """

    def __init__(self):

        return NotImplemented

    @abstractmethod
    def send_message(self):
        """ Sends a message to a specified location.
        """
        return NotImplemented

    @abstractmethod
    def capture(self):
        """ Creates a dictionary to store all the information about the
        weather data that has been obtained.

        Should use `send_message` on the dictionary and then store the
        data in the mongo database.

        returns: the dictionary of all the data.
        """
        return NotImplemented

    @abstractmethod
    def make_safety_decision(self):
        """ Results from `_get_cloud_safety`, `_get_wind_safety` and
        `_get_rain_safety` are checked with each other to get a decision
        whether or not the weather is safe for viewing.

        Only safe when all the individual safety conditions are True.

        Returns: Safety, Wind, Cloud and Rain condition.
        """
        return NotImplemented

    @abstractmethod
    def _get_cloud_safety(self):
        """ Defines thresholds/parameters for the cloud condition that define
        safe. Gets cloud data from a source and checks values with the
        parameters to decide if it is safe and what its condition is.

        Returns: Cloud condition and safety
        """
        return NotImplemented

    @abstractmethod
    def _get_wind_safety(self):
        """ Defines thresholds/parameters for the wind and gust condition that
        define safe. Gets wind and gust data from a source and checks values
        with the parameters to decide if they aresafe and what the condition
        are.

        Returns: Wind condition and safety, and gust condition and safety.
        """
        return NotImplemented

    @abstractmethod
    def _get_rain_safety(self):
        """ Defines thresholds/parameters for the rain condition that define
        safe. Gets rain data from a source and checks values with the
        parameters to decide if it is safe and what its condition is.

        Returns: Rain condition and safety.
        """
        return NotImplemented
