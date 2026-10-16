function run_psim_supervisor()
  settings = load_motor_config();
  if exist(settings.director_rezultate,'dir') != 7, mkdir(settings.director_rezultate); endif
  receiver = []; last_publication = -Inf;
  fprintf('Supraveghere PSIM: receptie TCP, comenzi DLL si calcule din masuratori.\n');
  unwind_protect
    receiver = create_psim_receiver(settings);
    while exist(settings.fisier_oprire,'file') != 2
      receiver = process_psim_sample(receiver,settings);
      receiver = control_psim(receiver,settings);
      if time()-last_publication >= 0.2
        publish_psim_status(receiver,settings);
        last_publication = time();
      endif
      pause(0.005);
    endwhile
  unwind_protect_cleanup
    if !isempty(receiver)
      close_recording(receiver.sesiune,settings,'OPRIT');
      receiver.sesiune = [];
      receiver.server = [];
      publish_psim_status(receiver,settings);
    endif
    fprintf('Supravegherea PSIM s-a oprit controlat.\n');
  end_unwind_protect
endfunction

