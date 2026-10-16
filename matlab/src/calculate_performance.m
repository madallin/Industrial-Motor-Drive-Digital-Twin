function perf = calculate_performance(p, m)
%CALCULATE_PERFORMANCE Compute baseline performance indicators.

    perf.apparentPower = ...
        m.inputPower / p.cosPhi;

    perf.reactivePower = ...
        sqrt(perf.apparentPower^2 - m.inputPower^2);

    perf.efficiency = ...
        p.Pn / m.inputPower;

    perf.powerFactor = ...
        p.cosPhi;

    perf.slipPercent = ...
        m.slip * 100;
end
