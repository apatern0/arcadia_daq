from tqdm import tqdm
import numpy as np
import math
import time

from ..test import customplot
from ..analysis import PixelData, CustomWord, TestPulse
from .scan import ScanTest

class ThresholdScan(ScanTest):
    pixels = {}
    th = 1
    sections = []
    axes = ["VCASN (#)", "Hits (#)"]
    injections = 1000

    def pre_main(self):
        super().pre_main()

        self.chip.injection_digital(0xffff)
        self.chip.read_enable(0xffff)
        self.chip.clock_enable(0xffff)
        self.chip.injection_enable(0xffff)

        self.chip.packets_reset()
        self.chip.send_tp(1)
        time.sleep(0.1)
        read = self.readout(reset=True)

        self.pixels = {}

        print("Starting scan on the following pixels:")
        counter = 0
        for packet in self.analysis.packets:
            if(type(packet) != PixelData):
                continue

            for p in packet.pixels:
                p.injected = [0] * 64
                p.noise    = [0] * 64
                self.pixels[(p.row,p.col)] = p
                print("\t%3d) %s" % (counter, p.to_string()))
                counter += 1

            if(packet.sec not in self.sections):
                self.sections.append(packet.sec)

        if counter == 0:
            raise ValueError("No pixels have been selected!")

        self.range  = range(0,64)
        print("Changing biases on sections: ", end=""); print(self.sections)

    def pre_loop(self):
        for section in self.sections:
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, 1)
        return

    def loop_body(self, iteration):
        th = iteration

        for section in self.sections:
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, th)
        
        self.chip.custom_word(0xDEAFABBA, iteration)
        self.chip.read_enable(self.sections)
        self.chip.injection_digital(self.sections)
        self.chip.send_tp(2)
        time.sleep(0.1)

        self.chip.custom_word(0xBEEFBEEF, iteration)
        self.chip.injection_analog(self.sections)
        self.chip.send_tp(self.injections)
        time.sleep(0.2)

        self.chip.custom_word(0xDEADBEEF, iteration)
        for i in range(0,self.injections):
            self.chip.injection_analog(self.sections)
            self.chip.injection_digital(self.sections)

        time.sleep(0.2)

        self.chip.read_disable(self.sections)
        self.chip.custom_word(0xCAFECAFE, iteration)

    def post_main(self):
        super().post_main()
        print("Fetching results...")
        self.readout(reset=True)
        print("Now analysing results...")

        iterator = iter(self.analysis.packets)
        packet = next(p for p in iterator if type(p) == CustomWord and p.word == 0xDEAFABBA)
        counter = 0
        invalid = [[] for _ in range(64)]
        with tqdm(total=len(self.analysis.packets), desc='Data analysis') as bar:
            while True:
                th = packet.payload
                bar.update(counter)
                counter = 0;

                # Check Digital injections
                dig_injs = []
                tps = 0
                ts = time.time()
                c=0
                while True:
                    try:
                        packet = next(iterator); counter += 1
                        if(type(packet) == PixelData):
                            dig_injs.append(packet)
                        elif(type(packet) == TestPulse):
                            tps += 1
                        else:
                            break
                    except StopIteration:
                        break

                    c += 1

                for section in self.sections:
                    packets = list(filter(lambda x:type(x) == PixelData and x.sec == section, dig_injs))
                    num = len(packets)

                    if(num < tps):
                        #raise RuntimeError("TH:%u - Section %u didn't receive the digitally injected packets." % (th, section))
                        invalid[th].append(section)

                #print("\t\tElapsed for digital: %3d (%d packets)" % ((time.time() - ts)*1000, c))

                # Go on to injected packets
                if(type(packet) != CustomWord or packet.word != 0xBEEFBEEF or packet.payload != th):
                    raise RuntimeError('Unexpected packet here %s ' % packet.to_string())

                ts = time.time()
                c=0
                while True:
                    try:
                        packet = next(iterator); counter += 1
                        if(type(packet) == PixelData):
                            for pix in packet.pixels:
                                try:
                                    self.pixels[(pix.row,pix.col)].injected[th] += 1
                                except KeyError:
                                    self.logger.warning("Unexpected pixel in this run: %s" % pix.to_string())

                        elif(type(packet) == TestPulse):
                            continue
                        else:
                            break
                    except StopIteration:
                        break
                    
                    c += 1

                #print("\t\tElapsed for injected: %3d (%d packets)" % ((time.time() - ts)*1000, c))

                # Go on to noisy packets
                if(type(packet) != CustomWord or packet.word != 0xDEADBEEF or packet.payload != th):
                    raise RuntimeError('Unexpected packet here: %s ' % packet.to_string())

                ts = time.time()
                c = 0
                while True:
                    try:
                        packet = next(iterator); counter += 1
                        if(type(packet) == PixelData):
                            for pix in packet.pixels:
                                try:
                                    self.pixels[(pix.row,pix.col)].noise[th] += 1
                                except KeyError:
                                    self.logger.warning("Unexpected pixel in this run: %s" % pix.to_string())
                        elif(type(packet) == TestPulse):
                            continue
                        else:
                            break
                    except StopIteration:
                        break

                    c += 1

                #print("\t\tElapsed for noise: %3d (%d packets)" % ((time.time() - ts)*1000, c))

                if(type(packet) != CustomWord or packet.word != 0xCAFECAFE or packet.payload != th):
                    raise RuntimeError('Unexpected packet here %s ' % packet.to_string())
                
                if(th > 63):
                    break

                try:
                    packet = next(iterator); counter += 1
                except StopIteration:
                    break

                if(type(packet) != CustomWord or packet.word != 0xDEAFABBA):
                    raise RuntimeError('Unexpected packet here: %s' % packet.to_string())

        for i,l in enumerate(invalid):
            if len(l) > 0:
                print("Lane %d missing digital injections for threshold trials: %s" % (i, str(l)))

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
