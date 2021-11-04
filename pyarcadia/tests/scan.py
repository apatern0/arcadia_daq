import time
import threading
import numpy as np
from tqdm import tqdm

from ..test import Test, customplot

class ParallelAnalysis(threading.Thread):
    test = None

    def __init__(self, test):
        threading.Thread.__init__(self)
        self.test = test

    def run(self):
        for i in self.test.range:
            while self.test.ctrl_iteration < i:
                time.sleep(0.5)

            for p in self.test.elab_phases:
                p(i)

            self.test.ebar.update(1)
            self.test.elab_iteration = i

        self.test.chip.packets_read_stop()


class ScanTest(Test):
    range = []
    axes = ["time (s)", "voltage (mV)"]
    title = "Scan Test"

    reader = None
    ebar = None

    ctrl_phases = []
    elab_phases = []

    ctrl_iteration = 0
    elab_iteration = 0

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
                for p in self.ctrl_phases:
                    p(i)
                bar.update(1)
                self.ctrl_iteration = i
        
        with tqdm(total=len(self.range), desc='Elaboration') as ebar:
            for i in self.range:
                for p in self.elab_phases:
                    p(i)
                ebar.update(1)
                self.elab_iteration = i

        self.post_main()

    def loop_parallel(self):
        analysis_thread = ParallelAnalysis(self)

        self.pre_main()
        self.chip.idle_timeout=5
        analysis_thread.start()

        with tqdm(total=len(self.range), desc='Acquisition') as abar, tqdm(total=len(self.range), desc='Elaboration') as self.ebar:
            for i in self.range:
                for p in self.ctrl_phases:
                    p(i)
                abar.update(1)
                self.ctrl_iteration = i

            analysis_thread.join()
 
    def loop_reactive(self):
        self.pre_main()

        lp = len(self.ctrl_phases)

        with tqdm(total=len(self.range), desc='Test') as bar:
            for i in self.range:
                for p in range(lp):
                    self.ctrl_phases[p](i)
                    self.elab_phases[p](i)

                bar.update(1)
                self.ctrl_iteration = i
                self.elab_iteration = i
        
        self.post_main()

    def __init__(self):
        super().__init__()

    @customplot(('X', 'Y'), 'Title')
    def plot(self, show=True, saveas=None, ax=None):
        ax.plot(self.range, self.result, '-o')
