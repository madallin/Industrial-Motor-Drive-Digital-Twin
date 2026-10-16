#include <assert.h>
#include <math.h>
#include <stdio.h>
#include "../bridge/drive_controller.h"

static DriveController controller(void)
{
    DriveController d;
    drive_init(&d);
    assert(drive_configure(&d,50,10,8.2,12.3,470,650,1650,510,610));
    return d;
}

static void step(DriveController *d, double seconds, double current,
                 double voltage, double rotor_override)
{
    int i;
    for (i=0; i<(int)(seconds*1000); ++i) {
        double rpm = isfinite(rotor_override) ? rotor_override : d->frequency_hz*30;
        double in[4] = {rpm,current,voltage,d->frequency_hz};
        drive_step(d,0.001,in);
    }
}

int main(void)
{
    DriveController d = controller();
    DriveController blocked, acceleration_failed;
    double out[3];
    assert(drive_command(&d,1,50,5,2,5,0) == COMMAND_NOT_READY);
    step(&d,0.2,0,565,NAN);
    assert(d.state == READY);
    assert(drive_command(&d,1,51,5,2,5,0) == COMMAND_INVALID);
    assert(drive_command(&d,1,50,5,2,5,0) == COMMAND_OK);
    step(&d,1,0,565,NAN);
    assert(d.pwm && d.state == STARTING && d.frequency_hz > 24);
    assert(drive_command(&d,1,50,5,2,5,0) == COMMAND_OK);
    step(&d,1.3,0,565,NAN);
    assert(d.state == RUNNING);
    assert(drive_command(&d,0,50,5,2,5,0) == COMMAND_OK);
    step(&d,1,0,565,NAN);
    drive_outputs(&d,out);
    assert(d.state == STOPPING && out[1] == 1 && out[0] > 39);
    assert(drive_command(&d,1,50,5,2,5,0) == COMMAND_STOPPING);
    assert(drive_command(&d,0,50,5,2,5,0) == COMMAND_OK);
    step(&d,4.2,0,565,120);
    assert(!d.pwm && d.state == COASTING);
    drive_outputs(&d,out);
    assert(out[2] == 5);
    assert(drive_command(&d,1,50,5,2,5,0) == COMMAND_STOPPING);
    step(&d,0.05,0,565,9);
    assert(d.state == COASTING);
    step(&d,0.07,0,565,9);
    assert(d.state == STOPPED);
    assert(drive_command(&d,1,25,5,2,5,0) == COMMAND_OK);
    step(&d,1.2,13,565,NAN);
    assert(d.fault == OVERCURRENT && !d.pwm);
    assert(drive_command(&d,1,25,5,2,5,0) == COMMAND_FAULT);
    blocked = controller();
    step(&blocked,0.2,0,565,0);
    assert(drive_command(&blocked,1,25,5,2,5,0) == COMMAND_OK);
    step(&blocked,2,5,565,0);
    assert(blocked.state == STARTING);
    step(&blocked,2.2,5,565,0);
    assert(blocked.fault == MOTOR_STALL && !blocked.pwm);
    acceleration_failed = controller();
    step(&acceleration_failed,0.2,0,565,0);
    assert(drive_command(&acceleration_failed,1,25,5,2,5,0) == COMMAND_OK);
    step(&acceleration_failed,6.2,0,565,0);
    assert(acceleration_failed.fault == ACCELERATION_FAILED && !acceleration_failed.pwm);
    step(&d,0.3,0,660,0);
    assert(drive_command(&d,0,25,5,2,5,1) == COMMAND_RESET_BLOCKED);
    step(&d,0.05,0,565,0);
    assert(drive_command(&d,0,25,5,2,5,1) == COMMAND_RESET_BLOCKED);
    step(&d,0.25,0,565,0);
    assert(drive_command(&d,0,25,5,2,5,1) == COMMAND_OK);
    assert(!d.fault && !d.requested_run);
    step(&d,0.2,0,565,0);
    assert(d.state == STOPPED);
    assert(drive_command(&d,1,25,5,2,5,0) == COMMAND_OK);
    step(&d,0.1,0,565,NAN);
    drive_trip(&d,COMMUNICATION_LOSS);
    assert(d.fault == COMMUNICATION_LOSS && !d.pwm);
    assert(drive_command(&d,1,25,5,2,5,0) == COMMAND_FAULT);
    puts("Controler: interblocari, feedback, STOP, inertie, defect memorat si RESET verificate.");
    return 0;
}
