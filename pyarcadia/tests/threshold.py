import math
import time
import os
import numpy as np
from tqdm import tqdm

from ..data import ChipData, CustomWord, TestPulse, Pixel
from ..test import customplot
from .scan import ScanTest

class ThresholdScan(ScanTest):
    pixels = {}
    th = 1
    sections = []
    axes = ["VCASN (#)", "Hits (#)"]
    injections = 1000

    def __init__(self):
        super().__init__()

        self.ctrl_phases = [self.ctrl_phase0, self.ctrl_phase1, self.ctrl_phase2]
        self.elab_phases = [self.elab_phase0, self.elab_phase1, self.elab_phase2]

    def pre_main(self):
        super().pre_main()

        self.chip.injection_digital(0xffff)
        self.chip.read_enable(0xffff)
        self.chip.clock_enable(0xffff)
        self.chip.injection_enable(0xffff)

        self.chip.packets_reset()
        self.chip.send_tp(1)
        time.sleep(0.1)
        self.chip.custom_word(0xDEADDEAD)

        test = None
        while True:
            test = self.sequence.pop(0)
            if test[-1] == CustomWord(message=0xDEADDEAD):
                break

        self.pixels = {}

        print("Starting scan on the following pixels:")
        counter = 0
        for packet in test.get_data():
            for p in packet.get_pixels():
                p.injected = [0] * 64
                p.noise    = [0] * 64
                self.pixels[(p.row,p.col)] = p
                print("\t%3d) %s" % (counter, p))
                counter += 1

            if(packet.sec not in self.sections):
                self.sections.append(packet.sec)

        if counter == 0:
            raise ValueError("No pixels have been selected!")

        self.range  = range(0,64)
        print("Changing biases on sections: ", end=""); print(self.sections)

    def ctrl_phase0(self, iteration):
        for section in self.sections:
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, 1)
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, iteration)
        
        self.chip.custom_word(0xDEAFABBA, iteration)
        self.chip.read_enable(self.sections)
        self.chip.injection_digital(self.sections)
        self.chip.send_tp(2)
        self.chip.custom_word(0xBEEFBEEF, iteration)

    def ctrl_phase1(self, iteration):
        self.chip.injection_analog(self.sections)
        self.chip.send_tp(self.injections)
        time.sleep(0.1)
        self.chip.custom_word(0xDEADBEEF, iteration)

    def ctrl_phase2(self, iteration):
        for i in range(0,self.injections):
            self.chip.injection_analog(self.sections)
            self.chip.injection_digital(self.sections)

        time.sleep(0.1)
        self.chip.read_disable(self.sections)
        self.chip.custom_word(0xCAFECAFE, iteration)

    def elab_phase0(self, iteration):
        # Start of test
        start = self.sequence.pop(0)

        # If readout is complete, exit
        if start[-1] != CustomWord(message=0xDEAFABBA):
            raise RuntimeError("Unable to locate 0xDEAFABBA packet")

        th = start[-1].payload

        # Check Digital injections
        dig_injs = self.sequence.pop(0)

        # If readout is complete, exit
        if dig_injs[-1] != CustomWord(message=0xBEEFBEEF):
            dig_injs.dump()
            raise RuntimeError("Unable to locate 0xBEEFBEEF packet")

        dig_injs_data = dig_injs.get_data()
        dig_injs_tps = dig_injs.get_tps()

        tps = len(dig_injs_tps)

        for section in self.sections:
            packets = list(filter(lambda x : x.sec == section, dig_injs_data))

            if len(packets) < tps:
                self.logger.warning("Section %d returned %d tps instead of %d" % (section, len(packets), tps))

    def elab_phase1(self, iteration):
        # Analog hits
        analog_hits = self.sequence.pop(0)

        # If readout is complete, exit
        if analog_hits[-1] != CustomWord(message=0xDEADBEEF):
            analog_hits.dump()
            raise RuntimeError("Unable to locate 0xDEADBEEF packet")

        analog_hits_data = analog_hits.get_data()
        analog_hits_tps = analog_hits.get_tps()
        th = analog_hits[-1].payload

        tps = len(analog_hits_tps)

        for p in analog_hits_data:
            for pix in p.get_pixels():
                try:
                    self.pixels[(pix.row,pix.col)].injected[th] += 1
                except KeyError:
                    self.logger.warning("Unexpected pixel in this run: %s" % pix)

    def elab_phase2(self, iteration):
        # Check Noise hits
        noisy_hits = self.sequence.pop(0)

        # If readout is complete, exit
        if noisy_hits[-1] != CustomWord(message=0xCAFECAFE):
            noisy_hits.dump()
            raise RuntimeError("Unable to locate 0xCAFECAFE packet")

        noisy_hits_data = noisy_hits.get_data()
        th = noisy_hits[-1].payload

        for p in noisy_hits_data:
            for pix in p.get_pixels():
                try:
                    self.pixels[(pix.row,pix.col)].noise[th] += 1
                except KeyError:
                    self.logger.warning("Unexpected pixel in this run: %s" % pix)

    @customplot(('VCASN (#)', 'Efficiency(#)'), 'Threshold scan') 
    def singleplot(self, pix, show=True, saveas=None, ax=None):
        inj = self.pixels[pix].injected
        #inj = [x/self.injections for x in inj]
        ax.plot(self.range, inj, '--bo', label='Test Pulses')
        ax.set_ylim(bottom=0, top=4000)

        noise = self.pixels[pix].noise
        total = [x + y for x, y in zip(inj, noise)]
        #total = [x/self.injections for x in total]
        return ax.plot(self.range, total, '--ro', label='Total')

    def plot(self, show=True, saveas=None):
        for pixel in self.pixels:
            pix_saveas = None if saveas is None else f"{saveas}_{pixel[0]}_{pixel[1]}"
            self.singleplot(pixel, show=show, saveas=pix_saveas)

    def serialize(self):
        listed = []
        listed.append(self.injections)

        for pixel in self.pixels:
            tmp = []
            tmp.append(pixel[0])
            tmp.append(pixel[1])
            tmp.append(self.pixels[pixel].injected)
            tmp.append(self.pixels[pixel].noise)

            listed.append(tmp)

        return listed

    def _run(self):
        self.loop_parallel()

    def deserialize(self, serialized):
        self.injections = serialized.pop(0)

        for line in serialized:
            p = Pixel(line[0], line[1])
            p.injected = line[2]
            p.noise = line[3]

            self.pixels[(line[0], line[1])] = p
