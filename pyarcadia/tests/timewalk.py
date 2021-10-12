from tqdm import tqdm
import numpy as np
import math
import time
import statistics

from ..test import customplot
from ..analysis import PixelData, CustomWord, TestPulse
from .threshold import ThresholdScan

class TimewalkScan(ScanTest):
    pixels = {}
    th = 1
    sections = []

    def pre_main(self):
        super().pre_main()
        self.daq.injection_digital(0xffff)
        self.daq.read_enable(0xffff)
        self.daq.clock_enable(0xffff)
        self.daq.injection_enable(0xffff)

        self.analysis.file.seek(0, 2)
        self.daq.send_tp(1)
        time.sleep(0.1)
        self.analysis.cleanup(); self.analysis.analyze()

        self.daq.send_tp(1)
        time.sleep(0.1)
        self.analysis.cleanup(); self.analysis.analyze()

        self.pixels = {}

        print("Starting scan on the following pixels:")
        counter = 0
        for packet in self.analysis.packets:
            if(type(packet) != PixelData):
                continue

            for p in packet.pixels:
                p.injected = {}
                p.noise    = [0] * 64
                self.pixels[(p.row,p.col)] = p
                print("\t%3d) %s" % (counter, p.to_string()))
                counter += 1

            if(packet.sec not in self.sections):
                self.sections.append(packet.sec)

        self.range  = range(0,64)

    def pre_loop(self):
        for section in self.sections:
            self.daq.write_gcrpar('BIAS%1d_VCASN' % section, 1)
        return

    def loop_body(self, iteration):
        th = iteration

        for section in self.sections:
            self.daq.write_gcrpar('BIAS%1d_VCASN' % section, th)
        
        self.daq.custom_word(0xDEAFABBA, iteration)
        self.daq.read_enable(self.sections)
        self.daq.injection_digital(self.sections)
        self.daq.send_tp(2)
        time.sleep(0.01)

        self.daq.custom_word(0xBEEFBEEF, iteration)
        self.daq.injection_analog(self.sections)
        self.daq.send_tp(100)
        time.sleep(0.01)

        self.daq.custom_word(0xDEADBEEF, iteration)
        for i in range(0,100):
            self.daq.injection_analog(self.sections)
            self.daq.injection_digital(self.sections)

        time.sleep(0.01)

        self.daq.read_disable(self.sections)
        self.daq.custom_word(0xCAFECAFE, iteration)

    def post_main(self):
        super().post_main()
        print("Now analysing results...")
        self.analysis.analyze()

        iterator = iter(self.analysis.packets)
        packet = next(p for p in iterator if type(p) == CustomWord and p.word == 0xDEAFABBA);
        counter = 0
        with tqdm(total=len(self.analysis.packets), desc='Data analysis') as bar:
            while True:
                th = packet.payload

                # Initialize arrays
                for i in self.pixels:
                    self.pixels[i].injected[th] = []

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
                        raise RuntimeError("TH:%u - Section %u didn't receive the digitally injected packets." % (th, section))

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
                                    self.pixels[(pix.row,pix.col)].injected[th].append(packet.ts_ext - packet.last_tp)
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

    @customplot(('VCASN (#)', 'Timewalk (us)'), 'Timewalk distribution')
    def singleplot(self, pix, show=True, saveas=None, ax=None):
        inj = []
        err = []
        for injected in self.pixels[pix].injected.values():
            c = len(injected)
            if(c>1):
                inj.append(statistics.mean (injected)*1E6/self.analysis.ts_hz)
                err.append(statistics.stdev(injected)*1E6/self.analysis.ts_hz)
            elif(c==1):
                inj.append(injected[0]*1E6/self.analysis.ts_hz)
                err.append(0)
            else:
                inj.append(0)
                err.append(0)

        ax.errorbar(list(self.range), inj, yerr=err, fmt='-o', label='Test Pulses')

    def plot(self, show=True, saveas=None):
        for pixel in self.pixels:
            pix_saveas = None if (saveas == None) else f"{saveas}_{pixel[0]}_{pixel[1]}"
            self.singleplot(pixel, show=show, saveas=pix_saveas)
