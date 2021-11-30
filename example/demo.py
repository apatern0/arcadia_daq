import sys
import os
import logging
from pyarcadia.data import ChipData, TestPulse
from pyarcadia.tests.threshold import ThresholdScan

x = ThresholdScan()

if len(sys.argv) > 1 and os.path.isfile(sys.argv[1]):
    x.load(sys.argv[1])
else:

    x.injections = 1000
    x.set_timestamp_resolution(1E-6)

    x.logger.setLevel(logging.WARNING)
    x.initialize()

    print("\n\nRunning Threshold Scan on 16 pixels...\n\n")

    x.chip.write_gcrpar('READOUT_CLK_DIVIDER', 0)

    x.chip.pixels_mask()
    x.chip.pixels_cfg(0b01, 0xffff, [0], [0], [0], [0])

    for i in range(16):
        x.chip.write_gcrpar('BIAS{}_VCAL_LO'.format(i), 0)
        x.chip.write_gcrpar('BIAS{}_VCAL_HI'.format(i), 15)

    x.run()

pix_list = list(x.pixels.keys())

print("\n\nScanned the following pixels: %s\n\n" % pix_list)

print("\n\nScan over! Now plotting the scurves of the first 5 pixels...\n\n")
for i in range(5):
    #x.plot_single(pix=pix_list[i])
    pass

print("\n\nSaving the results using autosave\n\n")

x.save()

print("\n\nSaving the results with a custom name\n\n")

x.save("pippopluto.json")


print("\n\nCreating a new test and importing the results\n\n")

del x
y = ThresholdScan()
y.load("pippopluto.json")

print("Loaded results. They contain the following pixels:\n\n")

for pixel in y.pixels:
    print(y.pixels[pixel])

last = list(y.pixels.keys())[-1]
print("Last pixel is {}".format(last))

print("\n\nPlotting the s-curve of the last pixel\n\n")

y.plot_single(pix=last)

print("\n\nExtracting the info\n\n")

info = ["fit_mu", "fit_mu_err", "fit_sigma", "fit_sigma_err", "gain", "noise", "baseline"]
for i in info:
    print("{}: {}".format(i, getattr(y.pixels[last], i)))

print("\n\nPlotting the heatmaps for this scan\n\n")
y.plot_heatmaps()

print("\n\nSaving the heatmaps as heatmap_....pdf\n\n")
y.plot_heatmaps(show=False, saveas="heatmap_")

print("\n\nPlotting the histograms for sections 2, 3, 4 and 5\n\n")
y.plot_histograms(sections=[2, 3, 4, 5])
