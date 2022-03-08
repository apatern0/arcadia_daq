import logging
import time
from random import random
from math import floor
from tabulate import tabulate
from pyarcadia.test import Test
from pyarcadia.sequence import SubSequence
from pyarcadia.data import Pixel

x = Test()
try:
    x.initialize()
    x.set_timestamp_resolution(1E-6)
except RuntimeError:
    pass

def inject_and_compare(pixels, injs=3, t_on=1000, t_off=1000):
    x.chip.send_tp(injs)

    toprint = []
    res = SubSequence(x.chip.readout())
    recv = {}
    for pkt in res.get_data():
        for p in pkt.get_pixels():
            addr = (p.row, p.col)
            if addr not in recv:
                recv[addr] = 1
            else:
                recv[addr] += 1

    for p in recv:
        exp = injs if p in pixels else 0
        toprint.append([p, Pixel(p[0], p[1]).get_sec(), recv[p], exp, recv[p]-exp])

    for p in pixels:
        if p not in recv:
            toprint.append([p, Pixel(p[0], p[1]).get_sec(), 0, injs, -injs])

    toprint.sort(key=lambda x:x[0][1])

    print(tabulate(toprint, headers=["Pixel", "Section", "Received", "Expected", "Difference"]))

def randomize_pixels():
    pixels = [(floor(random()*512), floor(random()*32)+sec*32) for sec in range(0,16)]
    x.chip.pixels_mask()
    x.chip.pixel_cfg(pixels, injection=True, mask=False)
    return pixels

x.chip.packets_read_stop()
x.chip.packets_reset()

# Test SPI SDO
gcr0_ex = x.chip.read_gcr(0)
gcr0 = x.chip.read_gcr(0, True)
print(f"GR0 is 0x%x. SPI SDO working? {gcr0 == gcr0_ex}\n" % gcr0)

# Packet count
pktcount = x.chip.packets_count()
print(f"Currently having {pktcount} packets in the FIFO.")

"""
# Inject some pixels
x.chip.write_gcrpar('DISABLE_SMART_READOUT', 1)
pixels = randomize_pixels()

print(f"Injecting pixels w/ 3 digital TPs: {pixels}")
print("Received:")

x.chip.injection_digital()
inject_and_compare(pixels)

print(f"Injecting pixels w/ 3 analog TPs: {pixels}")
print("Received:")

x.chip.injection_analog()
inject_and_compare(pixels)
"""
