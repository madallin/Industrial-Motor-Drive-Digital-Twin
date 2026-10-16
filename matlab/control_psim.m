function receiver = control_psim(receiver, settings)
  if time()-receiver.backend_lease_checked >= 0.2
    receiver.backend_lease_epoch = 0;
    try
      lease = jsondecode(fileread(fullfile(settings.director_control,'backend_lease.json')));
      if strcmp(lease.orchestrator_id,settings.orchestrator_id) && ...
          isfinite(lease.epoch) && lease.epoch <= time()
        receiver.backend_lease_epoch = lease.epoch;
      endif
    catch
      % Do not retain run authorization without a fresh backend lease.
    end_try_catch
    receiver.backend_lease_checked = time();
  endif
  backend_active = time()-receiver.backend_lease_epoch < settings.control.backend_lease_s;
  connected = !isempty(receiver.server) && receiver.server.Connected && receiver.hmi && time()-receiver.ack_epoch < 2.5;
  if connected && backend_active && settings.control.psim_activ
    file_path = fullfile(settings.director_control,'control_psim_cerere.json');
    if receiver.protocol == 2 && !receiver.control.configured
      p = settings.protection;
      frame = sprintf('CFG,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g,%.9g\n', ...
        settings.control.frecventa_max_hz,settings.control.sarcina_max_nm, ...
        p.rated_current_a,p.trip_current_a,p.dc_low_v,p.dc_high_v,p.max_speed_rpm,p.ready_low_v,p.ready_high_v, ...
        settings.control.watchdog_s);
      write(receiver.server,uint8(frame),'uint8');
    endif
    if time()-receiver.trimis_epoch >= 0.2
      try
        if exist(file_path,'file') == 2
          request = jsondecode(fileread(file_path));
          previous_sequence = max(receiver.control.secventa,receiver.ultima_secventa_ceruta);
          if !isempty(receiver.comanda), previous_sequence = max(previous_sequence,receiver.comanda.secventa); endif
          if validate_command(request,settings) && strcmp(request.mod,'manual') && ...
              strcmp(request.canal_id,receiver.canal_id) && request.secventa > previous_sequence
            receiver.comanda = request;
            receiver.ultima_secventa_ceruta = request.secventa;
          endif
        endif
        if !isempty(receiver.comanda)
          command = receiver.comanda;
          % Do not retry unconfirmed commands after expiry. Once acknowledged,
          % heartbeat only the state accepted by the DLL.
          confirmed = receiver.control.secventa == command.secventa;
          if (!confirmed && time() > command.expira_epoch) || ((receiver.control.watchdog || receiver.control.fault != 0) && receiver.control.secventa >= command.secventa)
            receiver.comanda = [];
          else
            frame = sprintf('CMD,%d,%d,%.9g,%.9g,%.9g,%.9g,%d\n',command.secventa,command.pornit,command.frecventa_hz,command.sarcina_nm,command.acceleration_s,command.deceleration_s,command.reset);
            if write(receiver.server,uint8(frame),'uint8') != numel(frame)
              receiver.hmi = false; receiver.comanda = [];
            endif
          endif
        endif
      catch
        receiver.hmi = false; receiver.comanda = [];
      end_try_catch
      receiver.trimis_epoch = time();
    endif
  endif
  if time()-receiver.stare_epoch >= 0.2
    state = receiver.control;
    state.orchestrator_id = settings.orchestrator_id;
    state.actualizat_epoch = time();
    state.ack_epoch = receiver.ack_epoch;
    state.conectat = connected && receiver.hmi;
    state.backend_activ = backend_active;
    state.canal_id = receiver.canal_id;
    state.esantion_epoch = receiver.ultim_epoch;
    state.respingere = receiver.respingere;
    write_json_atomic(fullfile(settings.director_control,'control_psim_stare.json'),state);
    receiver.stare_epoch = time();
  endif
endfunction
