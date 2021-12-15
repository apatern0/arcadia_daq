import sys
import logging
from pyarcadia.tests.threshold import ThresholdScan

x = ThresholdScan()
x.set_timestamp_resolution(1E-6, update_hw=False)

x.logger.setLevel(logging.WARNING)

if len(sys.argv) > 1:
    x.load(sys.argv[1])

    x.scurve_fit()

    x.plot_histograms()
