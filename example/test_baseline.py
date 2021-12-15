from pyarcadia.tests.baseline import BaselineScan
import logging

#x = BaselineScan()
x = BaselineScan()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize(auto_read=False)

x.chip.pixels_mask()
x.chip.pcr_cfg(0b01, 0xffff, 0xffff, None, [0], 0xf)
x.run()

slaves = x.result

x.chip.pcr_cfg(0b10, 0xffff, 0xffff, None, [0], 0xf)
x.chip.pcr_cfg(0b01, 0xffff, 0xffff, None, [1], 0xf)
x.run()

masters = x.result

for row in range(512):
    if row%4 > 1:
        continue

    for col in range(512):
        masters[row][col] = slaves[row][col]

x.result = masters

x.save('results/baseline')
print("Saving plots...")
x.plot(show=False, saveas='results/baseline')
print("Saved...")
