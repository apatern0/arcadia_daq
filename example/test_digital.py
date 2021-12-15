import logging
import time
import matplotlib.cm
import matplotlib.pyplot as plt
import numpy as np
from tabulate import tabulate
from pyarcadia.test import Test, customplot
from pyarcadia.data import TestPulse, ChipData, Pixel
from pyarcadia.sequence import SubSequence

x = Test()
x.chip.track_pcr = True

x.set_timestamp_resolution(1E-6)
x.initialize(auto_read=False)

x.logger.setLevel(logging.WARNING)

x.chip.pixels_mask()
x.chip.pcr_cfg(0b01, 0xffff, [0], [0], [0], 0xf)
x.chip.packets_reset()

x.chip.send_tp(3)
time.sleep(1)

# Test
tps = 0
hitcount = 0
hits = np.full((512, 512), np.nan)

seq = SubSequence(x.chip.readout(1000))

# Add received hits, keep track of tps
for p in seq._queue:
    if isinstance(p, TestPulse):
        tps += 1
        continue

    if not isinstance(p, ChipData):
        continue

    # Is ChipData
    pixels = p.get_pixels()
    for pix in pixels:
        if np.isnan(hits[pix.row][pix.col]):
            hits[pix.row][pix.col] = 1
        else:
            hits[pix.row][pix.col] += 1

        hitcount += 1

# Now subtract from what's expected
injectable = np.argwhere(x.chip.pcr == 0b01)
for (row, col) in injectable:
    if np.isnan(hits[row][col]):
        hits[row][col] = -1
    else:
        hits[row][col] -= tps

# Report differences
unexpected = np.argwhere(np.logical_and(~np.isnan(hits), hits != 0))

toprint = []
for (row, col) in unexpected:
    h = str(abs(hits[row][col])) + " (" + ("excess" if hits[row][col] > 0 else "missing") + ")"

    sec = Pixel.sec_from_col(col)
    dcol = Pixel.dcol_from_col(col)
    corepr = Pixel.corepr_from_row(row)
    master = Pixel.master_from_row(row)
    idx = Pixel.idx_from_pos(row, col)
    cfg = format(x.chip.pcr[row][col], '#04b')

    toprint.append([sec, dcol, corepr, master, idx, row, col, h, cfg])

print("Injectables: %d x %d TPs = %d -> Received: %d" % (len(injectable), tps, len(injectable)*tps, hitcount))
print(tabulate(toprint, headers=["Sec", "DCol", "CorePr", "Master", "Idx", "Row", "Col", "Unexpected Balance", "Pixel Cfg"]))

def plot():
    fig, ax = plt.subplots()
    cmap = matplotlib.cm.jet
    cmap.set_bad('gray', 1.)
    image = ax.imshow(hits, interpolation='none', cmap=cmap)

    for i in range(1, 16):
        plt.axvline(x=i*32-0.5, color='black')
