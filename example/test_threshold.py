import logging
from pyarcadia.tests.threshold import ThresholdScan

x = ThresholdScan()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize()

x.chip.pixels_mask()
x.chip.pixels_cfg(0b01, 0xffff, [0], [0], [0], 0x0001)

x.loop_parallel()
x.plot(False, 'results/injection')
