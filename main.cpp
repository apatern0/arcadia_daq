#include <iostream>
#include <unistd.h>

#include "cxxopts.hpp"
#include "DAQBoard_comm.h"

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
			cxxopts::value<std::string>()->default_value("id0"))
		("gcr",       "Select GCR", cxxopts::value<uint16_t>())
		("reg",       "Select fpga register", cxxopts::value<std::string>())
		("r,read",    "Read selected register")
		("w,write",   "Write \"arg\" in selected register", cxxopts::value<uint32_t>())
		("dump-regs", "Dump DAQ Board register")
		("q,daq",     "Start DAQ, with optional comma-separated list of chip to read",
			cxxopts::value<std::vector<std::string>>()->implicit_value("id0"))
		("daq-mode",  "value of daq mode register to set after starting the daq",
			cxxopts::value<uint16_t>()->default_value("0"))
		("controller", "select arcadia_controller register",
			cxxopts::value<std::string>()->default_value(""))
		("v,verbose",  "Verbose output, can be specified multiple times")
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

	bool daq_verbose_flag = (verbose_cnt >= 1);
	DAQBoard_comm DAQBoard_mng(
			cxxopts_res["conn"].as<std::string>(),
			cxxopts_res["device"].as<std::string>(),
			daq_verbose_flag
	);


	if (cxxopts_res.count("config")){
		std::string fname =  cxxopts_res["config"].as<std::string>();
		DAQBoard_mng.read_conf(fname);
	}


	if (cxxopts_res.count("write")){

		if (cxxopts_res.count("gcr")){
			std::string chipid = cxxopts_res["chip"].as<std::string>();
			uint16_t gcr = cxxopts_res["gcr"].as<uint16_t>();
			uint16_t value = cxxopts_res["write"].as<uint32_t>();
			DAQBoard_mng.write_register(chipid, gcr, value);
			std::cout << "write grc: " << gcr << " val: 0x" << std::hex << value << std::endl;
		}
		else if (cxxopts_res.count("reg")){
			std::string reg = cxxopts_res["reg"].as<std::string>();
			uint32_t value = cxxopts_res["write"].as<uint32_t>();
			DAQBoard_mng.write_fpga_register(reg, value);
			std::cout << "write reg: " << reg << " val: 0x" << std::hex << value << std::endl;
		}
		else if (!cxxopts_res.count("controller")) {
			std::cout << "no register selected" << std::endl;
			return -1;
		}

	}


	if (cxxopts_res.count("read")){

		if (cxxopts_res.count("gcr")){
			uint16_t val = 0;
			std::string chipid = cxxopts_res["chip"].as<std::string>();
			uint16_t gcr = cxxopts_res["gcr"].as<uint16_t>();
			DAQBoard_mng.read_register(chipid, gcr, &val);
			std::cout << "read grc: " << gcr << " val: 0x" << std::hex << val << std::endl;
		}
		else if(cxxopts_res.count("reg")){
			uint32_t val = 0;
			std::string reg = cxxopts_res["reg"].as<std::string>();
			DAQBoard_mng.read_fpga_register(reg, &val);
			std::cout << "read reg: " << reg << " val: 0x" << std::hex << val << std::endl;
		}
		else {
			std::cout << "no register selected" << std::endl;
			return -1;
		}

	}


	if (cxxopts_res.count("dump-regs"))
		DAQBoard_mng.dump_DAQBoard_reg();


	if (cxxopts_res.count("controller")){

		std::string chipid = cxxopts_res["chip"].as<std::string>();
		auto option = cxxopts_res["controller"].as<std::string>();
		std::string controllerid = "controller_" + chipid;

		auto search = ctrl_cmd_map.find(option);
		if (search == ctrl_cmd_map.end()){
			std::cerr << "Invalid command: " << option << std::endl;
			for (cmd = ctrl_cmd_map.begin(); cmd != ctrl_cmd_map.end(); cmd++)
				std::cout << cmd.first << std::endl;
			return -1;
		}

		uint16_t extra_data = 0;
		if (cxxopts_res.count("write"))
			extra_data = cxxopts_res["write"].as<uint32_t>();

		arcadia_reg_param const& param = search->second;

		uint32_t command = (param.word_address<<20) | extra_data;
		DAQBoard_mng.write_fpga_register(controllerid, command);
		uint32_t value = 0;
		DAQBoard_mng.read_fpga_register(controllerid, &value);
		std::cout << "response: " << std::hex << value << std::endl;

	}


	if (cxxopts_res.count("daq")){

		auto chipid_list = cxxopts_res["daq"].as<std::vector<std::string>>();
		auto daq_mode = cxxopts_res["daq-mode"].as<uint16_t>();

		std::cout << "Press enter to stop" << std::endl;

		for(auto chipid: chipid_list)
			DAQBoard_mng.start_daq(chipid);

		usleep(500000);
		DAQBoard_mng.write_fpga_register("regfile.mode", daq_mode);

		std::cin.get();

		DAQBoard_mng.write_fpga_register("regfile.mode", 0x0);
		usleep(100000);

		for (std::string id: {"id0", "id1", "id2"})
			DAQBoard_mng.stop_daq(id);

	}

	return 0;
}
