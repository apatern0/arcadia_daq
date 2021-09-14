import os, sys, argparse
import numpy as np
import matplotlib.pyplot as plt

# Load DAQBoard pythin bindings
_PATH = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.append(_PATH)
import DAQ_pybind


# Create DAQBoard instance, TODO: configurable..
IPBUS_CONF = os.path.join(_PATH, 'connection.xml')
try:
    DAQBoard_comm = DAQ_pybind.DAQBoard_comm(IPBUS_CONF, 'kc705', 0)
except:
    print('Fail instantiate DAQBoard_comm')
    sys.exit(255)




def run_histo_scan(gcrpar, start, stop, step):

    #TODO: verify gcrpar is valid

    hist = np.array([], np.uint32)

    print('Running scan...')
    rng = (stop-start)/step

    for i in range(start, stop, step):

        if (DAQBoard_comm.write_gcrpar('id0', gcrpar, i, 0, 1) != 0):
            raise Exception('Fail to write gcrpar')

        if (DAQBoard_comm.start_daq('id0', 0, 0, 2, 'dout.raw') != 0):
            raise Exception('Fail to start DAQ')

        DAQBoard_comm.send_pulse('id0')
        DAQBoard_comm.wait_daq_finished()

        count = DAQBoard_comm.get_packet_count('id0')
        hist = np.append(hist, count)

        print(f'{i}/{rng}..', end='\r')

    print('Done')
    return hist



if __name__ == '__main__':

    parser = argparse.ArgumentParser()

    parser.add_argument('-c', type=str, dest='conf_file',
            help='configuration file to apply before scan')
    parser.add_argument('--gcrpar', type=str, dest='gcr_par', required=True,
            help='paramter to scan')

    parser.add_argument('-s', '--start', type=int, dest='start', default=0,
            help='start value for the scan')
    parser.add_argument('-t', '--stop', type=int, dest='stop', required=True,
            help='stop value for the scan')
    parser.add_argument('--step', type=int, dest='step', default=1,
            help='step value for the scan')

    args = parser.parse_args()



    # Load configuration
    if args.c and os.path.isfile(args.conf_file):
        DAQBoard_comm.read_conf(args.conf_file)
    elif args.c:
        print('No such file: ', args.conf_file)
        sys.exit(255)

    # run scan procedure
    try:
        hist = run_scan(args.gcrpar, args.start, args.stop, args.step)
    except:
        pass

    # TODO: plot hist to pdf
