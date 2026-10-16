function receiver = create_psim_receiver(settings)
  receiver = struct('server', [], 'buffer', '', 'diagnostic', [], 'sesiune', [], ...
                    'ultim_timp', -Inf, 'ultim_epoch', 0, 'invalide', 0, 'valide',0,'ultim_cadru',[], 'eroare', '', ...
                    'protocol',0,'hmi',false,'canal_id','','control',struct('secventa',0,'mod','manual','pornit',false,'frecventa_hz',0,'sarcina_nm',0,'protocol',0,'configured',false,'fault',0), ...
                    'comanda',[],'respingere',[],'ultima_secventa_ceruta',0, ...
                    'ack_epoch',0,'trimis_epoch',0,'stare_epoch',0, ...
                    'backend_lease_epoch',0,'backend_lease_checked',0);
  if !settings.psim.receptie_activa
    receiver.eroare = 'Receptia PSIM este dezactivata in configuratie.';
    return;
  endif
  try
    pkg load instrument-control;
    receiver.server = tcpserver('127.0.0.1', settings.psim.port_tcp);
    set(receiver.server,'Timeout',0.05);
    fprintf('Receptor PSIM pe 127.0.0.1:%d; simularea se porneste manual cu F8.\n', settings.psim.port_tcp);
  catch error
    receiver.eroare = ['Receptor PSIM indisponibil: ' error.message];
    fprintf(2, '%s\n', receiver.eroare);
  end_try_catch
endfunction

