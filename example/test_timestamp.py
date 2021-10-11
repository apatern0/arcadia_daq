import logging
import time
from pyarcadia.analysis import PixelData
from pyarcadia.test import Test

x = Test()
x.logger.setLevel(logging.INFO)
x.initialize()

x.set_timestamp_resolution(125E-9)
x.timestamp_sync()

x.daq.enable_readout(0x0004)
x.daq.send_tp(200, 1E6, 1E6)

time.sleep(5); x.analysis.cleanup(); x.analysis.analyze()

for i in x.analysis.packets:
    print("%s" % i.to_string())
    if(type(i) == PixelData):
        print("\tTS_CHIP %x TS_EXT %x TS_FPGA %x LAST_TP %x" % (i.ts, i.ts_ext, i.ts_fpga, i.last_tp))
