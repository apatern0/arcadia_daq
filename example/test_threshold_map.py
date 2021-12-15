import os
import sys
import logging
import math
from tqdm import tqdm
from pyarcadia.data import ChipData, TestPulse
from pyarcadia.tests.threshold import ThresholdScan

def get_size(obj, seen=None):
    """Recursively finds size of objects"""
    size = sys.getsizeof(obj)
    if seen is None:
        seen = set()
    obj_id = id(obj)
    if obj_id in seen:
        return 0
    # Important mark as seen *before* entering recursion to gracefully handle
    # self-referential objects
    seen.add(obj_id)
    if isinstance(obj, dict):
        size += sum([get_size(v, seen) for v in obj.values()])
        size += sum([get_size(k, seen) for k in obj.keys()])
    elif hasattr(obj, '__dict__'):
        size += get_size(obj.__dict__, seen)
    elif hasattr(obj, '__iter__') and not isinstance(obj, (str, bytes, bytearray)):
        size += sum([get_size(i, seen) for i in obj])
    return size

x = ThresholdScan()
x.injections = 1000

x.logger.setLevel(logging.WARNING)
x.initialize()

x.chip.write_gcrpar('READOUT_CLK_DIVIDER', 2)
#x.chip.write_gcrpar('MAX_READS', 4)

for i in range(16):
    x.chip.write_gcrpar('BIAS{}_VCAL_LO'.format(i), 0)
    x.chip.write_gcrpar('BIAS{}_VCAL_HI'.format(i), 15)

start = 0
if len(sys.argv) > 1:
    try:
        num = int(sys.argv[1])
    except:
        print("%s is not a number. Aborting" % sys.argv[1])
        sys.exit()

    savedir = 'map_{}'.format(num)
    if not os.path.isdir(os.path.join(os.getcwd(), savedir)):
        print("%s is not a directory" % savedir)
        sys.exit()

    print("Resuming scan in map_{}".format(num))

    start = False
    for pr in range(0, 128, 2):
        if not os.path.exists(os.path.join(os.getcwd(), savedir, 'pr_{}.json'.format(pr))):
            start = pr
            break

    if not start:
        print("Scan was complete. Aborting.")
        sys.exit()

    print("Resuming from PR %d" % start)

else:
    print("Results will be saved in... ", end="")
    incr = -1
    savedir = ''
    while True:
        incr += 1
        savedir = 'map_{}'.format(incr)
        if not os.path.exists(os.path.join(os.getcwd(), savedir)):
            try:
                os.mkdir(savedir)
            except:
                continue

            break

    print(savedir+"\n\n")

x_step = 16
y_step = 16

sec_step = 1 if x_step <= 16 else math.floor(x_step/16)
col_step = 16 if x_step >= 16 else math.floor(x_step/2)
pr_step = 1 if y_step <= 4 else math.floor(y_step/4)

print("\n\nPerforming scan with x_step = {}, y_step = {}\n".format(x_step, y_step) + \
    "Calculated: sec_step = {}, col_step = {}, pr_step = {}\n\n".format(sec_step, col_step, pr_step))

results = {}
for pr in range(start, 128, pr_step):
    print("Test has size: %.3f MB" % (get_size(x)/1E6))
    x.__init__()
    print("After initialization: %.3f MB" % (get_size(x)/1E6))

    x.chip.pixels_mask()
    x.chip.pcr_cfg(0b01, list(range(0, 16, sec_step)), list(range(0, 16, col_step)), [pr], [0], [0])

    x.run()

    x.save(os.path.join(savedir, 'pr_{}.json'.format(pr)))
    results.update(x.pixels)

x.results = results
x.plot_heatmaps()
