function m = calculate_motor_model(p)
%CALCULATE_MOTOR_MODEL Compute the baseline induction motor model.
%
% The implementation follows the simplified equivalent-circuit equations
% used by this project's baseline model.

    validate_motor_parameters(p);

    %% Mechanical quantities
    m.slip = (p.Ns - p.Nn) / p.Ns;

    m.omegaSync = 2*pi*p.Ns / 60;
    m.omegaNominal = 2*pi*p.Nn / 60;

    %% Power and torque
    m.inputPower = p.Pn / p.eta;

    m.nominalTorque = p.Pn / m.omegaNominal;

    m.transmittedPower = ...
        m.nominalTorque * m.omegaSync;

    m.ironLosses = ...
        m.inputPower - m.transmittedPower;

    m.maximumTorque = ...
        m.nominalTorque * p.lambda;

    %% Rotor equivalent branch
    m.XR = ...
        (3 * p.Uphase^2) / ...
        (2 * m.omegaSync * m.maximumTorque);

    A = m.transmittedPower;
    B = -3 * p.Uphase^2;
    C = m.transmittedPower * m.XR^2;

    m.discriminant = B^2 - 4*A*C;

    if m.discriminant < 0
        error('Rotor resistance equation has no real solutions.');
    end

    delta = sqrt(m.discriminant);

    m.R1 = ...
        (3*p.Uphase^2 + delta) / ...
        (2*m.transmittedPower);

    m.R2 = ...
        (3*p.Uphase^2 - delta) / ...
        (2*m.transmittedPower);

    %% Rotor currents
    m.Ir1 = ...
        p.Uphase / sqrt(m.XR^2 + m.R1^2);

    m.Ir2 = ...
        p.Uphase / sqrt(m.XR^2 + m.R2^2);

    if m.Ir1 <= p.In
        m.Rrotor = m.R1;
        m.Irotor = m.Ir1;
    elseif m.Ir2 <= p.In
        m.Rrotor = m.R2;
        m.Irotor = m.Ir2;
    else
        error('Neither rotor-current solution satisfies In.');
    end

    %% Reactive power
    tanPhi = sqrt(1 - p.cosPhi^2) / p.cosPhi;

    m.Qrotor = ...
        3 * m.XR * m.Irotor^2;

    m.Qtotal = ...
        m.inputPower * tanPhi;

    m.Qmag = ...
        m.Qtotal - m.Qrotor;

    %% Magnetizing branch
    m.Imag = ...
        sqrt(m.ironLosses^2 + m.Qmag^2) ...
        / (3*p.Uphase);

    m.Xmag = ...
        m.Qmag / (3*m.Imag^2);

    m.Rmag = ...
        m.ironLosses / (3*m.Imag^2);

    %% Inductances
    m.Lmag = ...
        m.Xmag / (2*pi*p.f);

    m.Lrotor = ...
        m.XR / (2*pi*p.f);
end
