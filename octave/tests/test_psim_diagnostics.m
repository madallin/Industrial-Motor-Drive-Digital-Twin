function test_psim_diagnostics()
  addpath(fileparts(fileparts(mfilename('fullpath'))));
  settings = load_motor_config();
  % Synthetic samples are test inputs only and are never published.
  state = []; activation = false; recovery = false;
  for sample_time = 0:0.001:2.5
    frequency = min(50,max(0,(sample_time-0.32)*50));
    voltage = 565*(1-exp(-sample_time/0.045));
    if sample_time >= 1.3 && sample_time < 1.75, voltage = 430; endif
    sample = [sample_time,0.98*30*frequency,3.5*sin(2*pi*50*sample_time),voltage,frequency];
    [state,reading,events] = diagnostic_psim(state,sample,settings.diagnostic);
    for index = 1:numel(events)
      event = events{index};
      if strcmp(event.code,'VDC_LOW_HIGH')
        activation |= strcmp(event.level,'ALARM');
        recovery |= strcmp(event.level,'CLEARED');
      endif
    endfor
  endfor
  assert(activation && recovery && strcmp(reading.status,'RUNNING'));
  assert(state.ready_qualified && isfinite(reading.rms_a));
  fprintf('Verificari Octave reusite: preincarcare, RMS si ciclu alarma/revenire.\n');
endfunction
