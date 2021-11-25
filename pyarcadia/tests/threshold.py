import math
import time
import numpy as np
import scipy.optimize
import scipy.special
from matplotlib import pyplot as plt, cm, colors

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

    packets_count = 0

    def __init__(self, log=False):
        super().__init__()

        self.log = log

        self.title = 'Threshold Scan'
        self.xlabel = 'VCASN (#)'
        self.ylabel = 'Hits (#)'

        self.maxwait = 2
        self.range = range(0, 64)

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

        print("Starting scan on the following pixels:")
        counter = 0
        for packet in test.get_data():
            per_sec[packet.ser] += 1

            for p in packet.get_pixels():
                p.injected_hits = [0] * 64
                p.injected_fe_hits = [0] * 64
                p.noise_hits = [0] * 64
                p.saturation_hits = [0] * 64
                self.pixels[(p.row, p.col)] = p
                print("\t%3d) %s" % (counter, p))
                counter += 1

            if packet.sec not in self.sections:
                self.sections.append(packet.sec)

        if counter == 0:
            raise ValueError("No pixels have been selected!")

        ts_tp = test.get_tps()[0].ts
        ts_data = test.get_data()[-1].ts_fpga
        print("Total measured readout time is %d us" % ((ts_data - ts_tp)*self.chip.ts_us))
    
        packet_time = (2**self.chip.read_gcrpar('READOUT_CLK_DIVIDER'))*20/self.fpga.clock_hz
        injection_time = (self.tp_on+self.tp_off)*1E-6

        self.maxtime = max(packet_time, injection_time) * max(per_sec) * self.injections

        print("Expecting a maximum of %d packets per section. Max readout time should be: %d us" % (max(per_sec), self.maxtime*1E6))

        print("Changing biases on sections: %s" % self.sections)

        FPGAData.packets_count = 0
        self.chip.fifo_overflow_counter_reset()

    def post_main(self):
        self.autostart = False

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
            packets = list(filter(lambda x : x.sec == section, dig_injs_data))

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
                    self.logger.warning("Unexpected pixel in this run: %s", pix)

    @staticmethod
    def _fit(x, mu, sigma):
        return 0.5*(1+scipy.special.erf((x-mu)/(sigma*np.sqrt(2))))

    @staticmethod
    def find_baseline(x, y):
        #return x[y.index(max(y))]

        avg = 0
        for index, counts in enumerate(y):
            avg += x[index] * counts

        avg = avg/sum(x)
        return avg

    def scurve_fit(self, pixels=None):
        if pixels is None:
            pixels = list(self.pixels.keys())

        for pixel_idx in pixels:
            pixel = self.pixels[pixel_idx]

            data_normalized = [x/self.injections for x in pixel.injected_hits]
            # Correct for saturation
            for vcasn, count in enumerate(pixel.saturation_hits):
                if count > self.injections/4:
                    data_normalized[vcasn] = 1

            s_opt, s_cov = scipy.optimize.curve_fit(self._fit, self.range, data_normalized)
            stderrs = np.sqrt(np.diag(s_cov))

            vcal_hi = self.gcrs['BIAS{}_VCAL_HI'.format(pixel.get_sec())]
            vcal_lo = self.gcrs['BIAS{}_VCAL_LO'.format(pixel.get_sec())]
            q_in = ((595+35*vcal_hi)-(560*vcal_lo))*1.1625/1000

            pixel.baseline = 5*self.find_baseline(self.range, pixel.noise_hits) # mV
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

    def _plot_heatmap(self, fig, ax, **kwargs):
        return ax.imshow(kwargs['hm'], interpolation='none')

    def _plot_notes(self):
        return "Injections: {}\nNoise hits window: 500ms\nSaturation checks: {}\n".format(self.injections, self.injections) + \
                "Test Pulse rising edge: 10us\nTest Pulse falling edge: 10us";

    def plot_heatmaps(self, show=True, saveas=None, notes=None):
        hm_baseline = np.full((512, 512), np.nan)
        hm_gain = np.full((512, 512), np.nan)
        hm_noise = np.full((512, 512), np.nan)

        notes = "" if notes is None else notes
        notes = self._plot_notes() + notes

        gains = []
        noises = []

        for pix in self.pixels:
            p = self.pixels[pix]
            if 'baseline' not in p.__dict__:
                self.scurve_fit(p)

            if p.fit_mu_err > 5 or p.fit_sigma_err > 5:
                continue

            hm_baseline[pix[0], pix[1]] = p.baseline
            hm_gain[pix[0], pix[1]] = p.gain
            hm_noise[pix[0], pix[1]] = p.noise

            gains.append(p.gain)
            noises.append(p.noise)

        self.plot_heatmap(show=show, saveas=saveas, title='Baseline map', notes=notes, hm=hm_baseline)
        self.plot_heatmap(show=show, saveas=saveas, title='Gain map', notes=notes, hm=hm_gain)
        self.plot_heatmap(show=show, saveas=saveas, title='Noise map', notes=notes, hm=hm_noise)

        plt.figure()
        plt.plot(range(len(gains)), gains, '-bo', label="Gain")
        ax = plt.plot(range(len(noises)), noises, '-ro', label="Noise")
        ax.set(xlabel="Pixel", ylabel="mV o mV/fC", title="Extracted data")

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

    def _run(self):
        self.loop_parallel()

        self.scurve_fit()

        for pix in self.pixels:
            p = self.pixels[pix]

            print('Fit for pix {} yielded mu {} +- {}, sigma {} +- {}'.format(
                pix, p.fit_mu, p.fit_mu_err, p.fit_sigma, p.fit_sigma_err))

    def deserialize(self, serialized):
        self.injections = serialized.pop(0)

        for line in serialized:
            p = Pixel(line[0], line[1])
            p.injected_hits = line[2]
            p.noise_hits = line[3]
            p.saturation_hits = line[3]
            p.injected_fe_hits = line[4]

            self.pixels[(line[0], line[1])] = p
