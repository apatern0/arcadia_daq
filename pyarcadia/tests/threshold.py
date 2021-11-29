import math
import time
import numpy as np
import scipy.optimize
import scipy.special
from matplotlib import pyplot as plt, cm, colors

from ..daq import Chip
from ..data import CustomWord, Pixel, FPGAData
from .scan import ScanTest

class ThresholdScan(ScanTest):
    pixels = {}
    th = 1
    sections = []
    axes = ["VCASN (#)", "Hits (#)"]
    injections = 200

    tp_on = 10
    tp_off = 10

    def __init__(self, log=False):
        super().__init__()

        self.title = 'Threshold Scan'
        self.log = log

        self.maxtime = 2
        self.range = range(0, 64)

        self.packets_count = 0

        self.phases = {
            0xDEAFABBA : [self.ctrl_phase0, self.elab_phase0],
            0xBEEFBEEF : [self.ctrl_phase1, self.elab_phase1],
            0xDEADBEEF : [self.ctrl_phase2, self.elab_phase2],
            0xBEEFDEAD : [self.ctrl_phase3, self.elab_phase3],
            0xCAFECAFE : [self.ctrl_phase4, self.elab_phase4]
        }

    def pre_main(self):
        super().pre_main()

        self.chip.injection_digital(0xffff)
        self.chip.read_enable(0xffff)
        self.chip.clock_enable(0xffff)
        self.chip.injection_enable(0xffff)

        self.chip.packets_reset()
        self.sequence.autoread_start()
        self.chip.send_tp(1, self.tp_on, self.tp_off)
        self.chip.packets_idle_wait()
        self.chip.custom_word(0xDEADDEAD)

        test = None
        while True:
            test = self.sequence.pop(0, log=self.log)
            if test[-1] == CustomWord(message=0xDEADDEAD):
                break

        self.pixels = {}

        per_sec = [0] * 16

        print("Starting scan on the following pixels: [", end="")
        counter = 0
        for packet in test.get_data():
            per_sec[packet.ser] += 1

            for p in packet.get_pixels():
                p.injected_hits = [np.nan for _ in self.range]
                p.injected_fe_hits = [np.nan for _ in self.range]
                p.noise_hits = [np.nan for _ in self.range]
                p.saturation_hits = [np.nan for _ in self.range]
                self.pixels[(p.row, p.col)] = p
                print("(%d, %d)" % (p.row, p.col), end="")
                counter += 1

            if packet.sec not in self.sections:
                self.sections.append(packet.sec)

        print("]\nFor a total of %d pixels" % counter)

        if counter == 0:
            raise ValueError("No pixels have been selected!")

        ts_tp = test.get_tps()[0].ts
        ts_data = test.get_data()[-1].ts_fpga
        print("Total measured readout time is %d us" % ((ts_data - ts_tp)*Chip.ts_us))

        packet_time = (2**self.chip.read_gcrpar('READOUT_CLK_DIVIDER'))*20/self.fpga.clock_hz
        injection_time = (self.tp_on+self.tp_off)*1E-6

        self.maxtime = max(packet_time, injection_time) * max(per_sec) * self.injections

        print("Expecting a maximum of %d packets per section. Max readout time should be: %d us" % (max(per_sec), self.maxtime*1E6))

        print("Changing biases on sections: %s" % self.sections)

        FPGAData.packets_count = 0
        self.chip.fifo_overflow_counter_reset()

    def post_main(self):
        self.sequence.autoread = False

    def ctrl_phase0(self, iteration):
        for section in self.sections:
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, 1)
            self.chip.write_gcrpar('BIAS%1d_VCASN' % section, iteration)

        self.chip.custom_word(0xDEAFABBA, iteration)

    def ctrl_phase1(self, iteration):
        self.chip.read_enable(self.sections)
        self.chip.injection_digital(self.sections)
        self.chip.send_tp(2, self.tp_on, self.tp_off)
        self.chip.packets_idle_wait(expected=self.maxtime, timeout=10*self.maxtime)
        self.chip.custom_word(0xBEEFBEEF, iteration)

    def ctrl_phase2(self, iteration):
        self.chip.injection_analog(self.sections)
        self.chip.read_enable(self.sections)
        self.chip.send_tp(self.injections, self.tp_on, self.tp_off)
        self.chip.packets_idle_wait(expected=self.maxtime, timeout=10*self.maxtime)
        self.chip.custom_word(0xDEADBEEF, iteration)

    def ctrl_phase3(self, iteration):
        self.chip.read_enable(self.sections)
        time.sleep(1E-3)
        self.chip.read_disable()
        self.chip.packets_idle_wait(expected=self.maxtime, timeout=10*self.maxtime)
        self.chip.custom_word(0xBEEFDEAD, iteration)

    def ctrl_phase4(self, iteration):
        self.chip.read_enable(self.sections)
        for _ in range(self.injections):
            self.chip.injection_analog(self.sections)
            self.chip.injection_digital(self.sections)

        self.chip.packets_idle_wait(timeout=0.5)
        self.chip.custom_word(0xCAFECAFE, iteration)

    def elab_phase0(self, subseq):
        pass

    def elab_phase1(self, subseq):
        dig_injs_data = subseq.get_data()
        self.packets_count += len(dig_injs_data)
        dig_injs_tps = subseq.get_tps()

        tps = len(dig_injs_tps)

        for section in self.sections:
            packets = list(filter(lambda x: x.sec == section, dig_injs_data))

            if len(packets) < tps:
                self.logger.warning("Section %d returned %d tps instead of %d", section, len(packets), tps)

    def elab_phase2(self, subseq):
        analog_hits_tps = subseq.get_tps()
        tps = len(analog_hits_tps)
        th = subseq[-1].payload
        data = subseq.get_data()

        for pixel in self.pixels:
            self.pixels[pixel].injected_fe_hits[th] = 0
            self.pixels[pixel].injected_hits[th] = 0

        self.packets_count += len(data)
        subseq.filter_double_injections()
        for packet in data:
            for pix in packet.get_pixels():
                if (pix.row, pix.col) not in self.pixels:
                    self.logger.info("Unexpected pixel in this run: %s", pix)
                else:
                    if packet.tag == 'falling edge':
                        self.pixels[(pix.row, pix.col)].injected_fe_hits[th] += 1
                    else:
                        self.pixels[(pix.row, pix.col)].injected_hits[th] += 1

    def elab_phase3(self, subseq):
        noisy_hits_data = subseq.get_data()
        self.packets_count += len(noisy_hits_data)
        th = subseq[-1].payload

        for pixel in self.pixels:
            self.pixels[pixel].noise_hits[th] = 0

        for p in noisy_hits_data:
            for pix in p.get_pixels():
                try:
                    self.pixels[(pix.row, pix.col)].noise_hits[th] += 1
                except KeyError:
                    self.logger.info("Unexpected pixel in this run: %s", pix)

    def elab_phase4(self, subseq):
        noisy_hits_data = subseq.get_data()
        self.packets_count += len(noisy_hits_data)
        th = subseq[-1].payload

        for pixel in self.pixels:
            self.pixels[pixel].saturation_hits[th] = 0

        for p in noisy_hits_data:
            for pix in p.get_pixels():
                try:
                    self.pixels[(pix.row, pix.col)].saturation_hits[th] += 1
                except KeyError:
                    self.logger.info("Unexpected pixel in this run: %s", pix)

    @staticmethod
    def _fit(x, mu, sigma):
        return 0.5*(1+scipy.special.erf((x-mu)/(sigma*np.sqrt(2))))

    @staticmethod
    def find_baseline(x, noise, saturation):
        avg = 0
        total = 0
        for index, counts in enumerate(noise):
            avg += x[index] * counts
            total += counts

        if total > 0:
            avg = avg/total
            return avg

        """
        try:
            s_opt, s_cov = scipy.optimize.curve_fit(self._fit, list(range(0,len(saturation_normalized))), saturation_normalized)
        except RuntimeError:
            return np.nan
        """

        threshold = 0.1*max(saturation)
        for index, counts in enumerate(saturation):
            if counts >= threshold:
                return x[index]

        return np.nan

    def scurve_fit(self, pixels=None):
        if pixels is None:
            pixels = list(self.pixels.keys())

        for pixel_idx in pixels:
            pixel = self.pixels[pixel_idx]

            points = []
            data = []
            for vcasn in self.range:
                if pixel.injected_hits[vcasn] == np.nan:
                    continue

                tmp = min(pixel.injected_hits[vcasn]/self.injections, 1) if pixel.saturation_hits[vcasn] <= self.injections/4 else 1

                if math.isnan(tmp) or math.isinf(tmp):
                    points.append(vcasn)
                    data.append(tmp)

            try:
                s_opt, s_cov = scipy.optimize.curve_fit(self._fit, points, data)
            except (RuntimeError, ValueError):
                pixel.baseline = np.nan
                pixel.gain = np.nan
                pixel.noise = np.nan

                pixel.fit_mu = np.nan
                pixel.fit_mu_err = np.inf
                pixel.fit_sigma = np.nan
                pixel.fit_sigma_err = np.inf
                continue

            stderrs = np.sqrt(np.diag(s_cov))

            vcal_hi = self.gcrs['BIAS{}_VCAL_HI'.format(pixel.get_sec())]
            vcal_lo = self.gcrs['BIAS{}_VCAL_LO'.format(pixel.get_sec())]
            q_in = ((595+35*vcal_hi)-(560*vcal_lo))*1.1625/1000

            pixel.baseline = 5*self.find_baseline(self.range, pixel.noise_hits, pixel.saturation_hits) # mV
            pixel.gain = 5*(pixel.baseline - s_opt[0])/q_in # mV/fC
            pixel.noise = 5*s_opt[1] # mV

            pixel.fit_mu = s_opt[0]
            pixel.fit_mu_err = stderrs[0]
            pixel.fit_sigma = s_opt[1]
            pixel.fit_sigma_err = stderrs[1]

    def _plot_points(self, fig, ax, **kwargs):
        inj = self.pixels[kwargs['pix']].injected_hits
        ax.plot(self.range, inj, '--bo', label='Test Pulse hits')

        inj_fe = self.pixels[kwargs['pix']].injected_fe_hits
        ax.plot(self.range, inj_fe, '--co', label='Falling edge hits')

        noise = self.pixels[kwargs['pix']].noise_hits
        ax.plot(self.range, noise, '--ro', label='Noise hits')

        saturation = self.pixels[kwargs['pix']].saturation_hits
        ax.plot(self.range, saturation, '--go', label='Saturation hits')

        ax.set_ylim(bottom=0, top=4*self.injections)
        #total = [x + y for x, y in zip(inj, noise)]

    def plot_single(self, show=True, saveas=None, pix=None, notes=None):
        if pix is None or pix not in self.pixels:
            return

        notes = "" if notes is None else notes
        notes = self._plot_notes() + notes

        pix_saveas = None if saveas is None else f"{saveas}_{pix[0]}_{pix[1]}"
        self.plot_points(show=show, saveas=pix_saveas, title=f" for pixel [{pix[0]}][{pix[1]}]", notes=notes, pix=pix)

        curve = [i*self.injections for i in self._fit(self.range, self.pixels[pix].fit_mu, self.pixels[pix].fit_sigma)]
        plt.plot(self.range, curve, '-k', label='Fit')

    def plot(self, show=True, saveas=None):
        for pix in self.pixels:
            self.plot_single(show, saveas, pix=pix)

        self.plot_heatmaps()

    def _plot_notes(self):
        return "Injections: {}, Noise hits window: 500ms, Saturation checks: {}\n".format(self.injections, self.injections) + \
                "Test Pulse rising edge: 10us, Test Pulse falling edge: 10us";

    @staticmethod
    def _tight_axes(pixels):
        xes = list(set([x[1] for x in pixels]))
        yes = list(set([x[0] for x in pixels]))

        xes.sort()
        yes.sort()

        # Empty ticks for the spaces
        for ax in (xes, yes):
            old = np.nan
            new = []
            for idx, x in enumerate(ax):
                if idx != 0 and x != old-1:
                    new.append('')

                new.append(x)
                old = x

            ax = new

        print(xes)
        print(yes)

        return (xes, yes)

    def plot_heatmaps(self, show=True, saveas=None, notes=None, pixels=None):
        pixels = self.pixels.keys() if pixels is None else pixels
        xes, yes = self._tight_axes(pixels)

        hm_baseline = np.full((len(yes), len(xes)), np.nan)
        hm_gain = np.full((len(yes), len(xes)), np.nan)
        hm_gain_err = np.full((len(yes), len(xes)), np.nan)
        hm_noise = np.full((len(yes), len(xes)), np.nan)
        hm_noise_err = np.full((len(yes), len(xes)), np.nan)

        skipped = 0
        for pix in pixels:
            p = self.pixels[pix]
            if 'baseline' not in p.__dict__:
                self.scurve_fit([pix])

            if p.fit_mu_err > 5 or p.fit_sigma_err > 5:
                skipped += 1
                continue

            hm_baseline[yes.index(pix[0]), xes.index(pix[1])] = p.baseline
            hm_gain[yes.index(pix[0]), xes.index(pix[1])] = p.gain
            hm_gain_err[yes.index(pix[0]), xes.index(pix[1])] = p.fit_mu_err
            hm_noise[yes.index(pix[0]), xes.index(pix[1])] = p.noise
            hm_noise_err[yes.index(pix[0]), xes.index(pix[1])] = p.fit_sigma_err

        print("Skipped %d pixels with errors > 5" % skipped)

        notes = self._plot_notes() + ("" if notes is None else notes)

        # Baseline
        fig, ax1 = plt.subplots()
        img = ax1.imshow(hm_baseline, interpolation='none')
        plt.colorbar(img, orientation='horizontal', ax=ax1)
        self._plot_footer(fig, show, saveas, 'Baseline map', notes)

        # Gain
        fig, (ax1, ax2) = plt.subplots(1, 2, sharex=True, sharey=True)
        img = ax1.imshow(hm_gain, interpolation='none')
        plt.colorbar(img, orientation='horizontal', ax=ax1)
        img = ax2.imshow(hm_gain_err, interpolation='none')
        plt.colorbar(img, orientation='horizontal', ax=ax2)
        self._plot_footer(fig, show, saveas, 'Gain map', notes)

        # Noise
        fig, (ax1, ax2) = plt.subplots(1, 2, sharex=True, sharey=True)
        img = ax1.imshow(hm_noise, interpolation='none')
        plt.colorbar(img, orientation='horizontal', ax=ax1)
        img = ax2.imshow(hm_noise_err, interpolation='none')
        plt.colorbar(img, orientation='horizontal', ax=ax2)
        self._plot_footer(fig, show, saveas, 'Noise map', notes)

    def plot_histograms(self, show=True, saveas=None, notes=None, sections=None):
        sections = list(range(16)) if sections is None else sections
        if isinstance(sections, int):
            sections = [sections]

        length = len(sections)
        x_subplots = math.ceil(math.sqrt(length))
        y_subplots = math.ceil(length/x_subplots)

        pixels_per_sec = [[] for _ in range(16)]
        for pixel in self.pixels:
            pixels_per_sec[self.pixels[pixel].get_sec()].append(self.pixels[pixel])

        fig, axes = plt.subplots(y_subplots, x_subplots)
        for sec in sections:
            baselines = [int(pixel.baseline) for pixel in pixels_per_sec[sec]]
            if len(baselines) == 0:
                continue

            b_min = min(baselines)
            b_max = max(baselines)
            baseline_bins = [len([i for i in baselines if i == x]) for x in range(b_min, b_max+1)]
            axes[y_subplots-1-math.floor(sec/x_subplots)][sec%x_subplots].hist(baseline_bins, bins=(b_max-b_min))

    def _run(self):
        self.loop_parallel()

        self.scurve_fit()

    def serialize(self):
        listed = []
        listed.append(self.injections)

        for pixel in self.pixels:
            tmp = []
            tmp.append(pixel[0])
            tmp.append(pixel[1])
            tmp.append(self.pixels[pixel].injected_hits)
            tmp.append(self.pixels[pixel].noise_hits)
            tmp.append(self.pixels[pixel].saturation_hits)
            tmp.append(self.pixels[pixel].injected_fe_hits)

            listed.append(tmp)

        return listed

    def deserialize(self, serialized):
        self.injections = serialized.pop(0)

        for line in serialized:
            p = Pixel(line[0], line[1])
            p.injected_hits = line[2]
            p.noise_hits = line[3]
            p.saturation_hits = line[4]
            p.injected_fe_hits = line[5]

            self.pixels[(line[0], line[1])] = p
