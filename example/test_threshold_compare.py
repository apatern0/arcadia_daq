import os
import sys
import logging
import math
from tqdm import tqdm
from prettytable import PrettyTable
from pyarcadia.data import ChipData, TestPulse
from pyarcadia.tests.threshold import ThresholdScan

# Test results to import
if len(sys.argv) < 2:
    searchdir = ['.']
else:
    searchdir = sys.argv[1:]

files = [os.path.join(folder, filename) for folder in searchdir for filename in os.listdir(folder) if filename.endswith('.json') and os.path.isfile(os.path.join(folder, filename))]

tests = []
for f in files:
    x = ThresholdScan()
    x.set_timestamp_resolution(1E-6, update_hw=False)
    print("Loading results from %s..." % f)
    x.load(f)

    tests.append(x)

# Check GCR differences w.r.t. default
default_gcrs = tests[0].chip.dump_gcrs(False)
default_gcrs = {key: val for key, val in default_gcrs.items() if (not key.startswith('BIAS') or key.startswith('BIAS0')) and not key.startswith('HELPER')}
differing = []

for t in tests:
    tmp_diff = {gcr: t.gcrs[gcr] for gcr in default_gcrs.keys() if t.gcrs[gcr] != default_gcrs[gcr]}

    differing.append(tmp_diff)

# Filter common ones
common = {}
for gcr in differing[0]:
    shared = True
    for d in differing[1:]:
        if gcr not in differing or differing[0][gcr] != d[gcr]:
            shared = False
            break

    if shared:
        common[gcr] = differing[0][gcr]

for c in common:
    for d in differing:
        del d[gcr]

def print_as_table(data, title):
    table = PrettyTable()
    table.title = title

    itemized = list(data.items())
    total = len(data)
    if total == 0:
        print(table)
        return

    repeats = min(6, total)
    per_repeat = math.ceil(total/repeats)

    for i in range(repeats):
        subset = itemized[i*per_repeat : min((i+1)*per_repeat, total)]
        diff = per_repeat - len(subset)
        if diff > 0:
            subset.extend([('', '') for _ in range(diff)])

        table.add_column('GCR Parameter', [v[0] for v in subset])
        table.add_column('Value', [v[1] for v in subset])

    print(table)

# Tabulating
print_as_table(default_gcrs, 'Default GCRs')

print_as_table(common, 'Common changes')

for num, d in enumerate(differing):
    print_as_table(d, 'Changes in Test %d' % num)
