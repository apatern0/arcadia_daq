from tqdm import tqdm
import numpy as np
import math
import time

from ..test import customplot
from ..analysis import ChipData, CustomWord, TestPulse
from .scan import ScanTest

class BaselineScan(ScanTest):
    th_min = [1]
    th_max = [63]
    pixels = {}
    th = [1]
    sections = []

    def pre_main(self):
        super().pre_main()
        self.sections = [x for x in range(16) if x not in self.chip.sections_to_mask]

        self.th     = [0]  * 16
        self.th_min = [1]  * 16
        self.th_max = [63] * 16

        self.range  = math.log(64,2)
        self.result = [0] * len(self.sections)

    def pre_loop(self):
        for section in self.sections:
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, 1)
        return

    def loop_body(self, iteration):
        for section in self.sections:
            # Divide et impera
            self.th[section] = math.floor((self.th_min[section] + self.th_max[section])/2)
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, self.th[section])
        
        self.chip.custom_word(0xDEAFABBA)
        self.chip.read_enable(self.sections)
        self.chip.injection_digital(self.sections)
        self.chip.send_tp(2)

        self.chip.custom_word(0xBEEFBEEF)
        for i in range(0,99):
            self.chip.injection_analog(self.sections)
            self.chip.injection_digital(self.sections)

        self.chip.read_disable(self.sections)
        self.chip.custom_word(0xCAFECAFE)

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
    range = None

    sequence = None

    def pre_main(self):
        super().pre_main()
        self.sections = [x for x in range(16) if x not in self.chip.sections_to_mask]

        self.range  = range(1, 64)
        self.result = np.zeros((16, 64), int)

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
        for i in range(0,99):
            self.chip.injection_analog(self.sections)
            self.chip.injection_digital(self.sections)

        time.sleep(0.1)
        self.chip.read_disable(self.sections)
        self.chip.custom_word(0xCAFECAFE, iteration)

    def post_main(self, ebar=None):
        super().post_main()
        invalid = [[] for _ in range(16)]

        th = 0
        while th != 63:
            # Start of test
            results = self.elaborate_until(0xDEAFABBA)
            th = results.payload

            # Check Digital injections
            dig_injs = self.elaborate_until(0xBEEFBEEF)
            if dig_injs.word_error or dig_injs.incomplete:
                break

            for section in self.sections:
                packets = list(filter(lambda x : x.sec == section, dig_injs.data))

                if len(packets) < len(dig_injs.tps):
                    invalid[section].append(th)

            # Check Noise hits
            noisy_hits = self.elaborate_until(0xCAFECAFE)
            if noisy_hits.word_error or noisy_hits.incomplete:
                break

            for section in self.sections:
                packets = list(filter(lambda x : x.sec == section, noisy_hits.data))

                self.result[section][th] = len(packets)

            # Advance bar!
            self.ebar.update(1)

        for i,l in enumerate(invalid):
            if len(l) > 0:
                print("Lane %d missing digital injections for threshold trials: %s" % (i, str(l)))

    @customplot(('VCASN (#)', 'Section (#)'), 'Baseline distribution')
    def plot(self, show=True, saveas=None, ax=None):
        result_imshow = self.result
        for i in range(64):
            for j in range(16):
                if(result_imshow[j][i] > 200):
                    result_imshow[j][i] = 200

        image = ax.imshow(result_imshow, vmin=0, vmax=200)

        """
        for i in range(64):
            for j in range(16):
                text = ax.text(i, j, self.result[j][i],
                       ha="center", va="center", color="w")
        """
        return image

class MatrixBaselineScan(ScanTest):
    pixels = None
    th = 1
    sections = []
    axes = ["Section (#)", "VCASN (#)"]
    result = None
    range = None

    def pre_main(self):
        super().pre_main()
        self.sections = [x for x in range(16) if x not in self.chip.sections_to_mask]

        self.range  = range(1, 64)
        self.result = np.zeros((16, 64), int)

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
        for i in range(0,99):
            self.chip.injection_analog(self.sections)
            self.chip.injection_digital(self.sections)

        time.sleep(0.1)
        self.chip.read_disable(self.sections)
        self.chip.custom_word(0xCAFECAFE, iteration)

    def post_main(self, ebar=None):
        super().post_main()
        invalid = [[] for _ in range(16)]

        readout = self.readout()
        if readout == 0:
            return

        packet = None
        while not isinstance(packet, CustomWord) or packet.word != 0xDEAFABBA:
            try:
                packet = self.analysis.packets.pop(0)
            except IndexError:
                analyzed = self.readout(reset = True)
                if analyzed == 0:
                    return

        while True:
            th = packet.payload

            # Check Digital injections
            dig_injs = []
            tps = 0
            while True:
                try:
                    packet = self.analysis.packets.pop(0)
                except IndexError:
                    analyzed = self.readout(reset = True)
                    if analyzed == 0:
                        break
                    packet = self.analysis.packets.pop(0)

                if(type(packet) == PixelData):
                    dig_injs.append(packet)
                elif(type(packet) == TestPulse):
                    tps += 1
                else:
                    break

            if analyzed == 0:
                break

            for section in self.sections:
                packets = list(filter(lambda x:type(x) == PixelData and x.sec == section, dig_injs))
                num = len(packets)

                if(num < tps):
                    #raise RuntimeError("TH:%u - Section %u didn't receive the digitally injected packets." % (th, section))
                    invalid[section].append(th)

            # Go on to noise packets
            if(type(packet) != CustomWord or packet.word != 0xBEEFBEEF or packet.payload != th):
                raise RuntimeError('Expected 0xBEEFBEEF - ', str(th), '. Received: ', packet.to_string())

            noise_hits = []
            while True:
                try:
                    packet = self.analysis.packets.pop(0)
                except IndexError:
                    analyzed = self.readout(reset = True)
                    if analyzed == 0:
                        break
                    packet = self.analysis.packets.pop(0)

                if(type(packet) == PixelData):
                    noise_hits.append(packet)
                else:
                    break

            if analyzed == 0:
                break

            for section in self.sections:
                packets = list(filter(lambda x:type(x) == PixelData and x.sec == section, noise_hits))
                num = len(packets)
            
                self.result[section][th] = num


            if(type(packet) != CustomWord or packet.word != 0xCAFECAFE or packet.payload != th):
                raise RuntimeError('Expected 0xCAFECAFE - ', str(th), '. Received: ', packet.to_string())
            
            if(th > 63):
                break

            try:
                packet = self.analysis.packets.pop(0)
            except IndexError:
                analyzed = self.readout(reset = True)
                try:
                    packet = self.analysis.packets.pop(0)
                except IndexError:
                    break

            if(type(packet) != CustomWord or packet.word != 0xDEAFABBA):
                raise RuntimeError('Expected 0xDEAFABBA - ', str(th), '. Received: ', packet.to_string())

            self.ebar.update(1)

        for i,l in enumerate(invalid):
            if len(l) > 0:
                print("Lane %d missing digital injections for threshold trials: %s" % (i, str(l)))

    @customplot(('VCASN (#)', 'Section (#)'), 'Baseline distribution')
    def plot(self, show=True, saveas=None, ax=None):
        result_imshow = self.result
        for i in range(64):
            for j in range(16):
                if(result_imshow[j][i] > 200):
                    result_imshow[j][i] = 200

        image = ax.imshow(result_imshow, vmin=0, vmax=200)

        """
        for i in range(64):
            for j in range(16):
                text = ax.text(i, j, self.result[j][i],
                       ha="center", va="center", color="w")
        """
        return image
