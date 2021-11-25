import logging
from pyarcadia.data import ChipData, TestPulse
from pyarcadia.tests.threshold import ThresholdScan

x = ThresholdScan(log=True)
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize()

"""
from pyarcadia.data import CustomWord, FPGAData
from pyarcadia.sequence import Sequence, SubSequence
dummy = FPGAData(0)
tp0 = TestPulse(dummy); tp0.ts = 0
d0 = ChipData(dummy); d0.ts = 1
c0 = CustomWord(message=0xaacc)
tp1 = TestPulse(dummy); tp0.ts = 2
d1 = ChipData(dummy); d1.ts = 3
tp2 = TestPulse(dummy); tp2.ts = 4
d2 = ChipData(dummy); d2.ts = 5
c1 = CustomWord(message=0xcaca)

a = Sequence()
a.ts_sw = 1
a._queue.append(SubSequence(parent=a))
a._queue[0].append(tp0)
a._queue[0].append(d0)
a._queue[0].append(c0)
a._queue.append(SubSequence(parent=a))
a._queue[1].append(tp1)
a.dump()
a[0].dump()
a[1].dump()

b = Sequence()
b._queue.append(SubSequence(parent=b))
b._queue[0].append(d1)
b._queue[0].append(tp2)
b._queue[0].append(d2)
b._queue[0].append(c1)
b.ts_sw = 3
b[0].dump()

a.extend(b)
a.dump()
a[0].dump()
a[1].dump()
a[2].dump()
ext
"""

x.chip.write_gcrpar('READOUT_CLK_DIVIDER', 3)

for i in range(16):
    x.chip.write_gcrpar('BIAS{}_VCAL_LO'.format(i), 0)
    x.chip.write_gcrpar('BIAS{}_VCAL_HI'.format(i), 15)

results = {}
for pr in range(2):
    x.chip.pixels_mask()
    x.chip.pixels_cfg(0b01, 0xffff, [0], [pr], [1], 0xf)

    x.run()
    results.update(x.pixels)

x.plot_heatmaps(True, 'results/thresholdmap')
x.save()
