from tqdm import tqdm
import numpy as np
import math
import time

from ..test import customplot
from ..data import ChipData, CustomWord, TestPulse
from ..sequence import Sequence
from .scan import ScanTest

class BaselineScan(ScanTest):
    pixels = None
    th = 1
    sections = []
    range = None

    def __init__(self):
        super().__init__()
        self.sections = [x for x in range(16) if x not in self.lanes_excluded]
        self.result = np.full((512, 512), np.nan)
        self.sequence.timeout = 10

        self.ctrl_phases = [self.ctrl_phase0, self.ctrl_phase1]
        self.elab_phases = [self.elab_phase0, self.elab_phase1]

    def pre_main(self):
        self.range  = range(1, 64)
        self.result = np.full((512, 512), np.nan)

        self.chip.write_gcrpar('DISABLE_SMART_READOUT', 1)

    def ctrl_phase0(self, iteration):
        self.chip.packets_reset()
        self.chip.custom_word(0xDEAFABBA, iteration)

        for section in self.sections:
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, 1)
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, iteration)
        
    def elab_phase0(self, iteration):
        ok = False
        for _ in range(3):
            # Start of test
            try:
                extracted = self.sequence.pop(0)
            except:
                self.ctrl_phase0(iteration)
                continue

            if extracted[-1] == CustomWord(message=0xDEAFABBA):
                ok = True
                break

            self.ctrl_phase0(iteration)

        if not ok:
            print("Main")
            self.sequence.dump()
            print("Sub")
            for i in self.sequence._queue:
                i.dump()
            print("Extracted")
            extracted.dump()
            raise RuntimeError("Unexpected: %s" % extracted[-1])

        th = extracted[-1].payload

    def ctrl_phase1(self, iteration):
        self.chip.packets_reset()
        self.chip.read_enable(self.sections)
        for i in range(0,99):
            self.chip.injection_analog(self.sections)
            self.chip.injection_digital(self.sections)

        time.sleep(0.2)
        self.chip.read_disable(self.sections)

    def elab_phase1(self, iteration):
        trial = 0
        masked = 0
        masked_total = 0
        smart_readouts = 0

        threshold = 10
        sub_threshold_trials = 0

        while True:
            try:
                noisy_hits = self.sequence.pop(0, tries=1)

                # If readout is complete, exit
                if noisy_hits[-1] == CustomWord(message=0xBEEFBEEF) and noisy_hits is None:
                    break
            except Exception as e:
                break

            noisy_hits_data = noisy_hits.get_data()

            self.logger.info("Checking th %d, trial %d, read %d, masked past %d, total past %d" % (iteration, trial, len(noisy_hits_data), masked, masked_total))

            # Use noisy_hits_data to mask noisy pixels
            squashed = noisy_hits.squash_data()

            self.logger.info("Processing trial %d packets were %d became %d" % (trial, len(noisy_hits_data), len(squashed)))
            self.logger.info("Reduced to %d packets" % len(noisy_hits_data))

            masked = 0
            seen_again = 0
            for data in squashed:
                slave_hitmap = data.hitmap & 0xf
                if slave_hitmap != 0:
                    self.chip.pixels_cfg(0b11, [data.sec], [data.col], [data.corepr], [0], slave_hitmap)

                master_hitmap = (data.hitmap >> 4) & 0xf
                if master_hitmap != 0:
                    self.chip.pixels_cfg(0b11, [data.sec], [data.col], [data.corepr], [1], master_hitmap)

                pixels = data.get_pixels()

                for pix in pixels:
                    if not np.isnan(self.result[pix.row][pix.col]):
                        seen_again += 1
                        continue

                    # First time we see this pixel. Mark its baseline and mask it
                    self.result[pix.row][pix.col] = iteration
                    masked += 1

                self.logger.info("Masked @ %s" % data)

            masked_total += masked
            self.pbar.update(masked)

            self.logger.info("Masked %d seen again %d" % (masked, seen_again))

            # Avoid being stuck on barely-noisy pixels. Wiser to decrease the threshold,
            # be a little less precise, but faster
            if masked < threshold:
                self.logger.info("Increasing subthreshold from %d because masked are %d" % (sub_threshold_trials, masked))
                sub_threshold_trials += 1
            else:
                sub_threshold_trials = 0

            if sub_threshold_trials > 10:
                break

            # Loop again to check if there are more noisy pixels
            trial += 1
            self.ctrl_phase1(iteration + (trial << 6))

        self.logger.info("Passing w/ %d sub threshold trials out of %d" % (sub_threshold_trials, trial))

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
