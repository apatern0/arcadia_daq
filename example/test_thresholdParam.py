import logging
from pyarcadia.tests.threshold import ThresholdScan

x = ThresholdScan()
x.set_timestamp_resolution(1E-6)

x.logger.setLevel(logging.WARNING)
x.initialize()

for ib1_val in range(2):
   x.chip.write_gcpar(ib1, ib1_val)
   x.chip.pixels_mask()
   for col_val in range(16):
      for prs_val in range(8):
         for pix_val in range(4):
            x.chip.pixels_cfg(0b01, 0xffff, [col_val], [prs_val], [0], [pix_val])

            x.loop_parallel()
            x.plot(False, 'results/injection')
