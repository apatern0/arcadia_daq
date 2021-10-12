import time
import logging
from pyarcadia.daq import Daq
from pyarcadia.analysis import DataAnalysis

x = Daq()
a = DataAnalysis()

x.logger.setLevel(logging.DEBUG)
x.enable_readout(0x0)
#x.reset_fifo()
sync = x.initialize()
print("Sync result: %s" % hex(int(sync)))

count = x.listen_loop()
print("Read %d garbage packets" % count)

x.set_timestamp_period(10*(2**3))
a.ts_khz = 80E3/(10*(2**3))

x.pixels_mask()
x.noforce_injection()
x.noforce_nomask()

print("\n\nWriting custom word... 2 TPs")
x.custom_word(0x0000111133337777)
x.send_tp(2)
x.custom_word(0xDEADBEEFABBABEEF)

print("\n\nSending 1 test pulses on 16 prs")
x.pixels_cfg(0b01, 0xffff, [2,4], [1], [0], 0xF)

x.enable_readout(0xffff)
x.send_tp(1)
time.sleep(0.5)
count = x.listen_loop()
a.cleanup()
a.analyze()
print("Read %d packets (should be a lot)" % a.tot)
a.dump_tps(32)
a.dump(32)
print("Ciao")
