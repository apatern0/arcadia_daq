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



DAQBoard_comm::DAQBoard_comm(std::string connection_xml_path,	std::string device_id,
		bool verbose) :
		verbose(verbose),
		device_str(device_id),
		ConnectionMgr("file://" + connection_xml_path),
		lHW(ConnectionMgr.getDevice(device_str))
{

	// init flags
	for (auto &x: run_daq_flag)
		x = false;

	// init spi controller
	for (std::string id: master_ids){
		lHW.getNode(id + ".CTRL").write(0);
		lHW.getNode(id + ".SS").write(1);
	}

	try {
		lHW.dispatch();
	}
	catch(...){
		spi_unavaiable = true;
		std::cerr << "SPI core configuration fail" << std::endl;
	}

}


int DAQBoard_comm::read_conf(std::string fname){

	// init register array with default values
	for(auto const& reg: registers_map){
		arcadia_gcr_param const& param = reg.second;
		register_address_array[param.word_address] |= (param.default_value << param.offset);
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

	// parse section name
	std::string section_str(section);
	uint16_t chip_id;
	if (section_str == "id0"){
		chip_id = 0;
	}
	else if (section_str == "id1"){
		chip_id = 1;
	}
	else if (section_str == "id2"){
		chip_id = 2;
	}
	else {
		std::cerr << "Unknown section: " << section_str << std::endl;
		return inih_ERR;
	}

	// parse key/value
	std::string register_name(name);
	uint16_t reg_value = strtol(value, NULL, 0);

	// handle ICR0
	if (register_name == "ICR0"){
		//std::cout << "ICR0 :" << std::hex << reg_value << std::endl;
		self->spi_transfer(ARCADIA_WR_ICR0, reg_value, chip_id, NULL);
		return inih_OK;
	}

	// if not ICR0, lookup regname
	auto search = registers_map.find(name);
	if (search == registers_map.end()){
		std::cerr << "Warning: invalid conf key found: " << name << std::endl;
		return inih_ERR;
	}

	// write reg
	arcadia_gcr_param const& param = search->second;
	self->register_address_array[param.word_address] |=
		(reg_value & param.mask) << param.offset;

	//std::cout << "id: " << chip_id << " reg: " << param.word_address << " val: " <<
	//	std::hex << self->register_address_array[param.word_address] << std::endl;

	self->write_register(chip_id, param.word_address,
			self->register_address_array[param.word_address]);

	return inih_OK;
}


int DAQBoard_comm::spi_transfer(ARCADIA_command command, uint16_t payload, uint8_t chip_id,
		uint32_t* rcv_data){

	const uhal::Node& SPI_CTRL_Node = lHW.getNode(master_ids[chip_id] + ".CTRL");
	const uhal::Node& SPI_TxRx_node = lHW.getNode(master_ids[chip_id] + ".TxRx0");

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


int DAQBoard_comm::read_register(uint8_t chip_id, uint16_t addr, uint16_t* data){

	if (spi_unavaiable)
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


int DAQBoard_comm::write_register(uint8_t chip_id, uint16_t addr, uint16_t data){

	if (spi_unavaiable)
		return -1;

	int gcr_address = addr | 0x2000;
	int res;
	res = spi_transfer(ARCADIA_WR_PNTR, gcr_address, chip_id, NULL);
	res = spi_transfer(ARCADIA_WR_DATA, data, chip_id, NULL);

	return res;
}


int DAQBoard_comm::read_fpga_register(const std::string reg_handle, uint32_t* data){

	const uhal::Node& reg_Node = lHW.getNode("regfile." + reg_handle);

	uhal::ValWord<uint32_t> reg_data = reg_Node.read();
	lHW.dispatch();

	*data = reg_data.value();

	return 0;
}


int DAQBoard_comm::write_fpga_register(const std::string reg_handle, uint32_t data){

	const uhal::Node& reg_Node = lHW.getNode("regfile." + reg_handle);

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


void DAQBoard_comm::daq_loop(const std::string fname, uint8_t chip_id){

	const std::string id_str = std::to_string(chip_id);
	const std::string filename = fname + id_str + ".raw";

	const uhal::Node& Node_fifo_occupancy = lHW.getNode("fifo_id" + id_str + ".occupancy");
	const uhal::Node& Node_fifo_data = lHW.getNode("fifo_id" + id_str + ".data");
	std::ofstream outstrm(filename, std::ios::out | std::ios::trunc | std::ios::binary);

	if (!outstrm.is_open())
		throw std::runtime_error("Can't open file for write");

	const int max_iter = 5000;
	uint32_t iter = 0, max_occ = 0;
	double acc = 0.0;
	const double alpha = 1.0/max_iter;

	while (run_daq_flag[chip_id]){
		uhal::ValWord<uint32_t> fifo_occupancy = Node_fifo_occupancy.read();
		lHW.dispatch();

		uint32_t occupancy = (fifo_occupancy.value() & 0xffff);

		// print very rough statistics
		if (verbose) {
			acc = (alpha * occupancy) + (1.0 - alpha) * acc;
			iter++;
			max_occ = std::max(max_occ, occupancy);
			if (iter == max_iter){
				std::cout << (int)chip_id << ": " << (int)acc <<  " peak: " << max_occ << std::endl;
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


int DAQBoard_comm::start_daq(uint8_t chip_id, std::string fname){

	if (chip_id > 2)
		return -1;

	run_daq_flag[chip_id] = true;
	data_reader[chip_id] = std::thread(&DAQBoard_comm::daq_loop, this, fname, chip_id);
	std::cout << (int)chip_id << ": Data read thread started" << std::endl;

	return 0;
}


int DAQBoard_comm::stop_daq(uint8_t chip_id){

	if (chip_id > 2)
		return -1;

	if (!run_daq_flag[chip_id])
		return 0;

	run_daq_flag[chip_id] = false;
	data_reader[chip_id].join();
	std::cout << (int)chip_id << ": Data read thread stopped" << std::endl;

	return 0;
}
