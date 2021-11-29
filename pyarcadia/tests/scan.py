import time
import threading
from tqdm import tqdm

from ..test import Test

class ParallelAnalysis(threading.Thread):
    test = None

    def __init__(self, test):
        threading.Thread.__init__(self)
        self.test = test

    def run(self):
        minimum = len(self.test.range)*len(self.test.phases)
        i = 0
        timedout = False
        while i < minimum or len(self.test.sequence) > 0:
            try:
                self.test.elab_auto()
            except RuntimeError:
                timedout = True
                break

            self.test.ebar.update(1)
            i += 1

        if timedout:
            self.test.logger.warning("Analysis thread exited due to popping timeout")

class ScanTest(Test):
    range = []
    axes = ["time (s)", "voltage (mV)"]
    title = "Scan Test"

    reader = None
    ebar = None
    log = False

    def __init__(self):
        super().__init__()

        self.phases = {}
        self.ctrl_phases_to_run = []
        self.ctrl_phases_run = []
        self.elab_phases_run = []

        self.max_retries = 2
        self.analysis_thread = None

    def pre_main(self):
        return

    def post_main(self):
        self.sequence.timeout = 0
        print("Test is complete!")
        return

    def missing(self):
        elab_missing = []
        for t in self.ctrl_phases_run:
            if t not in self.elab_phases_run:
                elab_missing.append(t)

        if len(elab_missing) == 0:
            return []

        # Each missing could have corrupted the following!
        phase_names = list(self.phases.keys())
        additional = []
        for t in elab_missing:
            if t not in additional:
                additional.append(t)

            # Cross iteration
            if t[0] == phase_names[-1]:
                # Last iteration?
                if t[1] == len(self.range)-1:
                    # It was the last, nothing to add except itself
                    continue

                following_phase = phase_names[0]
                following_iteration = t[1]+1
            else:
                following_phase = phase_names[phase_names.index(t[0])+1]
                following_iteration = t[1]

            nt = (following_phase, following_iteration)
            if nt not in additional:
                additional.append(nt)

        # Extract iterations, run them again
        redo = []
        output = []
        for j in additional:
            if j[1] not in redo:
                redo.append(j[1])
                for phase in self.phases:
                    output.append( (phase, j[1]) )

        return output

    def elab_auto(self):
        popped = self.sequence.pop(0, log=self.log)

        if popped[-1].message not in self.phases:
            raise RuntimeError("Invalid phase: ", popped[-1])

        # Call elaboration
        self.phases[popped[-1].message][1](popped)

        self.elab_phases_run.append((popped[-1].message, popped[-1].payload))

    def _start_analysis_thread(self):
        if self.analysis_thread is not None and self.analysis_thread.is_alive():
            self.logger.warning("Analysis thread was alive, waiting for it to end...")
            self.analysis_thread.join()

        self.analysis_thread = ParallelAnalysis(self)
        self.analysis_thread.start()

    def loop(self):
        self.ctrl_phases_to_run = []
        for i in self.range:
            for phase in self.phases:
                self.ctrl_phases_to_run.append((phase, i))

        self.pre_main()

        while True:
            self.ctrl_phases_run = []
            self.elab_phases_run = []
            length = len(self.ctrl_phases_to_run)

            with tqdm(total=length, desc='Acquisition') as bar:
                for phase, iteration in self.ctrl_phases_to_run:
                    self.phases[phase][0](iteration)
                    self.ctrl_phases_run.append((phase, iteration))
                    bar.update(1)

            with tqdm(total=length, desc='Elaboration') as ebar:
                for _ in range(length):
                    try:
                        self.elab_auto()
                    except RuntimeError:
                        break

                    ebar.update(1)

            missing = self.missing()
            if len(missing) != 0:
                self.ctrl_phases_to_run = missing
                continue

            break

        self.post_main()

    def loop_parallel(self):
        self.chip.idle_timeout = 5

        self.ctrl_phases_to_run = []
        for i in self.range:
            for phase in self.phases:
                self.ctrl_phases_to_run.append((phase, i))

        self.pre_main()
        length = len(self.ctrl_phases_to_run)
        for _ in range(self.max_retries):
            self.ctrl_phases_run = []
            self.elab_phases_run = []
            length = len(self.ctrl_phases_to_run)

            self.sequence.timeout = None
            self._start_analysis_thread()

            with tqdm(total=length, desc='Acquisition') as abar, tqdm(total=length, desc='Elaboration') as self.ebar:
                for phase, iteration in self.ctrl_phases_to_run:
                    if phase not in self.phases:
                        raise RuntimeError("Unsupported phase %x", phase)
                    self.phases[phase][0](iteration)
                    self.ctrl_phases_run.append((phase, iteration))
                    abar.update(1)

                while self.sequence.autoread_idle < 10 or self.chip.packets_count() != 0:
                    time.sleep(0.5)

                self.logger.warning("FPGA FIFO Idle time: %d s, Autoread idle: %d s, Packet count: %d. Setting Sequence graceful timeout to 10 seconds" % (self.chip.packets_idle_time(), self.sequence.autoread_idle, self.chip.packets_count()))
                self.sequence.timeout = 10
                self.analysis_thread.join()

            missing = self.missing()
            if len(missing) != 0:
                print("Missing some steps - They'd need to be repeated!")
                for i in missing:
                    print("-- Iteration %2d - Phase 0x%x" % (i[1], i[0]))

                self.ctrl_phases_to_run = missing
                continue

            break

        self.post_main()

    def loop_reactive(self):
        """ TODO: Support recovery of lost phases """
        self.pre_main()

        with tqdm(total=len(self.range), desc='Test') as bar:
            while len(self.ctrl_phases_to_run) > 0:
                phase, iteration = self.ctrl_phases_to_run.pop(0)
                self.phases[phase][0](iteration)
                self.phases[phase][1](iteration)
                self.ctrl_phases_run.append((phase, iteration))
                bar.update(1)

        self.post_main()
