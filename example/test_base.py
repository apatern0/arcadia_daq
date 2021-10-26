import logging, time
import random
from pyarcadia.test import Test
from pyarcadia.analysis import Sequence, ChipData

from arcadia_daq import set_ipbus_loglevel
set_ipbus_loglevel(2)


x = Test()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize(sync='sync', auto_read=True)

x.chip.packets_reset()

tps = 100
space=6000
secs = [s for s in range(0, 16) if s not in x.lanes_excluded]

#print("Pixels [2][0]+[3][1] (Master 0) [4][1]+[5][0] (Slave 1)")
#x.chip.pixels_cfg(0b01, secs, [0], [0], [1], [0, 3])
#x.chip.pixels_cfg(0b01, secs, [0], [1], [0], [1, 2])

x.chip.write_gcrpar('READOUT_CLK_DIVIDER', 4)

x.chip.track_pcr = True
x.chip.pixels_mask()
for s in secs:
    for c in range(0, 16):
        for pr in random.sample(range(128), 10):
            x.chip.pixels_cfg(0b01, [s], [c], pr, random.randrange(2), 0b1) ;#random.randrange(16))

print("Smart Readout Disabled")
x.chip.write_gcrpar('DISABLE_SMART_READOUT', 1)
x.chip.send_tp(tps, space, space)
time.sleep(10)
print("Fifo has %d packts" % x.chip.packets_count())
#s = Sequence(x.readout_until())
s = Sequence(x.readout())

s.packets.sort(key=lambda x:x.ts_ext*512*512+x.master_idx() if isinstance(x, ChipData) else 0)
#s.dump()
s.analyze(x.chip.pcr, plot=True)

print("Shutdown")

"""
print("Smart Readout Enabled")
x.chip.write_gcrpar('DISABLE_SMART_READOUT', 0)
x.chip.send_tp(tps, space, space)
time.sleep(0.1)
s = Sequence(x.readout_until())
#s.packets.sort(key=lambda x:x.ts_ext*512*512+x.master_idx() if isinstance(x, ChipData) else 0)
#s.dump()
s.analyze(x.chip.pcr)
"""
