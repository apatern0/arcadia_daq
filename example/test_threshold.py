import logging
from pyarcadia.tests.threshold import ThresholdScan

x = ThresholdScan()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize()
x.daq.write_gcrpar('READOUT_CLK_DIVIDER', 0x3)

x.analysis.skip()
x.daq.pixels_mask()
x.daq.pixels_cfg(0b01, [7], 0xffff, [0, 32, 63, 95, 127], [0], 0x0001)

x.loop()
x.plot(False, 'results/injection')
