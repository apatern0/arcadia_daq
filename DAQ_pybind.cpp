#include <pybind11/pybind11.h>
#include "DAQBoard_comm.h"

namespace py = pybind11;


void set_ipbus_loglevel(int level){

	switch(level){

		case 0:
			uhal::disableLogging();
			break;
		case 1:
			uhal::setLogLevelTo(uhal::Error());
			break;
		default:
			uhal::setLogLevelTo(uhal::Warning());
			break;

	}

}


PYBIND11_MODULE(DAQ_pybind, m) {

	py::class_<DAQBoard_comm>(m, "DAQBoard_comm")
		.def(py::init<const std::string &, const std::string &, bool>())
		.def("read_conf", &DAQBoard_comm::read_conf)
		.def("spi_transfer", &DAQBoard_comm::spi_transfer)
		.def("read_gcr", &DAQBoard_comm::read_gcr)
		.def("write_gcr", &DAQBoard_comm::write_gcr)
		.def("reinitialize_gcr", &DAQBoard_comm::reinitialize_gcr)
		.def("write_icr", &DAQBoard_comm::write_icr)
		.def("write_gcrpar", &DAQBoard_comm::write_gcrpar)
		.def("read_gcrpar", &DAQBoard_comm::read_gcrpar)
		.def("check_consistency", &DAQBoard_comm::check_consistency)
		.def("send_controller_command", &DAQBoard_comm::send_controller_command)
		.def("read_fpga_register", &DAQBoard_comm::read_fpga_register)
		.def("write_fpga_register", &DAQBoard_comm::write_fpga_register)
		.def("send_pulse", &DAQBoard_comm::send_pulse)
		.def("dump_DAQBoard_reg", &DAQBoard_comm::dump_DAQBoard_reg)
		.def("reset_fifo", &DAQBoard_comm::reset_fifo)
		.def("start_daq", &DAQBoard_comm::start_daq)
		.def("stop_daq", &DAQBoard_comm::stop_daq)
		.def("wait_daq_finished", &DAQBoard_comm::wait_daq_finished)
		.def("get_packet_count", &DAQBoard_comm::get_packet_count)
		.def("cal_serdes_idealy", &DAQBoard_comm::cal_serdes_idealy);

	m.def("set_ipbus_loglevel", &set_ipbus_loglevel);

}
