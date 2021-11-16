import logging
from pyarcadia.test import Test

x = Test()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize()

x.chip.pixels_mask()
x.chip.pixels_cfg(0b01, 0xffff, [0], [0], [0], 0x0001)

for i in range(16):
    x.chip.write_gcrpar('BIAS%d_VCASN' % i, 35)
    x.chip.write_gcrpar('BIAS%d_VCAL_HI' % i, 15)
    x.chip.write_gcrpar('BIAS%d_VCAL_LO' % i, 0)

x.chip.injection_analog(0xffff)
x.chip.read_enable()
x.chip.send_tp(1)
x.chip.read_disable()

ans = x.sequence.pop(0)
ans.dump()

filtered, ambiguous = ans.filter_double_injections()
print("\n\nfiltered with %d ambiguous:" % ambiguous)
for i in filtered:
    print("%d -- %s " % (i.ts_ext, i))

