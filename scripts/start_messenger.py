# /var/panoptes/PEAS/scripts/start_messenger
# TODO(wtgee): Add documentation for this script (when to use and why).

from pocs.utils.messaging import PanMessaging
print("Staring message forwarding, hit Ctrl-c to stop")
print("Port: 6510 -> 6511")
try:
    f = PanMessaging.create_forwarder(6510,6511)
except KeyboardInterrupt:
    print("Shutting down and exiting...")

