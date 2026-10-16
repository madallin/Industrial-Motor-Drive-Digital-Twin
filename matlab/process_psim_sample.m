function receiver = process_psim_sample(receiver, settings)
  if isempty(receiver.server)
    try
      receiver.server = tcpserver('127.0.0.1', settings.psim.port_tcp);
      set(receiver.server,'Timeout',0.05);
      receiver.eroare = '';
    catch error
      receiver.eroare = ['Receptor PSIM indisponibil: ' error.message];
    end_try_catch
    return;
  endif
  % instrument-control can keep Connected=true after EOF. Release the stale
  % listener and recreate it on the next iteration for a new PSIM TCP session.
  last_traffic = max(receiver.ultim_epoch,receiver.ack_epoch);
  if last_traffic > 0 && time()-last_traffic > max(4,settings.date_vechi_s+1)
    close_recording(receiver.sesiune,settings,'INREGISTRARE');
    receiver.sesiune = []; receiver.diagnostic = []; receiver.ultim_timp = -Inf;
    receiver.server = []; receiver.hmi = false; receiver.canal_id = '';
    receiver.comanda = []; receiver.respingere = []; receiver.buffer = '';
    receiver.ack_epoch = 0; receiver.ultim_epoch = 0;
    return;
  endif
  connected = receiver.server.Connected;
  if !connected
    receiver.hmi = false; receiver.canal_id = ''; receiver.comanda = []; receiver.buffer = '';
    return;
  endif
  available_bytes = receiver.server.NumBytesAvailable;
  if available_bytes <= 0, return; endif
  received_bytes = read(receiver.server, min(available_bytes, 65536), 'uint8');
  receiver.buffer = [receiver.buffer char(received_bytes(:).')];
  terminators = find(receiver.buffer == char(10));
  cursor = 1;
  for index = 1:numel(terminators)
    end_time = terminators(index);
    columns = strsplit(strtrim(receiver.buffer(cursor:end_time-1)), ',');
    cursor = end_time + 1;
    if numel(columns) == 3 && strcmp(columns{1},'HELLO') && strcmp(columns{2},'HMI') && any(strcmp(columns{3},{'1','2'}))
      receiver.hmi = true; receiver.protocol = str2double(columns{3});
      receiver.canal_id = sprintf('%.6f',time());
      receiver.comanda = []; receiver.respingere = []; receiver.ultima_secventa_ceruta = 0;
      receiver.ack_epoch = 0;
      receiver.control = struct('secventa',0,'mod','manual','pornit',false,'frecventa_hz',0,'sarcina_nm',0,'watchdog',false,'protocol',receiver.protocol,'configured',false,'fault',0);
      continue;
    endif
    if receiver.hmi && receiver.protocol == 2 && numel(columns) == 3 && strcmp(columns{1},'NACK')
      rejection = str2double(columns(2:end));
      if all(isfinite(rejection)) && rejection(1) > 0 && fix(rejection(1)) == rejection(1) && ...
          any(rejection(2) == 1:6) && !isempty(receiver.comanda) && receiver.comanda.secventa == rejection(1)
        receiver.respingere = struct('secventa',rejection(1),'motiv',rejection(2));
        receiver.ultima_secventa_ceruta = max(receiver.ultima_secventa_ceruta,rejection(1));
        receiver.comanda = [];
        if !isempty(receiver.sesiune)
          fprintf(receiver.sesiune.evenimente,'%.6f,INFO,CMD_REJECT_%d,%.9g\n', ...
            max(0,receiver.ultim_timp),rejection(2),rejection(1));
        endif
      endif
      continue;
    endif
    if receiver.hmi && receiver.protocol == 2 && numel(columns) == 14 && strcmp(columns{1},'ACK')
      ack = str2double(columns(2:end));
      if all(isfinite(ack)) && ack(1) >= 0 && fix(ack(1)) == ack(1) && any(ack(2) == [0 1]) && ...
          ack(3) >= 0 && ack(3) <= 50 && ack(4) >= 0 && ack(4) <= 10 && ...
          any(ack(5) == [0 1]) && ack(6) == 2 && any(ack(7) == 0:7) && ...
          any(ack(8) == 0:11) && any(ack(9) == [0 1]) && ack(10) >= 0 && ack(10) <= 50 && ...
          ack(11) >= 1 && ack(11) <= 30 && ack(12) >= 2 && ack(12) <= 60 && any(ack(13) == [0 1])
        states = {'PRECHARGE','READY','STARTING','RUNNING','STOPPING','STOPPED','FAULT','COASTING'};
        previous_sequence = receiver.control.secventa;
        previous_state = '';
        if isfield(receiver.control,'drive_state'), previous_state = receiver.control.drive_state; endif
        receiver.control = struct('secventa',ack(1),'mod','manual','pornit',logical(ack(2)), ...
          'frecventa_hz',ack(3),'sarcina_nm',ack(4),'watchdog',logical(ack(5)), ...
          'protocol',2,'drive_state',states{ack(7)+1},'fault',ack(8),'pwm_enabled',logical(ack(9)), ...
          'output_frequency_hz',ack(10),'acceleration_s',ack(11),'deceleration_s',ack(12),'configured',logical(ack(13)));
        receiver.ack_epoch = time();
        if !isempty(receiver.sesiune)
          event_time = max(0,receiver.ultim_timp);
          if ack(1) > previous_sequence
            fprintf(receiver.sesiune.evenimente,'%.6f,INFO,CMD_ACCEPTED,%.9g\n',event_time,ack(1));
          endif
          if !strcmp(previous_state,states{ack(7)+1})
            fprintf(receiver.sesiune.evenimente,'%.6f,STATE,DRIVE_%s,%.9g\n', ...
              event_time,states{ack(7)+1},ack(8));
          endif
        endif
        if !isempty(receiver.respingere) && ack(1) > receiver.respingere.secventa
          receiver.respingere = [];
        endif
      endif
      continue;
    endif
    if receiver.hmi && numel(columns) == 7 && strcmp(columns{1},'ACK')
      ack = str2double(columns(2:end));
      if all(isfinite(ack)) && ack(1) >= 0 && fix(ack(1)) == ack(1) && any(ack(2) == [0 1]) && ...
          ack(3) >= 0 && ack(3) <= 1000 && ack(4) >= 0 && ack(4) <= 10000 && any(ack(5) == [0 1]) && ack(6) == 1
        receiver.control = struct('secventa',ack(1),'mod','manual','pornit',logical(ack(2)), ...
          'frecventa_hz',ack(3),'sarcina_nm',ack(4),'watchdog',logical(ack(5)),'protocol',1,'configured',false,'fault',0);
        receiver.ack_epoch = time();
      endif
      continue;
    endif
    values = str2double(columns);
    if numel(values) != 5 || any(!isfinite(values)) || values(1) < 0
      receiver.invalide += 1; continue;
    endif
    if values(1) < receiver.ultim_timp - 0.01
      close_recording(receiver.sesiune, settings, 'INREGISTRARE');
      receiver.sesiune = []; receiver.diagnostic = []; receiver.ultim_timp = -Inf;
    endif
    if values(1) <= receiver.ultim_timp
      receiver.invalide += 1; continue;
    endif
    if isempty(receiver.sesiune)
      identifier = sprintf('psim_%s_%d', datestr(now(), 'yyyymmdd_HHMMSS'), round(1e6*rem(time(),1)));
      receiver.sesiune = open_csv_recording('psim', settings, identifier, 1);
    endif
    [receiver.diagnostic, reading, events] = diagnostic_psim(receiver.diagnostic, values, settings.diagnostic);
    session = receiver.sesiune;
    if session.numar > 0 && values(1) - session.inceput_s >= settings.psim.segment_s
      close_recording(session, settings, 'INREGISTRARE');
      next_segment = open_csv_recording('psim', settings, session.id, session.parte+1);
      next_segment.alarme = session.alarme;
      session = next_segment;
    endif
    if isnan(session.inceput_s), session.inceput_s = values(1); endif
    fprintf(session.esantioane, '%.6f,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%s,%d,%d\n', ...
      reading.t_s,reading.rpm,reading.current_a,reading.rms_a,reading.vdc_v,reading.fref_hz, ...
      reading.sync_rpm,reading.speed_error_pct,reading.status,reading.active_alarm_count,reading.precharge_qualified);
    for event_index = 1:numel(events)
      event = events{event_index};
      fprintf(session.evenimente, '%.6f,%s,%s,%.9g\n', event.t_s,event.level,event.code,event.value);
      if strcmp(event.level,'WARN') || strcmp(event.level,'ALARM')
        alarm = struct('cod',event.code,'severitate',event.level, ...
          'activare_s',event.t_s,'revenire_s',NaN,'valoare',event.value);
        session.alarme{end+1} = alarm;
      elseif strcmp(event.level,'CLEARED')
        session.alarme = session.alarme(!cellfun(@(alarm) strcmp(alarm.cod,event.code), session.alarme));
      endif
    endfor
    session.numar += 1;
    session.ultim_s = values(1); session.esantion_epoch = time(); session.stare = reading.status;
    receiver.ultim_timp = values(1); receiver.ultim_epoch = time(); receiver.sesiune = session;
    receiver.valide += 1;
    receiver.ultim_cadru = struct('t_s',values(1),'rpm',values(2),'phase_current_a',values(3), ...
      'vdc_v',values(4),'f_ref_hz',values(5));
  endfor
  receiver.buffer = receiver.buffer(cursor:end);
  if numel(receiver.buffer) > 8192
    receiver.buffer = ''; receiver.invalide += 1;
  endif
endfunction
