from tqdm import tqdm
import numpy as np
import math
import time

from ..test import customplot
from ..analysis import PixelData, CustomWord, TestPulse
from .scan import ScanTest

class BaselineScan(ScanTest):
    th_min = [1]
    th_max = [63]
    pixels = {}
    th = [1]
    sections = []

    def pre_main(self):
        super().pre_main()
        self.sections = [x for x in range(16) if x not in self.daq.sections_to_mask]

        self.th     = [0]  * 16
        self.th_min = [1]  * 16
        self.th_max = [63] * 16

        self.range  = math.log(64,2)
        self.result = [0] * len(self.sections)

    def pre_loop(self):
        for section in self.sections:
            self.daq.write_gcrpar('BIAS%1d_VCASN' % section, 1)
        return

    def loop_body(self, iteration):
        for section in self.sections:
            # Divide et impera
            self.th[section] = math.floor((self.th_min[section] + self.th_max[section])/2)
            self.daq.write_gcrpar('BIAS%1d_VCASN' % section, self.th[section])
        
        self.daq.custom_word(0xDEAFABBA)
        self.daq.read_enable(self.sections)
        self.daq.injection_digital(self.sections)
        self.daq.send_tp(2)

        self.daq.custom_word(0xBEEFBEEF)
        for i in range(0,99):
            self.daq.injection_analog(self.sections)
            self.daq.injection_digital(self.sections)

        self.daq.read_disable(self.sections)
        self.daq.custom_word(0xCAFECAFE)

        time.sleep(0.5)
        self.analysis.cleanup()
        self.analysis.analyze()

        dig_injs   = self.analysis.subset(0xDEAFABBA, 0xBEEFBEEF)
        noise_hits = self.analysis.subset(0xBEEFBEEF, 0xCAFECAFE)

        for section in self.sections:
            packets = list(filter(lambda x:type(x) == PixelData and x.sec == section, dig_injs))
            num = len(packets)

            if(num < 2):
                raise RuntimeError("Section %u didn't receive the digitally injected packets." % section)

            packets = list(filter(lambda x:type(x) == PixelData and x.sec == section, noise_hits))
            num = len(packets)

            if(num == 0):
                self.th_min[section] = self.th[section]
            else:
                self.th_max[section] = self.th[section]

    def post_main(self):
        super().post_main()
        for i, section in enumerate(self.sections):
            self.result[i] = self.th[section]

class FullBaselineScan(ScanTest):
    pixels = None
    th = 1
    sections = []
    axes = ["Section (#)", "VCASN (#)"]
    result = None

    def pre_main(self):
        super().pre_main()
        self.sections = [x for x in range(16) if x not in self.daq.sections_to_mask]

        self.range  = range(1,64)
        self.result = np.zeros((16,64), int)

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
        time.sleep(0.1)

        self.daq.custom_word(0xBEEFBEEF, iteration)
        for i in range(0,99):
            self.daq.injection_analog(self.sections)
            self.daq.injection_digital(self.sections)

        time.sleep(0.1)
        self.daq.read_disable(self.sections)
        self.daq.custom_word(0xCAFECAFE, iteration)

    def post_main(self):
        super().post_main()
        self.readout(reset=True)

        iterator = iter(self.analysis.packets)
        packet = next(p for p in iterator if type(p) == CustomWord and p.word == 0xDEAFABBA);

        while True:
            th = packet.payload

            # Check Digital injections
            dig_injs = []
            tps = 0
            while True:
                try:
                    packet = next(p for p in iterator)
                    if(type(packet) == PixelData):
                        dig_injs.append(packet)
                    elif(type(packet) == TestPulse):
                        tps += 1
                    else:
                        break
                except StopIteration:
                    break

            for section in self.sections:
                packets = list(filter(lambda x:type(x) == PixelData and x.sec == section, dig_injs))
                num = len(packets)

                if(num < tps):
                    print("TH:%u - Section %u didn't receive the digitally injected packets." % (th, section))
                    #raise RuntimeError("TH:%u - Section %u didn't receive the digitally injected packets." % (th, section))

            # Go on to noise packets
            if(type(packet) != CustomWord or packet.word != 0xBEEFBEEF or packet.payload != th):
                raise RuntimeError('Unexpected packet here')

            noise_hits = []
            while True:
                try:
                    packet = next(p for p in iterator)
                    if(type(packet) == PixelData):
                        noise_hits.append(packet)
                    else:
                        break
                except StopIteration:
                    break

            for section in self.sections:
                packets = list(filter(lambda x:type(x) == PixelData and x.sec == section, noise_hits))
                num = len(packets)
            
                self.result[section][th] = num


            if(type(packet) != CustomWord or packet.word != 0xCAFECAFE or packet.payload != th):
                raise RuntimeError('Unexpected packet here')
            
            if(th > 63):
                break

            try:
                packet = next(iterator)
            except StopIteration:
                break

            if(type(packet) != CustomWord or packet.word != 0xDEAFABBA):
                raise RuntimeError('Unexpected packet here')

    @customplot(('VCASN (#)', 'Section (#)'), 'Baseline distribution')
    def plot(self, show=True, saveas=None, ax=None):
        result_imshow = self.result
        for i in range(64):
            for j in range(16):
                if(result_imshow[j][i] > 200):
                    result_imshow[j][i] = 200

        image = ax.imshow(result_imshow)

        """
        for i in range(64):
            for j in range(16):
                text = ax.text(i, j, self.result[j][i],
                       ha="center", va="center", color="w")
        """
        return image
