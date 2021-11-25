import logging
from tqdm import tqdm
from pyarcadia.data import ChipData, TestPulse
from pyarcadia.tests.threshold import ThresholdScan

x = ThresholdScan(log=True)
x.injections = 400
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize()

x.chip.write_gcrpar('READOUT_CLK_DIVIDER', 2)

for i in range(16):
    x.chip.write_gcrpar('BIAS{}_VCAL_LO'.format(i), 0)
    x.chip.write_gcrpar('BIAS{}_VCAL_HI'.format(i), 15)

"""
results = {}
with tqdm(total=4*2*2*4, desc='Overall test') as tbar:
    for cols_4 in range(4):
        for pr in range(2):
            for subpr in range(2):
                for pix in range(4):
                    x.chip.pixels_mask()
                    x.chip.pixels_cfg(0b01, 0xffff, 0x1111 << cols_4, [pr], [subpr], [pix])

                    x.run()
                    results.update(x.pixels)
                    x.sequence._popped = []
                    tbar.update(1)
"""


results = {}
step_pr = 8

with tqdm(total=512/8, desc='Overall test', position=3) as tbar:
    for pr in range(0, 512, 16):
        x.chip.pixels_mask()
        x.chip.pixels_cfg(0b01, 0xffff, [0, 8], [pr, pr+8], [0], [0])

        x.run()
        results.update(x.pixels)
        x.sequence._popped = []
        tbar.update(1)

x.pixels = results
x.plot_heatmaps(True, 'results/thresholdmap')
x.save()
