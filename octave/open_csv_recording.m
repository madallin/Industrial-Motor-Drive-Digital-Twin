function session = open_csv_recording(source, settings, identifier, part)
  if !strcmp(source,'psim'), error('Sunt acceptate numai masuratori PSIM.'); endif
  session = struct('sursa', source, 'id', identifier, 'parte', part);
  session.segment_id = sprintf('%s_part%04d', identifier, part);
  session.baza = fullfile(settings.director_rezultate, session.segment_id);
  session.esantioane = fopen([session.baza '_samples.csv'], 'w');
  if session.esantioane < 0, error('Nu pot crea CSV pentru %s', source); endif
  session.evenimente = fopen([session.baza '_events.csv'], 'w');
  if session.evenimente < 0
    fclose(session.esantioane); error('Nu pot crea jurnalul de evenimente.');
  endif
  fprintf(session.esantioane, 't_s,rpm,phase_current_a,rms_est_a,vdc_v,f_ref_hz,sync_rpm,speed_error_pct,status,active_alarm_count,precharge_qualified\n');
  fprintf(session.evenimente, 't_s,level,code,value\n');
  session.numar = 0;
  session.inceput_s = NaN;
  session.ultim_s = NaN;
  session.esantion_epoch = 0;
  session.alarme = {};
  session.stare = 'INIT';
  fflush(session.esantioane); fflush(session.evenimente);
  recording_metadata(session, settings, 'ASTEPTARE');
endfunction
