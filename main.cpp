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
		("c,chip",    "Chip id, one of [0,1,2]", cxxopts::value<uint8_t>()->default_value("0"))
		("gcr",       "Select GCR", cxxopts::value<uint16_t>())
		("reg",       "Select fpga register", cxxopts::value<std::string>())
		("r,read",    "Read selected register")
		("w,write",   "Write \"arg\" in selected register", cxxopts::value<uint32_t>())
		("dump-regs", "Dump DAQ Board register")
		("q,daq",     "Start DAQ, with optional comma-separated list of chip to read",
			cxxopts::value<std::vector<int>>()->implicit_value("0,1,2"))
		("daq-mode",  "value of daq mode register to set after starting the daq",
			cxxopts::value<uint16_t>()->default_value("0"))
		("v,verbose", "Verbose output, can be specified multiple times")
	;

	auto cxxopts_res = options.parse(argc, argv);
	auto verbose_cnt = cxxopts_res.count("verbose");

	if (cxxopts_res.count("help")) {
		std::cout << options.help() << std::endl;
		return 0;
	}

	if (verbose_cnt < 2)
		uhal::setLogLevelTo(uhal::Error());

	bool daq_verbose_flag = (verbose_cnt >= 1);
	DAQBoard_comm DAQBoard_mng(
			cxxopts_res["conn"].as<std::string>(),
			cxxopts_res["device"].as<std::string>(),
			daq_verbose_flag
	);


	if (cxxopts_res.count("write")){

		if (cxxopts_res.count("gcr")){
			uint8_t chipid = cxxopts_res["chip"].as<uint8_t>();
			uint16_t gcr = cxxopts_res["gcr"].as<uint16_t>();
			uint16_t value = cxxopts_res["write"].as<uint32_t>();
			DAQBoard_mng.Write_Register(chipid, gcr, value);
			std::cout << "write grc: " << gcr << " val: 0x" << std::hex << value << std::endl;
		}
		else if (cxxopts_res.count("reg")){
			std::string reg = cxxopts_res["reg"].as<std::string>();
			uint32_t value = cxxopts_res["write"].as<uint32_t>();
			DAQBoard_mng.Write_DAQ_register(reg, value);
			std::cout << "write reg: " << reg << " val: 0x" << std::hex << value << std::endl;
		}
		else {
			std::cout << "no register selected" << std::endl;
			return -1;
		}

	}


	if (cxxopts_res.count("read")){

		if (cxxopts_res.count("gcr")){
			uint16_t val;
			uint8_t chipid = cxxopts_res["chip"].as<uint8_t>();
			uint16_t gcr = cxxopts_res["gcr"].as<uint16_t>();
			DAQBoard_mng.Read_Register(chipid, gcr, &val);
			std::cout << "read grc: " << gcr << " val: 0x" << std::hex << val << std::endl;
		}
		else if(cxxopts_res.count("reg")){
			uint32_t val;
			std::string reg = cxxopts_res["reg"].as<std::string>();
			DAQBoard_mng.Read_DAQ_register(reg, &val);
			std::cout << "read reg: " << reg << " val: 0x" << std::hex << val << std::endl;
		}
		else {
			std::cout << "no register selected" << std::endl;
			return -1;
		}

	}


	if (cxxopts_res.count("dump-regs"))
		DAQBoard_mng.Dump_DAQBoard_reg();


	if (cxxopts_res.count("daq")){

		auto chipid_list = cxxopts_res["daq"].as<std::vector<int>>();
		auto daq_mode = cxxopts_res["daq-mode"].as<uint16_t>();

		std::cout << "Press enter to stop" << std::endl;

		for(auto chipid: chipid_list)
			DAQBoard_mng.start_DAQ(chipid);

		usleep(500000);
		DAQBoard_mng.Write_DAQ_register("mode", daq_mode);

		std::cin.get();

		DAQBoard_mng.Write_DAQ_register("mode", 0x0);
		usleep(100000);

		for(uint8_t chipid=0; chipid<3; chipid++)
			DAQBoard_mng.stop_DAQ(chipid);

	}

	return 0;
}
