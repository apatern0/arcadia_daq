import logging
from pyarcadia.tests.scan import ScanTest

x = ScanTest()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.daq.enable_readout(0x0)
sync = x.initialize()
print("Sync result: %s" % hex(int(sync)))
x.analysis.skip()

x.plot()
