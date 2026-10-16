function validate_motor_parameters(p)
%VALIDATE_MOTOR_PARAMETERS Validate the baseline motor parameter structure.

    assert(p.Pn > 0, ...
        'Pn must be greater than zero.');

    assert(p.Ns > 0, ...
        'Ns must be greater than zero.');

    assert(p.Nn > 0 && p.Nn < p.Ns, ...
        'Nn must satisfy 0 < Nn < Ns.');

    assert(p.In > 0, ...
        'In must be greater than zero.');

    assert(p.eta > 0 && p.eta <= 1, ...
        'Efficiency must be between 0 and 1.');

    assert(p.cosPhi > 0 && p.cosPhi <= 1, ...
        'Power factor must be between 0 and 1.');

    assert(p.lambda >= 1, ...
        'Maximum torque ratio must be >= 1.');

    assert(p.Uphase > 0, ...
        'Phase voltage must be greater than zero.');

    assert(p.f > 0, ...
        'Frequency must be greater than zero.');
end
