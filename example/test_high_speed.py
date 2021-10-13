import logging
from tqdm import tqdm
import time
from pyarcadia.test import Test, DaqListen

x = Test(auto_read=False)
x.set_timestamp_resolution(1E-6)

print("Disabling readout")
x.daq.enable_readout(0)

x.daq.hard_reset()
x.daq.reset_subsystem('chip', 1)
x.daq.reset_subsystem('chip', 2)
x.daq.write_gcr(0, (0xFF00) | (x.chip_timestamp_divider << 8))
x.daq.reset_subsystem('per', 1)
x.daq.reset_subsystem('per', 2)
x.daq.injection_digital()
x.daq.injection_enable()
x.daq.clock_enable()
x.daq.read_enable()
x.daq.force_injection()
x.daq.force_nomask()
x.daq.reset_subsystem('per', 1)
x.daq.reset_subsystem('per', 2)
x.daq.pixels_mask()
synced = x.daq.calibrate_serializers()

x.logger.setLevel(logging.INFO)

print("Synchronized lanes:", end='')
print(synced)

x.resync()

print("Sending 100 custom words")
for j in range(100):
    x.daq.custom_word(0xd34d)

time.sleep(0.1)
pkts = x.daq.get_fifo_occupancy()
print(f"Fifo has {pkts} packets. Resetting.")
x.daq.reset_fifo()

x.daq.enable_readout(0xffff)

print("Enabled readout on synced lanes")
print("Enabled pixels [0][0] in every section")
x.daq.pixels_mask()
x.daq.pixels_cfg(0b01, synced, [0], [0], [0], 0b1)
x.daq.noforce_injection()
x.daq.noforce_nomask()
time.sleep(0.01)
pkts = x.daq.get_fifo_occupancy()
print(f"Fifo has {pkts} packets. Resetting.")
x.daq.reset_fifo()

print("Sending 1 TPs")
x.daq.send_tp(1)
time.sleep(0.01)
pkts = x.daq.get_fifo_occupancy()
print(f"Fifo has {pkts} packets")
x.analysis.cleanup()

x.reader = DaqListen(x.daq)
x.reader.start()

print("Sending 1 TPs")
x.daq.send_tp(1)
time.sleep(0.01)
recv = x.readout()
print("Analyzed %d packets:" % recv)
x.analysis.dump()

"""
with tqdm(total=100, desc='Test') as bar:
    for i in range(100):
        # Check receives data
        for j in range(100):
            x.daq.custom_word(0xd34d)

        time.sleep(1)
        pkts = x.daq.get_fifo_occupancy()
        if(pkts != 200):
            raise ValueError('Expecting 100 packets in fifo, but there are %d' % pkts)

        x.analysis.cleanup()
        x.daq.listen_loop(0, 5, 0.1)
        pkts = x.analysis.analyze()

        if(pkts != 100):
            raise ValueError('Expecting to read 100 packets, read %d' % pkts)

        # Check reset
        for j in range(100):
            x.daq.custom_word(0xd34d)

        x.daq.reset_fifo()
        pkts = x.daq.get_fifo_occupancy()
        if(pkts != 0):
            raise ValueError('Expecting 100 packets in fifo, but there are %d' % pkts)

        bar.update(1)
"""
