function [state, reading, events] = diagnostic_psim(state, sample, settings)
  if !isnumeric(sample) || numel(sample) != 5 || any(!isfinite(sample))
    error('diagnostic_psim: sunt necesare cinci valori numerice finite');
  endif
  % Preserve the CSV protocol and v6 fields for existing consumers.
  % RMS is estimated from 1 ms samples and is subject to PWM aliasing.
  sample = sample(:)';
  sample_time = sample(1); speed = sample(2); current = sample(3);
  voltage = sample(4); frequency = sample(5);
  events = {};

  if isempty(state)
    state = struct();
    state.i_t = []; state.i_v = [];
    state.vdc_t = []; state.vdc_v = [];
    state.last_t = -Inf;
    state.last_fref = 0;
    state.speed_ready_t = NaN;
    state.ready_candidate_since = NaN;
    state.ready_qualified = false;
    state.start_without_ready = false;
    state.active = false(1,8);
    state.raise_since = NaN(1,8);
    state.clear_since = NaN(1,8);
    state.status = 'INIT';
    state.max_rms_a = NaN;
    state.event_count = 0;
    state.gap_count = 0;
  endif
  if sample_time <= state.last_t
    error('diagnostic_psim: timpul simulat trebuie sa creasca');
  endif
  if isfinite(state.last_t) && (sample_time - state.last_t) > 0.015
    state.gap_count += 1;
    events{end+1} = diagnostic_event(sample_time,'INFO','DATA_GAP',sample_time-state.last_t);
    state.i_t = []; state.i_v = [];
    state.vdc_t = []; state.vdc_v = [];
    state.ready_candidate_since = NaN;
  endif
  state.last_t = sample_time;

  state.i_t(end+1) = sample_time;
  state.i_v(end+1) = current;
  retain = state.i_t >= sample_time-settings.sample_window_s-1e-10;
  state.i_t = state.i_t(retain); state.i_v = state.i_v(retain);
  if numel(state.i_t) > 20000
    state.i_t = state.i_t(end-19999:end); state.i_v = state.i_v(end-19999:end);
  endif
  rms_a = NaN;
  if numel(state.i_t) >= settings.sample_min_count && ...
     state.i_t(end)-state.i_t(1) >= 0.9*settings.sample_window_s
    rms_a = sqrt(mean(state.i_v.^2));
    if isnan(state.max_rms_a) || rms_a > state.max_rms_a
      state.max_rms_a = rms_a;
    endif
  endif

  idle_command = frequency < 1.0 && abs(speed) < 50.0;
  within_interval = voltage >= settings.ready_vdc_low_v && ...
                   voltage <= settings.ready_vdc_high_v;
  if state.ready_qualified && idle_command && !within_interval
    state.ready_qualified = false;
    state.ready_candidate_since = NaN;
    state.vdc_t = []; state.vdc_v = [];
    events{end+1} = diagnostic_event(sample_time,'INFO','PRECHARGE_RESET',voltage);
  endif
  if !state.ready_qualified && idle_command && within_interval
    if isnan(state.ready_candidate_since)
      state.ready_candidate_since = sample_time;
    endif
    state.vdc_t(end+1) = sample_time;
    state.vdc_v(end+1) = voltage;
    retain = state.vdc_t >= sample_time-settings.ready_hold_s-1e-10;
    state.vdc_t = state.vdc_t(retain);
    state.vdc_v = state.vdc_v(retain);
    if numel(state.vdc_t) > 20000
      state.vdc_t = state.vdc_t(end-19999:end); state.vdc_v = state.vdc_v(end-19999:end);
    endif
    if (sample_time-state.ready_candidate_since >= settings.ready_hold_s) && ...
       numel(state.vdc_t) >= settings.ready_min_count && ...
       (state.vdc_t(end)-state.vdc_t(1) >= 0.9*settings.ready_hold_s) && ...
       (max(state.vdc_v)-min(state.vdc_v) <= settings.ready_span_max_v)
      state.ready_qualified = true;
      events{end+1} = diagnostic_event(sample_time,'INFO','PRECHARGE_READY',voltage);
    endif
  elseif !state.ready_qualified
    state.ready_candidate_since = NaN;
    state.vdc_t = []; state.vdc_v = [];
  endif

  if frequency >= 1.0 && state.last_fref < 1.0 && !state.ready_qualified
    state.start_without_ready = true;
    events{end+1} = diagnostic_event(sample_time,'WARN','START_BEFORE_READY',voltage);
    state.event_count += 1;
  endif
  if frequency < 1.0 && state.last_fref >= 1.0
    if state.start_without_ready
      events{end+1} = diagnostic_event(sample_time,'CLEARED','START_BEFORE_READY',voltage);
    endif
    state.start_without_ready = false;
  endif
  state.last_fref = frequency;

  sync_rpm = 60*frequency/settings.motor_pole_pairs;
  speed_error_pct = NaN;
  if frequency >= settings.speed_enable_f_hz
    if isnan(state.speed_ready_t), state.speed_ready_t = sample_time; endif
    speed_error_pct = 100*abs(speed-sync_rpm)/max(abs(sync_rpm),1);
  else
    state.speed_ready_t = NaN;
  endif
  curent_valid = sample_time >= settings.current_enable_after_s && isfinite(rms_a);
  tensiune_valida = sample_time >= settings.vdc_enable_after_s;
  turatie_valida = isfinite(state.speed_ready_t) && ...
                  (sample_time-state.speed_ready_t >= settings.speed_settle_s);

  codes = {'I_RMS_WARN','I_RMS_HIGH', ...
           'VDC_LOW_WARN','VDC_LOW_HIGH', ...
           'VDC_HIGH_WARN','VDC_HIGH_HIGH', ...
           'SPEED_WARN','SPEED_HIGH'};
  levels = {'WARN','ALARM','WARN','ALARM','WARN','ALARM','WARN','ALARM'};
  values = [rms_a,rms_a,voltage,voltage,voltage,voltage,speed_error_pct,speed_error_pct];
  trip = false(1,8); recovery = false(1,8);
  if curent_valid
    trip(1:2) = [rms_a > settings.current_warn_a, rms_a > settings.current_alarm_a];
    recovery(1:2) = [rms_a < settings.current_clear_warn_a, ...
                     rms_a < settings.current_clear_alarm_a];
  else
    recovery(1:2) = true;
  endif
  if tensiune_valida
    trip(3:6) = [voltage < settings.vdc_warn_low_v, voltage < settings.vdc_alarm_low_v, ...
                    voltage > settings.vdc_warn_high_v, voltage > settings.vdc_alarm_high_v];
    recovery(3:6) = [voltage > settings.vdc_warn_low_clear_v, ...
                     voltage > settings.vdc_alarm_low_clear_v, ...
                     voltage < settings.vdc_warn_high_clear_v, ...
                     voltage < settings.vdc_alarm_high_clear_v];
  else
    recovery(3:6) = true;
  endif
  if turatie_valida
    trip(7:8) = [speed_error_pct > settings.speed_warn_pct, ...
                    speed_error_pct > settings.speed_alarm_pct];
    recovery(7:8) = [speed_error_pct < settings.speed_warn_clear_pct, ...
                     speed_error_pct < settings.speed_alarm_clear_pct];
  else
    recovery(7:8) = true;
  endif

  % Apply hysteresis and hold times independently for each severity level.
  for index = 1:8
    if !state.active(index)
      state.clear_since(index) = NaN;
      if trip(index)
        if isnan(state.raise_since(index))
          state.raise_since(index) = sample_time;
        elseif sample_time-state.raise_since(index) >= settings.warn_hold_s
          state.active(index) = true;
          state.raise_since(index) = NaN;
          events{end+1} = diagnostic_event(sample_time,levels{index},codes{index},values(index));
          state.event_count += 1;
        endif
      else
        state.raise_since(index) = NaN;
      endif
    else
      if recovery(index)
        if isnan(state.clear_since(index))
          state.clear_since(index) = sample_time;
        elseif sample_time-state.clear_since(index) >= settings.clear_hold_s
          state.active(index) = false;
          state.clear_since(index) = NaN;
          events{end+1} = diagnostic_event(sample_time,'CLEARED',codes{index},values(index));
        endif
      else
        state.clear_since(index) = NaN;
      endif
    endif
  endfor

  if any(state.active(2:2:8))
    status = 'ALARM';
  elseif any(state.active(1:2:8)) || state.start_without_ready
    status = 'WARNING';
  elseif idle_command
    if state.ready_qualified && within_interval
      status = 'READY';
    elseif voltage <= settings.stop_vdc_max_v
      status = 'STOP';
    else
      status = 'PRECHARGE';
    endif
  elseif !state.ready_qualified
    status = 'NOT_READY';
  elseif frequency >= settings.speed_enable_f_hz && turatie_valida
    status = 'RUNNING';
  else
    status = 'ACCELERATING';
  endif
  if !strcmp(status,state.status)
    events{end+1} = diagnostic_event(sample_time,'STATE',['TO_' status],NaN);
    state.status = status;
  endif
  reading = struct('t_s',sample_time,'rpm',speed,'current_a',current, ...
                   'rms_a',rms_a,'vdc_v',voltage,'fref_hz',frequency, ...
                   'sync_rpm',sync_rpm,'speed_error_pct',speed_error_pct, ...
                   'status',status,'active_alarm_count', ...
                   sum(state.active)+double(state.start_without_ready), ...
                   'precharge_qualified',state.ready_qualified);
endfunction

function event = diagnostic_event(sample_time,level,code,value)
  event = struct('t_s',sample_time,'level',level,'code',code,'value',value);
endfunction
