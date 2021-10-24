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
        self.sections = [x for x in range(16) if x not in self.lanes_excluded]

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
    invalid = []

    def __init__(self):
        super().__init__()
        self.ctrl_phases = [self.ctrl_phase0, self.ctrl_phase1]
        self.elab_phases = [self.elab_phase0, self.elab_phase1]

    def pre_main(self):
        super().pre_main()
        self.sections = [x for x in range(16) if x not in self.lanes_excluded]

        self.range  = range(1, 64)
        self.result = np.zeros((16, 64), int)
        self.invalid = [0] * 16

    def ctrl_phase0(self, iteration):
        self.chip.custom_word(0xDEAFABBA, iteration)

        for section in self.sections:
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, 1)
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, iteration)
        
        self.chip.read_enable(self.sections)
        self.chip.injection_digital(self.sections)
        self.chip.send_tp(2)
        time.sleep(0.1)
        self.chip.custom_word(0xBEEFBEEF, iteration)

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

    def ctrl_phase1(self, iteration):
        for i in range(0,99):
            self.chip.injection_analog(self.sections)
            self.chip.injection_digital(self.sections)

        time.sleep(0.1)
        self.chip.read_disable(self.sections)
        self.chip.custom_word(0xCAFECAFE, iteration)

    def elab_phase1(self, iteration):
        # Check Noise hits
        noisy_hits = self.elaborate_until(0xCAFECAFE)
        if noisy_hits.message_error or noisy_hits.incomplete:
            raise ValueError()

        for section in self.sections:
            packets = list(filter(lambda x : x.sec == section, noisy_hits.data))

            self.result[section][iteration] = len(packets)

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
    range = None

    sequence = None

    def __init__(self):
        super().__init__()
        self.sections = [x for x in range(16) if x not in self.lanes_excluded]
        self.result = np.full((512, 512), np.nan)

        self.ctrl_phases = [self.ctrl_phase0, self.ctrl_phase1]
        self.elab_phases = [self.elab_phase0, self.elab_phase1]

    def pre_main(self):
        self.range  = range(1, 64)
        self.result = np.full((512, 512), np.nan)

        self.chip.write_gcrpar('DISABLE_SMART_READOUT', 1)
        self.chip.pixels_cfg(0b01, 0xffff, 0xffff, None, None, 0xf)

    def ctrl_phase0(self, iteration):
        self.chip.custom_word(0xDEAFABBA, iteration)

        for section in self.sections:
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, 1)
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, iteration)
        
        """
        self.chip.read_enable(self.sections)
        self.chip.injection_digital(self.sections)
        self.chip.send_tp(2)
        time.sleep(0.1)
        """
        self.chip.custom_word(0xBEEFBEEF, iteration)

    def elab_phase0(self, iteration):
        # Start of test
        results = self.elaborate_until(0xDEAFABBA)
        th = results.payload

        # Check Digital injections
        dig_injs = self.elaborate_until(0xBEEFBEEF)
        """
        if dig_injs.message_error or dig_injs.incomplete:
            raise ValueError()

        for section in self.sections:
            packets = list(filter(lambda x : x.sec == section, dig_injs.data))

            if len(packets) < len(dig_injs.tps):
                self.invalid[section].append(th)
        """

    def ctrl_phase1(self, iteration):
        self.chip.read_enable(self.sections)
        for i in range(0,99):
            self.chip.injection_analog(self.sections)
            self.chip.injection_digital(self.sections)

        time.sleep(0.1)
        self.chip.read_disable(self.sections)
        self.chip.custom_word(0xCAFECAFE, iteration)

    def elab_phase1(self, iteration):
        trial = 0
        masked = 0
        masked_total = 0
        already = 0
        smart_readouts = 0

        while True:
            # Check Noise hits
            noisy_hits = self.elaborate_until(0xCAFECAFE, (iteration + (trial << 6)), timeout=2, tries=2)
            self.logger.info("Checking th %d, trial %d, read %d, masked past %d, already past %d, total past %d" % (iteration, trial, len(noisy_hits.data), masked, already, masked_total))

            # If we received no data, it means there are no more noisy pixels
            if len(noisy_hits.data) == 0 and not noisy_hits.incomplete:
                self.logger.info("Done!")
                break

            already = 0

            # Otherwise, use noisy_hits.data to mask noisy pixels

            smart_readouts += noisy_hits.merge_data(check=False)
            self.logger.info("Reduced to %d packets" % len(noisy_hits.data))

            masked = 0
            for data in noisy_hits.data:
                slave_hitmap = data.hitmap & 0xf
                if slave_hitmap != 0:
                    self.chip.pixels_cfg(0b11, [data.sec], [data.col], [data.corepr], [0], slave_hitmap)

                master_hitmap = (data.hitmap >> 4) & 0xf
                if master_hitmap != 0:
                    self.chip.pixels_cfg(0b11, [data.sec], [data.col], [data.corepr], [1], master_hitmap)

                pixels = data.get_pixels()

                for pix in pixels:
                    if not np.isnan(self.result[pix.row][pix.col]):
                        continue

                    # First time we see this pixel. Mark its baseline and mask it
                    self.result[pix.row][pix.col] = iteration
                    masked += 1

                self.logger.info("Masked @ %s" % data)

            masked_total += masked
            self.pbar.update(masked)

            silence = self.check_stability(100)
            if not silence:
                raise RuntimeError("Unable to shut the chip up!")

            # Loop again to check if there are more noisy pixels
            trial += 1
            self.ctrl_phase1(iteration + (trial << 6))

        self.logger.warning("\n\nSmart readouts: %d\n\n" % smart_readouts)

    def loop_reactive(self):
        self.sections = [x for x in range(16) if x not in self.lanes_excluded]
        max = 512*32*len(self.sections)
        with tqdm(total=max, desc='Masked pixels') as self.pbar:
            super().loop_reactive()


    @customplot(('Row (#)', 'Col (#)'), 'Baseline distribution')
    def plot(self, show=True, saveas=None, ax=None):
        image = ax.imshow(self.result, interpolation='none')

        """
        for i in range(64):
            for j in range(16):
                text = ax.text(i, j, self.result[j][i],
                       ha="center", va="center", color="w")
        """
        return image
