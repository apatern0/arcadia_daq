import os, sys, argparse, time, logging, math
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import threading
from tqdm import tqdm

from Daq import *
from DataAnalysis import *

matplotlib.interactive(True)

class Sparse(dict):

    def __init__(self,rows=0,cols=0):
        super().__init__()
        self.rows = rows
        self.cols = cols

    def __indexToRanges(self,rowIndex,colIndex):
        scalar = isinstance(rowIndex,int) and isinstance(colIndex,int)
        if isinstance(rowIndex,slice):
            rowRange = range(*rowIndex.indices(self.rows))
        else:
            rowRange = range(rowIndex,rowIndex+1)
        if isinstance(colIndex,slice):
            colRange = range(*colIndex.indices(self.cols))
        else:
            colRange = range(colIndex,colIndex+1)
        return rowRange,colRange,scalar

    def __getitem__(self,indexes):
        row,col = indexes
        rowRange,colRange,scalar = self.__indexToRanges(row,col)
        if scalar: return super().__getitem__((row,col))
        return [v for (r,c),v in self.items() if r in rowRange and c in colRange]

    def __setitem__(self,index,value):
        row,col=index
        rowRange,colRange,scalar = self.__indexToRanges(row,col)
        if scalar:
            self.rows = max(self.rows,row+1)
            self.cols = max(self.cols,col+1)
            return super().__setitem__((row,col),value)

class Test:
    logger = None
    daq = None
    analysis = None

    def __init__(self):
        self.daq = Daq()
        self.analysis = DataAnalysis()
        self.logger = logging.getLogger(__name__)

        # Initialize Daq
        self.daq.init_connection("connection.xml")
        self.daq.logger = self.logger

        # Initialize DataAnalysis
        self.analysis = DataAnalysis()
        self.analysis.logger = self.logger

        # Initialize Logger
        ch = logging.StreamHandler()
        formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
        ch.setFormatter(formatter)
        ch.setLevel(logging.WARNING)
        self.logger.addHandler(ch)

    def set_timestamp_resolution(self, res_s):
        fpga_clock_hz = 80E6

        fpga_clock_divider = int(fpga_clock_hz * res_s)
        self.analysis.ts_hz = 1/res_s
        self.daq.set_timestamp_period(fpga_clock_divider-1)

    # Global
    def chip_init(self):
        self.daq.enable_readout(0)
        self.daq.hard_reset()
        self.daq.reset_subsystem('chip', 1)
        self.daq.reset_subsystem('chip', 2)
        self.daq.write_gcr(0, 0xFF30)
        self.daq.reset_subsystem('per', 1)
        self.daq.reset_subsystem('per', 2)
        self.daq.injection_digital()
        self.daq.injection_enable()
        self.daq.clock_enable()
        self.daq.read_enable()
        self.daq.force_injection()
        self.daq.force_nomask()
        self.daq.reset_subsystem('per', 1)
        self.daq.reset_subsystem('per', 2)
        self.daq.pixels_mask()
        self.daq.sync_mode()
        time.sleep(1)
        synced = self.daq.sync()
        self.daq.normal_mode()
        self.daq.enable_readout(0xffff)

        return synced

    def timestamp_sync(self):
        self.daq.pixels_mask()
        self.daq.noforce_injection()
        self.daq.noforce_nomask()

        self.daq.set_timestamp_delta(0)
        self.daq.enable_readout(0xffff)
        self.daq.pixels_cfg(0b01, 0x000f, [0], [0], [0], 0xF)

        self.analysis.skip()
        self.daq.send_tp(1)

        self.analysis.cleanup()
        self.analysis.analyze()

        tp = filter(lambda x:(type(x) == TestPulse), self.analysis.packets)
        data = filter(lambda x:(type(x) == PixelData), self.analysis.packets)

        try:
            tp = next(tp)
        except StopIteration:
            self.logger.fatal("Sync procedure returned no Test Pulses. Check chip status. Dump:")
            self.analysis.dump()
            print("\n")
            raise RuntimeError("Check previous CRITICAL error")

        try:
            data = next(data)
        except StopIteration:
            self.logger.fatal("Sync procedure returned no Data Packets. Check chip status. Dump:")
            self.analysis.dump()
            print("\n")
            raise RuntimeError("Check previous CRITICAL error")

        ts_tp = tp.ts
        ts_fpga = data.ts_fpga
        ts_fpga_lsb = (ts_fpga & 0xff)
        ts_chip = data.ts
        if(ts_fpga_lsb < ts_chip):
            ts_fpga_lsb = (1<<8) | ts_fpga_lsb

        ts_delta = ts_fpga_lsb - ts_chip - 1

        self.logger.info("Test Pulse timestamp: 0x%x" % ts_tp)
        self.logger.info("Data timestamp: 0x%x (FPGA) 0x%x (CHIP)" % (ts_fpga, ts_chip))

        self.logger.info("Chip event anticipates fpga event, thus ts_fpga must be decreased to reach ts_chip")
        self.logger.info("ts_fpga - X = ts_chip -> X = ts_fpga - ts_chip = 0x%x" % (ts_delta))

        self.logger.info("New Data timestamp: 0x%x (FPGA) 0x%x (CHIP)" % (ts_fpga-ts_delta, ts_chip))

        self.daq.set_timestamp_delta(ts_delta)

    def initialize(self):
        for i in range(4):
            ok = True
            self.chip_init()
            try:
                self.timestamp_sync()
            except RuntimeError:
                ok = False

            if(ok):
                return
        
        raise RuntimeError('Unable to receive data from the chip!')

class ScanTest(Test):
    range = []
    result = []
    axes = ["time (s)", "voltage (mV)"]
    title = "Scan Test"

    def pre_main(self):
        return

    def pre_loop(self):
        return

    def loop_body(self, iteration):
        return

    def post_loop(self):
        return

    def post_main(self):
        return

    def loop(self):
        self.pre_main()

        with tqdm(total=len(self.range), desc='Acquisition') as bar:
            for i in self.range:
                self.pre_loop()
                self.loop_body(i)
                self.post_loop()
                bar.update(1)
        
        self.post_main()

    def __init__(self):
        super().__init__()
        self.range = np.arange(0.0, 2.0, 0.01)
        self.result = 1 + np.sin(2 * np.pi * self.range)

    def plot(self, saveas=None):
        fig, ax = plt.subplots()
        ax.plot(self.range, self.result)
        ax.plot(self.range, self.result, 'o')

        ax.set(xlabel=self.axes[0], ylabel=self.axes[1], title=self.title)
        ax.grid()

        plt.show()

        if(saveas != None):
            fig.savefig(saveas)

class BaselineScan(ScanTest):
    th_min = [1]
    th_max = [63]
    pixels = None
    th = [1]
    sections = []

    def pre_main(self):
        self.sections = list(range(2,6)) + list(range(7,15))
        """
        self.sections = []
        for i in pixels:
            section = math.floor(pixel[0]/32)
            if(section not in self.sections):
                self.sections.append(section)
        """

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
        for i, section in enumerate(self.sections):
            self.result[i] = self.th[section]

class FullBaselineScan(ScanTest):
    pixels = None
    th = 1
    sections = []
    axes = ["Section (#)", "VCASN (#)"]
    result = None

    def pre_main(self):
        self.sections = list(range(2,6)) + list(range(7,15))
        """
        self.sections = []
        for i in pixels:
            section = math.floor(pixel[0]/32)
            if(section not in self.sections):
                self.sections.append(section)
        """

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
        self.analysis.cleanup()
        self.analysis.analyze()

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
                    raise RuntimeError("TH:%u - Section %u didn't receive the digitally injected packets." % (th, section))

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

    def plot(self, saveas=None):
        fig, ax = plt.subplots()

        result_imshow = self.result
        for i in range(64):
            for j in range(16):
                if(result_imshow[j][i] > 200):
                    result_imshow[j][i] = 200

        ax.imshow(result_imshow)

        ax.set(xlabel=self.axes[1], ylabel=self.axes[0], title=self.title)

        for i in range(64):
            for j in range(16):
                text = ax.text(i, j, self.result[j][i],
                       ha="center", va="center", color="w")

        fig.tight_layout()
        plt.show()

        if(saveas != None):
            fig.savefig(saveas)

class ThresholdScan(ScanTest):
    pixels = {}
    th = 1
    vcal_lo = 0
    vcal_hi = 8
    sections = []
    axes = ["Section (#)", "VCASN (#)"]

    def pre_main(self):
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
                p.injected = [0] * 64
                p.noise    = [0] * 64
                self.pixels[p.row*512+p.col] = p
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
        print("Now analysing results...")
        self.analysis.cleanup()
        self.analysis.analyze()

        iterator = iter(self.analysis.packets)
        packet = next(p for p in iterator if type(p) == CustomWord and p.word == 0xDEAFABBA);
        counter = 0
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
                        raise RuntimeError("TH:%u - Section %u didn't receive the digitally injected packets." % (th, section))

                #print("\t\tElapsed for digital: %3d (%d packets)" % ((time.time() - ts)*1000, c))

                # Go on to injected packets
                if(type(packet) != CustomWord or packet.word != 0xBEEFBEEF or packet.payload != th):
                    raise RuntimeError('Unexpected packet here %s ' % packet.to_string())

                inj_hits = []
                ts = time.time()
                c=0
                while True:
                    try:
                        packet = next(iterator); counter += 1
                        if(type(packet) == PixelData):
                            for pix in packet.pixels:
                                try:
                                    self.pixels[pix.row*512+pix.col].injected[th] += 1
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
                                    self.pixels[pix.row*512+pix.col].noise[th] += 1
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

    def plot(self, saveas=None):
        for counter, pixel in enumerate(self.pixels.values()):

            fig, ax = plt.subplots()

            inj = pixel.injected
            ax.plot(self.range, inj, '--bo', label='Test Pulses')

            noise = pixel.noise
            total = [x + y for x, y in zip(inj, noise)]
            ax.plot(self.range, total, '--ro', label='Total')

            ax.set(xlabel=self.axes[0], ylabel=self.axes[1], title=self.title)
            ax.grid()

            ax.legend()

            if(saveas != None):
                fig.savefig("%s_%d_%d.pdf" % (saveas, pixel.row, pixel.col), bbox_inches='tight')

            if(counter < 5):
                plt.show()
