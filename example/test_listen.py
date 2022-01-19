inject_random = 0.23

import time
import logging
import math
import random
from pyarcadia.test import Test
from pyarcadia.sequence import SubSequence

x = Test()
x.initialize()

x.set_timestamp_resolution(1E-6)

# Mask FEs, disable injection
x.chip.pcr_cfg(0b10, 0xffff, 0xffff, None, None, 0xf)

# Configure Biases
for sec in range(0,16):
    x.chip.write_gcrpar('BIAS%d_VCASN' % sec, 28)

# Enable FE outputs
x.chip.pcr_cfg(0b00, 0xffff, 0xffff, None, None, 0xf)

# Enable test injection on 1 example pixel
x.chip.pixel_cfg((400, 400), injection=True)

# Verify that no hits are read out
x.chip.packets_reset()
a = SubSequence( x.chip.readout(50) )
if len(a) == 0:
    print("No packets have been read. Good!")
else:
    print("Spurious packets have been detected:")
    a.dump()
    print("Press CTRL-C to resume.")
    try:
        time.sleep(999999)
    except KeyboardInterrupt:
        pass

x.chip.packets_read_start()
t0 = time.time()
rate_inf = 0
rate_min = [0 for i in range(0, 60)]
iteration = -1
try:
    while True:
        iteration += 1
        elapsed = time.time() - t0
        print("Iteration %4d @ %7d s: " % (iteration, elapsed), end="")

        # Inject random charge if enabled
        if inject_random is not False:
            if random.random() < inject_random:
                x.chip.send_tp()

        # If too many packets, abort
        if x.chip.packets_count() > 1E3:
            print("There are too many packets to analyze! Skipping this round.")
            x.chip.packets_reset()
            continue

        # Analyze
        a = SubSequence( x.chip.readout() )
        data = a.get_data()
        data_count = len(data)

        # Update rates
        rate_min[iteration % 60] = data_count
        rate_inf = (rate_inf*iteration + data_count)/(iteration+1)

        # Evaluate 10s, 1m rates
        rate_10s = sum(rate_min[iteration-10:iteration])/10
        rate_1m = sum(rate_min)/60
        print("Dark rates - 10s: %.3f Hz, 1m: %.3f Hz, inf: %.3f Hz" % (rate_10s, rate_1m, rate_inf))
        
        time.sleep(1)

except KeyboardInterrupt:
    pass

# Print stats
