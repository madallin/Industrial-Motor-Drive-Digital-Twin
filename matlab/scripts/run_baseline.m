clear;
clc;
close all;

%% Paths
scriptDir = fileparts(mfilename('fullpath'));
matlabRoot = fileparts(scriptDir);

srcDir = fullfile(matlabRoot, 'src');
resultsDir = fullfile(matlabRoot, 'results');

addpath(srcDir);

%% Load parameters and calculate model
p = motor_parameters();

m = calculate_motor_model(p);

perf = calculate_performance(p, m);

%% Display results
fprintf('\n');
fprintf('========================================\n');
fprintf('  INDUSTRIAL DRIVE - BASELINE MODEL\n');
fprintf('========================================\n');

fprintf('\nMechanical:\n');

fprintf('Slip              = %.4f %%\n', ...
    m.slip * 100);

fprintf('Sync speed        = %.2f rpm\n', ...
    p.Ns);

fprintf('Nominal speed     = %.2f rpm\n', ...
    p.Nn);

fprintf('Nominal torque    = %.3f Nm\n', ...
    m.nominalTorque);

fprintf('Maximum torque    = %.3f Nm\n', ...
    m.maximumTorque);


fprintf('\nPower:\n');

fprintf('Input power       = %.2f W\n', ...
    m.inputPower);

fprintf('Output power      = %.2f W\n', ...
    p.Pn);

fprintf('Iron losses       = %.2f W\n', ...
    m.ironLosses);

fprintf('Apparent power    = %.2f VA\n', ...
    perf.apparentPower);

fprintf('Reactive power    = %.2f var\n', ...
    perf.reactivePower);

fprintf('Power factor      = %.3f\n', ...
    perf.powerFactor);

fprintf('Efficiency        = %.2f %%\n', ...
    perf.efficiency * 100);


fprintf('\nRotor branch:\n');

fprintf('Rrotor            = %.5f Ohm\n', ...
    m.Rrotor);

fprintf('Xrotor            = %.5f Ohm\n', ...
    m.XR);

fprintf('Lrotor            = %.6f H\n', ...
    m.Lrotor);

fprintf('Irotor            = %.3f A\n', ...
    m.Irotor);


fprintf('\nMagnetizing branch:\n');

fprintf('Rmag              = %.5f Ohm\n', ...
    m.Rmag);

fprintf('Xmag              = %.5f Ohm\n', ...
    m.Xmag);

fprintf('Lmag              = %.6f H\n', ...
    m.Lmag);

fprintf('Imag              = %.3f A\n', ...
    m.Imag);

fprintf('\n========================================\n');


%% Create results directory if it does not exist
if ~exist(resultsDir, 'dir')
    mkdir(resultsDir);
end


%% Save complete MATLAB/Octave structure
results.parameters = p;
results.model = m;
results.performance = perf;

matFile = fullfile(resultsDir, 'baseline_motor.mat');

save(matFile, 'results');


%% Export model results to CSV
%
% We intentionally do not use table() or writetable()
% so that this script also works in GNU Octave.

csvFile = fullfile(resultsDir, 'baseline_motor.csv');

fid = fopen(csvFile, 'w');

if fid == -1
    error('Could not create baseline_motor.csv');
end

fprintf(fid, 'Parameter,Value\n');

modelNames = fieldnames(m);

for i = 1:length(modelNames)

    name = modelNames{i};

    value = m.(name);

    if isnumeric(value) && isscalar(value)

        fprintf(fid, '%s,%.15g\n', ...
            name, value);

    end
end

fclose(fid);


%% Export performance results separately
performanceCsvFile = ...
    fullfile(resultsDir, 'baseline_performance.csv');

fid = fopen(performanceCsvFile, 'w');

if fid == -1
    error('Could not create baseline_performance.csv');
end

fprintf(fid, 'Parameter,Value\n');

performanceNames = fieldnames(perf);

for i = 1:length(performanceNames)

    name = performanceNames{i};

    value = perf.(name);

    if isnumeric(value) && isscalar(value)

        fprintf(fid, '%s,%.15g\n', ...
            name, value);

    end
end

fclose(fid);


%% Export input parameters separately
parametersCsvFile = ...
    fullfile(resultsDir, 'baseline_parameters.csv');

fid = fopen(parametersCsvFile, 'w');

if fid == -1
    error('Could not create baseline_parameters.csv');
end

fprintf(fid, 'Parameter,Value\n');

parameterNames = fieldnames(p);

for i = 1:length(parameterNames)

    name = parameterNames{i};

    value = p.(name);

    if isnumeric(value) && isscalar(value)

        fprintf(fid, '%s,%.15g\n', ...
            name, value);

    end
end

fclose(fid);


%% Final confirmation
fprintf('\nResults saved successfully:\n');

fprintf('  MAT model:       %s\n', ...
    matFile);

fprintf('  Model CSV:       %s\n', ...
    csvFile);

fprintf('  Performance CSV: %s\n', ...
    performanceCsvFile);

fprintf('  Parameters CSV:  %s\n', ...
    parametersCsvFile);

fprintf('\nPhase 1 baseline execution completed successfully.\n');
