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


//TODO: find something cleaner for functions taking pointer arguments
PYBIND11_MODULE(DAQ_pybind, m) {

	py::class_<DAQBoard_comm>(m, "DAQBoard_comm")
		.def(py::init<const std::string &, const std::string &, bool>())
		.def("read_conf", &DAQBoard_comm::read_conf)

		.def("spi_transfer", [](DAQBoard_comm &DAQ, ARCADIA_command command, uint16_t payload,
					std::string chip_id) {
				uint32_t rcv_data;
				int ret = DAQ.spi_transfer(command, payload, chip_id, &rcv_data);
				return py::make_tuple(ret, rcv_data);
				})

		.def("read_gcr", [](DAQBoard_comm &DAQ, std::string chip_id, uint16_t addr,
					bool force_update) {
				uint16_t value;
				int ret = DAQ.read_gcr(chip_id, addr, &value, force_update);
				return py::make_tuple(ret, value);
				})

		.def("write_gcr", &DAQBoard_comm::write_gcr)
		.def("reinitialize_gcr", &DAQBoard_comm::reinitialize_gcr)
		.def("write_icr", &DAQBoard_comm::write_icr)
		.def("write_gcrpar", &DAQBoard_comm::write_gcrpar)

		.def("read_gcrpar", [](DAQBoard_comm &DAQ, std::string chip_id, std::string gcrpar,
					bool force_update) {
				uint16_t value;
				int ret = DAQ.read_gcrpar(chip_id, gcrpar, &value, force_update);
				return py::make_tuple(ret, value);
				})

		.def("check_consistency", &DAQBoard_comm::check_consistency)

		.def("send_controller_command", [](DAQBoard_comm &DAQ, std::string controller_id,
					const std::string cmd, uint32_t arg) {
				uint32_t resp;
				int ret = DAQ.send_controller_command(controller_id, cmd, arg, &resp);
				return py::make_tuple(ret, resp);
				})

		.def("read_fpga_register", &DAQBoard_comm::read_fpga_register)

		.def("read_fpga_register", [](DAQBoard_comm &DAQ, std::string reg_handler) {
				uint32_t value;
				int ret = DAQ.read_fpga_register(reg_handler, &value);
				return py::make_tuple(ret, value);
				})

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
