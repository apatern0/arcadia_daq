from pyarcadia.tests.baseline import FullBaselineScan
import logging

#x = BaselineScan()
x = FullBaselineScan()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize()

x.chip.pixels_mask()
x.chip.pixels_cfg(0b01, 0xffff, [0], [0], 0b01, 0xf)

x.loop_parallel()
print("Saving plots...")
x.plot(show=False, saveas='results/baseline')
print("Saved...")
