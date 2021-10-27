from tqdm import tqdm
import numpy as np
import math
import time

from ..test import customplot
from ..analysis import ChipData, CustomWord, TestPulse, SubSequence
from .scan import ScanTest

class BaselineScan(ScanTest):
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
        extracted = self.extract()
        if extracted != CustomWord(message=0xDEAFABBA):
            raise RuntimeError("Unexpected SubSequence: %s" % extracted)

        th = extracted.payload

        # Check Digital injections
        extracted = self.extract()
        if isinstance(extracted, SubSequence):
            dig_injs = extracted

            extracted = self.extract()
        else:
            dig_injs = SubSequence()

        if extracted != CustomWord(message=0xBEEFBEEF):
            raise RuntimeError("Unexpected word: %s" % extracted)

    def ctrl_phase1(self, iteration):
        self.chip.read_enable(self.sections)
        for i in range(0,99):
            self.chip.injection_analog(self.sections)
            self.chip.injection_digital(self.sections)

        time.sleep(0.1)
        self.chip.read_disable(self.sections)

    def elab_phase1(self, iteration):
        trial = 0
        masked = 0
        masked_total = 0
        smart_readouts = 0

        while True:
            extracted = self.extract(timeout=2, type='SubSequence')
            if isinstance(extracted, SubSequence):
                noisy_hits = extracted
            else:
                break

            self.logger.info("Checking th %d, trial %d, read %d, masked past %d, total past %d" % (iteration, trial, len(noisy_hits.data), masked, masked_total))

            # Use noisy_hits.data to mask noisy pixels
            smart_readouts += noisy_hits.squash_data(fail_on_smartreadout=False)
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
        total = 512*32*len(self.sections)
        with tqdm(total=total, desc='Masked pixels') as self.pbar:
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
