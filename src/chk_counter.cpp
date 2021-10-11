#include <iostream>
#include <fstream>
#include <string.h>

bool verbose = false;
uint32_t word_cnt = 0;
uint64_t error_counter = 0;


void check_counter(const uint32_t *buffer, uint32_t len){

	static uint32_t counter = 0;
	static bool file_start = true;

	for(uint32_t n=0; n<len; n++){

		if(file_start){
			counter = buffer[0];
			file_start = false;
			continue;
		}

		if (counter == 0xffffffff)
			counter = 0;
		else
			counter++;

		if (buffer[n] != counter){
			error_counter++;
			if (verbose){
				std::cout << "error at offset: 0x" << std::hex << (word_cnt+n)*4
					<< " skip: 0x" << buffer[n]-counter << std::endl;
			}
			counter = buffer[n];
		}

	}

	word_cnt += len;

}


int main(int argc, char** argv){

	const unsigned int buffsize = 8000;

	if (argc < 2){
		std::cout << "expected filename" << std::endl;
		return -1;
	}

	std::ifstream data_ifstrm(argv[1], std::ios::binary);
	if (! data_ifstrm.is_open()){
		std::cout << "Can't open file: " << argv[1] << std::endl;
		return -1;
	}

	if (argc > 2 && (strcmp(argv[2], "-v") == 0))
		verbose = true;

	uint32_t buffer[buffsize];

	while(data_ifstrm.good()){
		data_ifstrm.read(reinterpret_cast<char *>(&buffer), buffsize*4);
		check_counter(buffer, data_ifstrm.gcount()/4);
	}

	std::cout << "Word count: " << word_cnt << std::endl;
	std::cout << "Errors: " << error_counter << std::endl;

	return 0;
}
