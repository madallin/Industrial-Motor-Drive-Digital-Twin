# GNU Octave module

This directory contains the live PSIM data path and a separate analytical motor model.

## Runtime

`run_psim_supervisor.m` is launched by the Python orchestrator. It receives measurement frames and control feedback from the PSIM DLL, forwards validated commands, computes measurement-derived diagnostics, and writes session data. It does not simulate the electrical drive.

The runtime requires GNU Octave and the `instrument-control` package for TCP communication. The supervisor and diagnostics use Octave-specific syntax and APIs; the live runtime is not MATLAB-compatible as-is.

## Analytical model

`src/` contains standalone induction-motor calculations. `scripts/run_baseline.m` is the explicit entry point, and `tests/test_motor_model.m` checks the model. These files use MATLAB-compatible `.m` syntax and are intended to run in MATLAB and GNU Octave. MATLAB execution should be verified in the target MATLAB release before relying on it.

From this directory, run the model in either environment with:

```matlab
run('scripts/run_baseline.m')
```

Run the numerical model test with:

```matlab
run('tests/test_motor_model.m')
```

The PSIM diagnostics test uses Octave-specific syntax and should be run in GNU Octave:

```octave
addpath('tests');
test_psim_diagnostics();
```

## Data and configuration

The orchestrator passes the validated runtime configuration through `IDRIVE_CONFIG_RUNTIME`. Manual runs use the shared configuration at `../config/app_config.json`. Runtime recordings are written under `results/`; generated files are ignored by Git, while `.gitkeep` preserves the directory.

Only one receiver should own the configured PSIM TCP port, `5050` by default. RMS and diagnostic values derived from decimated telemetry are estimates; protection decisions are implemented in the DLL.
