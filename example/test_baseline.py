from pyarcadia.tests.baseline import FullBaselineScan
import logging

#x = BaselineScan()
x = FullBaselineScan()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize()

x.analysis.cleanup()
x.analysis.skip()
x.daq.pixels_mask()
x.daq.pixels_cfg(0b01, 0xffff, [0], [0], 0b11, 0xf)

x.loop()
x.plot(False, 'results/baseline')
