from tqdm import tqdm
import numpy as np
import math
import time

from ..analysis import ChipData, CustomWord, TestPulse, customplot
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
        read = self.elaborate_until(0xDEADDEAD)

        self.pixels = {}

        print("Starting scan on the following pixels:")
        counter = 0
        for packet in read.data:
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
        results = self.elaborate_until(0xDEAFABBA)
        th = results.payload

        # Check Digital injections
        dig_injs = self.elaborate_until(0xBEEFBEEF)
        if dig_injs.message_error or dig_injs.incomplete:
            raise ValueError()

        for section in self.sections:
            packets = list(filter(lambda x : x.sec == section, dig_injs.data))

            if len(packets) < len(dig_injs.tps):
                self.invalid[section].append(th)

    def elab_phase1(self, iteration):
        # Analog hits
        analog_hits = self.elaborate_until(0xDEADBEEF)
        th = analog_hits.payload
        if analog_hits.message_error or analog_hits.incomplete:
            raise ValueError()

        tps = len(analog_hits.tps)

        for p in analog_hits.data:
            for pix in p.get_pixels():
                try:
                    self.pixels[(pix.row,pix.col)].injected[th] += 1
                except KeyError:
                    self.logger.warning("Unexpected pixel in this run: %s" % pix)

    def elab_phase2(self, iteration):
        # Check Noise hits
        noisy_hits = self.elaborate_until(0xCAFECAFE)
        th = noisy_hits.payload
        if noisy_hits.message_error or noisy_hits.incomplete:
            raise ValueError()

        for p in noisy_hits.data:
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

        noise = self.pixels[pix].noise
        total = [x + y for x, y in zip(inj, noise)]
        #total = [x/self.injections for x in total]
        return ax.plot(self.range, total, '--ro', label='Total')

    def plot(self, show=True, saveas=None):
        for pixel in self.pixels:
            pix_saveas = None if saveas is None else f"{saveas}_{pixel[0]}_{pixel[1]}"
            self.singleplot(pixel, show=show, saveas=pix_saveas)
