inject_random = False # in Hz
cluster_time_us = 1E3
fading_time_us = 20E6
hamming = 5
refresh_time_us = 0.1
blob_min_radius = 2
resolution = 0.25E-6
speed = 0.01
save_min = 1
fe_alpide = True
cluster_analysis = False
last_save_file = None
already_hit_analysis = False

import os.path
import sys
import time
import logging
import math
import random
import threading
import numpy as np
import matplotlib
import matplotlib.pyplot as plt
import scipy
import scipy.optimize
import warnings
from pyarcadia.test import Test
from pyarcadia.sequence import Sequence, SubSequence
from pyarcadia.data import ChipData
from matplotlib.animation import FuncAnimation
from scipy.optimize import curve_fit
from scipy.special import factorial
from scipy.stats import poisson
#plt.style.use('seaborn-pastel')
#matplotlib.use("Qt5agg")
warnings.simplefilter('ignore')

past = None 

class Cluster:
    time = None
    swtime = None
    pixels = []
    patch = None
    to_remove = False
    width = 0
    height = 0
    blob = False
    bbox = None

    def update_size(self):
        min_x = 511; max_x = 0; min_y = 511; max_y = 0
        for y, x in self.pixels:
            min_x = x if x < min_x else min_x
            min_y = y if y < min_y else min_y
            max_x = x if x > max_x else max_x
            max_y = y if y > max_y else max_y

        self.height = max_y - min_y
        self.width = max_x - min_x
        self.bbox = ( (min_x, min_y), (max_x, max_y) )
        self.blob = self.has_blob()

    def has_blob(self):
        for pixel in self.pixels:
            neighbors = 0

            for neighbor in self.pixels:
                if pixel == neighbor:
                    continue

                if (
                        abs(pixel[0] - neighbor[0]) <= blob_min_radius and
                        abs(pixel[1] - neighbor[1]) <= blob_min_radius
                ):
                    neighbors += 1

            if neighbors > 3.14*blob_min_radius*blob_min_radius:
                return True

        return False

incr_cmap = matplotlib.cm.get_cmap("gist_rainbow").copy()
incr_cmap.set_bad('white',1.)
last_cmap = matplotlib.cm.get_cmap("viridis").copy()
last_cmap.set_bad('white',1.)

plt.ion()

def deserialize(self, words):
    if not hasattr(self, "packets") or self.packets is None:
        self.packets = SubSequence()

    print("Deserializing %d words" % len(words))

    for word in words:
        if len(word) == 0:
            continue

        word = word[1:-2]
        word = word.split(", ")

        packet = ChipData()
        try:
            packet.bottom = int(word[0])
            packet.hitmap = int(word[1])
            packet.corepr = int(word[2])
            packet.col = int(word[3])
            packet.sec = int(word[4])
            packet.ser = int(word[5])
            packet.falling = (word[6] == 'True')
            packet.ts = int(word[7])
            packet.ts_fpga = int(word[8])
            packet.ts_sw = int(word[9])
            packet.ts_ext = int(word[10])
        except ValueError:
            continue

        self.packets.append(packet)

def serialize(self):
    words = []
    for packet in self.packets:
        words.append( (
            packet.bottom,
            packet.hitmap,
            packet.corepr,
            packet.col,
            packet.sec,
            packet.ser,
            packet.falling,
            packet.ts,
            packet.ts_fpga,
            packet.ts_sw,
            packet.ts_ext
        ) )

    return words

Test.serialize = serialize
Test.deserialize = deserialize

def automask(data):
    squashed = data.squash_data()

    masked = 0
    for data in squashed:
        slave_hitmap = data.hitmap & 0xf
        if slave_hitmap != 0:
            self.chip.pcr_cfg(0b11, [data.sec], [data.col], [data.corepr], [0], slave_hitmap)

        master_hitmap = (data.hitmap >> 4) & 0xf
        if master_hitmap != 0:
            self.chip.pcr_cfg(0b11, [data.sec], [data.col], [data.corepr], [1], master_hitmap)

        masked += len(data.get_pixels())

    print(f"Masked {masked} pixels")

def autoscale(num, pad=3, prec=2):
    scales = {
        1e9 : "G",
        1e6 : "M",
        1e3 : "k",
        1 : "",
        1e-3 : "m",
        1e-6 : "u",
        1e-9 : "n",
        1e-12 : "p"
    }

    for scale in scales:
        if num >= scale:
            break

    return ("%0"+str(pad+prec+1)+"."+str(prec)+"f %s") % ( (num/scale), scales[scale] )

# New acquisition or replay?
filename = False
if len(sys.argv) > 1:
    filename = sys.argv[1]
    if not os.path.isfile(filename):
        print("File not found.")
        sys.exit(-1)

# Results
res_incr = np.full((512, 512), 0.0)
res_last = np.full((512, 512), 0.0)
res_cleaned = np.full((512, 512), 0.0)
times = []
last_time = None
count = 0

# Plots
fig, (ax_incr, ax_cleaned, ax_last) = plt.subplots(1, 3)

ax_incr.get_shared_x_axes().join(ax_incr, ax_last)
ax_incr.get_shared_y_axes().join(ax_incr, ax_last)
ax_incr.get_shared_x_axes().join(ax_incr, ax_cleaned)
ax_incr.get_shared_y_axes().join(ax_incr, ax_cleaned)

ax_incr.set_title("Incremental map")
ax_cleaned.set_title("Incremental map w/o blooms")
ax_last.set_title("Most recent hits")
img_last = ax_last.imshow(res_last, interpolation='none', origin='lower', vmin=0, vmax=fading_time_us, cmap=last_cmap)
img_incr = ax_incr.imshow(res_incr, interpolation='none', origin='lower', cmap=incr_cmap)
img_cleaned = ax_cleaned.imshow(res_cleaned, interpolation='none', origin='lower', cmap=incr_cmap)
cbar_last = plt.colorbar(img_last, orientation='horizontal', ax=ax_last)
cbar_incr = plt.colorbar(img_incr, orientation='horizontal', ax=ax_incr)
cbar_cleaned = plt.colorbar(img_cleaned, orientation='horizontal', ax=ax_cleaned)
plt.show()

fig_hist, (ax_cltime, ax_clsize) = plt.subplots(1, 2, tight_layout=True)
_, _, times_hist = ax_cltime.hist([0 for _ in range(20)], bins=30)
times_fit = ax_cltime.plot(np.arange(20), [0 for _ in range(20)])
plt.ylim([0, 1])
ax_cltime.set_ylabel('Probability')
ax_cltime.set_xlabel(f"Time between events (s)")
ax_clsize.set_ylabel('Number of clusters')
ax_clsize.set_xlabel(f"Cluster size in pixels")
timing_fit = ""

plt.show()


def visualize(new_clusters, clusters_removed, elapsed):
    if cluster_analysis:
        # Remove old clusters
        for cluster in clusters_removed:
            if cluster.patch:
                cluster.patch.remove()

        # Update existing clusters
        fading_delta = elapsed*1E6/fading_time_us
        for p in reversed(ax_last.patches):
            alpha = p.get_alpha() or 1
            p.set_alpha(alpha-fading_delta) if alpha > fading_delta else p.remove()

        # Add new clusters
        for i, cluster in enumerate(new_clusters):
            color = "limegreen" if not cluster.blob else "red"
            rect = plt.Rectangle((cluster.bbox[0][0]-.5, cluster.bbox[0][1]-.5), cluster.width+1, cluster.height+1, fill=False, color=color, linewidth=2)
            ax_last.add_patch(rect)
            cluster.patch = rect

    # Animate - should be in separate thread
    img_last.set_data(res_last)
    cbar_last.update_normal(img_last)

    img_incr.set_data(res_incr)
    img_incr.set_clim(vmin=0, vmax=np.nanmax(res_incr)+1)
    cbar_incr.update_normal(img_incr)

    img_cleaned.set_data(res_cleaned)
    img_cleaned.set_clim(vmin=0, vmax=np.nanmax(res_cleaned)+1)
    cbar_cleaned.update_normal(img_cleaned)

    fig.canvas.draw()
    fig.canvas.start_event_loop(refresh_time_us*1E-6)
    #plt.pause(refresh_time_us*1E-6)

    if cluster_analysis:
        histo_times()

def histo_times():
    global times_hist, times, times_fit

    # Remove old plots
    ax_cltime.clear()
    ax_clsize.clear()

    sizes = [len(cl.pixels) for cl in cluster_history]
    heights, bins, times_hist = ax_clsize.hist(sizes, bins=np.arange(30))

    #
    # Time between clusters
    #

    # New plot
    heights, bins, times_hist = ax_cltime.hist(times, bins=np.arange(20), density=True)

    # calculate bin centres
    bin_middles = 0.5 * (bins[1:] + bins[:-1])

    # calculate bin centres
    def fit_function(x, mu):
        return poisson.pmf(x, mu)

    # fit with curve_fit
    try:
        parameters, cov_matrix = curve_fit(fit_function, bin_middles, heights)

        # plot poisson-deviation with fitted parameter
        ax_cltime.plot(
            np.arange(20)+0.5,
            fit_function(bins, *parameters),
            marker='o', linestyle='',
            label='Fit result',
        )

        timing_fit = "Timing dispersion fit w/ poissonian distribution: mu = %ss +- %ss" % (autoscale(parameters[0]), autoscale(math.sqrt(cov_matrix[0][0])))
    except (RuntimeError, ValueError, scipy.optimize.OptimizeWarning):
        pass

    ax_cltime.set_ylabel('Probability')
    ax_cltime.set_xlabel(f"Time between events (s)")
    ax_clsize.set_ylabel('Number of clusters')
    ax_clsize.set_xlabel(f"Cluster size in pixels")

    fig_hist.canvas.draw()
    fig_hist.canvas.start_event_loop(refresh_time_us*1E-6)

# Test
t = Test()

if filename is False:
    t.initialize(auto_read=False)
    t.set_timestamp_resolution(resolution)
else:
    t.set_timestamp_resolution(resolution, False)

for sec in t.lanes_excluded:
    res_cleaned[:, sec*32:(sec+1)*32-1] = np.nan
    res_incr[:, sec*32:(sec+1)*32-1] = np.nan
    res_last[:, sec*32:(sec+1)*32-1] = np.nan

if filename is False:
    # Mask FEs, disable injection
    t.chip.pixels_mask()
    t.chip.injection_analog()
    t.chip.injection_enable()
    t.chip.read_enable()
    t.chip.clock_enable()

    # Configure Biases
    for sec in range(0, 16):
        t.chip.write_gcrpar('BIAS%d_VCAL_HI' % sec, 0)
        t.chip.write_gcrpar('BIAS%d_VCAL_LO' % sec, 1)
        t.chip.write_gcrpar('BIAS%d_VCASN' % sec, 15)

        if not fe_alpide:
            t.chip.write_gcrpar('BIAS%d_VINREF' % sec, 24)
            t.chip.write_gcrpar('BIAS%d_VCASP' % sec, 12)
            t.chip.write_gcrpar('BIAS%d_ID' % sec, 0)
            t.chip.write_gcrpar('BIAS%d_ICLIP' % sec, 0)

    t.chip.write_gcrpar('READOUT_CLK_DIVIDER', 3)
    t.chip.write_gcrpar('DISABLE_SMART_READOUT', 1)
    t.chip.write_gcrpar('TOKEN_COUNTER', 15)

    t.chip.pcr_cfg(0b00, 0xffff, 0xffff, None, None, 0xf)
    t.chip.pcr_cfg(0b10, [12], [9], [0x4d], None, 0xf)
    t.chip.pixel_cfg((36, 449), mask=True)
    time.sleep(0.05)
    t.chip.pixel_cfg((0, 64), injection=True, mask=False)

    if False:
        while t.chip.packets_count() > 0:
            print("Waiting for packets to drop...")
            t.chip.packets_reset()
            time.sleep(0.5)

    time.sleep(0.05)
    t.chip.packets_reset()
    t.chip.packets_read_start()
    t.packets = SubSequence()
else:
    t.loadcsv(filename)
    replay = [SubSequence()]

    epoch = 0
    for p in t.packets:
        if p.ts_ext*resolution > epoch+0.1:
            epoch += 0.1
            print(f"New epoch:  {epoch}. Collected {len(replay[-1])} packets")
            replay.append(SubSequence())

        replay[-1].append(p)

    print(f"Arrived to {epoch*10} s.") 

    """
    fig_hist, (ax_cltime, ax_clsize) = plt.subplots(1, 2, tight_layout=True)
    _, _, times_hist = ax_cltime.hist(times, bins=30)
    times_fit = ax_cltime.plot(np.arange(20), [0 for _ in range(20)])
    plt.ylim([0, 1])
    ax_cltime.set_ylabel('Probability')
    ax_cltime.set_xlabel(f"Time between events (s)")
    ax_clsize.set_ylabel('Number of clusters')
    ax_clsize.set_xlabel(f"Cluster size in pixels")
    timing_fit = ""
    plt.show()
    """

alive = True
slept = 0
past_time = time.time()
clusters = 0
new_clusters = []
clusters_removed = []
cluster_history = []
last_report = time.time()
last_save = time.time()
start_time = time.time()
last_time = time.time()
last_pixels = []
current_pixels = []

if filename is not False:
    init_ts = t.packets[0].ts_ext
    init_time = time.time()

last_ts_sw = None
while True:
    try:
        new_pixels = []
        new_pixels_times = {}

        if filename is False:
            current = SubSequence( t.chip.readout(), init_ts_sw=last_ts_sw )
            last_ts_sw = current.ts_sw
            this_time = time.time()

            t.packets = current
            last_save_file = t.savecsv(last_save_file)
        else:
            """
            if not hasattr(t, 'packets') or len(t.packets) == 0:
                break

            elapsed_real = time.time() - init_time
            elapsed_sim = (t.packets[0].ts_ext - init_ts)*resolution/speed
            """

            if len(replay) == 0:
                break

            current = replay.pop(0)
            """
            if time.time() - last_time < 0.
            last_time = time.time()
            this_time = elapsed_sim
            """

            this_time = time.time()

        print("Reading %d packets" % len(current))

        if len(current) > 0:
            current_pixels = []
            already_hit = {}
            for packet in current:
                if past_time is not None:
                    times.append(packet.ts_ext - past_time)
                past_time = packet.ts_ext

                pixels = packet.get_pixels()

                for pixel in pixels:
                    pixel.ts = packet.ts_ext

                    if already_hit_analysis:
                        for other in (last_pixels + current_pixels):
                            if pixel.row == other.row and pixel.col == other.col:
                                if (pixel.row, pixel.col) not in already_hit:
                                    already_hit[ (pixel.row, pixel.col) ] = [other.ts]

                                already_hit[ (pixel.row, pixel.col) ].append( pixel.ts )

                    res_incr[pixel.row][pixel.col] += 1
                    res_last[pixel.row][pixel.col] = fading_time_us

                    current_pixels.append(pixel)
                    new_pixels.append( (pixel.row, pixel.col) )
                    new_pixels_times[(pixel.row, pixel.col)] = packet.ts_ext

            if already_hit_analysis:
                for pixel in already_hit:
                    ots = already_hit[pixel].pop(0)
                    print("Pixel %s was originally hit @ %ss and then: " % (pixel, autoscale(resolution*ots)), end="")
                    print(", ".join([autoscale(resolution*(ts-ots))+"s ago" for ts in already_hit[pixel]]))

            last_pixels = current_pixels
        
        elapsed_step = this_time - past_time 
        past_time = this_time
        elapsed = this_time - start_time

        # Update res_last
        res_last[res_last > 0] -= int(elapsed_step*1E6)

        if cluster_analysis:
            clsearch_start = time.time()
            # Clusterize
            result = np.where(res_last > fading_time_us-cluster_time_us)
            old_pixels = list(zip(result[0], result[1]))

            # Until the pixels have all been checked
            old_clusters = new_clusters
            new_clusters = []
            total_pixels = new_pixels + old_pixels
            while len(new_pixels) > 0:
                cluster_pixels = [new_pixels[0]]
                pixel_idx = 0

                replacement = False
                # Build the new cluster
                while pixel_idx < len(cluster_pixels):
                    for row_delta in range(-hamming, hamming+1):
                        for col_delta in range(-hamming, hamming+1):
                            row, col = cluster_pixels[pixel_idx]
                            needle = (row+row_delta, col+col_delta)

                            # If this pixel is alive, include in current cluster and scan around it
                            if needle in total_pixels:
                                cluster_pixels.append(needle)
                                total_pixels.remove(needle)

                                if needle in new_pixels:
                                    new_pixels.remove(needle)

                                # If it was part of a previous cluster, destroy it
                                for old_cluster in old_clusters:
                                    if needle in old_cluster.pixels:
                                        old_cluster.to_remove = True
                                        replacement = old_cluster

                    pixel_idx += 1

                # Got it!
                newcl = Cluster()
                newcl.swtime = time.time()
                newcl.time = None
                newcl.pixels = list(set(cluster_pixels))
                newcl.update_size()

                if replacement:
                    newcl.time = replacement.time
                else:
                    clusters += 1
                    for pixel in newcl.pixels:
                        if pixel in new_pixels_times:
                            tt = new_pixels_times[pixel]
                            if newcl.time is None or tt < newcl.time:
                                newcl.time = tt

                    # Add for histogram
                    curr = packet.ts_ext*resolution
                    if last_time is not None:
                        diff = curr - last_time
                        if diff == 0.0 and len(times) > 0:
                            times.append(times[-1])
                        else:
                            times.append(diff)
                    last_time = curr

                new_clusters.append(newcl)
                cluster_history.append(newcl)

                if not newcl.blob:
                    for x,y in newcl.pixels:
                        res_cleaned[x][y] += 1
                #print("New cluster with pixels: %s" % cluster_pixels)

            to_replace = []
            to_remove = []
            for idx, cluster in enumerate(old_clusters):
                # Remove clusters marked for substitution
                if cluster.to_remove:
                    #print("Cluster %d marked for replacement. Deleting." % idx)
                    to_replace.append(idx)
                    continue

                # Removed clusters with no visible pixels
                delete = True
                for pixel in cluster.pixels:
                    if res_last[pixel[0]][pixel[1]] > 0:
                        delete = False
                        break

                if delete:
                    #print("Cluster %d has no more visible pixels. Deleting." % idx)
                    to_remove.append(idx)

            to_remove = list(set(to_remove + to_replace))

            clusters_removed = []
            for idx in reversed(to_remove):
                clusters_removed.append(old_clusters[idx])
                del old_clusters[idx]

            for idx in reversed(to_replace):
                for x,y in cluster_history[idx].pixels:
                    res_cleaned[x][y] -= 1

                del cluster_history[idx]


            clsearch_time = time.time() - clsearch_start
            print("Cluster search took %07.3f s", clsearch_time)

        # Update view!
        visualize(new_clusters, clusters_removed, elapsed_step)

        # Report rates
        if cluster_analysis and this_time - last_report > 30:
            rate_1m = 0; rate_1m_pix = 0
            rate_5m = 0; rate_5m_pix = 0
            rate_1h = 0; rate_1h_pix = 0
            rate_1m_f = 0; rate_1m_f_pix = 0
            rate_5m_f = 0; rate_5m_f_pix = 0
            rate_1h_f = 0; rate_1h_f_pix = 0

            for cluster in reversed(cluster_history):
                if cluster.swtime < this_time-60*60:
                    break

                if cluster.swtime > this_time-60:
                    rate_1m += 1
                    rate_1m_pix += len(cluster.pixels)
                    if not cluster.blob:
                        rate_1m_f += 1
                        rate_1m_f_pix += len(cluster.pixels)

                if cluster.swtime > this_time-60*5:
                    rate_5m += 1
                    rate_5m_pix += len(cluster.pixels)
                    if not cluster.blob:
                        rate_5m_f += 1
                        rate_5m_f_pix += len(cluster.pixels)

                rate_1h += 1
                rate_1h_pix += len(cluster.pixels)
                if not cluster.blob:
                    rate_1h_f += 1
                    rate_1h_f_pix += len(cluster.pixels)

            area_cm2 = (25e-6*25e-6*512*512)/(0.01*0.01)

            time_factor = elapsed if elapsed < 60 else 60
            rate_1m = rate_1m/time_factor/area_cm2
            rate_1m_pix = rate_1m_pix/time_factor/area_cm2
            rate_1m_f = rate_1m_f/time_factor/area_cm2
            rate_1m_f_pix = rate_1m_f_pix/time_factor/area_cm2

            time_factor = elapsed if elapsed < 60*5 else 60*5
            rate_5m = rate_5m/time_factor/area_cm2
            rate_5m_pix = rate_5m_pix/time_factor/area_cm2
            rate_5m_f = rate_5m_f/time_factor/area_cm2
            rate_5m_f_pix = rate_5m_f_pix/time_factor/area_cm2

            time_factor = elapsed if elapsed < 60*60 else 60*60
            rate_1h_err = math.sqrt(rate_1h)/time_factor/area_cm2
            rate_1h = rate_1h/time_factor/area_cm2
            rate_1h_pix_err = math.sqrt(rate_1h_pix)/time_factor/area_cm2
            rate_1h_pix = rate_1h_pix/time_factor/area_cm2
            rate_1h_f_err = math.sqrt(rate_1h_f)/time_factor/area_cm2
            rate_1h_f = rate_1h_f/time_factor/area_cm2
            rate_1h_f_pix_err = math.sqrt(rate_1h_f_pix)/time_factor/area_cm2
            rate_1h_f_pix = rate_1h_f_pix/time_factor/area_cm2

            print("Report @ %.3f s" % (this_time - start_time))
            print("1-minute rates  w/ big clusters. Particle rate: %sHz/cm2 - Pixel rate: %sHz/cm2" % (autoscale(rate_1m), autoscale(rate_1m_pix)))
            print("1-minute rates w/o big clusters. Particle rate: %sHz/cm2 - Pixel rate: %sHz/cm2" % (autoscale(rate_1m_f), autoscale(rate_1m_f_pix)))
            print("5-minute rates  w/ big clusters. Particle rate: %sHz/cm2 - Pixel rate: %sHz/cm2" % (autoscale(rate_5m), autoscale(rate_5m_pix)))
            print("5-minute rates w/o big clusters. Particle rate: %sHz/cm2 - Pixel rate: %sHz/cm2" % (autoscale(rate_5m_f), autoscale(rate_5m_f_pix)))
            print("  1-hour rates  w/ big clusters. Particle rate: %sHz/cm2 - Pixel rate: %sHz/cm2" % (autoscale(rate_1h), autoscale(rate_1h_pix)))
            print("  1-hour rates w/o big clusters. Particle rate: %sHz/cm2 - Pixel rate: %sHz/cm2" % (autoscale(rate_1h_f), autoscale(rate_1h_f_pix)))
            print("")

            print("Report @ %.3f s" % (this_time - start_time))
            print("W/ blooms: Particle rate: %sHz/cm2 +- %sHz/cm2| Pixel rate: %sHz/cm2 +- %sHz/cm2" % (autoscale(rate_1h), autoscale(rate_1h_err), autoscale(rate_1h_pix), autoscale(rate_1h_pix_err)))
            print("W/o blooms:  Particle rate: %sHz/cm2 +- %sHz/cm2| Pixel rate: %sHz/cm2 +- %sHz/cm2" % (autoscale(rate_1h_f), autoscale(rate_1h_f_err), autoscale(rate_1h_f_pix), autoscale(rate_1h_f_pix_err)))
            print("")
            print(timing_fit)
            last_report = this_time

        if not filename and this_time - last_save > 60*save_min:
            print("\n\nSaving\n")
            plt.savefig(t._filename(last_save_file + ".eps"), dpi=200.0, format='eps')
            last_save = this_time

    except ValueError: #KeyboardInterrupt:
        try:
            if cluster_analysis:
                rate = 0; rate_pix = 0
                rate_f = 0; rate_f_pix = 0

                for cluster in cluster_history:
                    rate += 1
                    rate_pix += len(cluster.pixels)

                    if not cluster.blob:
                        rate_f += 1
                        rate_f_pix += len(cluster.pixels)

                area_cm2 = (25e-6*25e-6*512*512)/(0.01*0.01)

                time_factor = elapsed
                rate = rate/time_factor/area_cm2
                rate_pix = rate_pix/time_factor/area_cm2
                rate_f = rate_f/time_factor/area_cm2
                rate_f_pix = rate_f_pix/time_factor/area_cm2

                print("Report @ %.3f s" % (this_time - start_time))
                print(" w/ big clusters. Particle rate: %sHz/cm2 - Pixel rate: %sHz/cm2" % (autoscale(rate), autoscale(rate_pix)))
                print("w/o big clusters. Particle rate: %sHz/cm2 - Pixel rate: %sHz/cm2" % (autoscale(rate_f), autoscale(rate_f_pix)))
                print(timing_fit)

            not filename and t.savecsv(last_save_file)

            time.sleep(1)
        except KeyboardInterrupt:
            break
