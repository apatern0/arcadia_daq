#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
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

PYBIND11_MODULE(arcadia_daq, m) {
	py::class_<FPGAIf>(m, "FPGAIf")
		.def(py::init<const std::string &, const std::string &, bool>())
		.def_property_readonly("chips", [](FPGAIf &fpga) {
			return py::make_tuple(fpga.chips[0], fpga.chips[1], fpga.chips[2]);
		})

		.def("get_chip", [](FPGAIf &fpga, uint8_t id) {
			if(id > 2)
				throw std::runtime_error("Invalid chip id: " + std::to_string(id));

			return fpga.chips[id];
		})

		.def("read_conf", &FPGAIf::read_conf)

		.def("read_register", [](FPGAIf &fpga, std::string reg_handler) {
				uint32_t value;
				int ret = fpga.read_register(reg_handler, &value);
				return py::make_tuple(ret, value);
				})
		.def("write_register", &FPGAIf::write_register)
		.def("dump_DAQBoard_reg", &FPGAIf::dump_DAQBoard_reg);


	py::class_<ChipIf>(m, "ChipIf")
		.def_readwrite("max_packets", &ChipIf::max_packets)
		.def("spi_transfer", [](ChipIf &chip, ARCADIA_command command, uint16_t payload) {
				uint32_t rcv_data;
				int ret = chip.spi_transfer(command, payload, &rcv_data);
				return py::make_tuple(ret, rcv_data);
				})

		.def("read_gcr", [](ChipIf &chip, uint16_t addr, bool force_update) {
				uint16_t value;
				int ret = chip.read_gcr(addr, &value, force_update);
				return py::make_tuple(ret, value);
				})

		.def("write_gcr", &ChipIf::write_gcr)
		.def("reinitialize_gcr", &ChipIf::reinitialize_gcr)
		.def("write_icr", &ChipIf::write_icr)
		.def("write_gcrpar", &ChipIf::write_gcrpar)

		.def("read_gcrpar", [](ChipIf &chip, std::string gcrpar, bool force_update) {
				uint16_t value;
				int ret = chip.read_gcrpar(gcrpar, &value, force_update);
				return py::make_tuple(ret, value);
				})

		.def("check_gcr_consistency", &ChipIf::check_gcr_consistency)

		.def("send_controller_command", [](ChipIf &chip, const std::string cmd, uint32_t arg) {
				uint32_t resp;
				int ret = chip.send_controller_command(cmd, arg, &resp);
				return py::make_tuple(ret, resp);
				})

		.def("send_pulse", &ChipIf::send_pulse)
		.def("fifo_count", &ChipIf::fifo_count)
		.def("fifo_reset", &ChipIf::fifo_reset)

		.def("fifo_read", &ChipIf::fifo_read)
		.def("fifo_read_start", [](ChipIf &chip, uint32_t stopafter, uint32_t timeout, uint32_t idle_timeout) {
			py::gil_scoped_release release;
			chip.fifo_read_start(stopafter, timeout, idle_timeout);
			})

		.def("fifo_read_stop", &ChipIf::fifo_read_stop)
		.def("fifo_read_wait", &ChipIf::fifo_read_wait)

		.def("readout", [](ChipIf &chip) {
				//std::cout << "Fetching " << chip.packets.size() << " packets into array!" << std::endl;
				auto result = py::make_tuple(chip.packets.size(), chip.packets.data());
				chip.packets_reset();
				return result;
				})
		.def("packets_reset", &ChipIf::packets_reset)
		.def("packets_count", &ChipIf::packets_count)

		.def("calibrate_deserializers", &ChipIf::calibrate_deserializers);

	m.def("set_ipbus_loglevel", &set_ipbus_loglevel);

}
