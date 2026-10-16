function close_recording(session, settings, activity)
  if isempty(session), return; endif
  fflush(session.esantioane); fflush(session.evenimente);
  fclose(session.esantioane); fclose(session.evenimente);
  recording_metadata(session, settings, activity);
endfunction
