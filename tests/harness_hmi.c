/* x86 host for testing the DLL contract without the PSIM motor circuit. */
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <stdio.h>
#include <stdlib.h>

typedef void (__cdecl *SimulationStep)(double,double,double*,double*,void**,int*,char*);
typedef void (__cdecl *SimulationClose)(const char*,void**);

int main(int argc, char **argv)
{
    HMODULE dll;
    SimulationStep step_s;
    SimulationClose close_simulation;
    double inputs[4] = {0,0,565,0}, outputs[3], time_s = 0;
    void *winsock_data = NULL;
    int error, index;
    char message[256] = {0};
    if (argc != 2) return 2;
    dll = LoadLibraryA(argv[1]);
    if (!dll) return 3;
    step_s = (SimulationStep)(void *)GetProcAddress(dll,"RUNSIMUSER");
    close_simulation = (SimulationClose)(void *)GetProcAddress(dll,"CLOSESIMUSER");
    if (!step_s || !close_simulation) return 4;
    for (index = 0; index < 12000; ++index) {
        step_s(time_s,0.005,inputs,outputs,&winsock_data,&error,message);
        inputs[0] = outputs[0]*30; inputs[3] = outputs[0];
        printf("%.3f,%.6f,%.0f,%.6f\n",time_s,outputs[0],outputs[1],outputs[2]);
        fflush(stdout); Sleep(5); time_s += 0.005;
    }
    close_simulation("verificare",&winsock_data); FreeLibrary(dll);
    return 0;
}
