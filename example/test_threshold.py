import logging
from pyarcadia.data import ChipData, TestPulse
from pyarcadia.tests.threshold import ThresholdScan

x = ThresholdScan()
x.injections = 1000
x.initialize()
x.set_timestamp_resolution(1E-6)

x.chip.write_gcrpar('READOUT_CLK_DIVIDER', 0)

x.chip.pixels_mask()
x.chip.pixels_cfg(0b01, 0xffff, [0], [0], [0], [0])

for i in range(16):
    x.chip.write_gcrpar('BIAS{}_VCAL_LO'.format(i), 0)
    x.chip.write_gcrpar('BIAS{}_VCAL_HI'.format(i), 15)

x.run()

x.plot(True, 'results/threshold')
x.save()
