function p = motor_parameters()
%MOTOR_PARAMETERS Baseline parameter set for the induction motor model.
%
% All electrical values use SI units.
% Uphase is the RMS phase-to-neutral voltage.

    % Rated motor data
    p.Pn = 4000;          % Rated mechanical output power [W]
    p.Ns = 1500;          % Synchronous speed [rpm]
    p.Nn = 1430;          % Nominal rotor speed [rpm]
    p.In = 8.2;           % Nominal current [A]

    p.eta = 0.86;         % Efficiency [0...1]
    p.cosPhi = 0.82;      % Power factor [0...1]
    p.lambda = 2.2;       % Maximum torque / nominal torque

    % Electrical supply
    p.Uphase = 230;       % RMS phase-to-neutral voltage [V]
    p.f = 50;             % Supply frequency [Hz]
end
