import logging
from pyarcadia.tests.threshold import ThresholdScan

x = ThresholdScan()
x.set_timestamp_resolution(1E-6, update_hw=False)

x.logger.setLevel(logging.WARNING)

x.range = range(64)
#x.load('results__09_11_2021/run__1__14_24_11.json')
#x.load('results__24_11_2021/run__1__10_28_52.json')
x.load('results__24_11_2021/run__1__13_15_01.json')

x.scurve_fit()

x.plot_histograms()
