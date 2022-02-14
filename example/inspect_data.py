import logging
from pyarcadia.data import ChipData, TestPulse
from pyarcadia.tests.threshold import ThresholdScan
import os

x = ThresholdScan()

rundate = [15,12,2021]
runnumber = 95
pixeladdress = (2,224)

resultfolder="results__{}_{}_{}".format(rundate[0],rundate[1],rundate[2])
runname = [filename for filename in os.listdir(resultfolder) if filename.startswith("run__{}".format(runnumber))]
x.load("{}/{}".format(resultfolder,runname[0]))
x.plot_single(pix=pixeladdress)
x.gcrs
