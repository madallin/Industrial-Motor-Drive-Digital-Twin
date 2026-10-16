/* Drive sequencing and simulated protections; PSIM computes the motor dynamics. */
#ifndef DRIVE_CONTROLLER_H
#define DRIVE_CONTROLLER_H
#include <math.h>
#include <string.h>

enum DriveState { PRECHARGE, READY, STARTING, RUNNING, STOPPING, STOPPED, FAULT, COASTING };
enum DriveFault { NO_FAULT, OVERCURRENT, UNDERVOLTAGE, OVERVOLTAGE, OVERSPEED,
                  COMMUNICATION_LOSS, INVALID_FEEDBACK, STOP_TIMEOUT,
                  PRECHARGE_TIMEOUT, THERMAL_OVERLOAD, MOTOR_STALL, ACCELERATION_FAILED };
enum CommandResult { COMMAND_OK, COMMAND_INVALID, COMMAND_NOT_READY, COMMAND_FAULT,
                     COMMAND_ROTOR_MOVING, COMMAND_STOPPING, COMMAND_RESET_BLOCKED };
typedef struct {
    int configured, requested_run, pwm, state, fault, has_run;
    double target_hz, load_nm, accel_s, decel_s, frequency_hz;
    double max_hz, max_load_nm, rated_current_a, trip_current_a;
    double low_v, high_v, max_rpm, ready_low_v, ready_high_v;
    double ready_s, start_s, stop_s, low_s, overload_s, thermal, stall_s, stopped_s, stationary_s, settled_s;
    double sum_i2, window_s, rms_a, measured_rpm, measured_hz, measured_v;
} DriveController;

static void drive_init(DriveController *d)
{
    memset(d, 0, sizeof(*d));
    d->state = PRECHARGE; d->accel_s = 2; d->decel_s = 5;
}

static void drive_trip(DriveController *d, int fault)
{
    if (!d->fault) d->fault = fault;
    d->requested_run = d->pwm = 0;
    d->frequency_hz = 0; d->state = FAULT;
}

static int drive_configure(DriveController *d, double hz, double nm, double rated,
    double trip, double low, double high, double rpm, double ready_low, double ready_high)
{
    if (d->configured || !isfinite(hz) || !isfinite(nm) || !isfinite(rated) ||
        !isfinite(trip) || !isfinite(low) || !isfinite(high) || !isfinite(rpm) ||
        !isfinite(ready_low) || !isfinite(ready_high) || hz <= 0 || hz > 50 ||
        nm <= 0 || nm > 10 || rated <= 0 || rated > 100 || trip < rated ||
        trip > 2*rated || low <= 0 || !(low < ready_low && ready_low < ready_high &&
        ready_high < high) || high > 1000 || rpm <= 0 || rpm > 10000) return 0;
    d->max_hz = hz; d->max_load_nm = nm; d->rated_current_a = rated;
    d->trip_current_a = trip; d->low_v = low; d->high_v = high;
    d->max_rpm = rpm; d->ready_low_v = ready_low; d->ready_high_v = ready_high;
    d->configured = 1;
    return 1;
}

static int drive_command(DriveController *d, int run, double hz, double nm,
                         double accel, double decel, int reset)
{
    if (!d->configured || !isfinite(hz) || !isfinite(nm) || !isfinite(accel) ||
        !isfinite(decel) || hz < 0 || hz > d->max_hz || nm < 0 || nm > d->max_load_nm ||
        accel < 1 || accel > 30 || decel < 2 || decel > 60 || (run && hz == 0) ||
        (reset && run)) return COMMAND_INVALID;
    if (reset) {
        if (d->stationary_s < 0.1 || d->ready_s < 0.1 ||
            d->rms_a > 0.9*d->trip_current_a || d->thermal > 5 ||
            d->measured_v > d->high_v || d->measured_v < d->low_v || d->pwm)
            return COMMAND_RESET_BLOCKED;
        d->fault = 0; d->low_s = d->overload_s = d->start_s = d->stop_s = d->stall_s = 0;
        d->stopped_s = 0;
    }
    if (d->fault && run) return COMMAND_FAULT;
    /* Restart during coasting requires rotor synchronization, which is unavailable. */
    if (run && !d->requested_run) {
        if (d->state == STOPPING || d->state == COASTING) return COMMAND_STOPPING;
        if (d->pwm || fabs(d->measured_rpm) >= 10) return COMMAND_ROTOR_MOVING;
        if (d->ready_s < 0.1 || d->measured_v < d->ready_low_v ||
            d->measured_v > d->ready_high_v || d->state == PRECHARGE)
            return COMMAND_NOT_READY;
    }
    if (!run && d->requested_run) {
        /* Begin deceleration from the frequency measured after PSIM's ramp limiter. */
        d->frequency_hz = fmin(d->frequency_hz, fmax(0, d->measured_hz));
        d->stop_s = 0;
    }
    d->requested_run = run; d->target_hz = hz; d->load_nm = nm;
    d->accel_s = accel; d->decel_s = decel;
    return COMMAND_OK;
}

static void drive_step(DriveController *d, double dt, const double *in)
{
    double target, change, ratio;
    int i;
    if (!in || !isfinite(dt) || dt <= 0) { d->stationary_s = 0; drive_trip(d, INVALID_FEEDBACK); return; }
    for (i=0; i<4; ++i) if (!isfinite(in[i])) { d->stationary_s = 0; drive_trip(d, INVALID_FEEDBACK); return; }
    if (in[2] < 0 || in[3] < -0.1) { d->stationary_s = 0; drive_trip(d, INVALID_FEEDBACK); return; }
    d->measured_rpm = in[0]; d->measured_v = in[2]; d->measured_hz = in[3];
    d->stationary_s = fabs(in[0]) < 10 ? fmin(0.2,d->stationary_s + dt) : 0;
    /* Integrate current at the solver time step rather than the 1 ms TCP rate. */
    d->sum_i2 += in[1]*in[1]*dt; d->window_s += dt;
    if (d->window_s >= 0.02) {
        d->rms_a = sqrt(d->sum_i2/d->window_s);
        d->sum_i2 = d->window_s = 0;
    }
    if (!d->configured) return;
    if (in[2] >= d->ready_low_v && in[2] <= d->ready_high_v)
        d->ready_s = fmin(0.2, d->ready_s + dt);
    else d->ready_s = 0;
    if (in[2] > d->high_v) drive_trip(d, OVERVOLTAGE);
    if (fabs(in[0]) > d->max_rpm) drive_trip(d, OVERSPEED);
    if (d->pwm) {
        if (fabs(in[1]) > 3*sqrt(2.0)*d->rated_current_a) drive_trip(d, OVERCURRENT);
        d->low_s = in[2] < d->low_v ? d->low_s + dt : 0;
        if (d->low_s >= 0.05) drive_trip(d, UNDERVOLTAGE);
        d->overload_s = d->rms_a > d->trip_current_a ? d->overload_s + dt : 0;
        if (d->overload_s >= 0.2) drive_trip(d, OVERCURRENT);
    } else d->low_s = d->overload_s = 0;
    ratio = d->rms_a/d->rated_current_a;
    d->thermal = fmax(0, d->thermal + (ratio*ratio - 1)*dt);
    if (d->thermal >= 20) drive_trip(d, THERMAL_OVERLOAD);
    if (d->fault) { d->state = FAULT; return; }
    if (d->requested_run && !d->pwm) {
        d->start_s += dt;
        if (d->start_s >= 10) { drive_trip(d, PRECHARGE_TIMEOUT); return; }
        if (d->ready_s < 0.1) { d->state = PRECHARGE; return; }
        d->pwm = 1; d->start_s = 0; d->has_run = 1;
    }
    target = d->requested_run ? d->target_hz : 0;
    change = d->max_hz * dt / (target >= d->frequency_hz ? d->accel_s : d->decel_s);
    /* Hold frequency increases at high current; active faults still trip. */
    if (target > d->frequency_hz && d->rms_a > 1.1*d->rated_current_a) change = 0;
    if (target >= d->frequency_hz) d->frequency_hz = fmin(target, d->frequency_hz + change);
    else d->frequency_hz = fmax(target, d->frequency_hz - change);
    if (d->requested_run) {
        d->stop_s = 0;
        d->settled_s = fabs(in[3]-target) <= 0.2 &&
            fabs(d->frequency_hz-target) <= 0.2 &&
            (target >= 5 ? (in[0] >= 0.8*30*target && in[0] <= 1.1*30*target)
                         : fabs(in[0]-30*target) <= 15)
            ? d->settled_s + dt : 0;
        d->state = d->settled_s >= 0.2 ? RUNNING : STARTING;
        /* The positive-direction V/f model has four poles: n_sync = 30 * f. */
        d->stall_s = fabs(in[3]-target) <= 0.2 && in[3] >= 5 &&
            fabs(in[0]) < 0.2*30*in[3]
            ? d->stall_s + dt : 0;
        if (d->stall_s >= 3 && d->rms_a >= 0.5*d->rated_current_a)
            drive_trip(d, MOTOR_STALL);
        else if (d->stall_s >= 5) drive_trip(d, ACCELERATION_FAILED);
    } else {
        d->stall_s = 0;
        d->settled_s = 0;
        d->start_s = 0;
        if (d->frequency_hz <= 0.01 && in[3] <= 0.2) d->pwm = 0;
        if (d->pwm) {
            d->state = STOPPING; d->stop_s += dt; d->stopped_s = 0;
            if (d->stop_s >= d->decel_s + 20) drive_trip(d, STOP_TIMEOUT);
        } else if (fabs(in[0]) >= 10) {
            d->state = COASTING; d->stop_s += dt; d->stopped_s = 0;
            if (d->stop_s >= d->decel_s + 20) drive_trip(d, STOP_TIMEOUT);
        } else {
            d->stopped_s += dt;
            d->state = d->stopped_s >= 0.1
                ? (d->ready_s >= 0.1 ? (d->has_run ? STOPPED : READY) : PRECHARGE)
                : (d->has_run ? COASTING : PRECHARGE);
        }
    }
}

static void drive_outputs(const DriveController *d, double *out)
{
    if (!out) return;
    out[0] = d->pwm ? d->frequency_hz : 0;
    out[1] = d->pwm;
    /* LOAD_MECH stays mechanically coupled and resists coasting rotation. */
    out[2] = d->load_nm * fmin(1, fabs(d->measured_rpm)/50.0);
}
#endif
