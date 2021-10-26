from pyarcadia.tests.baseline import MatrixBaselineScan
import logging

#x = BaselineScan()
x = MatrixBaselineScan()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize(auto_read=False)

x.chip.pixels_mask()
x.chip.pixels_cfg(0b01, 0xffff, [0], [0], 0b01, 0xf)
x.loop_reactive()

x.save('results/baseline')
print("Saving plots...")
x.plot(show=False, saveas='results/baseline')
print("Saved...")
