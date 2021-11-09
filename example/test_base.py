import logging
from pyarcadia.test import Test

x = Test()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize(sync='sync', auto_read=True)
