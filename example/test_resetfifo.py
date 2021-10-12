import logging
import time
from tqdm import tqdm
from pyarcadia.test import Test

x = Test()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.chip_init()

x.daq.listen_loop(0, 5, 1)

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
