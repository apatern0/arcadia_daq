inject_random = 0.23 # in Hz

import time
import logging
import math
import random
from pyarcadia.test import Test
from pyarcadia.sequence import SubSequence

def autoscale(num):
    scales = {
        1e9 : "G",
        1e6 : "M",
        1e3 : "k",
        1 : "",
        1e-3 : "m",
        1e-6 : "u",
        1e-9 : "n",
        1e-12 : "p"
    }

    for scale in scales:
        if num > scale:
            break

    return "%.3f %s" % ( (num/scale), scales[scale] )

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
iteration = -1
try:
    while True:
        iteration += 1

        x.chip.write_gcrpar("READOUT_CLK_DIVIDER", iteration)
        time.sleep(1)

        elapsed = autoscale( 1/4e6 * ( 2** iteration) )
        print(f"Iteration {iteration} - Read every {elapsed}s: ", end="")

        x.chip.packets_reset()
        x.chip.send_tp(pulses=50, us_on=1, us_off=1)

        # If too many packets, abort
        if x.chip.packets_count() > 1E3:
            print("There are too many packets to analyze! Skipping this round.")
            x.chip.packets_reset()
            continue

        # Analyze
        a = SubSequence( x.chip.readout() )
        data = a.get_data()
        data_count = len(data)

        print(f"Data count: {data_count}. Dump:")
        a.dump()
        print("")
        
        time.sleep(1)

except KeyboardInterrupt:
    pass

# Print stats
