import logging
from pyarcadia.data import ChipData, TestPulse
from pyarcadia.tests.threshold import ThresholdScan

x = ThresholdScan()
x.injections = 500
x.initialize()
x.set_timestamp_resolution(1E-6)

x.chip.write_gcrpar('READOUT_CLK_DIVIDER', 0)

x.chip.pixels_mask()
x.chip.pcr_cfg(0b01, [0,1,2,3,4,5,6,7,8,9,11,12,13,14,15], [0], [0], [0], [0])

for i in range(16):
    x.chip.write_gcrpar('BIAS{}_VCAL_LO'.format(i), 0)
    x.chip.write_gcrpar('BIAS{}_VCAL_HI'.format(i), 1)
    x.chip.write_gcrpar('BIAS{}_VINREF'.format(i), 24)
    x.chip.write_gcrpar('BIAS{}_VCASP'.format(i), 12)

    """
    x.chip.write_gcrpar('BIAS{}_ICLIP'.format(i), 0)
    x.chip.write_gcrpar('BIAS{}_VCASD'.format(i), 4)
    x.chip.write_gcrpar('BIAS{}_IBIAS'.format(i), 2)
    x.chip.write_gcrpar('BIAS{}_IFB'.format(i), 2)
    x.chip.write_gcrpar('BIAS{}_ID'.format(i), 0)
    """

x.run()

x.plot(True, 'results/threshold')
x.save()
