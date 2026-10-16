function publish_psim_status(receiver,settings)
  socket_detected = !isempty(receiver.server) && receiver.server.Connected;
  % Some tcpserver versions retain Connected after EOF. Require recent traffic
  % before reporting an active channel; an open socket alone is insufficient.
  connected = socket_detected && time()-max(receiver.ultim_epoch,receiver.ack_epoch) <= settings.date_vechi_s;
  transfer = struct('orchestrator_id',settings.orchestrator_id, ...
    'actualizat_epoch',time(),'conectat',logical(connected),'socket_detectat',logical(socket_detected), ...
    'dll_hmi',receiver.hmi && connected, ...
    'cadre_valide',receiver.valide,'cadre_respinse',receiver.invalide, ...
    'ultim_cadru',receiver.ultim_cadru,'esantion_epoch',receiver.ultim_epoch,'eroare',receiver.eroare);
  write_json_atomic(fullfile(settings.director_rezultate,'stare_receptie_psim.json'),transfer);
  if !isempty(receiver.sesiune)
    fflush(receiver.sesiune.esantioane); fflush(receiver.sesiune.evenimente);
    activity = 'ACTIV';
    if !connected || time()-receiver.ultim_epoch > settings.date_vechi_s, activity = 'ASTEPTARE'; endif
    recording_metadata(receiver.sesiune,settings,activity);
  else
    state = struct('sursa','psim','orchestrator_id',settings.orchestrator_id, ...
      'actualizat_epoch',time(),'achizitie','ASTEPTARE','eroare',receiver.eroare);
    if !isempty(receiver.eroare), state.achizitie = 'INDISPONIBIL'; endif
    write_json_atomic(fullfile(settings.director_rezultate,'stare_psim.json'),state);
  endif
endfunction
