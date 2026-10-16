clear;
clc;

testDir = fileparts(mfilename('fullpath'));
modelRoot = fileparts(testDir);
srcDir = fullfile(modelRoot, 'src');

addpath(srcDir);

p = motor_parameters();
m = calculate_motor_model(p);

assert(m.slip > 0);
assert(m.slip < 1);

assert(m.nominalTorque > 0);
assert(m.maximumTorque > m.nominalTorque);

assert(m.Rrotor > 0);
assert(m.XR > 0);

assert(m.Lrotor > 0);
assert(m.Lmag > 0);

assert(m.Irotor <= p.In);

disp('All motor model tests passed.');
