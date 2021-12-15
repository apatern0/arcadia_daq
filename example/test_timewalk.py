import logging
from pyarcadia.tests.timewalk import TimewalkScan

x = TimewalkScan()
x.set_timestamp_resolution(0.125E-6)

x.logger.setLevel(logging.WARNING)
x.initialize()

x.analysis.skip()
x.daq.pixels_mask()
x.daq.pcr_cfg(0b01, [7], 0x1, [0, 32, 63, 95, 127], [0], 0x0001)

x.loop()
x.plot(False, 'results/timewalk')
