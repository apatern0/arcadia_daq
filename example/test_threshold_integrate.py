import os
import sys
import logging
from tqdm import tqdm
from pyarcadia.data import ChipData, TestPulse
from pyarcadia.tests.threshold import ThresholdScan

if len(sys.argv) < 2:
    raise RuntimeError("Needs 1 argument: savefile beginning")

files = [filename for filename in os.listdir('.') if filename.startswith(sys.argv[1]) and os.path.isfile(filename)]

x = ThresholdScan()
x.injections = 1000
x.set_timestamp_resolution(1E-6, update_hw=False)

results = {}

tmp = None
for f in files:
    print("Loading results from %s..." % f)
    tmp = ThresholdScan()
    tmp.load(f)

    results.update(tmp.pixels)

print("Analysis contains %d unique pixels" % len(x.pixels))

x.gcrs = tmp.gcrs
x.pixels = results
x.plot_heatmaps()
