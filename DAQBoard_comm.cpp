#include <iostream>
#include <fstream>
#include <unistd.h>
#include <stdexcept>

#include "ini.h"
#include "DAQBoard_comm.h"

#define SPI_CHAR_LEN 0x18
#define SPI_GO_BUSY  0x100
#define SPI_RX_NEG   0x200
#define SPI_TX_NEG   0x400
#define SPI_LSB      0x800
#define SPI_IE       0x1000
#define SPI_ASS      0x2000

#define SPI_CLOCK_DIV 7


DAQBoard_comm::DAQBoard_comm(std::string connection_xml_path,	std::string device_id,
		bool verbose) :
		verbose(verbose),
		device_str(device_id),
		ConnectionMgr("file://" + connection_xml_path),
		lHW(ConnectionMgr.getDevice(device_str))
{

	// init chipstructs
	for (std::string id: {"id0", "id1", "id2"}){
		chip_stuctmap.insert(std::make_pair(id, new chip_struct()));
	}

	// init spi controller
	for (std::string id: {"id0", "id1", "id2"}){
		std::string spi_id = "spi_" + id;
		lHW.getNode(spi_id + ".CTRL").write(0);
		lHW.getNode(spi_id + ".DIVIDER").write(SPI_CLOCK_DIV);
		lHW.getNode(spi_id + ".SS").write(1);

		try {
			lHW.dispatch();
		}
		catch(...){
			chip_stuctmap[id]->spi_unavaiable = true;
			std::cerr << "SPI core " << spi_id << " configuration fail" << std::endl;
		}

	}

}


int DAQBoard_comm::read_conf(std::string fname){

	// init register array with default values
	for (auto id : {"id0", "id1", "id2"}){
		for(auto const& reg: GCR_map){
			arcadia_reg_param const& param = reg.second;
			chip_stuctmap[id]->GCR_address_array[param.word_address] |=
				(param.default_value << param.offset);
		}
	}

	// run parser
	if (ini_parse(fname.c_str(), conf_handler, this) < 0){
		std::cerr << "Can't open file: " << fname << std::endl;
		return -1;
	}

	return 0;
}


int DAQBoard_comm::conf_handler(void* user, const char* section, const char* name,
		const char* value){

	const int inih_OK  = 1;
	const int inih_ERR = 0;
	// cast *this pointer
	DAQBoard_comm* self = static_cast<DAQBoard_comm*>(user);

	// parse section name and key/value
	std::string section_str(section);
	std::string register_name(name);
	uint16_t reg_value = strtol(value, NULL, 0);

	if (section_str == "id0" || section_str == "id1" || section_str == "id2"){

		// handle ICR0
		if (register_name == "ICR0"){
			//std::cout << "ICR0 :" << std::hex << reg_value << std::endl;
			self->spi_transfer(ARCADIA_WR_ICR0, reg_value, section_str, NULL);
			return inih_OK;
		}

		// if not ICR0, lookup regname
		auto search = GCR_map.find(name);
		if (search == GCR_map.end()){
			std::cerr << "Warning: invalid conf key found: " << name << std::endl;
			return inih_ERR;
		}

		// write reg
		arcadia_reg_param const& param = search->second;
		self->chip_stuctmap[section_str]->GCR_address_array[param.word_address] |=
			(reg_value & param.mask) << param.offset;

		//std::cout << "id: " << section_str << " reg: " <<
		//	param.word_address << " val: " << std::hex <<
		//	self->chip_stuctmap[section_str]->GCR_address_array[param.word_address]
		//	<< std::endl;

		self->write_register(section_str, param.word_address,
				self->chip_stuctmap[section_str]->GCR_address_array[param.word_address]);

		return inih_OK;
	}
	else if (section_str == "controller_id0" || section_str == "controller_id1" ||
			section_str == "controller_id2"){

		auto search = ctrl_cmd_map.find(name);
		if (search == ctrl_cmd_map.end()){
			//std::cerr << "Warning: invalid conf key found: " << name << std::endl;
			return inih_ERR;
		}

		std::string chip_id = section_str.substr(11,3);
		arcadia_reg_param const& param = search->second;
		self->chip_stuctmap[chip_id]->ctrl_address_array[param.word_address] |=
			(reg_value & param.mask) << param.offset;

		uint32_t command = (param.word_address<<20) |
			self->chip_stuctmap[chip_id]->ctrl_address_array[param.word_address];

		//std::cout << "controller cmd:" << std::hex << command << std::endl;
		self->write_fpga_register(section_str, command);

		return inih_OK;
	}
	else {
		std::cerr << "Unknown section: " << section_str << std::endl;
		return inih_ERR;
	}

	return inih_OK;
}


int DAQBoard_comm::spi_transfer(ARCADIA_command command, uint16_t payload,
		std::string chip_id, uint32_t* rcv_data){

	const uhal::Node& SPI_CTRL_Node = lHW.getNode("spi_" + chip_id + ".CTRL");
	const uhal::Node& SPI_TxRx_node = lHW.getNode("spi_" + chip_id + ".TxRx0");

	// prepare CTRL register
	SPI_CTRL_Node.write(SPI_ASS | SPI_RX_NEG | SPI_CHAR_LEN);

	// write TX register
	SPI_TxRx_node.write((command<<20) | payload);

	// set CTRL register to start transfer
	SPI_CTRL_Node.write(SPI_GO_BUSY | SPI_ASS | SPI_RX_NEG | SPI_CHAR_LEN);
	lHW.dispatch();

	// wait done
	bool done = false;
	for(int tryes=0; tryes<3; tryes++){
		uhal::ValWord<uint32_t> CTRL_val = SPI_CTRL_Node.read();
		lHW.dispatch();

		done = ((CTRL_val.value() & SPI_GO_BUSY) == 0);
		if (done)
			break;
	}

	if(!done){
		std::cout << "Timeout on SPI xfer" << std::endl;
		return -1;
	}

	// read RX register
	uhal::ValWord<uint32_t> RX_data = SPI_TxRx_node.read();
	lHW.dispatch();

	if (rcv_data != NULL)
		*rcv_data = RX_data.value();

	return 0;
}


int DAQBoard_comm::read_register(std::string chip_id, uint16_t addr, uint16_t* data){

	if (chip_stuctmap[chip_id]->spi_unavaiable)
		return -1;

	int gcr_address = addr | 0x2000;
	int res;
	uint32_t reg_data;

	res = spi_transfer(ARCADIA_RD_PNTR, gcr_address, chip_id, NULL);
	res = spi_transfer(ARCADIA_RD_DATA, 0, chip_id, &reg_data);

	if (data != NULL)
		*data = (reg_data&0xffff);

	return res;
}


int DAQBoard_comm::write_register(std::string chip_id, uint16_t addr, uint16_t data){

	if (chip_stuctmap[chip_id]->spi_unavaiable)
		return -1;

	int gcr_address = addr | 0x2000;
	int res;
	res = spi_transfer(ARCADIA_WR_PNTR, gcr_address, chip_id, NULL);
	res = spi_transfer(ARCADIA_WR_DATA, data, chip_id, NULL);

	return res;
}


int DAQBoard_comm::read_fpga_register(const std::string reg_handler, uint32_t* data){

	const uhal::Node& reg_Node = lHW.getNode(reg_handler);

	uhal::ValWord<uint32_t> reg_data = reg_Node.read();
	lHW.dispatch();

	*data = reg_data.value();

	return 0;
}


int DAQBoard_comm::write_fpga_register(const std::string reg_handler, uint32_t data){

	const uhal::Node& reg_Node = lHW.getNode(reg_handler);

	reg_Node.write(data);
	lHW.dispatch();

	return 0;
}


void DAQBoard_comm::dump_DAQBoard_reg(){

	for(auto reg: lHW.getNodes("regfile\\..*")){
		const uhal::Node& reg_Node = lHW.getNode(reg);
		uhal::ValWord<uint32_t> reg_data = reg_Node.read();
		lHW.dispatch();

		std::cout << reg << ": 0x" << std::hex << reg_data.value() << std::endl;
	}

}


void DAQBoard_comm::daq_loop(const std::string fname, std::string chip_id){

	const std::string filename = fname + chip_id + ".raw";

	const uhal::Node& Node_fifo_occupancy = lHW.getNode("fifo_" + chip_id + ".occupancy");
	const uhal::Node& Node_fifo_data = lHW.getNode("fifo_" + chip_id + ".data");
	std::ofstream outstrm(filename, std::ios::out | std::ios::trunc | std::ios::binary);

	if (!outstrm.is_open())
		throw std::runtime_error("Can't open file for write");

	const int max_iter = 5000;
	uint32_t iter = 0, max_occ = 0;
	double acc = 0.0;
	const double alpha = 1.0/max_iter;

	while (chip_stuctmap[chip_id]->run_flag){
		uhal::ValWord<uint32_t> fifo_occupancy = Node_fifo_occupancy.read();
		lHW.dispatch();

		uint32_t occupancy = (fifo_occupancy.value() & 0xffff);

		// print very rough statistics
		if (verbose) {
			acc = (alpha * occupancy) + (1.0 - alpha) * acc;
			iter++;
			max_occ = std::max(max_occ, occupancy);
			if (iter == max_iter){
				std::cout << chip_id << ": " << (int)acc <<  " peak: " << max_occ << std::endl;
				iter=0;
				max_occ=0;
			}
		}

		if (occupancy == 0)
			continue;

		if (occupancy > Node_fifo_data.getSize())
			throw std::runtime_error("DAQ board returned an invalid fifo occupancy value");

		uhal::ValVector<uint32_t> data = Node_fifo_data.readBlock(occupancy);
		lHW.dispatch();

		if (data.size() < occupancy){
			std::cout << "fail to read data" << std::endl;
			continue;
		}

		outstrm.write((char*)data.value().data(), data.size()*4);
	}

	outstrm.close();
}


int DAQBoard_comm::start_daq(std::string chip_id, std::string fname){

	if (chip_stuctmap.find(chip_id) == chip_stuctmap.end()){
		std::cerr << "can't start thread, unknown id: " << chip_id << std::endl;
		return -1;
	}

	chip_stuctmap[chip_id]->run_flag = true;
	chip_stuctmap[chip_id]->dataread_thread =
		std::thread(&DAQBoard_comm::daq_loop, this, fname, chip_id);

	std::cout << chip_id << ": Data read thread started" << std::endl;

	return 0;
}


int DAQBoard_comm::stop_daq(std::string chip_id){

	if (chip_stuctmap.find(chip_id) == chip_stuctmap.end()){
		std::cerr << "can't stop thread, unknown id: " << chip_id << std::endl;
		return -1;
	}

	if (chip_stuctmap[chip_id]->run_flag == false)
		return 0;

	chip_stuctmap[chip_id]->run_flag = false;
	chip_stuctmap[chip_id]->dataread_thread.join();
	std::cout << chip_id << ": Data read thread stopped" << std::endl;

	return 0;
}
