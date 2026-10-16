/* PSIM 9 x86 General DLL Block: four measurement inputs and three HMI outputs.
 * Inputs: RPM, I_MOTOR_U [A], VDC_LINK [V], F_REF [Hz].
 * Outputs: F_TARGET_HMI [Hz], RUN_HMI [0/1], LOAD_HMI [Nm].
 * The schematic uses one block instance; static state is shared by the DLL.
 * Nonblocking transport with a two-second wall-clock watchdog.
 */
#define WIN32_LEAN_AND_MEAN
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <stdio.h>
#include <string.h>
#include <math.h>
#include "drive_controller.h"

#ifndef PORT_HMI
#define PORT_HMI 5050
#endif
#define SAMPLE_INTERVAL 0.001
#define WATCHDOG_MS 2000

static SOCKET connection = INVALID_SOCKET;
static int winsock_started, connection_state, hello_pending, ack_pending, watchdog_expired;
static char send_buffer[256], receive_buffer[512];
static int send_length, send_offset, receive_length, drop_line;
static DWORD next_connection_at, last_command_at, last_ack_at;
static unsigned long sequence;
static int run_requested, controller_initialized, reset_request;
static unsigned long rejected_sequence;
static int rejection_reason, nack_pending;
static DWORD watchdog_timeout_ms = WATCHDOG_MS;
static DriveController drive;
static double accel_s = 2, decel_s = 5;
static double frequency_hz, load_nm, last_sim_time = -1, next_sample_at;

static void close_connection(void)
{
    if (drive.requested_run || drive.pwm) drive_trip(&drive, COMMUNICATION_LOSS);
    drive.configured = 0;
    if (connection != INVALID_SOCKET) closesocket(connection);
    connection = INVALID_SOCKET; connection_state = 0;
    send_length = send_offset = receive_length = drop_line = 0;
    run_requested = 0; frequency_hz = load_nm = 0; sequence = 0; watchdog_expired = 0;
    rejected_sequence = 0; rejection_reason = nack_pending = 0;
}

static void schedule_reconnect(DWORD now_ms)
{
    close_connection(); next_connection_at = now_ms + 100;
}

static void mark_connected(DWORD now_ms)
{
    connection_state = 2; hello_pending = ack_pending = 1;
    last_command_at = last_ack_at = now_ms;
}

static void connect_to_server(DWORD now_ms)
{
    struct sockaddr_in address;
    WSADATA winsock_data;
    u_long nonblocking = 1;
    int error_code;
    if (!winsock_started) {
        if (WSAStartup(MAKEWORD(2,2), &winsock_data)) { next_connection_at = now_ms+100; return; }
        winsock_started = 1;
    }
    connection = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    if (connection == INVALID_SOCKET || ioctlsocket(connection,FIONBIO,&nonblocking)) { schedule_reconnect(now_ms); return; }
    memset(&address,0,sizeof(address)); address.sin_family = AF_INET;
    address.sin_port = htons(PORT_HMI); address.sin_addr.s_addr = inet_addr("127.0.0.1");
    if (!connect(connection,(struct sockaddr *)&address,sizeof(address))) { mark_connected(now_ms); return; }
    error_code = WSAGetLastError();
    if (error_code == WSAEWOULDBLOCK || error_code == WSAEINPROGRESS || error_code == WSAEALREADY) connection_state = 1;
    else schedule_reconnect(now_ms);
}

static void check_connection(DWORD now_ms)
{
    fd_set writable, errors;
    struct timeval no_wait = {0,0};
    int error_code = 0, option_length = sizeof(error_code), result;
    FD_ZERO(&writable); FD_ZERO(&errors); FD_SET(connection,&writable); FD_SET(connection,&errors);
    result = select(0,NULL,&writable,&errors,&no_wait);
    if (result == SOCKET_ERROR) { schedule_reconnect(now_ms); return; }
    if (!result) return;
    if (getsockopt(connection,SOL_SOCKET,SO_ERROR,(char *)&error_code,&option_length) || error_code) schedule_reconnect(now_ms);
    else mark_connected(now_ms);
}

static void send_pending(DWORD now_ms)
{
    int sent;
    if (connection_state != 2 || !send_length) return;
    sent = send(connection,send_buffer+send_offset,send_length-send_offset,0);
    if (sent > 0) {
        send_offset += sent;
        if (send_offset == send_length) send_length = send_offset = 0;
    } else if (!sent || WSAGetLastError() != WSAEWOULDBLOCK) schedule_reconnect(now_ms);
}

static void process_command(DWORD now_ms)
{
    unsigned long new_sequence;
    int run, reset, result;
    double hz, nm, acceleration, deceleration;
    double rated, trip, low, high, rpm, ready_low, ready_high, watchdog_s;
    char trailing;
    if (sscanf(receive_buffer,"CFG,%lf,%lf,%lf,%lf,%lf,%lf,%lf,%lf,%lf,%lf%c",
        &hz,&nm,&rated,&trip,&low,&high,&rpm,&ready_low,&ready_high,&watchdog_s,&trailing) == 10) {
        if (isfinite(watchdog_s) && watchdog_s >= 1 && watchdog_s <= 10 &&
            drive_configure(&drive,hz,nm,rated,trip,low,high,rpm,ready_low,ready_high)) {
            watchdog_timeout_ms = (DWORD)(watchdog_s*1000);
            ack_pending = 1;
        }
        return;
    }
    if (sscanf(receive_buffer,"CMD,%lu,%d,%lf,%lf,%lf,%lf,%d%c",&new_sequence,&run,&hz,&nm,
        &acceleration,&deceleration,&reset,&trailing) != 7 ||
        !new_sequence || new_sequence > 2147483647UL || new_sequence < sequence ||
        (run != 0 && run != 1) || (reset != 0 && reset != 1)) return;
    if (new_sequence == sequence) {
        if (watchdog_expired || drive.fault || run != run_requested || hz != frequency_hz || nm != load_nm ||
            acceleration != accel_s || deceleration != decel_s || reset != reset_request) return;
        last_command_at = now_ms;
        return;
    }
    result = drive_command(&drive,run,hz,nm,acceleration,deceleration,reset);
    if (result != COMMAND_OK) {
        rejected_sequence = new_sequence; rejection_reason = result;
        nack_pending = 1;
        return;
    }
    sequence = new_sequence; run_requested = drive.requested_run; frequency_hz = hz; load_nm = nm;
    accel_s = acceleration; decel_s = deceleration; reset_request = reset;
    last_command_at = now_ms; watchdog_expired = 0; ack_pending = 1;
}

static void receive_commands(DWORD now_ms)
{
    char chunk[512];
    int received, index, batch;
    for (batch = 0; batch < 16 && connection_state == 2; ++batch) {
        received = recv(connection,chunk,sizeof(chunk),0);
        if (received <= 0) {
            if (!received || WSAGetLastError() != WSAEWOULDBLOCK) schedule_reconnect(now_ms);
            return;
        }
        for (index = 0; index < received; ++index) {
            if (chunk[index] == '\n') {
                receive_buffer[receive_length] = '\0';
                if (!drop_line) process_command(now_ms);
                receive_length = drop_line = 0;
            } else if (chunk[index] != '\r' && !drop_line) {
                if (receive_length < (int)sizeof(receive_buffer)-1) receive_buffer[receive_length++] = chunk[index];
                else drop_line = 1;
            }
        }
    }
}

__declspec(dllexport)
void __cdecl RUNSIMUSER(double t, double delt, double *in, double *out,
                        void **ptrUserData, int *pnError, char *szErrorMsg)
{
    DWORD now_ms = GetTickCount();
    int sample_due, previous_state, previous_fault;
    if (!controller_initialized) { drive_init(&drive); controller_initialized = 1; }
    (void)ptrUserData; (void)szErrorMsg;
    if (pnError) *pnError = 0;
    if (isfinite(t) && last_sim_time >= 0 && t < last_sim_time-1e-8) {
        close_connection(); drive_init(&drive); next_connection_at = now_ms; next_sample_at = 0;
    }
    last_sim_time = t;
    if (!connection_state && (!next_connection_at || (LONG)(now_ms-next_connection_at) >= 0)) connect_to_server(now_ms);
    if (connection_state == 1) check_connection(now_ms);
    if (connection_state == 2) {
        if ((drive.requested_run || drive.pwm) && now_ms-last_command_at > watchdog_timeout_ms) {
            drive_trip(&drive,COMMUNICATION_LOSS); run_requested = 0; watchdog_expired = 1; ack_pending = 1;
        }
        receive_commands(now_ms);
    }
    previous_state = drive.state; previous_fault = drive.fault;
    drive_step(&drive,delt,in);
    run_requested = drive.requested_run;
    if (previous_state != drive.state || previous_fault != drive.fault) ack_pending = 1;
    drive_outputs(&drive,out);
    if (connection_state != 2) return;
    send_pending(now_ms);
    if (send_length || connection_state != 2) {
        drive_outputs(&drive,out);
        return;
    }
    sample_due = isfinite(t) && t+0.5*(delt > 0 ? delt : 0) >= next_sample_at;
    if (hello_pending) {
        send_length = snprintf(send_buffer,sizeof(send_buffer),"HELLO,HMI,2\n"); hello_pending = 0;
    } else if (nack_pending) {
        send_length = snprintf(send_buffer,sizeof(send_buffer),"NACK,%lu,%d\n",
            rejected_sequence,rejection_reason);
        nack_pending = 0;
    } else if (ack_pending || now_ms-last_ack_at >= 200) {
        send_length = snprintf(send_buffer,sizeof(send_buffer),"ACK,%lu,%d,%.9g,%.9g,%d,2,%d,%d,%d,%.9g,%.9g,%.9g,%d\n",
            sequence,run_requested,frequency_hz,load_nm,watchdog_expired,drive.state,drive.fault,drive.pwm,
            drive.frequency_hz,accel_s,decel_s,drive.configured);
        ack_pending = 0; last_ack_at = now_ms;
    } else if (sample_due && in && isfinite(in[0]) && isfinite(in[1]) && isfinite(in[2]) && isfinite(in[3])) {
        send_length = snprintf(send_buffer,sizeof(send_buffer),"%.6f,%.9g,%.9g,%.9g,%.9g\n",t,in[0],in[1],in[2],in[3]);
    }
    if (sample_due) next_sample_at = t+SAMPLE_INTERVAL;
    if (send_length < 0 || send_length >= (int)sizeof(send_buffer)) send_length = 0;
    send_pending(now_ms);
    drive_outputs(&drive,out);
}

__declspec(dllexport)
void __cdecl CLOSESIMUSER(const char *szId, void **ptrUserData)
{
    (void)szId; (void)ptrUserData;
    close_connection();
    if (winsock_started) WSACleanup();
    controller_initialized = 0;
    winsock_started = 0; watchdog_timeout_ms = WATCHDOG_MS;
    last_sim_time = -1; next_sample_at = 0; next_connection_at = GetTickCount();
}
