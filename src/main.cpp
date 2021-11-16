#include <iostream>
#include <unistd.h>
#include <csignal>

#include "cxxopts.hpp"
#include "DAQBoard_comm.h"

// for sign handler
FPGAIf* fpga_ptr;

void signal_handler(int signal){

	if (signal != SIGINT)
		return;

	std::cout << "interrupting DAQ..." << std::endl;
	for (uint8_t id: {0, 1, 2})
		fpga_ptr->chips[id]->packets_read_stop();
}


int main(int argc, char** argv){

	cxxopts::Options options("arcadia-cli", "Simple cli tool for arcadia DAQ");

	options.add_options()
		("h,help",    "Print usage")
		("conn",      "connection.xml file",
			cxxopts::value<std::string>()->default_value("connection.xml"))
		("device",    "Device id to select from connection.xml",
			cxxopts::value<std::string>()->default_value("kc705"))
		("config",    "load registers .conf file", cxxopts::value<std::string>())
		("c,chip",    "Chip id, one of [id0, id1, id2]",
			cxxopts::value<uint8_t>()->default_value("id0"))
		("gcr",       "Select GCR [num]", cxxopts::value<uint16_t>())
		("gcrpar",    "Select GCR paramer [paramater]", cxxopts::value<std::string>())
		("ICR0",      "Select ICR0")
		("ICR1",      "Select ICR1")
		("reg",       "Select fpga register", cxxopts::value<std::string>())
		("r,read",    "Read selected register")
		("w,write",   "Write [arg] in selected register", cxxopts::value<uint32_t>())
		("pulse",     "Send a test pulse to [chip id]",
			cxxopts::value<std::string>()->implicit_value("id0"))
		("dump-regs", "Dump DAQ Board register")
		("reset-fifo", "Reset readout fifos")
		("q,daq",     "Start DAQ, with optional comma-separated list of chip to read",
			cxxopts::value<std::vector<std::string>>()->implicit_value("id0"))
		("maxpkts",   "Max number of packet to read from a chip before exiting",
			cxxopts::value<uint32_t>()->default_value("0"))
		("maxtime",   "Stop DAQ after [arg] seconds",
			cxxopts::value<uint32_t>()->default_value("0"))
		("maxidle",   "Stop DAQ after [arg] seconds of idle time",
			cxxopts::value<uint32_t>()->default_value("0"))
		("daq-mode",  "value of daq mode register to set after starting the daq",
			cxxopts::value<uint16_t>()->default_value("0"))
		("controller", "select arcadia_controller register",
			cxxopts::value<std::string>())
		("v,verbose",  "Verbose output, can be specified multiple times")
		("calibrate",  "Attemp detection of best value for the SERDES delay taps")
	;

	auto cxxopts_res = options.parse(argc, argv);
	auto verbose_cnt = cxxopts_res.count("verbose");

	if (cxxopts_res.count("help")) {
		std::cout << options.help() << std::endl;
		return 0;
	}

	if (verbose_cnt < 2)
		uhal::disableLogging();
	else
		uhal::setLogLevelTo(uhal::Error());

	// init FPGAIf class instace
	bool daq_verbose_flag = (verbose_cnt >= 1);
	FPGAIf fpga (
			cxxopts_res["conn"].as<std::string>(),
			cxxopts_res["device"].as<std::string>(),
			daq_verbose_flag
	);

	//install signal handler
	fpga_ptr = &fpga;
	std::signal(SIGINT, signal_handler);

	///////////////// parse /////////////////////

	if (cxxopts_res.count("config")){
		std::string fname =  cxxopts_res["config"].as<std::string>();
		fpga.read_conf(fname);
	}

	std::uint8_t chipid = cxxopts_res["chip"].as<uint8_t>();

	if (cxxopts_res.count("calibrate")){
		std::cout << "start calibration.." << std::endl;
		fpga.chips[chipid]->calibrate_deserializers(true);
	}


	if (cxxopts_res.count("write")){
		uint32_t value = cxxopts_res["write"].as<uint32_t>();

		if (cxxopts_res.count("gcr")){
			uint16_t gcr = cxxopts_res["gcr"].as<uint16_t>();
			fpga.chips[chipid]->write_gcr(gcr, value);
			std::cout << "write grc: " << std::dec << gcr << " val: 0x" << std::hex << value << std::endl;
		}
		else if (cxxopts_res.count("reg")){
			std::string reg = cxxopts_res["reg"].as<std::string>();
			fpga.write_register(reg, value);
			std::cout << "write reg: " << reg << " val: 0x" << std::hex << value << std::endl;
		}
		else if (cxxopts_res.count("ICR0") || cxxopts_res.count("ICR1")){
			std::string icrstr = "000";
			if (cxxopts_res.count("ICR0")) icrstr = "ICR0";
			else if (cxxopts_res.count("ICR1")) icrstr = "ICR1";
			fpga.chips[chipid]->write_icr(icrstr, value);
		}
		else if (cxxopts_res.count("gcrpar")){
			std::string gcrpar = cxxopts_res["gcrpar"].as<std::string>();
			std::cout << "write gcrpar: " << gcrpar << " val: 0x" << std::hex << value
				<< std::endl;
			fpga.chips[chipid]->write_gcrpar(gcrpar, value);
		}
		else if (!cxxopts_res.count("controller")) {
			std::cout << "no register selected" << std::endl;
			return -1;
		}

	}

	if (cxxopts_res.count("read")){

		if (cxxopts_res.count("gcr")){
			uint16_t val = 0;
			uint16_t gcr = cxxopts_res["gcr"].as<uint16_t>();
			fpga.chips[chipid]->read_gcr(gcr, &val, true);
			std::cout << "read grc: " << gcr << " val: 0x" << std::hex << val << std::endl;
		}
		else if(cxxopts_res.count("reg")){
			uint32_t val = 0;
			std::string reg = cxxopts_res["reg"].as<std::string>();
			fpga.read_register(reg, &val);
			std::cout << "read reg: " << reg << " val: 0x" << std::hex << val << std::endl;
		}
		else if (cxxopts_res.count("gcrpar")){
			std::string gcrpar = cxxopts_res["gcrpar"].as<std::string>();
			uint16_t data;
			int ret = fpga.chips[chipid]->read_gcrpar(gcrpar, &data, true);
			if (ret != 0){
				std::cout << "read error: " << ret  << std::endl;
				return -1;
			}
			std::cout << "gcrpar: " << gcrpar << " val: 0x" << std::hex << data
				<< std::endl;
		}
		else {
			std::cout << "no register selected" << std::endl;
			return -1;
		}

	}

	if(cxxopts_res.count("pulse"))
		fpga.chips[cxxopts_res["pulse"].as<uint8_t>()]->send_pulse(10, 10, 1);

	if (cxxopts_res.count("dump-regs"))
		fpga.dump_DAQBoard_reg();

	if (cxxopts_res.count("controller")){

		auto command = cxxopts_res["controller"].as<std::string>();

		uint32_t extra_data = 0;
		if (cxxopts_res.count("write"))
			extra_data = cxxopts_res["write"].as<uint32_t>();

		uint32_t resp;
		int ret = fpga.chips[chipid]->send_controller_command(command, extra_data, &resp);

		if (ret == 0) {
			std::cout << "response: " << std::hex << resp << std::endl;
		}

		if (ret == -1) {
			std::cerr << "Available commands: " << std::endl;
			for (auto cmd = ctrl_cmd_map.begin(); cmd != ctrl_cmd_map.end(); cmd++)
				std::cout << cmd->first << std::endl;
		}
	}


	if (cxxopts_res.count("reset-fifo")){
		std::cout << "resetting readout FIFOs" << std::endl;
		for (uint8_t id: {0, 1, 2})
			fpga.chips[id]->packets_reset();
	}


	if (cxxopts_res.count("daq")){
		auto chipid_list = cxxopts_res["daq"].as<std::vector<uint8_t>>();
		auto daq_mode = cxxopts_res["daq-mode"].as<uint16_t>();
		auto maxpkts = cxxopts_res["maxpkts"].as<uint32_t>();
		auto maxtime = cxxopts_res["maxtime"].as<uint32_t>();
		auto maxidle = cxxopts_res["maxidle"].as<uint32_t>();

		std::cout << "starting DAQ, Ctrl-C to stop..." << std::endl;

		for(auto chipid: chipid_list) {
			fpga.chips[chipid]->stop_after = maxpkts;
			fpga.chips[chipid]->timeout = maxtime;
			fpga.chips[chipid]->idle_timeout = maxidle;
			fpga.chips[chipid]->packets_read_start();
		}

		if (daq_mode != 0){
			usleep(500000);
			fpga.write_register("regfile.mode", daq_mode);
		}

		for(auto chipid: chipid_list)
			fpga.chips[chipid]->dataread_thread.join();

		if (daq_mode != 0)
			fpga.write_register("regfile.mode", 0x0);
	}

	return 0;
}
