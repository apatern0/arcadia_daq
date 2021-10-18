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

template<typename T, typename... Args>
std::unique_ptr<T> make_unique(Args&&... args)
{
    return std::unique_ptr<T>(new T(std::forward<Args>(args)...));
}

// helper function to avoid making a copy when returning a py::array_t
 // author: https://github.com/YannickJadoul
 // source: https://github.com/pybind/pybind11/issues/1042#issuecomment-642215028
template <typename Sequence>
inline py::array_t<typename Sequence::value_type> as_pyarray(Sequence &&seq) {
	auto size = seq.size();
	auto data = seq.data();
	std::unique_ptr<Sequence> seq_ptr = make_unique<Sequence>(std::move(seq));
	auto capsule = py::capsule(seq_ptr.get(), [](void *p) { std::unique_ptr<Sequence>(reinterpret_cast<Sequence*>(p)); });
	seq_ptr.release();
	return py::array(size, data, capsule);
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
		.def_readwrite("timeout", &ChipIf::timeout)
		.def_readwrite("idle_timeout", &ChipIf::idle_timeout)

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

		// Packets
		.def("packets_count", &ChipIf::packets_count)
		.def("packets_reset", &ChipIf::packets_reset)
		.def("packets_read_start", [](ChipIf &chip) {
			py::gil_scoped_release release;
			chip.packets_read_start();
			})

		.def("packets_read_stop", &ChipIf::packets_read_stop)
		.def("packets_read_wait", &ChipIf::packets_read_wait)
		.def("packets_read_active", &ChipIf::packets_read_active)
		.def("packets_read", [](ChipIf &chip, size_t num_packets=0) {
			// Expose raw memory as NUMPY array
			auto packets = chip.packets_read(num_packets);
			if(packets == nullptr)
				return py::array_t<uint64_t>(0, 0);

		    return as_pyarray(std::move(*packets));
		})

		.def("packets_reset", &ChipIf::packets_reset)
		.def("packets_count", &ChipIf::packets_count)

		.def("calibrate_deserializers", &ChipIf::calibrate_deserializers);

	m.def("set_ipbus_loglevel", &set_ipbus_loglevel);

}
