#ifndef DAQUTIL_H
#define DAQUTIL_H

#include <stdint.h>
#include <string>
#include <thread>
#include <atomic>
#include <map>

#include "uhal/uhal.hpp"

enum ARCADIA_command {
	ARCADIA_WR_PNTR = 0x0,
	ARCADIA_WR_DATA = 0x1,
	ARCADIA_WR_STAT = 0x2,
	ARCADIA_WR_ICR0 = 0x3,
	ARCADIA_WR_ICR1 = 0x4,
	ARCADIA_RD_PNTR = 0x8,
	ARCADIA_RD_DATA = 0x9,
	ARCADIA_RD_STAT = 0xa,
	ARCADIA_RD_ICR0 = 0xb,
	ARCADIA_RD_ICR1 = 0xc
};

struct arcadia_reg_param{
	int word_address;
	int mask;
	int offset;
	int default_value;
};


#define BIASX_REGMAP(X) \
	{"BIAS"#X"_VCAL_LO",    {12+((X)*3), 0x0001,  0,  0}}, \
	{"BIAS"#X"_VCAL_HI",    {12+((X)*3), 0x000f,  1, 15}}, \
	{"BIAS"#X"_VCASD",      {12+((X)*3), 0x0007,  5,  4}}, \
	{"BIAS"#X"_VCASP",      {12+((X)*3), 0x000f,  8,  4}}, \
	{"BIAS"#X"_ISF_VINREF", {12+((X)*3), 0x0007, 12,  7}}, \
	{"BIAS"#X"_IOTA",       {12+((X)*3), 0x0001, 15,  0}}, \
	{"BIAS"#X"_VCASN",      {12+((X)*3), 0x003f,  0, 33}}, \
	{"BIAS"#X"_ICLIP",      {13+((X)*3), 0x0003,  6,  1}}, \
	{"BIAS"#X"_IBIAS",      {13+((X)*3), 0x0003,  8,  2}}, \
	{"BIAS"#X"_VREF_LDO",   {13+((X)*3), 0x0003, 10,  1}}, \
	{"BIAS"#X"_IFB",        {13+((X)*3), 0x0003, 12,  2}}, \
	{"BIAS"#X"_ISF",        {13+((X)*3), 0x0003, 14,  2}}, \
	{"BIAS"#X"_BGR_MEAN",   {14+((X)*3), 0x000f,  0,  7}}, \
	{"BIAS"#X"_BGR_SLOPE",  {14+((X)*3), 0x000f,  4,  7}}, \
	{"BIAS"#X"_VINREF",     {14+((X)*3), 0x001f,  8,  7}}, \
	{"BIAS"#X"_ID",         {14+((X)*3), 0x0003, 13,  1}}, \
	{"BIAS"#X"_LDO_EN",     {14+((X)*3), 0x0001, 15,  1}},


static const std::map <std::string, arcadia_reg_param> GCR_map = {
	{"READOUT_CLK_DIVIDER",       {0, 0x000f,  0, 3}},
	{"TIMING_CLK_DIVIDER",        {0, 0x000f,  4, 8}},
	{"MAX_READS",                 {0, 0x000f,  8, 8}},
	{"TOKEN_COUNTER",             {0, 0x000f, 12, 8}},

	{"TEST_PULSE_MASK",           {1, 0xffff, 0, 0}},
	{"SECTION_READ_MASK",         {2, 0xffff, 0, 0}},
	{"SECTION_CLOCK_MASK",        {3, 0xffff, 0, 0}},

	{"DIGITAL_INJECTION",         {4, 0xffff, 0, 0}},
	{"FORCE_ENABLE_INJECTION",    {5, 0xffff, 0, 0xffff}},
	{"FORCE_DISABLE_MASK",        {6, 0xffff, 0, 0xffff}},

	{"OPERATION",                 {7, 0x0001, 0, 0}},
	{"SERIALIZER_SYNC",           {7, 0x0001, 1, 0}},
	{"LVDS_STRENGTH",             {7, 0x0007, 2, 4}},
	{"SECTION_CLOCK_GATING",      {7, 0x0001, 5, 0}},
	{"TIMESTAMP_LATCHES",         {7, 0x0001, 6, 1}},
	{"DISABLE_SMART_READOUT",     {7, 0x0001, 7, 0}},
	{"EOS_CLOCK_GATING_ENABLE",   {7, 0x0001, 8, 0}},

	{"HELPER_SECCFG_SECTIONS",    { 8, 0xffff,  0, 0xffff}},
	{"HELPER_SECCFG_COLUMNS",     { 9, 0xffff,  0, 0xffff}},
	{"HELPER_SECCFG_PRSTART",     {10, 0x007f,  0, 0x007f}},
	{"HELPER_SECCFG_PRSKIP",      {10, 0x007f,  7, 0x0000}},
	{"HELPER_SECCFG_CFGDATA",     {10, 0x0003, 14, 0x0001}},
	{"HELPER_SECCFG_PRSTOP",      {11, 0x007f,  0, 0x0000}},
	{"HELPER_SECCFG_PIXELSELECT", {11, 0x001f,  7, 0x001f}},

	BIASX_REGMAP(0)
	BIASX_REGMAP(1)
	BIASX_REGMAP(2)
	BIASX_REGMAP(3)
	BIASX_REGMAP(4)
	BIASX_REGMAP(5)
	BIASX_REGMAP(6)
	BIASX_REGMAP(7)
	BIASX_REGMAP(8)
	BIASX_REGMAP(9)
	BIASX_REGMAP(10)
	BIASX_REGMAP(11)
	BIASX_REGMAP(12)
	BIASX_REGMAP(13)
	BIASX_REGMAP(14)
	BIASX_REGMAP(15)
};


static const std::map <std::string, arcadia_reg_param> ctrl_cmd_map = {
	{"resetIDELAYTCTRL",    {0x01, 0x0001,  0, 0}},
	{"resetISERDES",        {0x02, 0x0001,  0, 0}},
	{"setIDELAYTap0",       {0x03, 0x001f,  0, 0}},
	{"setIDELAYTap1",       {0x03, 0x001f,  5, 0}},
	{"setIDELAYTap2",       {0x03, 0x001f, 10, 0}},
	{"setIDELAYTap3",       {0x03, 0x001f, 15, 0}},
	{"setIDELAYTap4",       {0x04, 0x001f,  0, 0}},
	{"setIDELAYTap5",       {0x04, 0x001f,  5, 0}},
	{"setIDELAYTap6",       {0x04, 0x001f, 10, 0}},
	{"setIDELAYTap7",       {0x04, 0x001f, 15, 0}},
	{"setIDELAYTap8",       {0x05, 0x001f,  0, 0}},
	{"setIDELAYTap9",       {0x05, 0x001f,  5, 0}},
	{"setIDELAYTapa",       {0x05, 0x001f, 10, 0}},
	{"setIDELAYTapb",       {0x05, 0x001f, 15, 0}},
	{"setIDELAYTapc",       {0x06, 0x001f,  0, 0}},
	{"setIDELAYTapd",       {0x06, 0x001f,  5, 0}},
	{"setIDELAYTape",       {0x06, 0x001f, 10, 0}},
	{"setIDELAYTapf",       {0x06, 0x001f, 15, 0}},
	{"setSyncResetPhase",   {0x07, 0x0001,  0, 0}},
	{"doRESET",             {0x08, 0x0001,  0, 0}},
	{"resetSPI",            {0x09, 0x0001,  0, 0}},
	{"resetCounters",       {0x10, 0x0001,  0, 0}},
	{"syncTX",              {0x11, 0x00ff,  0, 0}},
	{"readTxState",         {0x12, 0xffff,  0, 0}},
	{"read8b10bErrCounters",{0x13, 0x000f,  0, 0}},
};



class DAQBoard_comm{
private:

	const bool verbose = false;
	const std::string device_str;
	uhal::ConnectionManager ConnectionMgr;
	uhal::HwInterface lHW;

	struct chip_struct {
		std::thread dataread_thread;
		std::atomic_bool run_flag;
		bool spi_unavaiable;

		std::vector<uint16_t> GCR_address_array;
		std::vector<uint32_t> ctrl_address_array;

		chip_struct() : run_flag({false}), spi_unavaiable(false),
			GCR_address_array(GCR_map.size()), ctrl_address_array(ctrl_cmd_map.size()) {}
	};

	std::map<std::string, chip_struct*> chip_stuctmap;

	static int conf_handler(void* user, const char* section, const char* name,
			const char* value);

	void daq_loop(const std::string fname, std::string chip_id);

public:

	DAQBoard_comm(std::string connection_xml_path, std::string device_id, bool verbose=false);
	int read_conf(std::string fname);

	int spi_transfer(ARCADIA_command command, uint16_t payload, std::string chip_id, uint32_t* rcv_data);
	int read_register(std::string chip_id, uint16_t addr, uint16_t* data);
	int write_register(std::string chip_id, uint16_t addr, uint16_t data);
	int write_icr(std::string chip_id, std::string icr_reg, uint16_t data);
	int write_gcrpar(std::string chip_id, std::string gcrpar, uint16_t value);

	int read_fpga_register(std::string reg_handler, uint32_t* data);
	int write_fpga_register(std::string reg_handler, uint32_t data);
	int send_pulse(const std::string chip_id);
	void dump_DAQBoard_reg();
	int reset_fifo(std::string chip_id);

	int start_daq(std::string chip_id, std::string fname = "dout");
	int stop_daq(std::string chip_id);

};
#endif
